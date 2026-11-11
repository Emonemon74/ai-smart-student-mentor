import csv
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import connector, db

SEED = Path(__file__).resolve().parent.parent / "seed"


def count(conn, sql):
    return conn.execute(sql).fetchone()["n"]


def test_import_twice_gives_same_counts(client):
    with db.pool.connection() as c:
        a = connector.import_csv(c, SEED, "baseline", shift_days=connector.seed_shift_days())
        b = connector.import_csv(c, SEED, "baseline", shift_days=connector.seed_shift_days())
    assert a["counts"] == b["counts"] and a["errors"] == [] == b["errors"]


def test_db_counts_match_valid_csv_rows(client):
    n_ass = sum(1 for r in csv.DictReader(open(SEED / "assessments.csv")) if r["batch"] == "baseline")
    n_att = sum(1 for r in csv.DictReader(open(SEED / "attendance.csv")) if r["batch"] == "baseline")
    with db.pool.connection() as c:
        assert count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'") == n_ass
        assert count(c, "SELECT count(*) AS n FROM attendance WHERE batch='baseline'") == n_att
        assert count(c, "SELECT count(*) AS n FROM students") == 30
        assert count(c, "SELECT count(*) AS n FROM resources") == 50


def test_resource_urls_unique_and_kinds_valid():
    rows = list(csv.DictReader(open(SEED / "resources.csv")))
    assert len(rows) == 50 and len({r["url"] for r in rows}) == 50
    assert {r["kind"] for r in rows} <= {"video", "article", "practice", "course"}


@pytest.fixture
def bad_folder(tmp_path):
    for f in ("subjects.csv", "students.csv", "resources.csv", "roles.csv", "attendance.csv"):
        shutil.copy(SEED / f, tmp_path / f)
    head = "roll_no,subject_code,topic,kind,score,max,taken_on,batch\n"
    (tmp_path / "assessments.csv").write_text(
        head
        + "CS23001,DSA,Trees,quiz,7,10,2026-09-01,baseline\n"       # good
        + "NOPE999,DSA,Trees,quiz,7,10,2026-09-01,baseline\n".replace("NOPE999,DSA,Trees,quiz,7,10,2026-09-01", "NOPE999,DSA,Trees,quiz,7,10,2026-09-02")  # unknown roll no
        + "CS23001,DSA,Graphs,quiz,11,10,2026-09-03,baseline\n"      # score > max
        + "CS23001,DSA,Trees,quiz,7,10,2026-09-01,baseline\n"        # duplicate of the first
        + "CS23002,DSA,Trees,quiz,,10,2026-12-30,baseline\n"         # blank score is fine (upcoming)
    )
    return tmp_path


def test_bad_rows_are_reported_and_the_rest_imported(client, bad_folder):
    try:
        with db.pool.connection() as c:
            res = connector.import_csv(c, bad_folder, "baseline")
            assert len(res["errors"]) == 3
            msgs = " | ".join(e["error"] for e in res["errors"])
            assert "unknown roll_no" in msgs and "outside 0.." in msgs and "duplicate" in msgs
            assert res["counts"]["assessments"] == 2
            assert count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'") == 2
            log = c.execute("SELECT errors FROM imports ORDER BY id DESC LIMIT 1").fetchone()["errors"]
            assert len(log) == 3
    finally:  # restore the shared baseline for later tests
        with db.pool.connection() as c:
            connector.import_csv(c, SEED, "baseline", shift_days=connector.seed_shift_days())


def test_review_import_leaves_baseline_untouched(client):
    with db.pool.connection() as c:
        before = count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'")
        res = connector.import_csv(c, SEED, "review", shift_days=connector.seed_shift_days())
        assert res["errors"] == []
        assert count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'") == before
        assert count(c, "SELECT count(*) AS n FROM assessments WHERE batch='review'") > 0
        c.execute("DELETE FROM assessments WHERE batch='review'")
        c.execute("DELETE FROM attendance WHERE batch='review'")
        c.commit()


