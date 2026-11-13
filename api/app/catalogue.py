"""C16: read-only catalogue (goals, resources, support contacts), goal eligibility and the resource matcher
(LLD_next C16). No writes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from app import auth, connector, db
from app.connector import ResourceRow
from app.schemas import Contact, Goal, GoalSubject, Level, Resource

router = APIRouter(prefix="/api")

ORDER: list[Level] = ["foundation", "beginner", "intermediate", "advanced"]
CONTACTS_FILE = Path(__file__).resolve().parent.parent / "seed" / "contacts.json"


@dataclass(frozen=True)
class GoalDef:
    name: str
    name_hi: str
    components: str
    indicators: str
    indicator_codes: tuple[str, ...]
    subjects: tuple[str, ...]
    needs_backlog: bool = False
    needs_target_date: bool = False


COURSES = ("DSA", "DBMS", "OS", "CN", "DM")
GOALS: dict[str, GoalDef] = {      # RB 6; dict order = display order
    "semester": GoalDef(
        "Semester improvement", "सेमेस्टर सुधार",
        "Weak subjects, topic sequence, assignments, revision and internal-exam preparation",
        "Topic quiz scores, assignment completion and comparable assessment marks",
        ("verified_change", "check_accuracy", "task_completion"), COURSES),
    "backlog": GoalDef(
        "Backlog recovery", "बैकलॉग रिकवरी",
        "Syllabus breakdown, prerequisite repair, weekly practice and exam-oriented revision",
        "Coverage, mock-test scores and exam result",
        ("topic_coverage", "verified_change", "check_accuracy"), COURSES, needs_backlog=True, needs_target_date=True),
    "gate": GoalDef(
        "GATE preparation", "गेट की तैयारी",
        "Subject-wise foundation, standard problems, previous-year questions and mock tests",
        "Accuracy, time per question and mock-test trend",
        ("check_accuracy", "check_speed", "verified_change"), COURSES, needs_target_date=True),
    "upsc": GoalDef(
        "UPSC preparation", "यूपीएससी की तैयारी",
        "Foundation reading, syllabus mapping, current affairs routine, revision and answer writing",
        "Topic coverage, revision consistency and practice quality",
        ("topic_coverage", "task_completion"), ("UPSC",), needs_target_date=True),
    "placement": GoalDef(
        "Placement / coding", "प्लेसमेंट / कोडिंग",
        "Programming fundamentals, DSA, projects, aptitude and interview practice",
        "Problem-solving accuracy, project milestones and mock interview feedback",
        ("check_accuracy", "checkpoints_done", "task_completion"), ("DSA", "DBMS", "OS", "APT")),
    "higher_studies": GoalDef(
        "Higher studies / research", "उच्च अध्ययन / अनुसंधान",
        "Core subject strengthening, research reading, tools and project milestones",
        "Reading notes, experiment milestones and project outputs",
        ("checkpoints_done", "topic_coverage"), COURSES),
}


def eligible_subjects(conn, student_id: int | None, goal: str) -> list[GoalSubject]:
    """GOALS[goal].subjects intersected with: tracks, plus the subjects the student has records for; for the
    backlog goal only subjects with a pending baseline backlog. student_id None (general mode): all of them."""
    g = GOALS[goal]
    existing = {r["code"]: r for r in conn.execute("SELECT code, name, kind FROM subjects").fetchall()}
    have: set[str] | None = None
    pending: set[str] = set()
    if student_id is not None:
        rec = connector.get_records(conn, student_id)
        have = {s.code for s in rec.subjects if s.rows or s.total}
        pending = {s.code for s in rec.subjects if s.backlog and s.backlog.status == "pending"}
    out = []
    for code in g.subjects:
        r = existing.get(code)
        if r is None:
            continue
        if student_id is not None:
            if r["kind"] == "course" and code not in have:
                continue
            if g.needs_backlog and code not in pending:
                continue
        out.append(GoalSubject(code=code, name=r["name"], kind=r["kind"]))
    return out


def pick_resources(resources: list[ResourceRow], *, goal: str | None, levels: dict[str, Level | None],
                   lang: str, daily_minutes: int | None) -> list[ResourceRow]:
    """Level window: one level below to two above the student's. Language: the student's, then English.
    Time: a resource must fit the daily budget (courses are multi-session). A topic is never left empty."""
    def fits(r: ResourceRow) -> bool:
        if not r.link_ok:
            return False
        if r.goals and goal not in r.goals:
            return False
        if r.lang not in (lang, "en"):
            return False
        if daily_minutes and r.minutes > daily_minutes and r.kind != "course":
            return False
        lv = levels.get(r.topic)
        if lv and not (ORDER.index(lv) - 1 <= ORDER.index(r.level) <= ORDER.index(lv) + 2):
            return False
        return True

    out = [r for r in resources if fits(r)]
    for topic in {r.topic for r in resources} - {r.topic for r in out}:     # never leave a topic empty
        out += [r for r in resources if r.topic == topic and r.link_ok and (not r.goals or goal in r.goals)]

    def key(r: ResourceRow):
        lv = levels.get(r.topic) or r.level
        return (r.topic, r.lang != lang, abs(ORDER.index(r.level) - ORDER.index(lv)), r.minutes)

    return sorted(out, key=key)


@cache
def _contacts() -> tuple[Contact, ...]:
    return tuple(Contact(**c) for c in json.loads(CONTACTS_FILE.read_text(encoding="utf-8")))


def contacts(teams: set[str] | None = None) -> list[Contact]:
    return [c for c in _contacts() if teams is None or c.team in teams]


# ---- endpoints ---------------------------------------------------------------------------------
@router.get("/goals", response_model=list[Goal])
def goals(s: auth.Session = Depends(auth.guided), conn=Depends(db.get_conn)):
    sid = s.student_id if s.mode == "personal" else None
    return [Goal(code=code, name=g.name, name_hi=g.name_hi, components=g.components, indicators=g.indicators,
                 needs_target_date=g.needs_target_date, subjects=eligible_subjects(conn, sid, code))
            for code, g in GOALS.items()]


@router.get("/resources", response_model=list[Resource])
def resources(subject_code: str, goal: str | None = None, topic: str | None = None,
              max_minutes: int | None = Query(default=None, ge=5, le=600), lang: str = Query(default="en", pattern="^(en|hi)$"),
              s: auth.Session = Depends(auth.guided), conn=Depends(db.get_conn)):
    if connector.subject_kind(conn, subject_code) is None:
        raise HTTPException(404, "not_found")
    if goal is not None and goal not in GOALS:
        raise HTTPException(404, "not_found")
    levels: dict[str, Level | None] = {}
    if s.mode == "personal":
        from app import analytics
        prof = analytics.build_profile(conn, s.student_id)
        summ = next((x for x in prof.subjects if x.code == subject_code), None)
        levels = {t.topic: t.level for t in summ.levels} if summ else {}
    rows = connector.get_resources(conn, subject_code)
    if topic:
        rows = [r for r in rows if r.topic == topic]
    return [r.api() for r in pick_resources(rows, goal=goal, levels=levels, lang=lang, daily_minutes=max_minutes)]


@router.get("/support/contacts", response_model=list[Contact])
def support_contacts():
    return contacts()
