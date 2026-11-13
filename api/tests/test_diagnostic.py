"""Concept check (LLD_next C17.4). Never touches the LLM."""
import pytest

from app import db, llm
from tests.conftest import login, take_check


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the concept check must not call the LLM")
    monkeypatch.setattr(llm, "chat", boom)
    monkeypatch.setattr(llm, "chat_json", boom)


def start(client, topic="Graphs", subject="DSA", **kw):
    return client.post("/api/diagnostics", json={"subject_code": subject, "topic": topic, **kw})


def test_start_has_no_answer_keys_and_five_questions_in_tier_order(client):
    login(client)
    d = start(client).json()
    assert [q["tier"] for q in d["questions"]] == ["basic", "basic", "standard", "standard", "multi"]
    text = str(d)
    assert "answer" not in text and "explanation" not in text and all(len(q["options"]) == 4 for q in d["questions"])


def test_all_correct_is_advanced_and_one_correct_is_foundation(client):
    login(client)
    assert take_check(client, "DSA", "Trees", correct=5)["level"] == "advanced"
    assert take_check(client, "DSA", "Trees", correct=1)["level"] == "foundation"
    r = take_check(client, "DSA", "Trees", correct=3)
    assert r["correct"] == 3 and r["total"] == 5 and "not a measure of ability" in r["note"]
    assert all(set(i) == {"id", "chosen", "answer", "correct", "explanation"} for i in r["items"])


def test_the_check_beats_the_records_estimate(client):
    login(client)
    prof = client.get("/api/me/profile").json()
    graphs = next(t for s in prof["subjects"] if s["code"] == "DSA" for t in s["levels"] if t["topic"] == "Graphs")
    assert graphs["level"] == "foundation" and graphs["source"] == "records"
    # b = 2, s = 1, m = 0: intermediate even though the records say foundation (no prerequisite coupling)
    r = client.post("/api/diagnostics", json={"subject_code": "DSA", "topic": "Graphs", "purpose": "level"}).json()
    with db.pool.connection() as c:
        keys = {x["id"]: x["answer"] for x in c.execute("SELECT id, answer FROM questions WHERE id = ANY(%s)", ([q["id"] for q in r["questions"]],)).fetchall()}
    ans = [keys[q["id"]] if i in (0, 1, 2) else (keys[q["id"]] + 1) % 4 for i, q in enumerate(r["questions"])]
    assert client.post(f"/api/diagnostics/{r['id']}/submit", json={"answers": ans}).json()["level"] == "intermediate"
    after = client.get("/api/me/profile").json()
    graphs = next(t for s in after["subjects"] if s["code"] == "DSA" for t in s["levels"] if t["topic"] == "Graphs")
    assert graphs["level"] == "intermediate" and graphs["source"] == "check"


def test_second_start_prefers_unseen_questions_when_the_bank_has_them(client):
    login(client)
    first = {q["id"] for q in start(client).json()["questions"]}
    d = start(client).json()
    with db.pool.connection() as c:                                   # nothing submitted yet: the open attempt was replaced
        assert c.execute("SELECT count(*) AS n FROM diagnostics WHERE submitted_at IS NULL").fetchone()["n"] == 1
    r = client.post(f"/api/diagnostics/{d['id']}/submit", json={"answers": [None] * 5})
    assert r.status_code == 200
    second = {q["id"] for q in start(client).json()["questions"]}
    seen = {i["id"] for i in r.json()["items"]}
    assert not (seen & second)                                         # Graphs has >= 4/4/2: all 5 new ones are unseen


def test_owner_only_double_submit_and_expiry(client):
    login(client, "CS23001")
    d = start(client).json()
    client.post("/api/auth/logout")
    client.cookies.clear()
    login(client, "CS23002")
    assert client.post(f"/api/diagnostics/{d['id']}/submit", json={"answers": [None] * 5}).status_code == 404
    client.post("/api/auth/logout")
    client.cookies.clear()
    login(client, "CS23001")
    assert client.post(f"/api/diagnostics/{d['id']}/submit", json={"answers": [0, 0, 0, 0, 0]}).status_code == 200
    assert client.post(f"/api/diagnostics/{d['id']}/submit", json={"answers": [0, 0, 0, 0, 0]}).json() == {"detail": "already_submitted"}
    d2 = start(client).json()
    with db.pool.connection() as c:
        c.execute("UPDATE diagnostics SET started_at = now() - interval '31 minutes' WHERE id=%s", (d2["id"],))
        c.commit()
    r = client.post(f"/api/diagnostics/{d2['id']}/submit", json={"answers": [0] * 5})
    assert r.status_code == 410 and r.json() == {"detail": "check_expired"}


def test_bad_inputs(client):
    login(client)
    assert start(client, topic="Nope").status_code == 404
    assert start(client, subject="NOPE").status_code == 404
    assert start(client, topic="Arrays", subject="DBMS").status_code == 404          # DBMS has no bank
    d = start(client).json()
    assert client.post(f"/api/diagnostics/{d['id']}/submit", json={"answers": [0, 1, 2]}).status_code == 422
    assert client.post(f"/api/diagnostics/{d['id']}/submit", json={"answers": [0, 1, 2, 3, 9]}).status_code == 422


def test_general_mode_cannot_take_a_check(client):
    login(client, scope="general")
    assert start(client).status_code == 403


def test_a_new_start_deletes_the_previous_unsubmitted_attempt(client):
    login(client)
    a = start(client).json()["id"]
    b = start(client).json()["id"]
    assert a != b
    with db.pool.connection() as c:
        assert [r["id"] for r in c.execute("SELECT id FROM diagnostics").fetchall()] == [b]
