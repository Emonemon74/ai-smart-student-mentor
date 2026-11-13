"""C3: data connector. The only code that knows where academic data comes from (LLD C3).
Replacing CSV import with a university API changes only this file."""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from psycopg.types.json import Jsonb

from app.schemas import Resource, StudentInfo

PERMITTED = ("programme", "semester", "subjects", "assessments", "attendance", "backlogs")  # shown on the consent screen
KINDS = {"quiz", "internal", "assignment", "lab"}
RES_KINDS = {"video", "article", "practice", "course"}
BATCHES = {"baseline", "review"}

# The bundled synthetic data was generated "as of" this date (seed/ANCHOR, written by seed/gen.py): its upcoming
# internal (SEED_UPCOMING) is 11 days after it. Dates are fixed in the CSVs, so left alone they go stale:
# once the clock passes SEED_UPCOMING every student would get a "missing mark" flag in every subject. Importing the
# bundled seed therefore moves every date forward by the days elapsed since SEED_ANCHOR (never backwards).
SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
_ANCHOR_FILE = SEED_DIR / "ANCHOR"
SEED_ANCHOR = date.fromisoformat(_ANCHOR_FILE.read_text().strip()) if _ANCHOR_FILE.exists() else date(2026, 11, 10)
SEED_UPCOMING = SEED_ANCHOR + timedelta(days=11)    # seed/gen.py: the upcoming internal is ANCHOR + 11 days


def seed_shift_days(today: date | None = None) -> int:
    """Days to move the bundled seed dates forward so that its upcoming internal is still in the future."""
    return max(0, ((today or date.today()) - SEED_ANCHOR).days)


@dataclass
class Row:
    topic: str
    kind: str
    score: float | None
    max: float
    taken_on: date


@dataclass
class BacklogRow:
    from_semester: int
    status: str


@dataclass
class SubjectRecords:
    code: str
    name: str
    rows: list[Row] = field(default_factory=list)
    attended: int | None = None
    total: int | None = None
    kind: str = "course"
    backlog: BacklogRow | None = None


@dataclass
class ResourceRow:
    """Internal row; the API model `Resource` omits goals and link_ok."""
    id: int
    topic: str
    title: str
    url: str
    kind: str
    level: str
    lang: str
    minutes: int
    goals: list[str]
    link_ok: bool

    def api(self) -> Resource:
        return Resource(id=self.id, topic=self.topic, title=self.title, url=self.url, kind=self.kind, level=self.level,
                        lang=self.lang, minutes=self.minutes, source=urlparse(self.url).netloc.removeprefix("www."))


@dataclass
class StudentRecords:
    student_id: int
    subjects: list[SubjectRecords]


# ---- import ------------------------------------------------------------------------------------
GOAL_CODES = {"semester", "backlog", "gate", "upsc", "placement", "higher_studies"}
LEVELS = {"foundation", "beginner", "intermediate", "advanced"}
TIERS = {"basic", "standard", "multi"}


def _read(folder: Path, name: str, required: bool = True) -> list[dict]:
    p = folder / name
    if not p.exists():
        if required:
            raise FileNotFoundError(p)
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v: str, what: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number: {v!r}")


def _cycle(edges: list[tuple[tuple[str, str], tuple[str, str]]]) -> tuple[str, str] | None:
    """DFS over (subject, topic) nodes; returns a node on a cycle, or None."""
    graph: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
    state: dict[tuple[str, str], int] = {}

    def visit(n):
        state[n] = 1
        for m in graph.get(n, []):
            if state.get(m) == 1:
                return m
            if state.get(m) is None:
                hit = visit(m)
                if hit:
                    return hit
        state[n] = 2
        return None

    for n in list(graph):
        if state.get(n) is None:
            hit = visit(n)
            if hit:
                return hit
    return None


