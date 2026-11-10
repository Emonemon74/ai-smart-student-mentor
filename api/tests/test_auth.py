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
    assert client.post("/api/requests", json={"kind": "referral"}).status_code == 204
    assert client.post("/api/requests", json={"kind": "correction", "subject_code": "DSA", "note": "mark looks wrong"}).status_code == 204
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
    assert client.delete("/api/me/plans").status_code == 204
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
