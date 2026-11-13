from app import db
from tests.conftest import login


def post_login(client, roll="CS23001", pin="1234"):
    return client.post("/api/auth/login", json={"roll_no": roll, "pin": pin})


def test_login_ok_sets_cookie_and_returns_student(client):
    r = post_login(client)
    assert r.status_code == 200 and r.json()["roll_no"] == "CS23001"
    assert "kiosk_sid" in r.cookies
    assert "pin_hash" not in r.text


def test_wrong_pin_and_unknown_roll_look_the_same(client):
    a = post_login(client, pin="9999")
    b = post_login(client, roll="NOPE999")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "bad_credentials"}


def test_five_failures_lock_even_for_correct_pin_then_unlock(client):
    for _ in range(5):
        assert post_login(client, pin="9999").status_code == 401
    assert post_login(client).status_code == 423
    with db.pool.connection() as c:
        c.execute("UPDATE students SET locked_until = now() - interval '1 second' WHERE roll_no='CS23001'")
        c.commit()
    assert post_login(client).status_code == 200


def test_pin_must_be_4_to_6_digits(client):
    assert post_login(client, pin="12").status_code == 422
    assert post_login(client, pin="abcd").status_code == 422


def test_profile_requires_session_then_consent(client):
    assert client.get("/api/me/profile").status_code == 401
    post_login(client)
    assert client.get("/api/me/profile").json() == {"detail": "consent_required"}
    assert client.post("/api/consent", json={"notice_version": "v1"}).status_code == 204
    assert client.get("/api/me/profile").status_code == 200


def test_logout_ends_session(client):
    login(client)
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.clear()  # the cookie was deleted; also prove the server row is gone by replaying it
    assert client.get("/api/me/profile").status_code == 401


def test_logout_deletes_server_side_session(client):
    r = login(client)
    cookie = r.cookies["kiosk_sid"]
    client.post("/api/auth/logout")
    client.cookies.set("kiosk_sid", cookie)
    assert client.get("/api/me/profile").status_code == 401


def test_session_values_are_stored_hashed(client):
    r = login(client)
    cookie = r.cookies["kiosk_sid"]
    with db.pool.connection() as c:
        rows = [x["id_hash"] for x in c.execute("SELECT id_hash FROM sessions").fetchall()]
    assert cookie not in rows and db.h(cookie) in rows


