import csv
import shutil
from pathlib import Path

import pytest

from app import connector, db

SEED = Path(__file__).resolve().parent.parent / "seed"


def count(conn, sql):
    return conn.execute(sql).fetchone()["n"]


def test_import_twice_gives_same_counts(client):
    with db.pool.connection() as c:
        a = connector.import_csv(c, SEED, "baseline")
        b = connector.import_csv(c, SEED, "baseline")
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
            connector.import_csv(c, SEED, "baseline")


def test_review_import_leaves_baseline_untouched(client):
    with db.pool.connection() as c:
        before = count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'")
        res = connector.import_csv(c, SEED, "review")
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
