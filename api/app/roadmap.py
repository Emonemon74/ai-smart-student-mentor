"""C7: roadmap engine and sharing (LLD C7). The LLM writes only the summary and tasks;
everything else is decided or re-checked by the server."""
from __future__ import annotations

import math
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app import analytics, auth, catalogue, config, connector, db, llm
from app.schemas import (
    DraftRequest, DraftView, Resource, ReviewIn, RoadmapIn, RoadmapListItem, RoadmapView, ShareOut, TaskIn, TaskView, TopicLevel,
)

router = APIRouter(prefix="/api")

SHARE_MINUTES = 10
LANGUAGE = {"en": "English", "hi": "Hindi (Devanagari script)"}


class LLMPlan(BaseModel):
    summary: str = Field(max_length=600)
    tasks: list[TaskIn] = Field(min_length=3, max_length=15)


# ---- validation ---------------------------------------------------------------------------------
def validate_plan(plan: LLMPlan, allowed_ids: set[int], days: int, daily_minutes: int) -> None:
    """Raises ValueError with a short message on the first failure (fed back to the model on retry)."""
    tasks = plan.tasks
    for t in tasks:
        if t.resource_id not in allowed_ids:
            raise ValueError(f"resource_id {t.resource_id} is not in the approved list")
    if tasks[0].day_from != 1:
        raise ValueError("the first task must start on day 1")
    for prev, nxt in zip(tasks, tasks[1:]):
        if nxt.day_from != prev.day_to + 1:
            raise ValueError(f"tasks must be in order with no gap or overlap (day {prev.day_to} then day {nxt.day_from})")
    if tasks[-1].day_to != days:
        raise ValueError(f"the last task must end on day {days}")
    for t in tasks:
        if t.minutes > daily_minutes:
            raise ValueError(f"minutes {t.minutes} exceeds the daily budget of {daily_minutes}")
    need = math.ceil(days / 7)
    if sum(1 for t in tasks if t.kind == "checkpoint") < need:
        raise ValueError(f"at least {need} checkpoint tasks are required")
    if tasks[-1].kind != "checkpoint":
        raise ValueError("the last task must be a checkpoint")


def _check_saved(plan: RoadmapIn, allowed_ids: set[int]) -> None:
    """Never trust the client copy: re-run the resource and budget checks, require in-range sorted
    non-overlapping day ranges (gaps allowed: the student may have deleted tasks)."""
    last_to = 0
    for t in plan.tasks:
        if t.resource_id not in allowed_ids:
            raise ValueError("resource not approved")
        if t.minutes > plan.daily_minutes:
            raise ValueError("over the daily budget")
        if not (1 <= t.day_from <= t.day_to <= plan.days):
            raise ValueError("day range outside the plan")
        if t.day_from <= last_to:
            raise ValueError("tasks overlap or are out of order")
        last_to = t.day_to


# ---- helpers ------------------------------------------------------------------------------------
def _subject_id(conn, code: str) -> int | None:
    r = conn.execute("SELECT id FROM subjects WHERE code=%s", (code,)).fetchone()
    return r["id"] if r else None


def _has_records(rec, code: str) -> bool:
    return any(s.code == code for s in rec.subjects)


def snapshot(conn, student_id: int, subject_code: str) -> dict:
    """Baseline evidence for the report (C7.6), recomputed server-side at save time. A track has no marks."""
    if connector.subject_kind(conn, subject_code) == "track":
        return {"flags": [], "subject_pct": None, "topics": [], "as_of": None}
    p = analytics.build_profile(conn, student_id)
    summ = next(s for s in p.subjects if s.code == subject_code)
    rec = connector.get_records(conn, student_id)
    rows = next(s for s in rec.subjects if s.code == subject_code).rows
    topics = [{"topic": t, "kind": k, "pct": round(v[0], 1), "n": v[1]} for (t, k), v in sorted(analytics.topic_pcts(rows).items())]
    return {"flags": [f.model_dump(mode="json") for f in summ.flags], "subject_pct": summ.pct, "topics": topics,
            "as_of": p.as_of.isoformat() if p.as_of else None}