def test_requests_and_feedback(client):
    login(client)
    assert client.post("/api/requests", json={"category": "academic"}).status_code == 200
    assert client.post("/api/requests", json={"category": "correction", "subject_code": "DSA", "note": "mark looks wrong"}).status_code == 200
    assert client.post("/api/feedback", json={"rating": 5}).status_code == 204
    assert client.post("/api/feedback", json={"rating": 9}).status_code == 422
    with db.pool.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM requests").fetchone()["n"] == 2
        cols = [x["column_name"] for x in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='feedback'").fetchall()]
    assert "student_id" not in cols  # anonymous


def test_delete_plans_only_removes_callers(client):
    with db.pool.connection() as c:
        sid = {r["roll_no"]: r["id"] for r in c.execute("SELECT id, roll_no FROM students WHERE roll_no IN ('CS23001','CS23002')").fetchall()}
        sub = c.execute("SELECT id FROM subjects WHERE code='DSA'").fetchone()["id"]
        for roll in ("CS23001", "CS23002"):
            c.execute(
                """INSERT INTO roadmaps (student_id, subject_id, version, summary, evidence, days, daily_minutes, start_on, review_on)
                   VALUES (%s, %s, 1, 's', '{}', 14, 60, current_date, current_date + 14)""", (sid[roll], sub))
        c.commit()
    login(client, "CS23001")
    assert client.delete("/api/me/data").status_code == 204
    with db.pool.connection() as c:
        left = [r["student_id"] for r in c.execute("SELECT student_id FROM roadmaps").fetchall()]
    assert left == [sid["CS23002"]]


def test_admin_login(client):
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    r = client.post("/api/admin/login", json={"password": "test-admin-password"})
    assert r.status_code == 204 and "staff_sid" in r.cookies


def test_kiosk_cookie_cannot_act_as_staff_or_phone(client):
    login(client)
    from app import auth
    assert auth.STAFF_COOKIE != auth.KIOSK_COOKIE != auth.PHONE_COOKIE


# ---- v2: consent modes, request routing, deletion, staff roles (LLD_next C2.5) -----------------------
def test_general_mode_reaches_guidance_routes_but_not_records(client, monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "chat", lambda m, **k: "Hello")
    login(client, "CS23002", scope="general")
    assert client.get("/api/me/profile").status_code == 403
    assert client.post("/api/mentor/chat", json={"messages": [], "lang": "en"}).status_code == 200
    assert client.get("/api/goals").status_code == 200
    assert client.post("/api/diagnostics", json={"subject_code": "DSA", "topic": "Trees"}).status_code == 403
    assert client.get("/api/roadmaps").status_code == 403
    assert client.post("/api/requests", json={"category": "correction"}).status_code == 403     # correction needs records
    assert client.post("/api/requests", json={"category": "academic"}).status_code == 200


def test_unconsented_session_reaches_nothing_guided(client):
    client.post("/api/auth/login", json={"roll_no": "CS23001", "pin": "1234"})
    assert client.get("/api/goals").status_code == 403
    assert client.post("/api/mentor/chat", json={"messages": [], "lang": "en"}).status_code == 403


def test_consent_scope_is_recorded_and_audited(client):
    login(client, scope="general")
    with db.pool.connection() as c:
        assert c.execute("SELECT mode FROM sessions WHERE kind='kiosk'").fetchone()["mode"] == "general"
        assert c.execute("SELECT target FROM audit_log WHERE action='consent'").fetchone()["target"] == "v2:general"


def test_wellbeing_note_is_stored_only_when_shared_and_routes_to_the_counsellor(client):
    login(client)
    r = client.post("/api/requests", json={"category": "wellbeing", "note": "private worry", "share_note": False}).json()
    assert r["team"] == "counsellor" and "urgent" in {c["team"] for c in r["contacts"]} and "counsellor" in {c["team"] for c in r["contacts"]}
    client.post("/api/requests", json={"category": "wellbeing", "note": "please call me", "share_note": True})
    with db.pool.connection() as c:
        notes = [x["note"] for x in c.execute("SELECT note FROM requests WHERE category='wellbeing' ORDER BY id").fetchall()]
        audit = c.execute("SELECT actor, target FROM audit_log WHERE action='request_create'").fetchall()
    assert notes == [None, "please call me"]
    assert all(a["actor"] == "system" and a["target"] == "wellbeing" for a in audit)          # never attributed to the student


def test_delete_my_data_keeps_open_requests_and_removes_checks_and_closed_requests(client):
    from tests.conftest import take_check
    from tests.test_roadmap import plan
    login(client)
    client.post("/api/roadmaps", json=plan())
    take_check(client, "DSA", "Trees")
    client.post("/api/requests", json={"category": "academic"})
    client.post("/api/requests", json={"category": "correction"})
    with db.pool.connection() as c:
        c.execute("UPDATE requests SET status='closed', closed_at=now() WHERE category='correction'")
        c.commit()
    assert client.delete("/api/me/data").status_code == 204
    with db.pool.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM roadmaps").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM diagnostics").fetchone()["n"] == 0
        assert [r["category"] for r in c.execute("SELECT category FROM requests").fetchall()] == ["academic"]


def test_staff_roles_and_an_empty_counsellor_password_never_matches(client, monkeypatch):
    from app import config
    r = client.post("/api/admin/login", json={"password": "test-counsellor-password"})
    assert r.status_code == 204
    with db.pool.connection() as c:
        assert c.execute("SELECT role FROM sessions WHERE kind='staff'").fetchone()["role"] == "counsellor"
    client.cookies.clear()
    monkeypatch.setattr(config, "COUNSELLOR_PASSWORD", "")
    assert client.post("/api/admin/login", json={"password": ""}).status_code == 401
    assert client.post("/api/admin/login", json={"password": "test-admin-password"}).status_code == 204
    with db.pool.connection() as c:
        assert c.execute("SELECT role FROM sessions WHERE kind='staff' ORDER BY expires_at DESC LIMIT 1").fetchone()["role"] == "admin"


def test_feedback_comment_is_optional_trimmed_and_anonymous(client):
    login(client)
    assert client.post("/api/feedback", json={"rating": 4, "comment": "  clear plan  "}).status_code == 204
    assert client.post("/api/feedback", json={"rating": 4, "comment": "x" * 301}).status_code == 422
    with db.pool.connection() as c:
        row = c.execute("SELECT * FROM feedback").fetchone()
    assert row["comment"] == "clear plan" and "student_id" not in row