def import_csv(conn, folder: Path, batch: Literal["baseline", "review"], shift_days: int = 0) -> dict:
    """Validate every row first. Any rejected row aborts the whole batch: nothing is written and the
    errors are recorded in a separate transaction (LLD_next F4). `shift_days` moves every assessment date
    forward; it is only ever non-zero for the bundled synthetic seed. Unknown extra columns are ignored
    and never stored (this is how an `institution` column is dropped, RB 5.2)."""
    from app import auth, config  # PIN hashing lives with auth; called through the module so tests can patch it

    folder = Path(folder)
    errors: list[dict] = []
    counts: dict[str, int] = {}

    def bad(file: str, line: int, msg: str) -> None:
        errors.append({"file": file, "line": line, "error": msg})

    sub_rows: list[tuple] = []
    stu_rows: list[dict] = []
    res_rows: list[tuple] = []
    role_rows: list[tuple] = []
    pre_rows: list[tuple] = []
    q_rows: list[tuple] = []

    known_subjects = {x["code"] for x in conn.execute("SELECT code FROM subjects").fetchall()}
    known_students = {x["roll_no"] for x in conn.execute("SELECT roll_no FROM students").fetchall()}

    if batch == "baseline":
        for i, r in enumerate(_read(folder, "subjects.csv"), start=2):
            code, name = (r.get("code") or "").strip(), (r.get("name") or "").strip()
            kind = (r.get("kind") or "course").strip() or "course"
            if not code or not name or kind not in ("course", "track"):
                bad("subjects.csv", i, "code and name are required; kind is course or track"); continue
            sub_rows.append((code, name, kind))
            known_subjects.add(code)
        for i, r in enumerate(_read(folder, "students.csv"), start=2):
            try:
                roll = r["roll_no"].strip().upper()
                if not roll or not r["name"].strip() or not r["programme"].strip():
                    raise ValueError("roll_no, name and programme are required")
                sem = int(r["semester"])
                pin = r["pin"].strip()
                if not (pin.isdigit() and 4 <= len(pin) <= 6):
                    raise ValueError("pin must be 4-6 digits")
            except (KeyError, ValueError) as e:
                bad("students.csv", i, str(e)); continue
            stu_rows.append({"roll": roll, "name": r["name"].strip(), "programme": r["programme"].strip(), "sem": sem, "pin": pin})
            known_students.add(roll)

        topics_by_subject: dict[str, set[str]] = {}
        seen_urls: set[str] = set()
        for i, r in enumerate(_read(folder, "resources.csv"), start=2):
            try:
                code = (r.get("subject_code") or "").strip()
                if code not in known_subjects:
                    raise ValueError(f"unknown subject_code {code!r}")
                url = r["url"].strip()
                if r["kind"] not in RES_KINDS or not url or not r["title"].strip() or not r["topic"].strip():
                    raise ValueError("invalid kind, or missing topic/title/url")
                host = urlparse(url).netloc
                if not config.approved_host(host):
                    raise ValueError(f"host {host!r} is not on the approved domain list")
                level = (r.get("level") or "beginner").strip()
                lang = (r.get("lang") or "en").strip()
                if level not in LEVELS or lang not in ("en", "hi"):
                    raise ValueError("level or lang is not valid")
                minutes = int((r.get("minutes") or "30").strip())
                if not (5 <= minutes <= 600):
                    raise ValueError("minutes must be 5..600")
                goals = [g.strip() for g in (r.get("goals") or "").split(";") if g.strip()]
                if any(g not in GOAL_CODES for g in goals):
                    raise ValueError("unknown goal code")
                if url in seen_urls:
                    raise ValueError("duplicate url")
                seen_urls.add(url)
            except (KeyError, ValueError) as e:
                bad("resources.csv", i, str(e)); continue
            topics_by_subject.setdefault(code, set()).add(r["topic"].strip())
            res_rows.append((code, r["topic"].strip(), r["title"].strip(), url, r["kind"], level, lang, minutes, goals))

        for i, r in enumerate(_read(folder, "roles.csv"), start=2):
            code = (r.get("subject_code") or "").strip()
            if code not in known_subjects or not (r.get("role") or "").strip():
                bad("roles.csv", i, "unknown subject_code or missing role"); continue
            role_rows.append((r["role"].strip(), code))

        edges = []
        for i, r in enumerate(_read(folder, "prereqs.csv", required=False), start=2):
            a, b = ((r.get("subject_code") or "").strip(), (r.get("topic") or "").strip()), ((r.get("prereq_subject_code") or "").strip(), (r.get("prereq_topic") or "").strip())
            if a[0] not in known_subjects or b[0] not in known_subjects or not a[1] or not b[1]:
                bad("prereqs.csv", i, "unknown subject or missing topic"); continue
            if a == b:
                bad("prereqs.csv", i, "a topic cannot be its own prerequisite"); continue
            edges.append((a, b))
            pre_rows.append((a[0], a[1], b[0], b[1]))
        hit = _cycle(edges)
        if hit:
            bad("prereqs.csv", 1, f"prerequisite cycle through {hit[0]}/{hit[1]}")

        seen_q: set[tuple] = set()
        for i, r in enumerate(_read(folder, "questions.csv", required=False), start=2):
            try:
                code, topic, stem = (r.get("subject_code") or "").strip(), (r.get("topic") or "").strip(), (r.get("stem") or "").strip()
                if code not in known_subjects:
                    raise ValueError(f"unknown subject_code {code!r}")
                if (r.get("tier") or "").strip() not in TIERS:
                    raise ValueError("tier must be basic, standard or multi")
                opts = [(r.get(f"option_{c}") or "").strip() for c in "abcd"]
                if not all(opts) or len(set(opts)) != 4:
                    raise ValueError("need 4 non-empty, distinct options")
                ans = (r.get("answer") or "").strip().lower()
                if ans not in ("a", "b", "c", "d"):
                    raise ValueError("answer must be a-d")
                if not stem or not (r.get("explanation") or "").strip() or not (r.get("reviewed_by") or "").strip():
                    raise ValueError("stem, explanation and reviewed_by are required")
                if topic not in topics_by_subject.get(code, set()):
                    raise ValueError(f"topic {topic!r} has no resource in {code}")
                if (code, topic, stem) in seen_q:
                    raise ValueError("duplicate question")
                seen_q.add((code, topic, stem))
            except (KeyError, ValueError) as e:
                bad("questions.csv", i, str(e)); continue
            q_rows.append((code, topic, r["tier"].strip(), stem, opts, "abcd".index(ans), r["explanation"].strip(), r["reviewed_by"].strip()))

    # assessments: only rows of the requested batch; other batches are ignored, not errors
    good_ass, seen = [], set()
    for i, r in enumerate(_read(folder, "assessments.csv"), start=2):
        if r.get("batch") not in BATCHES:
            bad("assessments.csv", i, f"batch must be one of {sorted(BATCHES)}"); continue
        if r["batch"] != batch:
            continue
        try:
            roll, code = r["roll_no"].strip().upper(), r["subject_code"].strip()
            if roll not in known_students:
                raise ValueError(f"unknown roll_no {roll!r}")
            if code not in known_subjects:
                raise ValueError(f"unknown subject_code {code!r}")
            if r["kind"] not in KINDS:
                raise ValueError(f"kind must be one of {sorted(KINDS)}")
            if not r["topic"].strip():
                raise ValueError("topic is required")
            mx = _num(r["max"], "max")
            if mx <= 0:
                raise ValueError("max must be > 0")
            score = None if (r["score"] or "").strip() == "" else _num(r["score"], "score")
            if score is not None and not (0 <= score <= mx):
                raise ValueError(f"score {score:g} is outside 0..{mx:g}")
            on = date.fromisoformat(r["taken_on"].strip()) + timedelta(days=shift_days)
            key = (roll, code, r["topic"].strip(), r["kind"], on, batch)
            if key in seen:
                raise ValueError("duplicate row")
            seen.add(key)
        except (KeyError, ValueError) as e:
            bad("assessments.csv", i, str(e)); continue
        good_ass.append((roll, code, r["topic"].strip(), r["kind"], score, mx, on, batch))

    good_att, seen_att = [], set()
    for i, r in enumerate(_read(folder, "attendance.csv"), start=2):
        if r.get("batch") not in BATCHES:
            bad("attendance.csv", i, f"batch must be one of {sorted(BATCHES)}"); continue
        if r["batch"] != batch:
            continue
        try:
            roll, code = r["roll_no"].strip().upper(), r["subject_code"].strip()
            if roll not in known_students:
                raise ValueError(f"unknown roll_no {roll!r}")
            if code not in known_subjects:
                raise ValueError(f"unknown subject_code {code!r}")
            attended, total = int(r["attended"]), int(r["total"])
            if total <= 0 or not (0 <= attended <= total):
                raise ValueError("need total > 0 and 0 <= attended <= total")
            if (roll, code) in seen_att:
                raise ValueError("duplicate row")
            seen_att.add((roll, code))
        except (KeyError, ValueError) as e:
            bad("attendance.csv", i, str(e)); continue
        good_att.append((roll, code, batch, attended, total))

    good_back, seen_back = [], set()
    for i, r in enumerate(_read(folder, "backlogs.csv", required=False), start=2):
        if r.get("batch") not in BATCHES:
            bad("backlogs.csv", i, f"batch must be one of {sorted(BATCHES)}"); continue
        if r["batch"] != batch:
            continue
        try:
            roll, code = r["roll_no"].strip().upper(), r["subject_code"].strip()
            if roll not in known_students:
                raise ValueError(f"unknown roll_no {roll!r}")
            if code not in known_subjects:
                raise ValueError(f"unknown subject_code {code!r}")
            if r["status"] not in ("pending", "cleared"):
                raise ValueError("status must be pending or cleared")
            sem = int(r["from_semester"])
            if sem < 1:
                raise ValueError("from_semester must be >= 1")
            if (roll, code) in seen_back:
                raise ValueError("duplicate row")
            seen_back.add((roll, code))
        except (KeyError, ValueError) as e:
            bad("backlogs.csv", i, str(e)); continue
        good_back.append((roll, code, sem, r["status"], batch))

    if errors:   # F4: any rejected row aborts the batch; nothing is written
        conn.rollback()
        counts["rejected"] = len(errors)
        conn.execute("INSERT INTO imports (batch, counts, errors) VALUES (%s, %s, %s)", (batch, Jsonb(counts), Jsonb(errors)))
        conn.commit()
        return {"batch": batch, "counts": counts, "errors": errors}

    # one transaction: subjects -> students -> resources -> prereqs -> questions -> batch data
    if batch == "baseline":
        for code, name, kind in sub_rows:
            conn.execute("INSERT INTO subjects (code, name, kind) VALUES (%s, %s, %s) ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, kind=EXCLUDED.kind", (code, name, kind))
        counts["subjects"] = len(sub_rows)
        existing = {x["roll_no"] for x in conn.execute("SELECT roll_no FROM students").fetchall()}
        for s in stu_rows:
            if s["roll"] in existing:
                conn.execute("UPDATE students SET name=%s, programme=%s, semester=%s WHERE roll_no=%s", (s["name"], s["programme"], s["sem"], s["roll"]))
            else:
                conn.execute("INSERT INTO students (roll_no, name, programme, semester, pin_hash) VALUES (%s, %s, %s, %s, %s)",
                             (s["roll"], s["name"], s["programme"], s["sem"], auth.hash_pin(s["pin"])))
                existing.add(s["roll"])
        counts["students"] = len(stu_rows)
    students = {x["roll_no"]: x["id"] for x in conn.execute("SELECT id, roll_no FROM students").fetchall()}
    subjects = {x["code"]: x["id"] for x in conn.execute("SELECT id, code FROM subjects").fetchall()}

    if batch == "baseline":
        for code, topic, title, url, kind, level, lang, minutes, goals in res_rows:
            conn.execute(
                """INSERT INTO resources (subject_id, topic, title, url, kind, level, lang, minutes, goals) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (url) DO UPDATE SET subject_id=EXCLUDED.subject_id, topic=EXCLUDED.topic, title=EXCLUDED.title, kind=EXCLUDED.kind,
                   level=EXCLUDED.level, lang=EXCLUDED.lang, minutes=EXCLUDED.minutes, goals=EXCLUDED.goals""",
                (subjects[code], topic, title, url, kind, level, lang, minutes, goals))
        counts["resources"] = len(res_rows)
        for role, code in role_rows:
            conn.execute("INSERT INTO role_subjects (role, subject_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (role, subjects[code]))
        counts["roles"] = len(role_rows)
        conn.execute("DELETE FROM topic_prereqs")
        for a, at, b, bt in pre_rows:
            conn.execute("INSERT INTO topic_prereqs (subject_id, topic, prereq_subject_id, prereq_topic) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (subjects[a], at, subjects[b], bt))
        counts["prereqs"] = len(pre_rows)
        for code, topic, tier, stem, opts, ans, expl, by in q_rows:   # upsert: ids stay stable for past diagnostics
            conn.execute(
                """INSERT INTO questions (subject_id, topic, tier, stem, options, answer, explanation, reviewed_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (subject_id, topic, stem) DO UPDATE SET tier=EXCLUDED.tier, options=EXCLUDED.options, answer=EXCLUDED.answer,
                   explanation=EXCLUDED.explanation, reviewed_by=EXCLUDED.reviewed_by""",
                (subjects[code], topic, tier, stem, Jsonb(opts), ans, expl, by))
        counts["questions"] = len(q_rows)

    # synchronise: replace this batch only
    conn.execute("DELETE FROM assessments WHERE batch=%s", (batch,))
    conn.execute("DELETE FROM attendance WHERE batch=%s", (batch,))
    conn.execute("DELETE FROM backlogs WHERE batch=%s", (batch,))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO assessments (student_id, subject_id, topic, kind, score, max, taken_on, batch) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(students[a], subjects[b], *rest) for a, b, *rest in good_ass])
        cur.executemany("INSERT INTO attendance (student_id, subject_id, batch, attended, total) VALUES (%s,%s,%s,%s,%s)",
                        [(students[a], subjects[b], *rest) for a, b, *rest in good_att])
        cur.executemany("INSERT INTO backlogs (student_id, subject_id, from_semester, status, batch) VALUES (%s,%s,%s,%s,%s)",
                        [(students[a], subjects[b], *rest) for a, b, *rest in good_back])
    counts["assessments"], counts["attendance"], counts["backlogs"] = len(good_ass), len(good_att), len(good_back)

    conn.execute("INSERT INTO imports (batch, counts, errors) VALUES (%s, %s, %s)", (batch, Jsonb(counts), Jsonb(errors)))
    conn.execute("INSERT INTO audit_log (actor, action, target) VALUES ('system', 'import', %s)", (batch,))
    conn.commit()
    return {"batch": batch, "counts": counts, "errors": errors}


