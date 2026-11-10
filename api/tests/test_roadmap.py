from datetime import date, timedelta

import pytest

from app import db, llm, roadmap
from app.schemas import TaskIn
from tests.conftest import login


def resource_ids(code="DSA"):
    with db.pool.connection() as c:
        return [r["id"] for r in c.execute("SELECT r.id FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code=%s ORDER BY r.id", (code,)).fetchall()]


def task(a, b, kind="learn", rid=None, minutes=60, **kw):
    return {"day_from": a, "day_to": b, "kind": kind, "topic": "Graphs", "activity": "Do BFS drills", "reason": "Graphs 40.0% across 2 assessments",
            "minutes": minutes, "resource_id": rid or resource_ids()[0], "check": "Short quiz", **kw}


def plan(days=14, tasks=None, **kw):
    t = tasks or [task(1, 7), task(8, 10, "practice"), task(11, 14, "checkpoint")]
    return {"subject_code": "DSA", "summary": "Focus on graphs", "days": days, "daily_minutes": 60,
            "review_on": (date.today() + timedelta(days=days + 2)).isoformat(), "tasks": t, **kw}


# ---- validate_plan: pure -----------------------------------------------------------------------
def mk(tasks):
    return roadmap.LLMPlan(summary="s", tasks=[TaskIn(**t) for t in tasks])


def check(tasks, days=14, minutes=60):
    roadmap.validate_plan(mk(tasks), set(resource_ids()), days, minutes)


def good():
    return [task(1, 7, "checkpoint"), task(8, 10, "practice"), task(11, 14, "checkpoint")]


def test_valid_plan_passes():
    check(good())


# Built lazily (functions) because task() reads resource ids from the DB, which is not open at import time.
BAD = [
    (lambda: [task(1, 7, "checkpoint"), task(8, 10, rid=999999), task(11, 14, "checkpoint")], "not in the approved list"),
    (lambda: [task(1, 7, "checkpoint"), task(9, 10), task(11, 14, "checkpoint")], "gap or overlap"),
    (lambda: [task(1, 7, "checkpoint"), task(7, 10), task(11, 14, "checkpoint")], "gap or overlap"),
    (lambda: [task(1, 7, "checkpoint"), task(8, 10), task(11, 13, "checkpoint")], "last task must end on day 14"),
    (lambda: [task(2, 7, "checkpoint"), task(8, 10), task(11, 14, "checkpoint")], "start on day 1"),
    (lambda: [task(1, 7, "checkpoint"), task(8, 10, minutes=90), task(11, 14, "checkpoint")], "daily budget"),
    (lambda: [task(1, 7), task(8, 10), task(11, 14, "checkpoint")], "checkpoint tasks"),
    (lambda: [task(1, 7, "checkpoint"), task(8, 10, "checkpoint"), task(11, 14)], "last task must be a checkpoint"),
]


@pytest.mark.parametrize("make,msg", BAD)
def test_validate_rejects(make, msg):
    with pytest.raises(ValueError, match=msg):
        check(make())


# ---- draft ------------------------------------------------------------------------------------------
def fake_plan_llm(monkeypatch, tasks):
    seen = {}

    def fake(messages, model_cls, *, validate=None, max_tokens=1500):
        seen["messages"] = messages
        obj = model_cls(summary="Focus on graphs first", tasks=[TaskIn(**t) for t in tasks])
        if validate:
            validate(obj)
        return obj

    monkeypatch.setattr(llm, "chat_json", fake)
    return seen


def draft_body(**kw):
    return {"subject_code": "DSA", "days": 14, "daily_minutes": 60, "review_on": (date.today() + timedelta(days=16)).isoformat(),
            "lang": "en", "messages": [{"role": "user", "content": "BFS is hard"}], **kw}