def test_records_and_helpers(client):
    with db.pool.connection() as c:
        sid = c.execute("SELECT id FROM students WHERE roll_no='CS23001'").fetchone()["id"]
        rec = connector.get_records(c, sid)
        assert {s.code for s in rec.subjects} == {"DSA", "DBMS", "OS", "CN", "DM"}
        dsa = next(s for s in rec.subjects if s.code == "DSA")
        assert dsa.attended and dsa.total == 60 and len(dsa.rows) == 13  # 10 quizzes + 2 internals + 1 upcoming
        assert set(connector.class_means(c)) == {"DSA", "DBMS", "OS", "CN", "DM"}
        assert len(connector.get_resources(c, "DSA")) == 10
        assert connector.role_map(c)["Software Developer"] == ["DBMS", "DSA", "OS"]
        assert connector.student_info(c, sid).roll_no == "CS23001"
        assert connector.last_import(c, "baseline") is not None


# --- the bundled seed's dates follow the clock (otherwise every student gets a "missing mark" after SEED_UPCOMING) ---

@pytest.mark.parametrize("today", [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 24), date(2026, 12, 5), date(2027, 6, 1)])
def test_seed_shift_keeps_upcoming_in_the_future_and_the_designed_missing_mark_in_the_past(today):
    shift = connector.seed_shift_days(today)
    assert connector.SEED_UPCOMING + timedelta(days=shift) > today          # still upcoming, never "missing"
    assert date(2026, 10, 20) + timedelta(days=shift) < today                # the designed missing mark stays missing


def test_seed_shift_is_never_negative():
    assert connector.seed_shift_days(date(2026, 1, 1)) == 0
    assert connector.seed_shift_days(connector.SEED_ANCHOR) == 0
    assert connector.seed_shift_days(connector.SEED_ANCHOR + timedelta(days=25)) == 25


def test_reimport_with_a_different_shift_replaces_the_batch_instead_of_duplicating(client):
    def state(c):
        up = c.execute("SELECT max(taken_on) AS d FROM assessments WHERE batch='baseline' AND score IS NULL").fetchone()["d"]  # the upcoming internal
        return up, count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'")
    try:
        with db.pool.connection() as c:
            connector.import_csv(c, SEED, "baseline", shift_days=3)
            d3, t3 = state(c)
            connector.import_csv(c, SEED, "baseline", shift_days=40)
            d40, t40 = state(c)
        assert d3 == connector.SEED_UPCOMING + timedelta(days=3)
        assert d40 == connector.SEED_UPCOMING + timedelta(days=40)
        assert t3 == t40                                                    # replaced, not appended
    finally:
        with db.pool.connection() as c:                                     # leave the shared session data current
            connector.import_csv(c, SEED, "baseline", shift_days=connector.seed_shift_days())


@pytest.mark.parametrize("late_today", [date(2026, 12, 5), date(2027, 6, 1)])
def test_a_late_import_flags_nobody_as_missing_except_the_designed_case(client, late_today):
    """The failure this guards against: 30 of 30 students flagged 'missing mark' once the clock passed 24 Nov."""
    from app import analytics
    try:
        with db.pool.connection() as c:
            connector.import_csv(c, SEED, "baseline", shift_days=connector.seed_shift_days(late_today))
            ids = [r["id"] for r in c.execute("SELECT id FROM students ORDER BY id").fetchall()]
            profiles = [analytics.build_profile(c, sid, "baseline", late_today) for sid in ids]
        missing = [f for p in profiles for s in p.subjects for f in s.flags if f.code == "MISSING"]
        assert len(missing) == 1                                            # only the one designed missing-mark student
        assert all(p.upcoming for p in profiles)                            # everyone still has an upcoming internal
    finally:
        with db.pool.connection() as c:
            connector.import_csv(c, SEED, "baseline", shift_days=connector.seed_shift_days())