# ---- read access ---------------------------------------------------------------------------------
def get_records(conn, student_id: int, batch: str = "baseline") -> StudentRecords:
    subs: dict[str, SubjectRecords] = {}
    for r in conn.execute(
        """SELECT s.code, s.name, a.topic, a.kind, a.score, a.max, a.taken_on FROM assessments a
           JOIN subjects s ON s.id = a.subject_id WHERE a.student_id=%s AND a.batch=%s ORDER BY s.code, a.taken_on, a.topic""",
        (student_id, batch),
    ).fetchall():
        rec = subs.setdefault(r["code"], SubjectRecords(r["code"], r["name"]))
        rec.rows.append(Row(r["topic"], r["kind"], None if r["score"] is None else float(r["score"]), float(r["max"]), r["taken_on"]))
    for r in conn.execute(
        "SELECT s.code, s.name, a.attended, a.total FROM attendance a JOIN subjects s ON s.id=a.subject_id WHERE a.student_id=%s AND a.batch=%s",
        (student_id, batch),
    ).fetchall():
        rec = subs.setdefault(r["code"], SubjectRecords(r["code"], r["name"]))
        rec.attended, rec.total = r["attended"], r["total"]
    for r in conn.execute(
        "SELECT s.code, s.name, b.from_semester, b.status FROM backlogs b JOIN subjects s ON s.id=b.subject_id WHERE b.student_id=%s AND b.batch=%s",
        (student_id, batch),
    ).fetchall():
        rec = subs.setdefault(r["code"], SubjectRecords(r["code"], r["name"]))
        rec.backlog = BacklogRow(r["from_semester"], r["status"])
    return StudentRecords(student_id, sorted(subs.values(), key=lambda x: x.code))


