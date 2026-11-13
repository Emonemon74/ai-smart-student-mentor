"""Catalogue: goals, eligibility, the resource matcher and contacts (LLD_next C16.4)."""
import pytest

from app import catalogue, connector, db
from app.connector import ResourceRow
from tests.conftest import login


def res(topic="T", level="beginner", lang="en", minutes=30, kind="article", goals=(), ok=True, i=[0]):
    i[0] += 1
    return ResourceRow(i[0], topic, f"r{i[0]}", f"https://x/{i[0]}", kind, level, lang, minutes, list(goals), ok)


@pytest.mark.parametrize("lv,inside,outside", [
    ("foundation", ["foundation", "beginner", "intermediate"], ["advanced"]),
    ("beginner", ["foundation", "beginner", "intermediate", "advanced"], []),
    ("intermediate", ["beginner", "intermediate", "advanced"], ["foundation"]),
    ("advanced", ["intermediate", "advanced"], ["foundation", "beginner"])])
def test_level_window_is_one_below_to_two_above(lv, inside, outside):
    pool = [res(level=x) for x in ("foundation", "beginner", "intermediate", "advanced")]
    got = {r.level for r in catalogue.pick_resources(pool, goal=None, levels={"T": lv}, lang="en", daily_minutes=None) if r.topic == "T"}
    # the never-empty fallback only applies when a topic would have nothing: here the window always keeps something
    assert set(inside) <= got and not (set(outside) & got)


def test_language_hindi_first_then_english_never_another():
    pool = [res(lang="en"), res(lang="hi"), res(lang="ta")]
    out = catalogue.pick_resources(pool, goal=None, levels={}, lang="hi", daily_minutes=None)
    assert [r.lang for r in out] == ["hi", "en"]


def test_time_filter_drops_long_videos_but_keeps_courses():
    pool = [res(minutes=45, kind="video"), res(minutes=300, kind="course"), res(minutes=15, kind="article")]
    out = catalogue.pick_resources(pool, goal=None, levels={}, lang="en", daily_minutes=20)
    assert sorted((r.kind, r.minutes) for r in out) == [("article", 15), ("course", 300)]


def test_broken_links_and_other_goals_are_excluded_and_a_topic_is_never_empty():
    pool = [res(topic="A", ok=False), res(topic="B", goals=["gate"]), res(topic="C", level="advanced", minutes=90, kind="video")]
    out = catalogue.pick_resources(pool, goal="semester", levels={"C": "foundation"}, lang="en", daily_minutes=30)
    topics = [r.topic for r in out]
    assert "A" not in topics and "B" not in topics        # broken link; goal-tagged for another goal
    assert "C" in topics                                  # outside the window, but the fallback keeps the topic usable


def test_goal_tagged_resource_appears_for_that_goal():
    pool = [res(goals=["gate"])]
    assert catalogue.pick_resources(pool, goal="gate", levels={}, lang="en", daily_minutes=None)


def test_goal_catalogue_is_consistent():
    from app.report import INDICATORS
    assert list(catalogue.GOALS) == ["semester", "backlog", "gate", "upsc", "placement", "higher_studies"]
    for g in catalogue.GOALS.values():
        assert set(g.indicator_codes) <= set(INDICATORS)


def eligible(client, roll, goal):
    login(client, roll)
    return {g["code"]: [s["code"] for s in g["subjects"]] for g in client.get("/api/goals").json()}[goal]


def test_backlog_goal_only_for_a_student_with_a_pending_backlog(client):
    assert eligible(client, "CS23005", "backlog") == ["DM"]
    client.cookies.clear()
    assert eligible(client, "CS23001", "backlog") == []


def test_placement_includes_the_aptitude_track_for_everyone_and_tracks_need_no_records(client):
    subs = eligible(client, "CS23001", "placement")
    assert "APT" in subs and "DSA" in subs
    client.cookies.clear()
    assert eligible(client, "CS23001", "upsc") == ["UPSC"]


def test_general_mode_lists_everything_and_contacts_need_no_session(client):
    login(client, "CS23002", scope="general")
    goals = {g["code"]: [s["code"] for s in g["subjects"]] for g in client.get("/api/goals").json()}
    assert goals["backlog"] == ["DSA", "DBMS", "OS", "CN", "DM"] and goals["upsc"] == ["UPSC"]
    client.cookies.clear()
    r = client.get("/api/support/contacts")
    assert r.status_code == 200 and {c["team"] for c in r.json()} == {"faculty_mentor", "counsellor", "records_office", "urgent"}


def test_resources_endpoint_is_level_aware_for_a_student_and_open_in_general_mode(client):
    login(client)
    r = client.get("/api/resources", params={"subject_code": "DSA", "topic": "Graphs", "goal": "gate"}).json()
    assert r and {x["level"] for x in r} <= {"foundation", "beginner", "intermediate", "advanced"}
    assert all(x["source"] and not x["source"].startswith("www.") for x in r)
    # CS23001's Graphs is foundation (records): the advanced Dijkstra page is outside the window
    assert "Dijkstra shortest paths" not in {x["title"] for x in r}
    client.cookies.clear()
    login(client, scope="general")
    g = client.get("/api/resources", params={"subject_code": "DSA", "topic": "Graphs", "goal": "gate"}).json()
    assert "Dijkstra shortest paths" in {x["title"] for x in g}
    assert client.get("/api/resources", params={"subject_code": "NOPE"}).status_code == 404


def test_contacts_file_loads_and_validates():
    assert len(catalogue.contacts()) == 4 and [c.team for c in catalogue.contacts({"urgent"})] == ["urgent"]


def test_every_seed_resource_is_on_the_approved_list():
    from app import config
    with db.pool.connection() as c:
        urls = [r["url"] for r in c.execute("SELECT url FROM resources").fetchall()]
    assert urls and all(config.approved_host(__import__("urllib.parse", fromlist=["urlparse"]).urlparse(u).netloc) for u in urls)
