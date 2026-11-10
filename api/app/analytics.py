"""C4: academic analytics. Pure, explainable rules; the router is a thin wrapper (LLD C4)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends

from app import auth, connector, db
from app.connector import Row, StudentRecords
from app.schemas import Flag, Profile, RoleReadiness, SubjectSummary, Upcoming

router = APIRouter(prefix="/api")

RULES = {"self_gap": 10, "class_gap": 10, "decline": 10, "trend_quizzes": 4, "attendance": 75, "weak_topic": 50}  # faculty-tunable


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


def analyse(rec: StudentRecords, means: dict[str, float], today: date) -> list[SubjectSummary]:
    all_rows = [r for s in rec.subjects for r in s.rows]
    overall = pct(all_rows)
    out: list[SubjectSummary] = []
    for s in rec.subjects:
        sp = pct(s.rows)
        n = _n(s.rows)
        flags: list[Flag] = []

        def add(code, reason, values, topic=None):
            flags.append(Flag(code=code, subject_code=s.code, topic=topic, values=values, reason=reason))

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
        out.append(SubjectSummary(code=s.code, name=s.name, pct=None if sp is None else _r1(sp),
                                  attendance_pct=None if att is None else _r1(att), n_assessments=n, flags=flags))
    out.sort(key=lambda x: (-len(x.flags), x.pct if x.pct is not None else 101.0))
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


def build_profile(conn, student_id: int, batch: str = "baseline", today: date | None = None) -> Profile:
    today = today or date.today()
    rec = connector.get_records(conn, student_id, batch)
    subjects = analyse(rec, connector.class_means(conn, batch), today)
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
    )


@router.get("/me/profile", response_model=Profile)
def profile(s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    p = build_profile(conn, s.student_id)
    db.audit(conn, f"student:{s.student_id}", "profile_view")
    conn.commit()
    return p