def class_means(conn, batch: str = "baseline") -> dict[str, float]:
    """subject_code -> class percentage (sum of marks over sum of max, scored rows only)."""
    rows = conn.execute(
        """SELECT s.code, 100.0 * SUM(a.score) / SUM(a.max) AS pct FROM assessments a JOIN subjects s ON s.id=a.subject_id
           WHERE a.batch=%s AND a.score IS NOT NULL GROUP BY s.code""",
        (batch,),
    ).fetchall()
    return {r["code"]: float(r["pct"]) for r in rows}


def get_resources(conn, subject_code: str) -> list[ResourceRow]:
    rows = conn.execute(
        """SELECT r.id, r.topic, r.title, r.url, r.kind, r.level, r.lang, r.minutes, r.goals, r.link_ok
           FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code=%s ORDER BY r.topic, r.id""",
        (subject_code,),
    ).fetchall()
    return [ResourceRow(**r) for r in rows]


def prereq_map(conn) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """(subject_code, topic) -> its prerequisites [(subject_code, topic)]."""
    out: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for r in conn.execute(
        """SELECT s.code AS code, p.topic, ps.code AS pcode, p.prereq_topic FROM topic_prereqs p
           JOIN subjects s ON s.id=p.subject_id JOIN subjects ps ON ps.id=p.prereq_subject_id ORDER BY 1, 2, 3, 4"""
    ).fetchall():
        out.setdefault((r["code"], r["topic"]), []).append((r["pcode"], r["prereq_topic"]))
    return out


