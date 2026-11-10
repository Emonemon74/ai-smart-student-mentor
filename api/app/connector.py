"""C3: data connector. The only code that knows where academic data comes from (LLD C3).
Replacing CSV import with a university API changes only this file."""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from psycopg.types.json import Jsonb

from app.schemas import Resource, StudentInfo

PERMITTED = ("programme", "semester", "subjects", "assessments", "attendance")  # shown on the consent screen
KINDS = {"quiz", "internal", "assignment"}
RES_KINDS = {"video", "article", "practice", "course"}
BATCHES = {"baseline", "review"}


@dataclass
class Row:
    topic: str
    kind: str
    score: float | None
    max: float
    taken_on: date


@dataclass
class SubjectRecords:
    code: str
    name: str
    rows: list[Row] = field(default_factory=list)
    attended: int | None = None
    total: int | None = None


@dataclass
class StudentRecords:
    student_id: int
    subjects: list[SubjectRecords]


# ---- import ------------------------------------------------------------------------------------
def _read(folder: Path, name: str) -> list[dict]:
    with open(folder / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v: str, what: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number: {v!r}")


def import_csv(conn, folder: Path, batch: Literal["baseline", "review"]) -> dict:
    """Validate every row first, skip invalid ones, write the rest in one transaction."""
    from app import auth  # PIN hashing lives with auth; called through the module so tests can patch it

    folder = Path(folder)
    errors: list[dict] = []
    counts: dict[str, int] = {}

    def bad(file: str, line: int, msg: str) -> None:
        errors.append({"file": file, "line": line, "error": msg})

    if batch == "baseline":
        # subjects
        n = 0
        for i, r in enumerate(_read(folder, "subjects.csv"), start=2):
            if not (r.get("code") or "").strip() or not (r.get("name") or "").strip():
                bad("subjects.csv", i, "code and name are required"); continue
            conn.execute("INSERT INTO subjects (code, name) VALUES (%s, %s) ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name", (r["code"].strip(), r["name"].strip()))
            n += 1
        counts["subjects"] = n

        # students (PIN hashed on import; an existing student keeps their hash)
        existing = {x["roll_no"] for x in conn.execute("SELECT roll_no FROM students").fetchall()}
        n = 0
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
            if roll in existing:
                conn.execute("UPDATE students SET name=%s, programme=%s, semester=%s WHERE roll_no=%s", (r["name"].strip(), r["programme"].strip(), sem, roll))
            else:
                conn.execute(
                    "INSERT INTO students (roll_no, name, programme, semester, pin_hash) VALUES (%s, %s, %s, %s, %s)",
                    (roll, r["name"].strip(), r["programme"].strip(), sem, auth.hash_pin(pin)),
                )
                existing.add(roll)
            n += 1
        counts["students"] = n

    students = {x["roll_no"]: x["id"] for x in conn.execute("SELECT id, roll_no FROM students").fetchall()}
    subjects = {x["code"]: x["id"] for x in conn.execute("SELECT id, code FROM subjects").fetchall()}

    if batch == "baseline":
        n = 0
        for i, r in enumerate(_read(folder, "resources.csv"), start=2):
            sid = subjects.get((r.get("subject_code") or "").strip())
            if sid is None:
                bad("resources.csv", i, f"unknown subject_code {r.get('subject_code')!r}"); continue
            if r["kind"] not in RES_KINDS or not r["url"].strip() or not r["title"].strip() or not r["topic"].strip():
                bad("resources.csv", i, "invalid kind, or missing topic/title/url"); continue
            conn.execute(
                """INSERT INTO resources (subject_id, topic, title, url, kind) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (url) DO UPDATE SET subject_id=EXCLUDED.subject_id, topic=EXCLUDED.topic, title=EXCLUDED.title, kind=EXCLUDED.kind""",
                (sid, r["topic"].strip(), r["title"].strip(), r["url"].strip(), r["kind"]),
            )
            n += 1
        counts["resources"] = n
        n = 0
        for i, r in enumerate(_read(folder, "roles.csv"), start=2):
            sid = subjects.get((r.get("subject_code") or "").strip())
            if sid is None or not (r.get("role") or "").strip():
                bad("roles.csv", i, "unknown subject_code or missing role"); continue
            conn.execute("INSERT INTO role_subjects (role, subject_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (r["role"].strip(), sid))
            n += 1
        counts["roles"] = n

    # assessments: only rows of the requested batch; other batches are ignored, not errors
    good_ass, seen = [], set()
    for i, r in enumerate(_read(folder, "assessments.csv"), start=2):
        if r.get("batch") not in BATCHES:
            bad("assessments.csv", i, f"batch must be one of {sorted(BATCHES)}"); continue
        if r["batch"] != batch:
            continue
        try:
            roll, code = r["roll_no"].strip().upper(), r["subject_code"].strip()
            if roll not in students:
                raise ValueError(f"unknown roll_no {roll!r}")
            if code not in subjects:
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
            on = date.fromisoformat(r["taken_on"].strip())
            key = (roll, code, r["topic"].strip(), r["kind"], on, batch)
            if key in seen:
                raise ValueError("duplicate row")
            seen.add(key)
        except (KeyError, ValueError) as e:
            bad("assessments.csv", i, str(e)); continue
        good_ass.append((students[roll], subjects[code], r["topic"].strip(), r["kind"], score, mx, on, batch))

    good_att, seen_att = [], set()
    for i, r in enumerate(_read(folder, "attendance.csv"), start=2):
        if r.get("batch") not in BATCHES:
            bad("attendance.csv", i, f"batch must be one of {sorted(BATCHES)}"); continue
        if r["batch"] != batch:
            continue
        try:
            roll, code = r["roll_no"].strip().upper(), r["subject_code"].strip()
            if roll not in students:
                raise ValueError(f"unknown roll_no {roll!r}")
            if code not in subjects:
                raise ValueError(f"unknown subject_code {code!r}")
            attended, total = int(r["attended"]), int(r["total"])
            if total <= 0 or not (0 <= attended <= total):
                raise ValueError("need total > 0 and 0 <= attended <= total")
            if (roll, code) in seen_att:
                raise ValueError("duplicate row")
            seen_att.add((roll, code))
        except (KeyError, ValueError) as e:
            bad("attendance.csv", i, str(e)); continue
        good_att.append((students[roll], subjects[code], batch, attended, total))

    # synchronise: replace this batch only
    conn.execute("DELETE FROM assessments WHERE batch=%s", (batch,))
    conn.execute("DELETE FROM attendance WHERE batch=%s", (batch,))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO assessments (student_id, subject_id, topic, kind, score, max, taken_on, batch) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", good_ass
        )
        cur.executemany("INSERT INTO attendance (student_id, subject_id, batch, attended, total) VALUES (%s,%s,%s,%s,%s)", good_att)
    counts["assessments"], counts["attendance"] = len(good_ass), len(good_att)

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
    return StudentRecords(student_id, sorted(subs.values(), key=lambda x: x.code))


def class_means(conn, batch: str = "baseline") -> dict[str, float]:
    """subject_code -> class percentage (sum of marks over sum of max, scored rows only)."""
    rows = conn.execute(
        """SELECT s.code, 100.0 * SUM(a.score) / SUM(a.max) AS pct FROM assessments a JOIN subjects s ON s.id=a.subject_id
           WHERE a.batch=%s AND a.score IS NOT NULL GROUP BY s.code""",
        (batch,),
    ).fetchall()
    return {r["code"]: float(r["pct"]) for r in rows}


def get_resources(conn, subject_code: str) -> list[Resource]:
    rows = conn.execute(
        "SELECT r.id, r.topic, r.title, r.url, r.kind FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code=%s ORDER BY r.topic, r.id",
        (subject_code,),
    ).fetchall()
    return [Resource(**r) for r in rows]


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
def _load_env_file() -> None:
    p = Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip() if k.strip() == "PUBLIC_BASE_URL" else v.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.connector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("folder")
    imp.add_argument("--batch", choices=sorted(BATCHES), required=True)
    args = ap.parse_args(argv)

    _load_env_file()
    from app import db

    db.init()
    try:
        with db.pool.connection() as conn:
            result = import_csv(conn, Path(args.folder), args.batch)
    finally:
        db.close()
    print(f"imported batch={result['batch']} counts={result['counts']}")
    for e in result["errors"]:
        print(f"  REJECTED {e['file']} line {e['line']}: {e['error']}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
