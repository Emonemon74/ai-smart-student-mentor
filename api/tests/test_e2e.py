"""End-to-end demo script (LLD phase 3 gate): the whole journey, run twice. Only the LLM is faked."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import connector, db, llm
from app.main import app
from app.schemas import TaskIn
from tests.conftest import SEED, login
from tests.test_roadmap import good


@pytest.fixture
def fake_ai(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda messages, **kw: "Your records show Graphs at 40%. Which part feels hardest?")

    def chat_json(messages, model_cls, *, validate=None, max_tokens=1500):
        obj = model_cls(summary="Focus on graphs first", tasks=[TaskIn(**t) for t in good()])
        if validate:
            validate(obj)       # the real validation rules still run
        return obj

    monkeypatch.setattr(llm, "chat_json", chat_json)


@pytest.mark.parametrize("run", [1, 2])
def test_full_demo_journey(client, fake_ai, run):
    # 1. sign in + consent, then the academic picture explains why DSA is flagged
    login(client, "CS23001")
    prof = client.get("/api/me/profile").json()
    dsa = next(s for s in prof["subjects"] if s["code"] == "DSA")
    assert {"LOW_VS_SELF", "DECLINING", "WEAK_TOPIC"} <= {f["code"] for f in dsa["flags"]}
    assert prof["subjects"][0]["code"] == "DSA"                         # flagged subjects first

    # 2. mentor conversation
    opening = client.post("/api/mentor/chat", json={"messages": [], "lang": "en"}).json()["reply"]
    assert "40%" in opening
    convo = [{"role": "assistant", "content": opening}, {"role": "user", "content": "BFS and DFS. One hour a day."}]

    # 3. roadmap draft -> student saves
    review_on = (date.today() + timedelta(days=16)).isoformat()
    draft = client.post("/api/roadmaps/draft", json={"subject_code": "DSA", "days": 14, "daily_minutes": 60, "review_on": review_on, "lang": "en", "messages": convo}).json()
    saved = client.post("/api/roadmaps", json=draft["roadmap"]).json()
    assert saved["version"] == 1 and len(saved["tasks"]) == 3

    # 4. QR -> phone (a different browser): redeem once, tick tasks
    link = client.post(f"/api/roadmaps/{saved['id']}/share").json()["url"]
    token = link.rsplit("/r/", 1)[1]
    phone = TestClient(app)
    assert phone.get(f"/api/r/{token}").status_code == 200
    assert TestClient(app).get(f"/api/r/{token}").status_code == 410             # a photographed QR is useless
    for t in saved["tasks"][:2]:
        assert phone.patch(f"/api/phone/tasks/{t['id']}", json={"status": "done"}).status_code == 204
    before = phone.get("/api/phone/report").json()
    assert before["has_review_data"] is False and before["self_reported"]["done"] == 2

    # 5. review date: new assessment evidence arrives
    with db.pool.connection() as c:
        assert connector.import_csv(c, SEED, "review", shift_days=connector.seed_shift_days())["errors"] == []
    after = client.get(f"/api/roadmaps/{saved['id']}/report").json()
    graphs = next(v for v in after["verified"] if v["topic"] == "Graphs")
    assert graphs["baseline_pct"] == 40.0 and graphs["delta"] == 20.0
    assert after["self_reported"] == before["self_reported"]                       # self-report never mixes with marks
    assert after["has_review_data"] is True

    # 6. staff see aggregates, the request queue and the audit trail
    client.post("/api/requests", json={"category": "academic", "subject_code": "DSA"})
    client.post("/api/feedback", json={"rating": 5})
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me/profile").status_code == 401
    staff = TestClient(app)
    assert staff.post("/api/admin/login", json={"password": "test-admin-password"}).status_code == 204
    s = staff.get("/api/admin/summary").json()
    assert next(x for x in s["subjects"] if x["code"] == "DSA")["active_plans"] == 1
    assert [r["roll_no"] for r in s["requests"]] == ["CS23001"]
    assert s["metrics"]["plans_with_progress"] == 1.0 and s["metrics"]["feedback_avg"] == 5.0
    actions = {a["action"] for a in s["recent_audit"]}
    assert {"login_ok", "consent", "roadmap_save", "share_create", "share_redeem", "task_update", "request_create"} <= actions


# ---- v2 journey (HLD_next section 13), run twice: check Graphs -> GATE plan -> review check-in -> report with next steps ----
from tests.conftest import take_check  # noqa: E402
from tests.test_roadmap import tasks_for  # noqa: E402


@pytest.mark.parametrize("run", [1, 2])
def test_v2_demo_journey(client, fake_ai, monkeypatch, run):
    # 1. CS23001 sees PREREQ_GAP and Graphs at foundation (records)
    login(client, "CS23001")
    prof = client.get("/api/me/profile").json()
    dsa = next(s for s in prof["subjects"] if s["code"] == "DSA")
    assert "PREREQ_GAP" in {f["code"] for f in dsa["flags"]} and all(f["response"] for f in dsa["flags"])
    graphs = next(t for t in dsa["levels"] if t["topic"] == "Graphs")
    assert graphs["level"] == "foundation" and graphs["source"] == "records" and graphs["has_check"] is True

    # 2. they take the Graphs check and see their level
    chk = take_check(client, "DSA", "Graphs", correct=4)
    assert chk["level"] in ("intermediate", "beginner") and "not a measure of ability" in chk["note"]

    # 3. GATE plan for DSA with a target date (the AI is faked; the real validation still runs)
    monkeypatch.setattr(llm, "chat_json", lambda messages, cls, *, validate=None, max_tokens=1500: _plan(cls, validate))
    body = {"goal": "gate", "subject_code": "DSA", "days": 14, "daily_minutes": 60, "review_on": (date.today() + timedelta(days=16)).isoformat(),
            "target_date": (date.today() + timedelta(days=120)).isoformat(), "lang": "en", "messages": []}
    draft = client.post("/api/roadmaps/draft", json=body).json()
    assert draft["levels"]["Graphs"]["source"] == "check"
    saved = client.post("/api/roadmaps", json=draft["roadmap"]).json()
    assert saved["goal"] == "gate" and saved["goal_name"] == "GATE preparation"

    # 4. QR to the phone, tick tasks
    from tests.test_share import new_phone, share
    phone = new_phone(client)
    assert phone.get(f"/api/r/{share(client, saved['id'])}").status_code == 200
    for t in saved["tasks"][:2]:
        assert phone.patch(f"/api/phone/tasks/{t['id']}", json={"status": "done"}).status_code == 204

    # 5. import the review batch: the review banner appears
    with db.pool.connection() as c:
        assert connector.import_csv(c, SEED, "review", shift_days=connector.seed_shift_days())["errors"] == []
    assert saved["id"] in client.get("/api/me/profile").json()["reviews_due"]

    # 6. check-in with confidence, then the Graphs check again
    assert client.post(f"/api/roadmaps/{saved['id']}/review", json={"confidence": 2, "plan_fit": 4}).status_code == 204
    after = take_check(client, "DSA", "Graphs", correct=5, purpose="review", roadmap_id=saved["id"])
    assert after["level"] == "advanced"
    assert saved["id"] not in client.get("/api/me/profile").json()["reviews_due"]

    # 7. the report keeps verified, kiosk-check and self-reported apart, with indicators and next steps
    rep = client.get(f"/api/roadmaps/{saved['id']}/report").json()
    assert rep["has_review_data"] is True and rep["goal"] == "gate" and rep["confidence_review"] == 2
    graphs_check = next(c for c in rep["checks"] if c["topic"] == "Graphs")
    assert graphs_check["after_level"] == "advanced" and graphs_check["before_score"] is not None
    assert {i["source"] for i in rep["indicators"]} <= {"verified", "kiosk_check", "self_reported"}
    assert rep["next_steps"] and rep["self_reported"]["done"] == 2 and rep["limitations"]

    # 8. a different student declines records: general mode
    client.post("/api/auth/logout")
    client.cookies.clear()
    login(client, "CS23002", scope="general")
    assert client.get("/api/me/profile").status_code == 403
    assert client.get("/api/goals").status_code == 200

    # 9. a distress message shows the support panel; the counsellor sees the referral, the admin only a count
    monkeypatch.setattr(llm, "chat", lambda m, **k: "Let's keep going.")
    assert client.post("/api/mentor/chat", json={"messages": [{"role": "user", "content": "I feel so stressed"}], "lang": "en"}).json()["support"] is True
    assert client.post("/api/requests", json={"category": "wellbeing", "note": "please call", "share_note": True}).status_code == 200
    client.cookies.clear()
    assert client.post("/api/admin/login", json={"password": "test-counsellor-password"}).status_code == 204
    cs = client.get("/api/admin/summary").json()
    assert [r["category"] for r in cs["requests"]] == ["wellbeing"]
    client.cookies.clear()
    assert client.post("/api/admin/login", json={"password": "test-admin-password"}).status_code == 204
    ad = client.get("/api/admin/summary").json()
    assert ad["wellbeing_open"] == 1 and all(r["category"] != "wellbeing" for r in ad["requests"])


def _plan(cls, validate):
    from tests.test_roadmap import task
    with db.pool.connection() as c:     # Graphs resources that fit CS23001's level window, so the review check can target Graphs
        ids = [r["id"] for r in c.execute(
            "SELECT r.id FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code='DSA' AND r.topic='Graphs' AND r.level IN ('beginner','intermediate') AND r.minutes <= 60 AND r.lang='en' AND (cardinality(r.goals)=0 OR 'gate' = ANY(r.goals)) ORDER BY r.id").fetchall()]
    obj = cls(summary="Graphs for GATE", tasks=[TaskIn(**t) for t in [task(1, 7, "checkpoint", rid=ids[0]), task(8, 10, "practice", rid=ids[1]), task(11, 14, "checkpoint", rid=ids[0])]])
    if validate:
        validate(obj)
    return obj
