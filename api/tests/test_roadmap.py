from datetime import date, timedelta

import pytest

from app import connector, db, llm, roadmap
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
    # The seed's upcoming internal moves with the clock; it must be listed as upcoming, never as a missing mark.
    upcoming = (connector.SEED_UPCOMING + timedelta(days=connector.seed_shift_days())).isoformat()
    assert "Graphs" in user and "BFS is hard" in user and f"internal on {upcoming}" in user
    assert "no recorded score" not in user
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


# ---- v2: goals, levels, capacity, review date on save, track plans (LLD_next C7.7) ------------------------
from tests.conftest import take_check  # noqa: E402


def gplan(goal="semester", subject="DSA", **kw):
    p = plan(**kw)
    p["goal"], p["subject_code"] = goal, subject
    return p


def tasks_for(subject, n=3):
    """A valid three-task plan using real resources of the subject (checkpoint first so a 7-day rule is met)."""
    with db.pool.connection() as c:
        ids = [r["id"] for r in c.execute("SELECT r.id FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code=%s AND r.link_ok ORDER BY r.id", (subject,)).fetchall()]
    return [task(1, 7, "checkpoint", rid=ids[0]), task(8, 10, "practice", rid=ids[1]), task(11, 14, "checkpoint", rid=ids[0])]


def test_ineligible_subject_for_a_goal_is_404_and_backlog_goal_works_for_the_right_student(client):
    login(client, "CS23001")
    assert client.post("/api/roadmaps", json=gplan("backlog", "DM", tasks=tasks_for("DM"))).status_code == 404
    assert client.post("/api/roadmaps", json=gplan("upsc", "DSA")).status_code == 404
    client.cookies.clear()
    login(client, "CS23005")
    r = client.post("/api/roadmaps", json=gplan("backlog", "DM", tasks=tasks_for("DM")))
    assert r.status_code == 200 and r.json()["goal"] == "backlog" and r.json()["goal_name"] == "Backlog recovery"


def test_a_track_plan_drafts_and_saves_with_a_track_safe_snapshot(client, monkeypatch):
    login(client)
    t = tasks_for("APT")
    r = client.post("/api/roadmaps", json=gplan("placement", "APT", tasks=t))
    assert r.status_code == 200
    with db.pool.connection() as c:
        ev = c.execute("SELECT evidence FROM roadmaps WHERE id=%s", (r.json()["id"],)).fetchone()["evidence"]
    assert ev == {"flags": [], "subject_pct": None, "topics": [], "as_of": None}
    seen = fake_plan_llm(monkeypatch, tasks_for("APT"))
    d = client.post("/api/roadmaps/draft", json={**draft_body(subject_code="APT"), "goal": "placement"})
    assert d.status_code == 200
    user = seen["messages"][1]["content"]
    assert "a track without institutional marks" in user and "no institutional records" in user and "GOAL: Placement / coding" in user


def test_over_daily_capacity_at_241_not_at_240_and_finished_plans_do_not_count(client):
    login(client)

    def heavy(goal, minutes):
        p = gplan(goal, "DSA", tasks=[task(1, 7, "checkpoint", minutes=minutes), task(8, 10, "practice", minutes=minutes), task(11, 14, "checkpoint", minutes=minutes)])
        p["daily_minutes"] = minutes
        return p

    assert client.post("/api/roadmaps", json=heavy("semester", 120)).status_code == 200
    assert client.post("/api/roadmaps", json=heavy("gate", 121)).json() == {"detail": "over_daily_capacity"}      # 120 + 121 = 241
    assert client.post("/api/roadmaps", json=heavy("gate", 120)).status_code == 200                                 # 240 exactly
    assert client.post("/api/roadmaps", json=heavy("higher_studies", 60)).status_code == 422                        # both plans still run
    with db.pool.connection() as c:                                                                                 # both ended long ago
        c.execute("UPDATE roadmaps SET start_on = current_date - 40")
        c.commit()
    assert client.post("/api/roadmaps", json=heavy("higher_studies", 120)).status_code == 200