def subject_kind(conn, code: str) -> str | None:
    r = conn.execute("SELECT kind FROM subjects WHERE code=%s", (code,)).fetchone()
    return r["kind"] if r else None


def check_links(conn, client=None) -> list[dict]:
    """RB 7 link safety: HEAD (GET when HEAD is refused) every resource, follow redirects, and mark the link
    broken if it fails or ends on a host that is not approved. Returns the broken ones."""
    import httpx
    from app import config, db

    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=10, headers={"User-Agent": "campus-kiosk-linkcheck"})
    broken: list[dict] = []
    rows = conn.execute("SELECT id, url FROM resources ORDER BY id").fetchall()
    try:
        for r in rows:
            try:
                resp = client.head(r["url"])
                if resp.status_code in (403, 405):
                    resp = client.get(r["url"])
                ok = resp.status_code < 400 and config.approved_host(resp.url.host or "")
            except httpx.HTTPError:
                ok = False
            conn.execute("UPDATE resources SET link_ok=%s, checked_on=%s WHERE id=%s", (ok, date.today(), r["id"]))
            if not ok:
                broken.append({"id": r["id"], "url": r["url"]})
    finally:
        if own:
            client.close()
    db.audit(conn, "system", "link_check", f"{len(broken)}/{len(rows)}")
    conn.commit()
    return broken


