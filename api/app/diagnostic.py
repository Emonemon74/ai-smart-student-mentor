"""C17: concept check. Select questions from the reviewed bank, mark them, store topic evidence.
Never calls the LLM, so it keeps working during an AI outage (LLD_next C17)."""
from __future__ import annotations

import random
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb

from app import analytics, auth, db
from app.schemas import DiagnosticOut, DiagnosticResult, DiagnosticStart, DiagnosticSubmit, QuestionOut, QuestionResult

router = APIRouter(prefix="/api")

TIERS = (("basic", 2), ("standard", 2), ("multi", 1))
EXPIRES = timedelta(minutes=30)
NOTE = "A starting point from 5 questions, not a measure of ability. You can change it."


def _subject(conn, code: str):
    return conn.execute("SELECT id, code FROM subjects WHERE code=%s", (code,)).fetchone()


@router.post("/diagnostics", response_model=DiagnosticOut)
def start(body: DiagnosticStart, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    subj = _subject(conn, body.subject_code)
    if subj is None:
        raise HTTPException(404, "not_found")
    pool_rows = conn.execute("SELECT id, tier FROM questions WHERE subject_id=%s AND topic=%s ORDER BY id", (subj["id"], body.topic)).fetchall()
    if not pool_rows:
        raise HTTPException(404, "not_found")
    if body.purpose == "review":
        if body.roadmap_id is None or not conn.execute("SELECT 1 FROM roadmaps WHERE id=%s AND student_id=%s", (body.roadmap_id, s.student_id)).fetchone():
            raise HTTPException(404, "not_found")
        topics = {r["topic"] for r in conn.execute(
            "SELECT DISTINCT res.topic FROM tasks t JOIN resources res ON res.id = t.resource_id WHERE t.roadmap_id=%s", (body.roadmap_id,)).fetchall()}
        if body.topic not in topics:     # the catalogue topic of one of the plan's tasks, never the AI's free text
            raise HTTPException(404, "not_found")
    conn.execute("DELETE FROM diagnostics WHERE student_id=%s AND submitted_at IS NULL", (s.student_id,))   # one open check per student
    seen: set[int] = set()
    for r in conn.execute("SELECT question_ids FROM diagnostics WHERE student_id=%s AND subject_id=%s AND topic=%s AND submitted_at IS NOT NULL",
                          (s.student_id, subj["id"], body.topic)).fetchall():
        seen.update(r["question_ids"])
    rng = random.Random(secrets.randbits(32))
    picks: list[int] = []
    for tier, k in TIERS:
        ids = [r["id"] for r in pool_rows if r["tier"] == tier]
        fresh, old = [i for i in ids if i not in seen], [i for i in ids if i in seen]
        rng.shuffle(fresh)
        rng.shuffle(old)
        take = (fresh + old)[:k]
        if len(take) < k:
            raise HTTPException(422, "not_enough_questions")
        picks += take
    row = conn.execute(
        """INSERT INTO diagnostics (student_id, subject_id, topic, purpose, roadmap_id, question_ids) VALUES (%s,%s,%s,%s,%s,%s)
           RETURNING id, started_at""",
        (s.student_id, subj["id"], body.topic, body.purpose, body.roadmap_id if body.purpose == "review" else None, picks),
    ).fetchone()
    db.audit(conn, f"student:{s.student_id}", "diagnostic_start", f"{body.subject_code}:{body.topic}")
    conn.commit()
    qs = {r["id"]: r for r in conn.execute("SELECT id, tier, stem, options FROM questions WHERE id = ANY(%s)", (picks,)).fetchall()}
    return DiagnosticOut(
        id=row["id"], subject_code=body.subject_code, topic=body.topic, expires_at=row["started_at"] + EXPIRES,
        questions=[QuestionOut(id=i, tier=qs[i]["tier"], stem=qs[i]["stem"], options=qs[i]["options"]) for i in picks])   # no answer keys


@router.post("/diagnostics/{diagnostic_id}/submit", response_model=DiagnosticResult)
def submit(diagnostic_id: int, body: DiagnosticSubmit, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    row = conn.execute(
        """SELECT d.*, s.code AS subject_code, (d.started_at + interval '30 minutes' < now()) AS expired FROM diagnostics d
           JOIN subjects s ON s.id = d.subject_id WHERE d.id=%s AND d.student_id=%s FOR UPDATE OF d""",
        (diagnostic_id, s.student_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "not_found")
    if row["submitted_at"] is not None:
        conn.rollback()
        raise HTTPException(409, "already_submitted")
    if row["expired"]:
        conn.rollback()
        raise HTTPException(410, "check_expired")
    qids = list(row["question_ids"])
    qs = {r["id"]: r for r in conn.execute("SELECT id, tier, answer, explanation FROM questions WHERE id = ANY(%s)", (qids,)).fetchall()}
    items: list[QuestionResult] = []
    per = {"basic": 0, "standard": 0, "multi": 0}
    for qid, chosen in zip(qids, body.answers):
        q = qs[qid]
        ok = chosen is not None and chosen == q["answer"]
        per[q["tier"]] += 1 if ok else 0
        items.append(QuestionResult(id=qid, chosen=chosen, answer=q["answer"], correct=ok, explanation=q["explanation"]))
    lvl = analytics.level(per["basic"], per["standard"], per["multi"])
    correct = sum(1 for i in items if i.correct)
    seconds = conn.execute(
        """UPDATE diagnostics SET submitted_at=now(), answers=%s, basic=%s, standard=%s, multi=%s, correct=%s, total=5,
           seconds=LEAST(EXTRACT(epoch FROM now() - started_at), 3600)::int, level=%s WHERE id=%s RETURNING seconds""",
        (Jsonb(body.answers), per["basic"], per["standard"], per["multi"], correct, lvl, diagnostic_id),
    ).fetchone()["seconds"]
    db.audit(conn, f"student:{s.student_id}", "diagnostic_submit", f"{row['subject_code']}:{row['topic']}:{lvl}")
    conn.commit()
    return DiagnosticResult(id=diagnostic_id, subject_code=row["subject_code"], topic=row["topic"], correct=correct, total=5,
                            basic=per["basic"], standard=per["standard"], multi=per["multi"], seconds=seconds, level=lvl, items=items, note=NOTE)