def test_same_subject_under_two_goals_keeps_two_active_plans_and_resave_supersedes_only_its_goal(client):
    login(client)
    t = tasks_for("DSA")
    a = client.post("/api/roadmaps", json=gplan("semester", tasks=t)).json()
    b = client.post("/api/roadmaps", json=gplan("gate", tasks=t)).json()
    c2 = client.post("/api/roadmaps", json=gplan("semester", tasks=t)).json()
    st = {x["id"]: x["status"] for x in client.get("/api/roadmaps").json()}
    assert st == {a["id"]: "superseded", b["id"]: "active", c2["id"]: "active"} and c2["version"] == 2 and b["version"] == 1


def test_save_with_a_past_review_date_is_rejected(client):
    login(client)
    p = plan()
    p["review_on"] = (date.today() + timedelta(days=3)).isoformat()
    assert client.post("/api/roadmaps", json=p).json() == {"detail": "review_too_soon"}
    p = plan()
    p["target_date"] = (date.today() - timedelta(days=1)).isoformat()
    assert client.post("/api/roadmaps", json=p).status_code == 422


def test_overrides_are_stored_with_source_student_audited_and_validated(client):
    login(client)
    p = plan()
    p["level_overrides"] = {"Graphs": "advanced"}
    r = client.post("/api/roadmaps", json=p).json()
    assert r["levels"]["Graphs"]["level"] == "advanced" and r["levels"]["Graphs"]["source"] == "student"
    with db.pool.connection() as c:
        assert c.execute("SELECT target FROM audit_log WHERE action='level_override'").fetchone()["target"] == "Graphs"
    p["level_overrides"] = {"Quantum": "advanced"}                                                 # not a topic of the subject
    assert client.post("/api/roadmaps", json=p).json() == {"detail": "invalid_plan"}


def test_draft_prompt_carries_goal_levels_responses_and_only_level_matched_resources(client, monkeypatch):
    seen = fake_plan_llm(monkeypatch, good())
    login(client)
    r = client.post("/api/roadmaps/draft", json={**draft_body(), "goal": "gate", "target_date": (date.today() + timedelta(days=90)).isoformat()})
    assert r.status_code == 200
    user = seen["messages"][1]["content"]
    assert "GOAL: GATE preparation" in user and "TARGET DATE:" in user and "PREREQ_GAP Graphs" in user
    assert "Graphs foundation (records)" in user and "RECOMMENDED RESPONSES:" in user
    graphs = [l for l in user.split("[") if "] Graphs" in l or l.split("]")[-1].strip().startswith("Graphs")]
    assert graphs and not any(", advanced," in l for l in graphs)                                   # Dijkstra (advanced) is out of the window


def test_free_text_task_topic_never_decides_the_catalogue_topic(client):
    """A task titled 'Binary trees' that points at a Trees resource counts as Trees in the report."""
    login(client)
    with db.pool.connection() as c:
        rid = c.execute("SELECT r.id FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code='DSA' AND r.topic='Trees' ORDER BY r.id LIMIT 1").fetchone()["id"]
    p = plan(tasks=[task(1, 7, "checkpoint", rid=rid, topic="Binary trees"), task(8, 14, "checkpoint", rid=rid, topic="Binary trees")])
    saved = client.post("/api/roadmaps", json=p).json()
    take_check(client, "DSA", "Trees", correct=5, purpose="review", roadmap_id=saved["id"])
    rep = client.get(f"/api/roadmaps/{saved['id']}/report").json()
    assert [c["topic"] for c in rep["checks"]] == ["Trees"]
    assert client.post("/api/diagnostics", json={"subject_code": "DSA", "topic": "Binary trees", "purpose": "review", "roadmap_id": saved["id"]}).status_code == 404


def test_review_checkin_is_owner_only_and_validated(client):
    login(client, "CS23001")
    rid = client.post("/api/roadmaps", json=plan()).json()["id"]
    assert client.post(f"/api/roadmaps/{rid}/review", json={"confidence": 2, "plan_fit": 4}).status_code == 204
    assert client.post(f"/api/roadmaps/{rid}/review", json={"confidence": 9}).status_code == 422
    client.post("/api/auth/logout")
    client.cookies.clear()
    login(client, "CS23002")
    assert client.post(f"/api/roadmaps/{rid}/review", json={}).status_code == 404
