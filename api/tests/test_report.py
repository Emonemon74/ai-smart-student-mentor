from app import connector, db
from tests.conftest import login
from tests.test_roadmap import plan

SEED = connector.Path(__file__).resolve().parent.parent / "seed"


def save(client):
    login(client)
    return client.post("/api/roadmaps", json=plan()).json()


def import_review():
    with db.pool.connection() as c:
        connector.import_csv(c, SEED, "review", shift_days=connector.seed_shift_days())


def test_no_review_batch_means_no_verified_data(client):
    rid = save(client)["id"]
    r = client.get(f"/api/roadmaps/{rid}/report").json()
    assert r["has_review_data"] is False and r["remaining_flags"] == [] and r["review_subject_pct"] is None
    assert all(v["review_pct"] is None and v["note"] == "No comparable assessment yet" for v in r["verified"])
    assert r["caveat"].startswith("Changes compare similar assessments")


def test_marking_every_task_done_never_changes_verified_figures(client):
    rm = save(client)
    import_review()
    before = client.get(f"/api/roadmaps/{rm['id']}/report").json()
    from tests.test_share import new_phone, share
    phone = new_phone(client)
    phone.get(f"/api/r/{share(client, rm['id'])}")
    for t in rm["tasks"]:
        assert phone.patch(f"/api/phone/tasks/{t['id']}", json={"status": "done"}).status_code == 204
    after = client.get(f"/api/roadmaps/{rm['id']}/report").json()
    assert after["verified"] == before["verified"] and after["review_subject_pct"] == before["review_subject_pct"]
    assert after["baseline_subject_pct"] == before["baseline_subject_pct"]
    assert before["self_reported"]["done"] == 0 and after["self_reported"]["done"] == 3


def test_verified_compares_same_topic_and_kind_and_shows_improvement(client):
    rid = save(client)["id"]
    import_review()
    r = client.get(f"/api/roadmaps/{rid}/report").json()
    assert r["has_review_data"] is True
    by = {v["topic"]: v for v in r["verified"]}
    assert by["Graphs"]["baseline_pct"] == 40.0 and by["Graphs"]["review_pct"] == 60.0 and by["Graphs"]["delta"] == 20.0  # seed "~62%" lands on 60 (half-mark steps)
    assert by["Trees"]["baseline_pct"] == 55.0 and by["Trees"]["review_pct"] == 70.0
    assert r["review_subject_pct"] is not None and r["baseline_subject_pct"] is not None


def test_topic_without_a_review_quiz_gets_a_note_not_a_delta(client):
    rid = save(client)["id"]
    import_review()
    with db.pool.connection() as c:
        c.execute("DELETE FROM assessments WHERE batch='review' AND topic='Graphs'")
        c.commit()
    by = {v["topic"]: v for v in client.get(f"/api/roadmaps/{rid}/report").json()["verified"]}
    assert by["Graphs"]["delta"] is None and by["Graphs"]["note"] == "No comparable assessment yet"
    assert by["Trees"]["delta"] is not None


def test_overdue_pending_task_is_listed(client):
    rm = save(client)
    with db.pool.connection() as c:
        c.execute("UPDATE tasks SET due_on = current_date - 1 WHERE id=%s", (rm["tasks"][0]["id"],))
        c.commit()
    r = client.get(f"/api/roadmaps/{rm['id']}/report").json()
    assert [t["id"] for t in r["self_reported"]["overdue"]] == [rm["tasks"][0]["id"]]
    assert r["self_reported"]["pending"] == 3


# ---- v2: kiosk checks, indicators, next steps, limitations (LLD_next C9.5) -------------------------------
from datetime import date, timedelta  # noqa: E402

from app import report  # noqa: E402
from app.schemas import CheckChange, Flag, TaskView, TopicChange  # noqa: E402
from tests.conftest import take_check  # noqa: E402
from tests.test_roadmap import task  # noqa: E402


def test_a_review_check_changes_checks_and_indicator_but_never_the_verified_figures(client):
    rm = save(client)
    before = client.get(f"/api/roadmaps/{rm['id']}/report").json()
    take_check(client, "DSA", "Trees", correct=3, purpose="level")                       # before the plan? it is after: plan was just saved
    after = client.get(f"/api/roadmaps/{rm['id']}/report").json()
    assert after["verified"] == before["verified"] and after["review_subject_pct"] == before["review_subject_pct"]
    assert after["baseline_subject_pct"] == before["baseline_subject_pct"] and after["self_reported"] == before["self_reported"]


def test_check_changes_are_before_and_after_the_plan_started(client):
    login(client)
    take_check(client, "DSA", "Graphs", correct=1)                                       # before the plan: foundation
    p = plan(tasks=[task(1, 7, "checkpoint", rid=graph_rid()), task(8, 14, "checkpoint", rid=graph_rid())])
    rm = client.post("/api/roadmaps", json=p).json()
    r0 = client.get(f"/api/roadmaps/{rm['id']}/report").json()
    g0 = next(c for c in r0["checks"] if c["topic"] == "Graphs")
    assert g0["before_level"] == "foundation" and g0["after_level"] is None and g0["note"] == "No check after the plan started yet"
    take_check(client, "DSA", "Graphs", correct=5, purpose="review", roadmap_id=rm["id"])
    r1 = client.get(f"/api/roadmaps/{rm['id']}/report").json()
    g1 = next(c for c in r1["checks"] if c["topic"] == "Graphs")
    assert g1["before_score"] == "1/5" and g1["after_score"] == "5/5" and g1["after_level"] == "advanced"
    acc = next(i for i in r1["indicators"] if i["code"] == "check_accuracy")
    assert acc["value"] == "1/5 → 5/5" and acc["source"] == "kiosk_check"
    assert r1["verified"] == r0["verified"]


