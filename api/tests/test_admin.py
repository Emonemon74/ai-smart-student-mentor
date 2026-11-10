from app import admin, db, llm
from tests.conftest import login
from tests.test_roadmap import plan


def staff(client):
    assert client.post("/api/admin/login", json={"password": "test-admin-password"}).status_code == 204


def test_summary_requires_a_staff_session(client):
    assert client.get("/api/admin/summary").status_code == 401
    login(client)                                                     # a kiosk (student) cookie is not a staff cookie
    assert client.get("/api/admin/summary").status_code == 401
    assert client.post("/api/admin/requests/1/close").status_code == 401


def test_summary_shape_and_aggregates(client):
    staff(client)
    s = client.get("/api/admin/summary").json()
    assert set(s) == {"subjects", "metrics", "requests", "last_import", "health", "recent_audit"}
    dsa = next(x for x in s["subjects"] if x["code"] == "DSA")
    assert dsa["students"] == 30 and dsa["suppressed"] is False and 0 < dsa["flagged"] < 30 and dsa["avg_pct"] is not None
    assert s["last_import"]["baseline"] is not None and s["last_import"]["review"] is None
    assert s["health"]["db"] is True


def test_no_student_level_fields_leak(client):
    login(client, "CS23001")
    client.post("/api/roadmaps", json=plan())
    client.cookies.clear()
    staff(client)
    text = client.get("/api/admin/summary").text
    assert "Aarav" not in text and "pin_hash" not in text and "Graphs 40" not in text


def test_small_groups_are_suppressed(client, monkeypatch):
    monkeypatch.setattr(admin, "MIN_GROUP", 31)   # every subject has 30 students: all become 'small'
    staff(client)
    rows = client.get("/api/admin/summary").json()["subjects"]
    assert rows and all(r["suppressed"] and r["students"] is None and r["flagged"] is None and r["avg_pct"] is None and r["active_plans"] is None for r in rows)


def test_intervention_queue_and_close(client):
    login(client, "CS23002")
    client.post("/api/requests", json={"kind": "referral", "subject_code": "OS"})
    client.post("/api/requests", json={"kind": "correction", "subject_code": "DSA", "note": "wrong mark"})
    client.cookies.clear()
    staff(client)
    reqs = client.get("/api/admin/summary").json()["requests"]
    assert {(r["roll_no"], r["kind"]) for r in reqs} == {("CS23002", "referral"), ("CS23002", "correction")}
    rid = reqs[0]["id"]
    assert client.post(f"/api/admin/requests/{rid}/close").status_code == 204
    assert client.post(f"/api/admin/requests/{rid}/close").status_code == 404           # already closed
    assert len(client.get("/api/admin/summary").json()["requests"]) == 1


def test_metrics_come_from_audit_feedback_and_plans(client, monkeypatch):
    client.post("/api/auth/login", json={"roll_no": "CS23001", "pin": "0000"})        # one failed login
    login(client, "CS23001")                                                           # one success
    rid = client.post("/api/roadmaps", json=plan()).json()
    client.post("/api/feedback", json={"rating": 5})
    client.post("/api/feedback", json={"rating": 3})
    with db.pool.connection() as c:
        c.execute("INSERT INTO audit_log (actor, action) VALUES ('student:1','draft_ok'), ('student:1','draft_ok'), ('student:1','draft_fail')")
        c.execute("UPDATE tasks SET status='done' WHERE id=%s", (rid["tasks"][0]["id"],))
        c.commit()
    client.cookies.clear()
    staff(client)
    m = client.get("/api/admin/summary").json()["metrics"]
    assert m["login_success_rate_7d"] == 0.5 and m["draft_success_rate_7d"] == 0.667
    assert m["feedback_avg"] == 4.0 and m["feedback_n"] == 2 and m["plans_with_progress"] == 1.0


def test_metrics_are_null_when_there_is_no_data(client):
    staff(client)
    m = client.get("/api/admin/summary").json()["metrics"]
    assert m["draft_success_rate_7d"] is None and m["feedback_avg"] is None and m["plans_with_progress"] is None


def test_viewing_is_audited_and_llm_health_is_exposed(client):
    llm.STATUS["last_error"] = "groq: RateLimitError"
    try:
        staff(client)
        s = client.get("/api/admin/summary").json()
        assert s["health"]["llm"]["last_error"] == "groq: RateLimitError"
        with db.pool.connection() as c:
            assert c.execute("SELECT count(*) AS n FROM audit_log WHERE action='admin_view'").fetchone()["n"] == 1
    finally:
        llm.STATUS["last_error"] = None
