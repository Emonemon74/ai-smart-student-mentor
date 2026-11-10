"""C10: staff dashboard. Aggregates, success metrics, intervention queue, health, audit (LLD C10).
No student-level record lookup in the MVP."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response

from app import analytics, auth, connector, db, llm

router = APIRouter(prefix="/api")

MIN_GROUP = 5  # groups smaller than this are suppressed (counts returned as null)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def subject_rows(conn, today: date) -> list[dict]:
    # ponytail: O(students) per request, fine for one cohort; precompute when cohorts grow
    means = connector.class_means(conn)
    students = [r["id"] for r in conn.execute("SELECT id FROM students").fetchall()]
    agg: dict[str, dict] = {}
    for sid in students:
        for s in analytics.analyse(connector.get_records(conn, sid), means, today):
            a = agg.setdefault(s.code, {"code": s.code, "name": s.name, "students": 0, "flagged": 0, "pcts": []})
            a["students"] += 1
            a["flagged"] += 1 if s.flags else 0
            if s.pct is not None:
                a["pcts"].append(s.pct)
    plans = {r["code"]: r["n"] for r in conn.execute(
        "SELECT s.code, count(*) AS n FROM roadmaps r JOIN subjects s ON s.id=r.subject_id WHERE r.status='active' GROUP BY s.code").fetchall()}
    out = []
    for code in sorted(agg):
        a = agg[code]
        if a["students"] < MIN_GROUP:  # small-group suppression
            out.append({"code": code, "name": a["name"], "students": None, "flagged": None, "avg_pct": None, "active_plans": None, "suppressed": True})
        else:
            out.append({"code": code, "name": a["name"], "students": a["students"], "flagged": a["flagged"],
                        "avg_pct": round(sum(a["pcts"]) / len(a["pcts"]), 1) if a["pcts"] else None,
                        "active_plans": plans.get(code, 0), "suppressed": False})
    return out


def metrics(conn) -> dict:
    """Brief section 19: authentication and roadmap success, usefulness, engagement."""
    c = {r["action"]: r["n"] for r in conn.execute(
        "SELECT action, count(*) AS n FROM audit_log WHERE at > now() - interval '7 days' AND action IN ('login_ok','login_fail','draft_ok','draft_fail') GROUP BY action").fetchall()}
    fb = conn.execute("SELECT avg(rating)::float AS a, count(*) AS n FROM feedback").fetchone()
    plans = conn.execute(
        """SELECT count(*) AS total, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM tasks t WHERE t.roadmap_id=r.id AND t.status <> 'pending')) AS progressed
           FROM roadmaps r WHERE r.status='active'""").fetchone()
    return {
        "login_success_rate_7d": _rate(c.get("login_ok", 0), c.get("login_ok", 0) + c.get("login_fail", 0)),
        "draft_success_rate_7d": _rate(c.get("draft_ok", 0), c.get("draft_ok", 0) + c.get("draft_fail", 0)),
        "feedback_avg": None if fb["a"] is None else round(fb["a"], 2), "feedback_n": fb["n"],
        "plans_with_progress": _rate(plans["progressed"], plans["total"]),
    }


@router.get("/admin/summary")
def summary(_: auth.Session = Depends(auth.staff), conn=Depends(db.get_conn)):
    out = {
        "subjects": subject_rows(conn, date.today()),
        "metrics": metrics(conn),
        # Roll numbers are shown here because the student asked for contact.
        "requests": [
            {"id": r["id"], "roll_no": r["roll_no"], "kind": r["kind"], "subject_code": r["subject_code"], "note": r["note"], "created_at": r["created_at"].isoformat()}
            for r in conn.execute(
                "SELECT q.id, st.roll_no, q.kind, q.subject_code, q.note, q.created_at FROM requests q JOIN students st ON st.id=q.student_id WHERE q.status='open' ORDER BY q.created_at DESC").fetchall()
        ],
        "last_import": {b: (lambda t: t.isoformat() if t else None)(connector.last_import(conn, b)) for b in ("baseline", "review")},
        "health": {"db": True, "llm": dict(llm.STATUS)},
        "recent_audit": [{"at": r["at"].isoformat(), "actor": r["actor"], "action": r["action"]}
                         for r in conn.execute("SELECT at, actor, action FROM audit_log ORDER BY id DESC LIMIT 25").fetchall()],
    }
    db.audit(conn, "staff", "admin_view")
    conn.commit()
    return out


@router.post("/admin/requests/{request_id}/close", status_code=204)
def close_request(request_id: int, _: auth.Session = Depends(auth.staff), conn=Depends(db.get_conn)):
    cur = conn.execute("UPDATE requests SET status='closed' WHERE id=%s AND status='open'", (request_id,))
    if cur.rowcount == 0:
        conn.commit()
        raise HTTPException(404, "not_found")
    db.audit(conn, "staff", "request_close", str(request_id))
    conn.commit()
    return Response(status_code=204)
