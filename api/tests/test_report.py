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
