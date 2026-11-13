"""C4: academic analytics. Pure, explainable rules; the router is a thin wrapper (LLD C4)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends

from app import auth, connector, db
from app.connector import Row, StudentRecords
from app.schemas import Backlog, Flag, Level, Profile, RoleReadiness, SubjectSummary, TopicLevel, Upcoming

router = APIRouter(prefix="/api")

RULES = {"self_gap": 10, "class_gap": 10, "decline": 10, "trend_quizzes": 4, "attendance": 75, "weak_topic": 50,
         "theory_gap": 15, "min_labs": 2, "prereq_weak": 60, "prereq_strong": 70, "min_evidence": 3}   # faculty-tunable

RESPONSES = {   # RB 5.3 "recommended response", shown under the reason and given to the plan prompt
    "LOW_VS_SELF": "Start with prerequisite explanation, worked examples and practice.",
    "LOW_VS_CLASS": "Start with prerequisite explanation, worked examples and practice.",
    "DECLINING": "Revisit the most recent topics with worked examples before moving on.",
    "WEAK_TOPIC": "Start with prerequisite explanation, worked examples and practice.",
    "LOW_ATTENDANCE": "This is the attendance figure. A mentor can help if something is getting in the way.",
    "MISSING": "Check this record with the department and ask for a correction if it is wrong.",
    "BACKLOG": "Backlog recovery: syllabus breakdown, prerequisite repair, weekly practice, exam-oriented revision.",
    "THEORY_PRACTICE_GAP": "Add coding labs, guided exercises and debugging tasks.",
    "PREREQ_GAP": "Repair the prerequisite topic first, then return to this topic.",
    "TARGETED_GAP": "Target this topic directly instead of repeating the whole subject.",
    "LOW_EVIDENCE": "Evidence is limited: answer a few questions and take a short concept check before drawing conclusions.",
}

ORDER: list[Level] = ["foundation", "beginner", "intermediate", "advanced"]


def pct(rows: list[Row]) -> float | None:
    """Weighted by max marks, over scored rows only."""
    scored = [r for r in rows if r.score is not None]
    total = sum(r.max for r in scored)
    return None if not total else 100 * sum(r.score for r in scored) / total


def topic_pcts(rows: list[Row]) -> dict[tuple[str, str], tuple[float, int]]:
    """(topic, kind) -> (pct, n) over scored rows, topic != 'All'."""
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in rows:
        if r.topic != "All" and r.score is not None:
            groups[(r.topic, r.kind)].append(r)
    return {k: (pct(v), len(v)) for k, v in groups.items()}


def _n(rows: list[Row]) -> int:
    return sum(1 for r in rows if r.score is not None)


def _r1(x: float) -> float:
    return round(x, 1)


def _tp(rec: StudentRecords) -> dict[tuple[str, str], tuple[float, int]]:
    """(subject, topic) -> (pct, n) over that topic's non-'All' rows of every kind."""
    out: dict[tuple[str, str], tuple[float, int]] = {}
    for s in rec.subjects:
        by_topic: dict[str, list[Row]] = defaultdict(list)
        for r in s.rows:
            if r.topic != "All":
                by_topic[r.topic].append(r)
        for t, rows in by_topic.items():
            p = pct(rows)
            if p is not None:
                out[(s.code, t)] = (p, _n(rows))
    return out