def _resources_by_id(conn, ids: set[int]) -> dict[int, Resource]:
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT id, topic, title, url, kind, level, lang, minutes, goals, link_ok FROM resources WHERE id = ANY(%s)", (list(ids),)).fetchall()
    return {r["id"]: connector.ResourceRow(**r).api() for r in rows}


def view(conn, roadmap_id: int) -> RoadmapView | None:
    """Shared by the kiosk and phone endpoints. Callers do the ownership check."""
    r = conn.execute(
        "SELECT r.*, s.code, s.name AS subject_name FROM roadmaps r JOIN subjects s ON s.id=r.subject_id WHERE r.id=%s", (roadmap_id,)
    ).fetchone()
    if not r:
        return None
    rows = conn.execute("SELECT * FROM tasks WHERE roadmap_id=%s ORDER BY position", (roadmap_id,)).fetchall()
    tasks = [TaskView(id=t["id"], day_from=t["day_from"], day_to=t["day_to"], kind=t["kind"], topic=t["topic"], activity=t["activity"],
                      reason=t["reason"], minutes=t["minutes"], resource_id=t["resource_id"], check=t["check_text"],
                      due_on=t["due_on"], status=t["status"]) for t in rows]
    return RoadmapView(id=r["id"], version=r["version"], status=r["status"], goal=r["goal"], goal_name=catalogue.GOALS[r["goal"]].name,
                       target_date=r["target_date"], levels={k: TopicLevel(**v) for k, v in (r["levels"] or {}).items()},
                       subject_code=r["code"], subject_name=r["subject_name"],
                       summary=r["summary"], days=r["days"], daily_minutes=r["daily_minutes"], start_on=r["start_on"], review_on=r["review_on"],
                       tasks=tasks, resources=_resources_by_id(conn, {t.resource_id for t in tasks}))


def _owned(conn, roadmap_id: int, student_id: int) -> bool:
    return conn.execute("SELECT 1 FROM roadmaps WHERE id=%s AND student_id=%s", (roadmap_id, student_id)).fetchone() is not None


# ---- draft prompt ---------------------------------------------------------------------------------
PLAN_SYSTEM = "You write personalised study plans for a university student. Output only one JSON object, no other text."

PLAN_USER = """GOAL: {goal_name}: {goal_components}
PROGRESS INDICATORS: {goal_indicators}
TARGET DATE: {target}
SUBJECT: {name} ({code}){track}
EVIDENCE: {evidence}
RECOMMENDED RESPONSES: {responses}
LEVELS (provisional): {levels}
WEAK TOPICS: {weak}
UPCOMING ASSESSMENTS: {upcoming}
CONSTRAINTS: {days} days starting today, at most {minutes} minutes per day, review on {review_on}.
APPROVED RESOURCES (use only these ids): {resources}
CONVERSATION: {conversation}
Write all text fields in {language}. Keep JSON keys and "kind" values in English.
Return: {{"summary": "...", "tasks": [{{"day_from": 1, "day_to": 3, "kind": "learn", "topic": "...",
  "activity": "...", "reason": "...", "minutes": 60, "resource_id": 12, "check": "..."}}]}}
Rules:
- Weakest topics first. Revise before any upcoming assessment.
- Start each topic at its level and move up at most one level per stage; foundation topics begin with explanations and worked examples.
- Follow RECOMMENDED RESPONSES: repair a prerequisite before its topic; for a theory-practice gap include labs and debugging tasks.
- Match the goal's components. For goals with a target date, put previous-year questions or timed practice before it.
- Prefer formats the student asked for in CONVERSATION, and the student's language, when an approved resource exists.
- Tasks are in order, do not overlap, and cover every day from 1 to {days}.
- "minutes" is effort per day and must not exceed {minutes}.
- At least one "checkpoint" task in every 7 days, and the last task is a checkpoint.
- "reason" says why, citing the evidence or the student's stated goal.
- "check" is a concrete way to know the task is complete.
- "kind" is one of: learn, practice, checkpoint. Keep "activity" under 300 characters, "reason" and "check" under 160, "topic" under 80."""


