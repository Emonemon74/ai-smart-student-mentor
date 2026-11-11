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
    client.post("/api/requests", json={"kind": "referral", "subject_code": "DSA"})
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