def analyse(rec: StudentRecords, means: dict[str, float], today: date,
            prereqs: dict[tuple[str, str], list[tuple[str, str]]] | None = None) -> list[SubjectSummary]:
    prereqs = prereqs or {}
    tpm = _tp(rec)
    all_rows = [r for s in rec.subjects for r in s.rows]
    overall = pct(all_rows)
    out: list[SubjectSummary] = []
    for s in rec.subjects:
        sp = pct(s.rows)
        n = _n(s.rows)
        flags: list[Flag] = []

        def add(code, reason, values, topic=None):
            flags.append(Flag(code=code, subject_code=s.code, topic=topic, values=values, reason=reason, response=RESPONSES[code]))

        if sp is not None and overall is not None and sp < overall - RULES["self_gap"]:
            add("LOW_VS_SELF", f"{s.name} average {sp:.1f}% vs your overall {overall:.1f}%",
                {"subject_pct": _r1(sp), "overall_pct": _r1(overall), "n": n})
        cm = means.get(s.code)
        if sp is not None and cm is not None and sp < cm - RULES["class_gap"]:
            add("LOW_VS_CLASS", f"{s.name} {sp:.1f}% vs class average {cm:.1f}%",
                {"subject_pct": _r1(sp), "class_mean": _r1(cm), "n": n})
        quizzes = sorted((r for r in s.rows if r.kind == "quiz" and r.score is not None), key=lambda r: (r.taken_on, r.topic))
        if len(quizzes) >= RULES["trend_quizzes"]:
            q = [100 * r.score / r.max for r in quizzes]
            first, last = sum(q[:2]) / 2, sum(q[-2:]) / 2
            if last < first - RULES["decline"]:
                add("DECLINING", f"{s.name} quiz scores fell from {first:.1f}% to {last:.1f}%",
                    {"first_pct": _r1(first), "last_pct": _r1(last), "n": len(quizzes)})
        att = None
        if s.total:
            att = 100 * s.attended / s.total
            if att < RULES["attendance"]:
                add("LOW_ATTENDANCE", f"Attendance {att:.1f}% ({s.attended} of {s.total} classes)",
                    {"pct": _r1(att), "attended": s.attended, "total": s.total, "n": s.total})
        for r in s.rows:
            if r.score is None and r.taken_on <= today:
                add("MISSING", f"{r.kind} on {r.taken_on.isoformat()} has no recorded score",
                    {"kind": r.kind, "taken_on": r.taken_on.isoformat(), "n": 1})
        if any(f.code in ("LOW_VS_SELF", "LOW_VS_CLASS", "DECLINING") for f in flags):
            by_topic: dict[str, list[Row]] = defaultdict(list)
            for r in s.rows:
                if r.topic != "All":
                    by_topic[r.topic].append(r)
            for topic, rows in sorted(by_topic.items()):
                tp = pct(rows)
                if tp is not None and tp < RULES["weak_topic"]:
                    add("WEAK_TOPIC", f"{topic}: {tp:.1f}% across {_n(rows)} assessments",
                        {"pct": _r1(tp), "n": _n(rows)}, topic=topic)
        # --- RB 5.3 signals -------------------------------------------------------------------
        if s.backlog and s.backlog.status == "pending":
            add("BACKLOG", f"Backlog from semester {s.backlog.from_semester} not yet cleared",
                {"from_semester": s.backlog.from_semester, "n": 1})
        labs = [r for r in s.rows if r.kind == "lab" and r.score is not None]
        if len(labs) >= RULES["min_labs"]:
            theory = pct([r for r in s.rows if r.kind in ("quiz", "internal")])
            lab = pct(labs)
            if theory is not None and lab is not None and theory - lab >= RULES["theory_gap"]:
                add("THEORY_PRACTICE_GAP", f"Theory {theory:.0f}% vs lab work {lab:.0f}% ({len(labs)} labs)",
                    {"theory_pct": _r1(theory), "lab_pct": _r1(lab), "n": len(labs)})
        for (code, topic), (tpct, tn) in sorted(tpm.items()):
            if code != s.code or tpct >= RULES["weak_topic"] or tn < 2:
                continue
            pre = prereqs.get((code, topic), [])
            weak = [(tpm[p][0], p) for p in pre if p in tpm and tpm[p][0] < RULES["prereq_weak"]]
            if weak:
                qp, q = min(weak)
                add("PREREQ_GAP", f"{topic} {tpct:.0f}%; its prerequisite {q[1]} is also low at {qp:.0f}%",
                    {"pct": _r1(tpct), "n": tn, "prereq": q[1], "prereq_pct": _r1(qp)}, topic=topic)
            elif pre and all(p in tpm and tpm[p][0] >= RULES["prereq_strong"] for p in pre):
                avg = sum(tpm[p][0] for p in pre) / len(pre)
                add("TARGETED_GAP", f"{topic} {tpct:.0f}% while its prerequisites average {avg:.0f}%",
                    {"pct": _r1(tpct), "n": tn, "prereq_avg": _r1(avg)}, topic=topic)
        if n < RULES["min_evidence"]:
            add("LOW_EVIDENCE", f"Only {n} assessments recorded for {s.name}", {"n": n})
        out.append(SubjectSummary(code=s.code, name=s.name, pct=None if sp is None else _r1(sp),
                                  attendance_pct=None if att is None else _r1(att), n_assessments=n, flags=flags))
    out.sort(key=lambda x: (-len(x.flags), x.pct if x.pct is not None else 101.0))
    return out


