from app import db
from tests.conftest import login
from tests.test_roadmap import plan


def make_plan(client, roll="CS23001"):
    login(client, roll)
    return client.post("/api/roadmaps", json=plan()).json()


def share(client, rid):
    r = client.post(f"/api/roadmaps/{rid}/share")
    assert r.status_code == 200
    return r.json()["url"].rsplit("/r/", 1)[1]


def new_phone(client):
    """A separate client = a separate browser (the phone)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_token_works_once_then_410(client):
    rid = make_plan(client)["id"]
    tok = share(client, rid)
    phone = new_phone(client)
    r = phone.get(f"/api/r/{tok}")
    assert r.status_code == 200 and r.json()["id"] == rid and "phone_sid" in r.cookies
    assert new_phone(client).get(f"/api/r/{tok}").json() == {"detail": "link_used_or_expired"}


def test_expired_token_is_410(client):
    rid = make_plan(client)["id"]
    tok = share(client, rid)
    with db.pool.connection() as c:
        c.execute("UPDATE share_tokens SET expires_at = now() - interval '1 second'")
        c.commit()
    assert new_phone(client).get(f"/api/r/{tok}").status_code == 410


def test_share_url_uses_public_base_url_and_stores_only_a_hash(client):
    rid = make_plan(client)["id"]
    url = client.post(f"/api/roadmaps/{rid}/share").json()["url"]
    tok = url.rsplit("/r/", 1)[1]
    with db.pool.connection() as c:
        hashes = [r["token_hash"] for r in c.execute("SELECT token_hash FROM share_tokens").fetchall()]
    assert tok not in hashes and db.h(tok) in hashes


def test_phone_can_update_own_task_but_not_another_roadmap_and_not_kiosk_routes(client):
    a = make_plan(client, "CS23001")
    tok = share(client, a["id"])
    client.post("/api/auth/logout")
    client.cookies.clear()
    b = make_plan(client, "CS23002")               # another student's roadmap
    phone = new_phone(client)
    phone.get(f"/api/r/{tok}")
    assert phone.patch(f"/api/phone/tasks/{a['tasks'][0]['id']}", json={"status": "done"}).status_code == 204
    assert phone.patch(f"/api/phone/tasks/{b['tasks'][0]['id']}", json={"status": "done"}).status_code == 404
    assert phone.patch(f"/api/phone/tasks/{a['tasks'][0]['id']}", json={"status": "bogus"}).status_code == 422
    assert phone.get("/api/me/profile").status_code == 401          # phone cookie never reaches kiosk routes
    assert phone.get("/api/roadmaps").status_code == 401
    got = phone.get("/api/phone/roadmap").json()
    assert got["tasks"][0]["status"] == "done"


def test_phone_report_equals_kiosk_report(client):
    rid = make_plan(client)["id"]
    tok = share(client, rid)
    phone = new_phone(client)
    phone.get(f"/api/r/{tok}")
    assert phone.get("/api/phone/report").json() == client.get(f"/api/roadmaps/{rid}/report").json()


def test_second_share_revokes_the_first_phone_session(client):
    rid = make_plan(client)["id"]
    first = share(client, rid)
    phone = new_phone(client)
    phone.get(f"/api/r/{first}")
    assert phone.get("/api/phone/roadmap").status_code == 200
    share(client, rid)
    assert phone.get("/api/phone/roadmap").status_code == 401


def test_phone_without_session_is_401(client):
    assert new_phone(client).get("/api/phone/roadmap").status_code == 401
