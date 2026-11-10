"""C9: progress report (LLD C9).
Invariant: `verified` and `review_subject_pct` come only from assessments; `self_reported` only from tasks.
No field mixes them."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app import analytics, auth, connector, db, roadmap
from app.schemas import Flag, Report, SelfReport, TaskView, TopicChange

router = APIRouter(prefix="/api")

CAVEAT = "Changes compare similar assessments before and after the plan. They do not show that the plan caused the change."


def build_report(conn, roadmap_id: int, today: date) -> Report:
    row = conn.execute("SELECT r.student_id, r.evidence FROM roadmaps r WHERE r.id=%s", (roadmap_id,)).fetchone()
    plan = roadmap.view(conn, roadmap_id)
    base = row["evidence"]
    info = connector.student_info(conn, row["student_id"])

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
    # Baseline is derived from the stored evidence snapshot (marks are max-weighted; quizzes share one max, so n-weighting is exact).
    n_total = sum(t["n"] for t in base["topics"])
    base_like = round(sum(t["pct"] * t["n"] for t in base["topics"]) / n_total, 1) if n_total else None
    like_rows = [r for r in review_rows if (r.topic, r.kind) in base_keys]
    review_like = analytics.pct(like_rows) if has_review_like(like_rows) else None

    tasks = plan.tasks
    counts = {s: sum(1 for t in tasks if t.status == s) for s in ("done", "partial", "pending")}
    self_reported = SelfReport(**counts, total=len(tasks), overdue=[t for t in tasks if t.status != "done" and t.due_on < today])

    remaining: list[Flag] = []
    if has_review:
        for s in analytics.analyse(review_rec, connector.class_means(conn, "review"), today):
            if s.code == plan.subject_code:
                remaining = s.flags

    return Report(
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