def level(basic: int, standard: int, multi: int) -> Level:
    """Concept check: 2 basic, 2 standard, 1 multi-step. Inputs are scores only (RB 5.2): no institution,
    name or other attribute can reach it. It measures only the topic asked about; a prerequisite gap changes
    the plan order (PREREQ_GAP), not this level."""
    total = basic + standard + multi
    if total <= 1:
        return "foundation"
    if basic == 2 and standard == 2 and multi == 1:
        return "advanced"
    if basic >= 1 and standard >= 1 and total >= 3:
        return "intermediate"
    return "beginner"


def level_from_records(pct: float, prereq_gap: bool) -> Level:
    """prereq_gap = PREREQ_GAP on this topic, computed from the same records, so it can never be stale."""
    if pct < 40 or prereq_gap:
        return "foundation"
    if pct < 60:
        return "beginner"
    if pct < 80:
        return "intermediate"
    return "advanced"


@dataclass
class Check:
    topic: str
    level: Level
    on: date
    total: int      # latest submitted check per topic


def topic_levels(rows: list[Row], flags: list[Flag], checks: dict[str, Check], bank_topics: set[str]) -> list[TopicLevel]:
    """Priority: check > records (n >= 2) > unknown. Student overrides are applied by the roadmap module."""
    by_topic: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        if r.topic != "All":
            by_topic[r.topic].append(r)
    gap_topics = {f.topic for f in flags if f.code == "PREREQ_GAP"}
    out: list[TopicLevel] = []
    for topic in sorted(set(by_topic) | set(checks)):
        trows = by_topic.get(topic, [])
        p, n = pct(trows), _n(trows)
        chk = checks.get(topic)
        if chk:
            out.append(TopicLevel(topic=topic, level=chk.level, source="check", as_of=chk.on, n=chk.total, has_check=topic in bank_topics))
        elif p is not None and n >= 2:
            out.append(TopicLevel(topic=topic, level=level_from_records(p, topic in gap_topics), source="records",
                                  as_of=max((r.taken_on for r in trows if r.score is not None), default=None), n=n, has_check=topic in bank_topics))
        else:
            out.append(TopicLevel(topic=topic, level=None, source=None, as_of=None, n=n, has_check=topic in bank_topics))
    out.sort(key=lambda t: (ORDER.index(t.level) if t.level else -1, t.topic))
    return out


def readiness(subjects: list[SubjectSummary], roles: dict[str, list[str]]) -> list[RoleReadiness]:
    """Skill coverage indicator per career role: mean of the student's marks in the role's subjects."""
    by_code = {s.code: s for s in subjects}
    out = []
    for role, codes in roles.items():
        have = [(c, by_code[c].pct) for c in codes if c in by_code and by_code[c].pct is not None]
        if not have:
            out.append(RoleReadiness(role=role, pct=None, weakest_subject=None))
            continue
        out.append(RoleReadiness(role=role, pct=_r1(sum(p for _, p in have) / len(have)), weakest_subject=min(have, key=lambda x: x[1])[0]))
    return out


