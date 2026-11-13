"""C9: progress report (LLD C9).
Invariant: `verified` and `review_subject_pct` come only from assessments; `checks` and the kiosk_check indicators
only from diagnostics; `self_reported` only from tasks and reviews. No field mixes them."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException

from app import analytics, auth, catalogue, connector, db, roadmap
from app.schemas import CheckChange, Flag, Indicator, NextStep, Report, SelfReport, TaskView, TopicChange

router = APIRouter(prefix="/api")

CAVEAT = "Changes compare similar assessments before and after the plan. They do not show that the plan caused the change."


@dataclass
class Ctx:
    """Everything the pure report rules need."""
    tasks: list
    plan_topics: list[str]
    checks: list[CheckChange]
    last_check_seconds: int | None
    has_review: bool
    base_like: float | None
    review_like: float | None
    verified: list[TopicChange]
    remaining: list[Flag]
    evidence: dict
    subject_name: str
    subject_kind: str
    baseline_as_of: date | None
    review_imported_at: datetime | None
    today: date
    after_levels: dict[str, str] = field(default_factory=dict)
    task_topic: dict[int, str] = field(default_factory=dict)


def _fmt(p: float | None) -> str:
    return "?" if p is None else f"{p:.1f}%"


def _ind_verified_change(c: Ctx) -> Indicator:
    if c.review_like is not None and c.base_like is not None:
        return Indicator(code="verified_change", label="Comparable marks", value=f"{_fmt(c.base_like)} \u2192 {_fmt(c.review_like)}", source="verified")
    return Indicator(code="verified_change", label="Comparable marks", value="No comparable assessment yet", source="verified")


def _ind_check_accuracy(c: Ctx) -> Indicator:
    both = [k for k in c.checks if k.before_score and k.after_score]
    if both:
        num = lambda s: tuple(int(x) for x in s.split("/"))
        b = [num(k.before_score) for k in both]
        a = [num(k.after_score) for k in both]
        val = f"{sum(x for x, _ in b)}/{sum(y for _, y in b)} \u2192 {sum(x for x, _ in a)}/{sum(y for _, y in a)}"
    else:
        latest = [k.after_score or k.before_score for k in c.checks if (k.after_score or k.before_score)]
        val = latest[-1] if latest else "No concept check yet"
    return Indicator(code="check_accuracy", label="Concept check accuracy", value=val, source="kiosk_check")


def _ind_check_speed(c: Ctx) -> Indicator:
    val = f"{round(c.last_check_seconds / 5)} s" if c.last_check_seconds is not None else "No concept check yet"
    return Indicator(code="check_speed", label="Time per question", value=val, source="kiosk_check")


def _ind_task_completion(c: Ctx) -> Indicator:
    n = sum(1 for t in c.tasks if t.status in ("done", "partial"))
    return Indicator(code="task_completion", label="Tasks done or partly done", value=f"{n} of {len(c.tasks)}", source="self_reported")


def _ind_topic_coverage(c: Ctx) -> Indicator:
    started = {c.task_topic.get(t.id) for t in c.tasks if t.status != "pending"}
    return Indicator(code="topic_coverage", label="Plan topics started", value=f"{len(started & set(c.plan_topics))} of {len(c.plan_topics)} topics", source="self_reported")


def _ind_checkpoints(c: Ctx) -> Indicator:
    cps = [t for t in c.tasks if t.kind == "checkpoint"]
    return Indicator(code="checkpoints_done", label="Checkpoints done", value=f"{sum(1 for t in cps if t.status == 'done')} of {len(cps)}", source="self_reported")


INDICATORS = {"verified_change": _ind_verified_change, "check_accuracy": _ind_check_accuracy, "check_speed": _ind_check_speed,
              "task_completion": _ind_task_completion, "topic_coverage": _ind_topic_coverage, "checkpoints_done": _ind_checkpoints}


def next_steps(c: Ctx) -> list[NextStep]:
    """First two matches, in order (LLD_next C9.2). The wording never claims the plan caused anything (RB 9)."""
    after_exists = any(k.after_score for k in c.checks)
    done_part = sum(1 for t in c.tasks if t.status in ("done", "partial"))
    overdue = [t for t in c.tasks if t.status != "done" and t.due_on < c.today]
    if c.has_review:
        gaps = sorted({f.topic for f in c.remaining if f.topic})
    else:
        gaps = sorted(t for t, lv in c.after_levels.items() if lv in ("foundation", "beginner"))
    out: list[NextStep] = []
    if not c.has_review and not after_exists:
        out.append(NextStep(code="check", text="Take the 5-question topic check to see where you are now."))
        out.append(NextStep(code="await_evidence", text="New marks are not in yet. This report updates after the next assessment import."))
    prereq = next((f for f in c.remaining if f.code == "PREREQ_GAP"), None)
    if prereq:
        out.append(NextStep(code="prerequisite", text=f"Make a short plan for {prereq.values.get('prereq')} first, then return to {prereq.topic}."))
    deltas = [v.delta for v in c.verified if v.topic in gaps and v.delta is not None]
    if gaps and ((deltas and all(d <= 0 for d in deltas)) or any(c.after_levels.get(g) == "foundation" for g in gaps)):
        out.append(NextStep(code="mentor", text=f"Talk to a faculty mentor about {', '.join(gaps)}: the plan has not moved it yet."))
    if c.tasks and done_part / len(c.tasks) < 0.3 and overdue:
        out.append(NextStep(code="revise", text="Fit the plan to the time you have: fewer minutes a day or fewer topics."))
    if gaps:
        out.append(NextStep(code="revise", text=f"Make a revised plan focused on {', '.join(gaps)}."))
    out.append(NextStep(code="continue", text="Keep going: pick your next topic or goal."))
    return out[:2]


def limitations(c: Ctx) -> list[str]:
    out = []
    per_topic: dict[str, int] = {}
    for t in c.evidence.get("topics", []):          # the snapshot is per (topic, kind): add the kinds up for each topic
        per_topic[t["topic"]] = per_topic.get(t["topic"], 0) + t["n"]
    for topic, n in per_topic.items():
        if n < 3:
            out.append(f"{topic} rests on {n} assessments.")
    if not c.has_review:
        out.append("No review assessment has been imported yet.")
    out.append("Concept checks have 5 questions; levels are provisional.")
    out.append("Task ticks are your own record and are not verified.")
    if c.subject_kind == "track":
        out.append(f"{c.subject_name} is a track without institutional marks.")
    base = c.baseline_as_of.isoformat() if c.baseline_as_of else "not available"
    rev = f"review data imported {c.review_imported_at.date().isoformat()}" if c.review_imported_at else "review data not yet imported"
    out.append(f"Records as of {base}; {rev}.")
    return list(dict.fromkeys(out))


def build_report(conn, roadmap_id: int, today: date) -> Report:
    row = conn.execute("SELECT r.student_id, r.subject_id, r.goal, r.target_date, r.evidence, r.created_at FROM roadmaps r WHERE r.id=%s", (roadmap_id,)).fetchone()
    plan = roadmap.view(conn, roadmap_id)
    base = row["evidence"]
    info = connector.student_info(conn, row["student_id"])
    kind = connector.subject_kind(conn, plan.subject_code) or "course"

    review_rec = connector.get_records(conn, row["student_id"], "review")
    review_rows = next((s.rows for s in review_rec.subjects if s.code == plan.subject_code), [])
    has_review = any(r.score is not None for r in review_rows)
    review_topics = analytics.topic_pcts(review_rows)

    # Verified change: only for the same topic AND assessment kind; otherwise say there is no comparable assessment.
    verified: list[TopicChange] = []
    base_keys = set()
    for t in base["topics"]:
        key = (t["topic"], t["kind"])
        base_keys.add(key)
        if key in review_topics:
            rp = round(review_topics[key][0], 1)
            verified.append(TopicChange(topic=t["topic"], kind=t["kind"], baseline_pct=t["pct"], review_pct=rp, delta=round(rp - t["pct"], 1), note=None))
        else:
            verified.append(TopicChange(topic=t["topic"], kind=t["kind"], baseline_pct=t["pct"], review_pct=None, delta=None, note="No comparable assessment yet"))

    # Like-for-like subject figures: the same (topic, kind) groups on both sides.
    n_total = sum(t["n"] for t in base["topics"])
    base_like = round(sum(t["pct"] * t["n"] for t in base["topics"]) / n_total, 1) if n_total else None
    like_rows = [r for r in review_rows if (r.topic, r.kind) in base_keys]
    review_like = analytics.pct(like_rows) if has_review_like(like_rows) else None

    tasks = plan.tasks
    counts = {s: sum(1 for t in tasks if t.status == s) for s in ("done", "partial", "pending")}
    self_reported = SelfReport(**counts, total=len(tasks), overdue=[t for t in tasks if t.status != "done" and t.due_on < today])

    remaining: list[Flag] = []
    if has_review and kind == "course":
        for s in analytics.analyse(review_rec, connector.class_means(conn, "review"), today, prereqs=connector.prereq_map(conn)):
            if s.code == plan.subject_code:
                remaining = s.flags

    # catalogue topics of the plan: resources.topic of each task's resource, never the AI's free-text task topic
    topic_of = {r["id"]: r["topic"] for r in conn.execute("SELECT id, topic FROM resources WHERE id = ANY(%s)", ([t.resource_id for t in tasks] or [0],)).fetchall()}
    plan_topics = list(dict.fromkeys(topic_of[t.resource_id] for t in tasks if t.resource_id in topic_of))
    diag = conn.execute(
        """SELECT topic, level, correct, total, seconds, submitted_at FROM diagnostics
           WHERE student_id=%s AND subject_id=%s AND submitted_at IS NOT NULL ORDER BY submitted_at""",
        (row["student_id"], row["subject_id"]),
    ).fetchall()
    checks: list[CheckChange] = []
    after_levels: dict[str, str] = {}
    for topic in plan_topics:
        mine = [d for d in diag if d["topic"] == topic]
        if not mine:
            continue
        before = [d for d in mine if d["submitted_at"] <= row["created_at"]]
        after = [d for d in mine if d["submitted_at"] > row["created_at"]]
        b, a = (before[-1] if before else None), (after[-1] if after else None)
        if a:
            after_levels[topic] = a["level"]
        checks.append(CheckChange(
            topic=topic, before_level=b["level"] if b else None, before_score=f"{b['correct']}/{b['total']}" if b else None,
            before_on=b["submitted_at"].date() if b else None, after_level=a["level"] if a else None,
            after_score=f"{a['correct']}/{a['total']}" if a else None, after_on=a["submitted_at"].date() if a else None,
            note=None if a else "No check after the plan started yet"))
    last_seconds = diag[-1]["seconds"] if diag else None

    rev = conn.execute("SELECT confidence FROM reviews WHERE roadmap_id=%s ORDER BY at DESC, id DESC LIMIT 1", (roadmap_id,)).fetchone()
    ref = conn.execute(
        "SELECT status FROM requests WHERE student_id=%s AND category='academic' AND created_at > %s ORDER BY created_at DESC LIMIT 1",
        (row["student_id"], row["created_at"]),
    ).fetchone()   # wellbeing requests never appear on a report

    ctx = Ctx(tasks=tasks, plan_topics=plan_topics, checks=checks, last_check_seconds=last_seconds, has_review=has_review,
              base_like=base_like, review_like=None if review_like is None else round(review_like, 1), verified=verified, remaining=remaining,
              evidence=base, subject_name=plan.subject_name, subject_kind=kind,
              baseline_as_of=date.fromisoformat(base["as_of"]) if base.get("as_of") else None,
              review_imported_at=connector.last_import(conn, "review"), today=today, after_levels=after_levels)
    ctx.task_topic = {t.id: topic_of.get(t.resource_id, "") for t in tasks}
    indicators = [INDICATORS[c](ctx) for c in catalogue.GOALS[row["goal"]].indicator_codes]

    return Report(
        goal=row["goal"], goal_name=catalogue.GOALS[row["goal"]].name, semester=info.semester, target_date=row["target_date"],
        baseline_as_of=ctx.baseline_as_of, review_imported_at=ctx.review_imported_at,
        checks=checks, indicators=indicators, next_steps=next_steps(ctx),
        academic_referral=ref["status"] if ref else "none", confidence_review=rev["confidence"] if rev else None, limitations=limitations(ctx),
        roadmap_id=roadmap_id, version=plan.version, subject_code=plan.subject_code, subject_name=plan.subject_name,
        roll_no=info.roll_no, programme=info.programme, start_on=plan.start_on, review_on=plan.review_on,
        baseline_flags=[Flag(**f) for f in base["flags"]], baseline_subject_pct=base_like,
        review_subject_pct=None if review_like is None else round(review_like, 1), has_review_data=has_review,
        verified=verified, self_reported=self_reported, remaining_flags=remaining, caveat=CAVEAT,
    )


def has_review_like(rows) -> bool:
    return any(r.score is not None for r in rows)


@router.get("/roadmaps/{roadmap_id}/report", response_model=Report)
def get_report(roadmap_id: int, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    if not roadmap._owned(conn, roadmap_id, s.student_id):
        raise HTTPException(404, "not_found")
    out = build_report(conn, roadmap_id, date.today())
    db.audit(conn, f"student:{s.student_id}", "report_view", str(roadmap_id))
    conn.commit()
    return out