def graph_rid():
    with db.pool.connection() as c:
        return c.execute("SELECT r.id FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code='DSA' AND r.topic='Graphs' ORDER BY r.id LIMIT 1").fetchone()["id"]


def test_indicators_follow_the_goals_order_and_sources(client):
    login(client)
    for goal, codes_ in (("semester", ["verified_change", "check_accuracy", "task_completion"]), ("gate", ["check_accuracy", "check_speed", "verified_change"])):
        p = plan()
        p["goal"] = goal
        rid = client.post("/api/roadmaps", json=p).json()["id"]
        ind = client.get(f"/api/roadmaps/{rid}/report").json()["indicators"]
        assert [i["code"] for i in ind] == codes_
        assert {i["code"]: i["source"] for i in ind}["task_completion" if goal == "semester" else "verified_change"] in ("self_reported", "verified")


def test_a_wellbeing_request_never_changes_the_academic_referral_status(client):
    rm = save(client)
    client.post("/api/requests", json={"category": "wellbeing", "share_note": False})
    assert client.get(f"/api/roadmaps/{rm['id']}/report").json()["academic_referral"] == "none"
    client.post("/api/requests", json={"category": "academic"})
    assert client.get(f"/api/roadmaps/{rm['id']}/report").json()["academic_referral"] == "open"


def test_track_plan_report_has_no_verified_data_and_the_track_limitation(client):
    login(client)
    with db.pool.connection() as c:
        ids = [r["id"] for r in c.execute("SELECT r.id FROM resources r JOIN subjects s ON s.id=r.subject_id WHERE s.code='APT' ORDER BY r.id").fetchall()]
    p = plan(tasks=[task(1, 7, "checkpoint", rid=ids[0]), task(8, 14, "checkpoint", rid=ids[1])])
    p["goal"], p["subject_code"] = "placement", "APT"
    rid = client.post("/api/roadmaps", json=p).json()["id"]
    r = client.get(f"/api/roadmaps/{rid}/report").json()
    assert r["verified"] == [] and any("is a track without institutional marks" in x for x in r["limitations"])


def test_phone_report_has_next_steps_and_the_same_content_as_the_kiosk(client):
    from tests.test_share import new_phone, share
    rm = save(client)
    phone = new_phone(client)
    phone.get(f"/api/r/{share(client, rm['id'])}")
    pr = phone.get("/api/phone/report").json()
    assert pr["next_steps"] and pr == client.get(f"/api/roadmaps/{rm['id']}/report").json()
    assert "wellbeing" not in str(pr).lower()


# --- next_steps: pure, first two matches -----------------------------------------------------------------
def tv(i, status="pending", kind="learn", due=1):
    return TaskView(id=i, day_from=1, day_to=2, kind=kind, topic="T", activity="a", reason="r", minutes=30, resource_id=1, check="c",
                    due_on=date.today() + timedelta(days=due), status=status)


def ctx(**kw):
    base = dict(tasks=[tv(1), tv(2)], plan_topics=["Graphs"], checks=[], last_check_seconds=None, has_review=False, base_like=50.0, review_like=None,
                verified=[], remaining=[], evidence={"topics": []}, subject_name="DSA", subject_kind="course", baseline_as_of=date(2026, 11, 1),
                review_imported_at=None, today=date.today(), after_levels={})
    base.update(kw)
    return report.Ctx(**base)


def flag(code, topic, **v):
    return Flag(code=code, subject_code="DSA", topic=topic, values={"n": 2, **v}, reason="x")


def codes_of(c):
    return [s.code for s in report.next_steps(c)]


def test_next_steps_table():
    assert codes_of(ctx()) == ["check", "await_evidence"]
    after = [CheckChange(topic="Graphs", before_level=None, after_level="foundation", after_score="1/5", after_on=date.today())]
    assert codes_of(ctx(checks=after, after_levels={"Graphs": "foundation"}))[0] == "mentor"
    assert codes_of(ctx(has_review=True, remaining=[flag("PREREQ_GAP", "Graphs", prereq="Trees")]))[0] == "prerequisite"
    down = [TopicChange(topic="Graphs", kind="quiz", baseline_pct=50, review_pct=48, delta=-2, note=None)]
    assert codes_of(ctx(has_review=True, remaining=[flag("WEAK_TOPIC", "Graphs")], verified=down))[0] == "mentor"
    up = [TopicChange(topic="Graphs", kind="quiz", baseline_pct=50, review_pct=55, delta=5, note=None)]
    assert codes_of(ctx(has_review=True, remaining=[flag("WEAK_TOPIC", "Graphs")], verified=up))[0] == "revise"
    assert codes_of(ctx(has_review=True, tasks=[tv(1, due=-2), tv(2, due=-2)]))[0] == "revise"       # under 30% done and overdue
    assert codes_of(ctx(has_review=True, tasks=[tv(1, "done"), tv(2, "done")])) == ["continue"]
    assert all(len(report.next_steps(ctx(has_review=True, remaining=[flag("PREREQ_GAP", "Graphs", prereq="Trees")], verified=down))) <= 2 for _ in range(1))


def test_limitations_list_what_is_thin():
    c = ctx(evidence={"topics": [{"topic": "Graphs", "n": 2}, {"topic": "Trees", "n": 4}]})
    out = report.limitations(c)
    assert "Graphs rests on 2 assessments." in out and not any(x.startswith("Trees rests") for x in out)
    assert "No review assessment has been imported yet." in out and any(x.startswith("Records as of 2026-11-01") for x in out)
    assert len(out) == len(set(out))