def upcoming(rec: StudentRecords, today: date) -> list[Upcoming]:
    items = [Upcoming(subject_code=s.code, kind=r.kind, topic=r.topic, on=r.taken_on)
             for s in rec.subjects for r in s.rows if r.score is None and r.taken_on > today]
    return sorted(items, key=lambda u: (u.on, u.subject_code))


def latest_checks(conn, student_id: int) -> dict[tuple[str, str], Check]:
    """Latest submitted concept check per (subject, topic) for the student."""
    rows = conn.execute(
        """SELECT DISTINCT ON (d.subject_id, d.topic) s.code, d.topic, d.level, d.submitted_at::date AS on_, d.total
           FROM diagnostics d JOIN subjects s ON s.id = d.subject_id
           WHERE d.student_id=%s AND d.submitted_at IS NOT NULL ORDER BY d.subject_id, d.topic, d.submitted_at DESC""",
        (student_id,),
    ).fetchall()
    return {(r["code"], r["topic"]): Check(r["topic"], r["level"], r["on_"], r["total"]) for r in rows}


def bank_topics(conn) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for r in conn.execute("SELECT s.code, q.topic FROM questions q JOIN subjects s ON s.id=q.subject_id GROUP BY s.code, q.topic").fetchall():
        out[r["code"]].add(r["topic"])
    return out


def reviews_due(conn, student_id: int, today: date) -> list[int]:
    """Active plans with no review check-in whose review date has come, or where a review import is newer than the plan."""
    last = connector.last_import(conn, "review")
    rows = conn.execute(
        """SELECT r.id, r.review_on, r.created_at FROM roadmaps r
           WHERE r.student_id=%s AND r.status='active' AND NOT EXISTS (SELECT 1 FROM reviews v WHERE v.roadmap_id=r.id)
           ORDER BY r.id""",
        (student_id,),
    ).fetchall()
    return [r["id"] for r in rows if r["review_on"] <= today or (last is not None and r["created_at"] < last)]


def build_profile(conn, student_id: int, batch: str = "baseline", today: date | None = None) -> Profile:
    today = today or date.today()
    rec = connector.get_records(conn, student_id, batch)
    subjects = analyse(rec, connector.class_means(conn, batch), today, prereqs=connector.prereq_map(conn))
    checks, banks = latest_checks(conn, student_id), bank_topics(conn)
    rec_by = {s.code: s for s in rec.subjects}
    for s in subjects:
        s.levels = topic_levels(rec_by[s.code].rows, s.flags,
                                {t: c for (code, t), c in checks.items() if code == s.code}, banks.get(s.code, set()))
    all_rows = [r for s in rec.subjects for r in s.rows]
    overall = pct(all_rows)
    scored_dates = [r.taken_on for r in all_rows if r.score is not None]
    return Profile(
        student=connector.student_info(conn, student_id),
        as_of=max(scored_dates) if scored_dates else None,
        imported_at=connector.last_import(conn, batch),
        overall_pct=None if overall is None else _r1(overall),
        subjects=subjects,
        upcoming=upcoming(rec, today),
        roles=readiness(subjects, connector.role_map(conn)),
        backlogs=[Backlog(subject_code=s.code, subject_name=s.name, from_semester=s.backlog.from_semester, status=s.backlog.status)
                  for s in rec.subjects if s.backlog],
        reviews_due=reviews_due(conn, student_id, today) if batch == "baseline" else [],
    )


@router.get("/me/profile", response_model=Profile)
def profile(s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    p = build_profile(conn, s.student_id)
    db.audit(conn, f"student:{s.student_id}", "profile_view")
    conn.commit()
    return p