def test_draft_builds_a_grounded_prompt_and_returns_resources(client, monkeypatch):
    seen = fake_plan_llm(monkeypatch, good())
    login(client)
    r = client.post("/api/roadmaps/draft", json=draft_body())
    assert r.status_code == 200
    body = r.json()
    assert body["roadmap"]["days"] == 14 and len(body["roadmap"]["tasks"]) == 3
    assert str(resource_ids()[0]) in body["resources"]
    user = seen["messages"][1]["content"]
    assert "Graphs" in user and "BFS is hard" in user and "internal on 2026-11-24" in user
    assert "CS23001" not in user and "Aarav" not in user
    with db.pool.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM roadmaps").fetchone()["n"] == 0  # a draft is never saved


def test_draft_rejects_bad_requests(client, monkeypatch):
    fake_plan_llm(monkeypatch, good())
    login(client)
    assert client.post("/api/roadmaps/draft", json=draft_body(subject_code="ZZZ")).status_code == 404
    soon = draft_body(review_on=(date.today() + timedelta(days=5)).isoformat())
    assert client.post("/api/roadmaps/draft", json=soon).json() == {"detail": "review_too_soon"}
    assert client.post("/api/roadmaps/draft", json=draft_body(days=3)).status_code == 422


def test_draft_ai_failure_is_502_and_audited(client, monkeypatch):
    def boom(*a, **k):
        raise llm.AIUnavailable
    monkeypatch.setattr(llm, "chat_json", boom)
    login(client)
    r = client.post("/api/roadmaps/draft", json=draft_body())
    assert r.status_code == 502 and r.json() == {"detail": "ai_unavailable"}
    with db.pool.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM audit_log WHERE action='draft_fail'").fetchone()["n"] == 1


# ---- save, list, get -----------------------------------------------------------------------------------
def test_save_snapshots_server_side_and_versions(client):
    login(client)
    p = plan()
    p["evidence"] = {"flags": [], "subject_pct": 99}          # client-supplied evidence must be ignored (no such field)
    a = client.post("/api/roadmaps", json=p).json()
    assert a["version"] == 1 and a["status"] == "active" and a["start_on"] == date.today().isoformat()
    assert [t["due_on"] for t in a["tasks"]] == [(date.today() + timedelta(days=d - 1)).isoformat() for d in (7, 10, 14)]
    with db.pool.connection() as c:
        ev = c.execute("SELECT evidence FROM roadmaps WHERE id=%s", (a["id"],)).fetchone()["evidence"]
    assert ev["subject_pct"] != 99 and any(f["code"] == "DECLINING" for f in ev["flags"])
    assert any(t["topic"] == "Graphs" and t["pct"] == 40.0 for t in ev["topics"])
    b = client.post("/api/roadmaps", json=plan()).json()
    assert b["version"] == 2
    lst = client.get("/api/roadmaps").json()
    assert {x["id"]: x["status"] for x in lst} == {a["id"]: "superseded", b["id"]: "active"}


MUTATIONS = [
    lambda p: p["tasks"][0].update(resource_id=999999),   # unapproved resource
    lambda p: p["tasks"][0].update(minutes=120),          # over the daily budget
    lambda p: p["tasks"][2].update(day_to=20),            # outside the plan
    lambda p: p["tasks"].reverse(),                       # out of order
    lambda p: p["tasks"][1].update(day_from=5),           # overlap
]


@pytest.mark.parametrize("mutate", MUTATIONS)
def test_save_rechecks_the_client_copy(client, mutate):
    login(client)
    p = plan()
    mutate(p)
    r = client.post("/api/roadmaps", json=p)
    assert r.status_code == 422


def test_save_allows_gaps_after_the_student_deletes_a_task(client):
    login(client)
    p = plan(tasks=[task(1, 7, "checkpoint"), task(11, 14, "checkpoint")])
    assert client.post("/api/roadmaps", json=p).status_code == 200


def test_owner_scoping(client, monkeypatch):
    login(client, "CS23001")
    rid = client.post("/api/roadmaps", json=plan()).json()["id"]
    client.post("/api/auth/logout")
    client.cookies.clear()
    login(client, "CS23002")
    assert client.get(f"/api/roadmaps/{rid}").status_code == 404
    assert client.post(f"/api/roadmaps/{rid}/share").status_code == 404
    assert client.get(f"/api/roadmaps/{rid}/report").status_code == 404
    assert client.get("/api/roadmaps").json() == []