def _plan_context(conn, student_id: int, goal: str, subject_code: str, overrides: dict, lang: str, daily_minutes: int, today: date):
    """Levels (computed + the student's overrides) and the resources the plan may use. Shared by draft and save."""
    kind = connector.subject_kind(conn, subject_code)
    levels: dict[str, TopicLevel] = {}
    summ = None
    if kind == "course":
        profile = analytics.build_profile(conn, student_id, today=today)
        summ = next((s for s in profile.subjects if s.code == subject_code), None)
        levels = {tl.topic: tl for tl in summ.levels} if summ else {}
    resources = connector.get_resources(conn, subject_code)
    cat_topics = {r.topic for r in resources} | set(levels)
    if any(t not in cat_topics for t in overrides):
        raise HTTPException(422, "invalid_plan")
    for t, lv in overrides.items():
        levels[t] = TopicLevel(topic=t, level=lv, source="student", as_of=today, n=0, has_check=levels[t].has_check if t in levels else False)
    allowed = catalogue.pick_resources(resources, goal=goal, levels={t: tl.level for t, tl in levels.items()}, lang=lang, daily_minutes=daily_minutes)
    return kind, summ, levels, allowed


def _check_request(conn, student_id: int, goal: str, subject_code: str, days: int, daily_minutes: int, review_on: date,
                   target_date: date | None, today: date) -> None:
    """C7.2 checks 1-3, repeated on save: the client copy is never trusted."""
    if goal not in catalogue.GOALS or subject_code not in {x.code for x in catalogue.eligible_subjects(conn, student_id, goal)}:
        raise HTTPException(404, "not_found")
    if review_on < today + timedelta(days=days):
        raise HTTPException(422, "review_too_soon")
    if target_date is not None and target_date < today:
        raise HTTPException(422, "invalid_plan")
    other = conn.execute(
        """SELECT COALESCE(SUM(r.daily_minutes), 0) AS m FROM roadmaps r JOIN subjects s ON s.id=r.subject_id
           WHERE r.student_id=%s AND r.status='active' AND NOT (r.goal=%s AND s.code=%s) AND r.start_on + r.days - 1 >= %s""",
        (student_id, goal, subject_code, today),
    ).fetchone()["m"]
    if int(other) + daily_minutes > config.MAX_DAILY_MINUTES:
        raise HTTPException(422, "over_daily_capacity")


def build_draft_prompt(conn, student_id: int, req: DraftRequest, today: date) -> tuple[list[dict], set[int], dict[str, TopicLevel]]:
    g = catalogue.GOALS[req.goal]
    kind, summ, levels, allowed = _plan_context(conn, student_id, req.goal, req.subject_code, req.level_overrides, req.lang, req.daily_minutes, today)
    name = conn.execute("SELECT name FROM subjects WHERE code=%s", (req.subject_code,)).fetchone()["name"]
    weak, upcoming, evidence, responses = "none", "none", "no institutional records", "none"
    if kind == "course":
        rec = connector.get_records(conn, student_id)
        subj = next(s for s in rec.subjects if s.code == req.subject_code)
        profile = analytics.build_profile(conn, student_id, today=today)
        topics = sorted(analytics.topic_pcts(subj.rows).items(), key=lambda kv: kv[1][0])[:5]
        weak = ", ".join(f"{t} {v[0]:.1f}% ({v[1]} assessments)" for (t, _k), v in topics) or "none"
        up = [f"{u.kind} on {u.on} (day {(u.on - today).days + 1} of the plan)" if (u.on - today).days + 1 <= req.days else f"{u.kind} on {u.on}"
              for u in profile.upcoming if u.subject_code == req.subject_code]
        upcoming = "; ".join(up) or "none"
        flags = summ.flags if summ else []
        # de-duplicate by topic: show the most specific flag for a topic
        spec = {"PREREQ_GAP": 0, "TARGETED_GAP": 0, "WEAK_TOPIC": 1}
        best: dict[object, object] = {}
        for f in flags:
            key = f.topic if f.topic else (f.code, None)
            if key not in best or spec.get(f.code, 2) < spec.get(best[key].code, 2):
                best[key] = f
        shown = list(best.values())
        evidence = "; ".join(f.reason for f in shown) or "no flags"
        responses = "; ".join(f"{f.code} {f.topic or req.subject_code} -> {f.response}" for f in shown if f.response) or "none"
    lv_text = "; ".join(f"{t} {tl.level or 'unknown'} ({tl.source or 'no evidence'})" for t, tl in sorted(levels.items())) or "none"
    convo = "\n".join(f"{'Student' if m.role == 'user' else 'Mentor'}: {m.content}" for m in req.messages[-16:]) or "(none)"
    user = PLAN_USER.format(
        goal_name=g.name, goal_components=g.components, goal_indicators=g.indicators, target=req.target_date or "none",
        name=name, code=req.subject_code, track=" - a track without institutional marks" if kind == "track" else "",
        evidence=evidence, responses=responses, levels=lv_text, weak=weak, upcoming=upcoming,
        days=req.days, minutes=req.daily_minutes, review_on=req.review_on,
        resources=" ".join(f'[{r.id}] {r.topic} - "{r.title}" ({r.kind}, {r.level}, {r.lang}, {r.minutes} min)' for r in allowed),
        conversation=convo, language=LANGUAGE[req.lang],
    )
    return [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}], {r.id for r in allowed}, levels