def role_map(conn) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in conn.execute("SELECT rs.role, s.code FROM role_subjects rs JOIN subjects s ON s.id=rs.subject_id ORDER BY rs.role, s.code").fetchall():
        out.setdefault(r["role"], []).append(r["code"])
    return out


def student_info(conn, student_id: int) -> StudentInfo:
    r = conn.execute("SELECT roll_no, name, programme, semester FROM students WHERE id=%s", (student_id,)).fetchone()
    return StudentInfo(**r)


def last_import(conn, batch: str) -> datetime | None:
    r = conn.execute("SELECT max(imported_at) AS t FROM imports WHERE batch=%s", (batch,)).fetchone()
    return r["t"] if r else None


# ---- CLI: uv run python -m app.connector import seed --batch baseline|review -------------------
def _load_env_file(path: Path | None = None) -> None:
    p = path or Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split(" #")[0].strip())   # F7: strip an inline " #" comment, like bash


def end_semester(conn) -> int:
    """Retention (HLD 9): plans are cleared at semester end. Deleting roadmaps cascades to tasks and share tokens."""
    from app import db

    conn.execute("DELETE FROM sessions WHERE kind='phone'")
    n = conn.execute("DELETE FROM roadmaps").rowcount
    conn.execute("DELETE FROM diagnostics")
    db.audit(conn, "staff", "plans_delete", f"semester_end:{n}")
    conn.commit()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.connector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("folder")
    imp.add_argument("--batch", choices=sorted(BATCHES), required=True)
    imp.add_argument("--exact-dates", action="store_true",
                     help="keep the CSV dates as they are (by default the bundled seed is moved forward to today)")
    sub.add_parser("end-semester", help="HLD 9: clear all saved plans, tasks, share links and phone sessions")
    sub.add_parser("check-links", help="RB 7: check every approved resource link; broken ones are excluded from recommendations")
    args = ap.parse_args(argv)

    _load_env_file()
    from app import db

    db.init()
    if args.cmd == "end-semester":
        try:
            with db.pool.connection() as conn:
                n = end_semester(conn)
        finally:
            db.close()
        print(f"end of semester: removed {n} plans (tasks and share links cascade), phone sessions cleared")
        return 0
    if args.cmd == "check-links":
        try:
            with db.pool.connection() as conn:
                broken = check_links(conn)
        finally:
            db.close()
        for b in broken:
            print(f"  BROKEN [{b['id']}] {b['url']}")
        print(f"link check done: {len(broken)} broken")
        return 1 if broken else 0
    folder = Path(args.folder)
    is_bundled_seed = folder.resolve() == SEED_DIR.resolve()
    shift = 0 if args.exact_dates or not is_bundled_seed else seed_shift_days()
    try:
        with db.pool.connection() as conn:
            result = import_csv(conn, folder, args.batch, shift_days=shift)
    finally:
        db.close()
    print(f"imported batch={result['batch']} counts={result['counts']}")
    if shift:
        print(f"  synthetic dates moved forward {shift} day(s) so the data is current (use --exact-dates to keep the CSV dates)")
    for e in result["errors"]:
        print(f"  REJECTED {e['file']} line {e['line']}: {e['error']}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
