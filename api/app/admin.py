"""C10: staff dashboard. Aggregates, success metrics, intervention queue, health, audit (LLD C10).
No student-level record lookup in the MVP."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response

from app import analytics, auth, catalogue, connector, db, llm, report

router = APIRouter(prefix="/api")

MIN_GROUP = 5  # groups smaller than this are suppressed (counts returned as null)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def subject_rows(conn, today: date) -> list[dict]:
    # ponytail: O(students) per request, fine for one cohort; precompute when cohorts grow
    means = connector.class_means(conn)
    prereqs = connector.prereq_map(conn)
    students = [r["id"] for r in conn.execute("SELECT id FROM students").fetchall()]
    agg: dict[str, dict] = {}
    for sid in students:
        for s in analytics.analyse(connector.get_records(conn, sid), means, today, prereqs=prereqs):
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


def metrics(conn, today: date | None = None) -> dict:
    """RB 16 evaluation metrics: authentication, roadmap success, usefulness, engagement, links, human support."""
    today = today or date.today()
    c = {r["action"]: r["n"] for r in conn.execute(
        "SELECT action, count(*) AS n FROM audit_log WHERE at > now() - interval '7 days' AND action IN ('login_ok','login_fail','draft_ok','draft_fail','diagnostic_submit') GROUP BY action").fetchall()}
    consent = {r["scope"]: r["n"] for r in conn.execute(
        "SELECT split_part(target, ':', 2) AS scope, count(*) AS n FROM audit_log WHERE action='consent' AND at > now() - interval '7 days' GROUP BY 1").fetchall()}
    fb = conn.execute("SELECT avg(rating)::float AS a, count(*) AS n FROM feedback").fetchone()
    plans = conn.execute(
        """SELECT count(*) AS total, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM tasks t WHERE t.roadmap_id=r.id AND t.status <> 'pending')) AS progressed
           FROM roadmaps r WHERE r.status='active'""").fetchone()
    links = conn.execute(
        "SELECT count(*) AS n, count(*) FILTER (WHERE link_ok AND checked_on >= %s) AS ok FROM resources", (today - timedelta(days=30),)).fetchone()
    fit = conn.execute("SELECT avg(plan_fit)::float AS a, count(plan_fit) AS n FROM reviews").fetchone()
    support = {}
    for cat in ("academic", "wellbeing", "correction"):
        r = conn.execute(
            """SELECT count(*) FILTER (WHERE status='open') AS open,
                      count(*) FILTER (WHERE status='closed' AND closed_at > now() - interval '7 days') AS closed_7d,
                      (percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM closed_at - created_at) / 3600)
                         FILTER (WHERE status='closed' AND closed_at IS NOT NULL))::float AS median_hours
               FROM requests WHERE category=%s""", (cat,)).fetchone()
        support[cat] = {"open": r["open"], "closed_7d": r["closed_7d"], "median_hours": None if r["median_hours"] is None else round(r["median_hours"], 1)}
    comments = [r["comment"] for r in conn.execute(
        "SELECT comment FROM feedback WHERE comment IS NOT NULL AND comment <> '' ORDER BY id DESC LIMIT 20").fetchall()]
    # ponytail: O(plans) via build_report, fine for one cohort
    improved = total = 0
    for r in conn.execute("SELECT id FROM roadmaps WHERE status='active'").fetchall():
        rep = report.build_report(conn, r["id"], today)
        if rep.has_review_data and rep.baseline_subject_pct is not None and rep.review_subject_pct is not None:
            total += 1
            improved += 1 if rep.review_subject_pct > rep.baseline_subject_pct else 0
    return {
        "login_success_rate_7d": _rate(c.get("login_ok", 0), c.get("login_ok", 0) + c.get("login_fail", 0)),
        "draft_success_rate_7d": _rate(c.get("draft_ok", 0), c.get("draft_ok", 0) + c.get("draft_fail", 0)),
        "feedback_avg": None if fb["a"] is None else round(fb["a"], 2), "feedback_n": fb["n"],
        "plans_with_progress": _rate(plans["progressed"], plans["total"]),
        "consent_personal_7d": consent.get("personal", 0), "consent_general_7d": consent.get("general", 0),
        "diagnostics_7d": c.get("diagnostic_submit", 0),
        "link_health": _rate(links["ok"], links["n"]),
        "human_support": support,
        "plan_fit_avg": None if fit["a"] is None else round(fit["a"], 2), "plan_fit_n": fit["n"],
        "feedback_comments": comments,
        "plans_improved": _rate(improved, total),
    }


@router.get("/admin/summary")
def summary(s: auth.Session = Depends(auth.staff), conn=Depends(db.get_conn)):
    wellbeing_open = conn.execute("SELECT count(*) AS n FROM requests WHERE status='open' AND category='wellbeing'").fetchone()["n"]
    scope = ("academic", "correction") if s.role == "admin" else ("wellbeing",)
    out: dict = {
        "role": s.role,
        "wellbeing_open": wellbeing_open,     # a count only: admin never sees wellbeing rows
        # Roll numbers are shown here because the student asked for contact.
        "requests": [
            {"id": r["id"], "roll_no": r["roll_no"], "category": r["category"], "subject_code": r["subject_code"], "note": r["note"], "created_at": r["created_at"].isoformat()}
            for r in conn.execute(
                "SELECT q.id, st.roll_no, q.category, q.subject_code, q.note, q.created_at FROM requests q JOIN students st ON st.id=q.student_id "
                "WHERE q.status='open' AND q.category = ANY(%s) ORDER BY q.created_at DESC", (list(scope),)).fetchall()
        ],
    }
    if s.role == "admin":
        links = conn.execute("SELECT count(*) AS n, count(*) FILTER (WHERE NOT link_ok) AS broken FROM resources").fetchone()
        out.update({
            "subjects": subject_rows(conn, date.today()),
            "metrics": metrics(conn),
            "links": {"total": links["n"], "broken": links["broken"]},
            "last_import": {b: (lambda t: t.isoformat() if t else None)(connector.last_import(conn, b)) for b in ("baseline", "review")},
            "health": {"db": True, "llm": dict(llm.STATUS)},
            # wellbeing referrals are audited as actor 'system' / target 'wellbeing' and never shown here
            "recent_audit": [{"at": r["at"].isoformat(), "actor": r["actor"], "action": r["action"]}
                             for r in conn.execute("SELECT at, actor, action FROM audit_log WHERE NOT (actor='system' AND target='wellbeing') ORDER BY id DESC LIMIT 25").fetchall()],
        })
    else:
        out["contacts"] = [c.model_dump() for c in catalogue.contacts()]
    db.audit(conn, "staff", "admin_view", s.role)
    conn.commit()
    return out


@router.post("/admin/requests/{request_id}/close", status_code=204)
def close_request(request_id: int, s: auth.Session = Depends(auth.staff), conn=Depends(db.get_conn)):
    row = conn.execute("SELECT category FROM requests WHERE id=%s AND status='open'", (request_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "not_found")
    allowed = ("academic", "correction") if s.role == "admin" else ("wellbeing",)
    if row["category"] not in allowed:
        raise HTTPException(403, "forbidden_role")
    conn.execute("UPDATE requests SET status='closed', closed_at=now() WHERE id=%s", (request_id,))
    db.audit(conn, "system" if row["category"] == "wellbeing" else "staff", "request_close", "wellbeing" if row["category"] == "wellbeing" else str(request_id))
    conn.commit()
    return Response(status_code=204)