# ---- endpoints ------------------------------------------------------------------------------------
@router.post("/roadmaps/draft", response_model=DraftView)
def draft(req: DraftRequest, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    today = date.today()
    _check_request(conn, s.student_id, req.goal, req.subject_code, req.days, req.daily_minutes, req.review_on, req.target_date, today)
    messages, allowed, levels = build_draft_prompt(conn, s.student_id, req, today)
    conn.commit()  # release the read transaction before the slow external call
    try:
        plan = llm.chat_json(messages, LLMPlan, validate=lambda p: validate_plan(p, allowed, req.days, req.daily_minutes))
    except llm.AIUnavailable:
        db.audit(conn, f"student:{s.student_id}", "draft_fail", req.subject_code)
        conn.commit()
        raise HTTPException(502, "ai_unavailable")
    db.audit(conn, f"student:{s.student_id}", "draft_ok", req.subject_code)
    conn.commit()
    rm = RoadmapIn(goal=req.goal, subject_code=req.subject_code, target_date=req.target_date, level_overrides=req.level_overrides,
                   summary=plan.summary, days=req.days, daily_minutes=req.daily_minutes, review_on=req.review_on, tasks=plan.tasks)
    return DraftView(roadmap=rm, resources=_resources_by_id(conn, {t.resource_id for t in plan.tasks}), levels=levels)


@router.post("/roadmaps", response_model=RoadmapView)
def save(plan: RoadmapIn, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    today = date.today()
    _check_request(conn, s.student_id, plan.goal, plan.subject_code, plan.days, plan.daily_minutes, plan.review_on, plan.target_date, today)
    sid = _subject_id(conn, plan.subject_code)
    # the plan does not carry the language it was drafted in: "hi" admits Hindi and English rows, a superset of what a
    # draft in either language could have used
    kind, _summ, levels, allowed_rows = _plan_context(conn, s.student_id, plan.goal, plan.subject_code, plan.level_overrides, "hi", plan.daily_minutes, today)
    allowed = {r.id for r in allowed_rows}
    try:
        _check_saved(plan, allowed)
    except ValueError:
        raise HTTPException(422, "invalid_plan")
    start_on = today
    evidence = snapshot(conn, s.student_id, plan.subject_code)  # recomputed server-side: never taken from the client
    conn.execute("UPDATE roadmaps SET status='superseded' WHERE student_id=%s AND goal=%s AND subject_id=%s AND status='active'", (s.student_id, plan.goal, sid))
    version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM roadmaps WHERE student_id=%s AND goal=%s AND subject_id=%s", (s.student_id, plan.goal, sid)).fetchone()["v"]
    rid = conn.execute(
        """INSERT INTO roadmaps (student_id, goal, subject_id, version, summary, evidence, levels, days, daily_minutes, start_on, review_on, target_date)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (s.student_id, plan.goal, sid, version, plan.summary, Jsonb(evidence), Jsonb({t: tl.model_dump(mode="json") for t, tl in levels.items()}),
         plan.days, plan.daily_minutes, start_on, plan.review_on, plan.target_date),
    ).fetchone()["id"]
    for i, t in enumerate(plan.tasks):
        conn.execute(
            """INSERT INTO tasks (roadmap_id, position, day_from, day_to, due_on, kind, topic, activity, reason, minutes, resource_id, check_text)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rid, i, t.day_from, t.day_to, start_on + timedelta(days=t.day_to - 1), t.kind, t.topic, t.activity, t.reason, t.minutes, t.resource_id, t.check),
        )
    db.audit(conn, f"student:{s.student_id}", "roadmap_save", str(rid))
    if plan.level_overrides:
        db.audit(conn, f"student:{s.student_id}", "level_override", ",".join(sorted(plan.level_overrides)))
    conn.commit()
    return view(conn, rid)


@router.get("/roadmaps", response_model=list[RoadmapListItem])
def list_roadmaps(s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    rows = conn.execute(
        """SELECT r.id, s.code AS subject_code, s.name AS subject_name, r.version, r.goal, r.daily_minutes, r.review_on, r.status,
                  count(*) FILTER (WHERE t.status = 'done') AS done, count(t.id) AS total
           FROM roadmaps r JOIN subjects s ON s.id = r.subject_id LEFT JOIN tasks t ON t.roadmap_id = r.id
           WHERE r.student_id = %s GROUP BY r.id, s.code, s.name ORDER BY r.created_at DESC, r.id DESC""",
        (s.student_id,),
    ).fetchall()
    return [RoadmapListItem(goal_name=catalogue.GOALS[r["goal"]].name, **r) for r in rows]


@router.post("/roadmaps/{roadmap_id}/review", status_code=204)
def review(roadmap_id: int, body: ReviewIn, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    if not _owned(conn, roadmap_id, s.student_id):
        raise HTTPException(404, "not_found")
    conn.execute("INSERT INTO reviews (roadmap_id, confidence, plan_fit) VALUES (%s,%s,%s)", (roadmap_id, body.confidence, body.plan_fit))
    db.audit(conn, f"student:{s.student_id}", "review_checkin", str(roadmap_id))
    conn.commit()


@router.get("/roadmaps/{roadmap_id}", response_model=RoadmapView)
def get_roadmap(roadmap_id: int, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    if not _owned(conn, roadmap_id, s.student_id):
        raise HTTPException(404, "not_found")  # missing or not owned: never leak existence
    return view(conn, roadmap_id)


@router.post("/roadmaps/{roadmap_id}/share", response_model=ShareOut)
def share(roadmap_id: int, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    if not _owned(conn, roadmap_id, s.student_id):
        raise HTTPException(404, "not_found")
    conn.execute("DELETE FROM sessions WHERE kind='phone' AND roadmap_id=%s", (roadmap_id,))        # revoke older phones
    conn.execute("DELETE FROM share_tokens WHERE roadmap_id=%s AND used_at IS NULL", (roadmap_id,))
    token = secrets.token_urlsafe(32)
    exp = conn.execute(
        "INSERT INTO share_tokens (token_hash, roadmap_id, expires_at) VALUES (%s,%s, now() + make_interval(mins => %s)) RETURNING expires_at",
        (db.h(token), roadmap_id, SHARE_MINUTES),
    ).fetchone()["expires_at"]
    db.audit(conn, f"student:{s.student_id}", "share_create", str(roadmap_id))
    conn.commit()
    return ShareOut(url=f"{config.PUBLIC_BASE_URL}/r/{token}", expires_at=exp)
