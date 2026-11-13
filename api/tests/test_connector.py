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
        assert count(c, "SELECT count(*) AS n FROM resources") == len(list(csv.DictReader(open(SEED / "resources.csv"))))


def test_resource_urls_unique_and_kinds_valid():
    rows = list(csv.DictReader(open(SEED / "resources.csv")))
    assert len(rows) >= 80 and len({r["url"] for r in rows}) == len(rows)
    assert {r["kind"] for r in rows} <= {"video", "article", "practice", "course"}


@pytest.fixture
def bad_folder(tmp_path):
    for f in ("subjects.csv", "students.csv", "resources.csv", "roles.csv", "attendance.csv", "prereqs.csv", "questions.csv", "backlogs.csv"):
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


def test_any_rejected_row_aborts_the_whole_batch(client, bad_folder):
    """LLD_next F4: bad rows are all reported and nothing at all is written."""
    with db.pool.connection() as c:
        before = count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'")
        res = connector.import_csv(c, bad_folder, "baseline")
        assert len(res["errors"]) == 3
        msgs = " | ".join(e["error"] for e in res["errors"])
        assert "unknown roll_no" in msgs and "outside 0.." in msgs and "duplicate" in msgs
        assert count(c, "SELECT count(*) AS n FROM assessments WHERE batch='baseline'") == before   # batch unchanged
        log = c.execute("SELECT errors FROM imports ORDER BY id DESC LIMIT 1").fetchone()["errors"]
        assert len(log) == 3


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
        assert dsa.attended and dsa.total == 60 and len(dsa.rows) == 15  # 10 quizzes + 2 internals + 1 upcoming + 2 labs
        assert set(connector.class_means(c)) == {"DSA", "DBMS", "OS", "CN", "DM"}
        assert len(connector.get_resources(c, "DSA")) == sum(1 for r in csv.DictReader(open(SEED / "resources.csv")) if r["subject_code"] == "DSA")
        assert connector.role_map(c)["Software Developer"] == ["DBMS", "DSA", "OS"]
        assert connector.student_info(c, sid).roll_no == "CS23001"
        assert connector.last_import(c, "baseline") is not None


# --- the bundled seed's dates follow the clock (otherwise every student gets a "missing mark" after SEED_UPCOMING) ---

@pytest.mark.parametrize("today", [date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 25), date(2026, 12, 5), date(2027, 6, 1)])
def test_seed_shift_keeps_upcoming_in_the_future_and_the_designed_missing_mark_in_the_past(today):
    shift = connector.seed_shift_days(today)
    assert connector.SEED_UPCOMING + timedelta(days=shift) > today          # still upcoming, never "missing"
    assert connector.SEED_ANCHOR - timedelta(weeks=3) + timedelta(days=shift) < today   # the designed missing mark stays missing


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


# ---- v2: new CSVs, validation, links (LLD_next C3.6) -------------------------------------------------------
import json  # noqa: E402


def folder_with(tmp_path, **edits):
    """A copy of the seed where selected files are replaced or appended to (name -> text to append, or callable)."""
    for f in SEED.iterdir():
        if f.suffix in (".csv", ".json"):
            shutil.copy(f, tmp_path / f.name)
    for name, extra in edits.items():
        p = tmp_path / name
        p.write_text(p.read_text() + extra)
    return tmp_path


def errors_of(res):
    return " | ".join(e["error"] for e in res["errors"])


def test_rejected_resource_domain_prereq_cycle_bad_question_and_duplicate_backlog_all_abort(client, tmp_path):
    q = "DSA,Trees,basic,Bad question,only,three,options,here,a,why,me\nDSA,Trees,basic,Dup opts,x,x,y,z,a,why,me\n"
    f = folder_with(
        tmp_path,
        **{"resources.csv": "DSA,Trees,Evil,https://evil.example.com/x,article,beginner,en,20,\n",
           "prereqs.csv": "DSA,Trees,DSA,Graphs\n",                       # Graphs <- Trees already exists: Trees <- Graphs is a cycle
           "questions.csv": q,
           "backlogs.csv": "CS23005,DM,2,pending,baseline\n"})             # duplicate (student, subject, batch)
    with db.pool.connection() as c:
        before = (count(c, "SELECT count(*) AS n FROM resources"), count(c, "SELECT count(*) AS n FROM questions"), count(c, "SELECT count(*) AS n FROM backlogs"))
        res = connector.import_csv(c, f, "baseline")
        msg = errors_of(res)
        assert "not on the approved domain list" in msg and "cycle" in msg and "distinct options" in msg and "duplicate" in msg
        after = (count(c, "SELECT count(*) AS n FROM resources"), count(c, "SELECT count(*) AS n FROM questions"), count(c, "SELECT count(*) AS n FROM backlogs"))
    assert before == after


def test_an_institution_column_is_ignored_and_no_table_stores_it(client, tmp_path):
    f = folder_with(tmp_path)
    text = (f / "students.csv").read_text().splitlines()
    (f / "students.csv").write_text("\n".join([text[0] + ",institution"] + [l + ",IIT Test" for l in text[1:]]) + "\n")
    with db.pool.connection() as c:
        res = connector.import_csv(c, f, "baseline", shift_days=connector.seed_shift_days())
        assert res["errors"] == []
        cols = {r["column_name"] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public'").fetchall()}
    assert not any("institution" in x or "college" in x for x in cols)


def test_reimporting_questions_keeps_ids(client):
    with db.pool.connection() as c:
        a = {(r["topic"], r["stem"]): r["id"] for r in c.execute("SELECT id, topic, stem FROM questions").fetchall()}
        connector.import_csv(c, SEED, "baseline", shift_days=connector.seed_shift_days())
        b = {(r["topic"], r["stem"]): r["id"] for r in c.execute("SELECT id, topic, stem FROM questions").fetchall()}
    assert a == b and len(a) >= 60


def test_backlogs_and_prereqs_are_loaded(client):
    with db.pool.connection() as c:
        pm = connector.prereq_map(c)
        sid = c.execute("SELECT id FROM students WHERE roll_no='CS23005'").fetchone()["id"]
        rec = connector.get_records(c, sid)
    assert ("DSA", "Trees") in pm["DSA", "Graphs"] and ("DM", "Graph Theory") in pm["DSA", "Graphs"]
    dm = next(s for s in rec.subjects if s.code == "DM")
    assert dm.backlog and dm.backlog.status == "pending" and dm.backlog.from_semester == 2


def test_check_links_marks_404_and_off_domain_redirects_broken_and_200_ok(client):
    import httpx

    with db.pool.connection() as c:
        rows = c.execute("SELECT id, url FROM resources ORDER BY id LIMIT 3").fetchall()
    bad404, bad_redirect, good = (r["url"] for r in rows)

    def handler(req: httpx.Request):
        if str(req.url) == bad404:
            return httpx.Response(404)
        if str(req.url) == bad_redirect:
            return httpx.Response(302, headers={"location": "https://parked.example.net/"})
        if req.url.host == "parked.example.net":
            return httpx.Response(200)
        return httpx.Response(200)

    client_ = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    try:
        with db.pool.connection() as c:
            ids = [r["id"] for r in rows]
            broken = connector.check_links(c, client=client_)
            states = {r["id"]: (r["link_ok"], r["checked_on"]) for r in c.execute("SELECT id, link_ok, checked_on FROM resources WHERE id = ANY(%s)", (ids,)).fetchall()}
        assert {b["url"] for b in broken} >= {bad404, bad_redirect}
        assert states[ids[0]][0] is False and states[ids[1]][0] is False and states[ids[2]] == (True, date.today())
    finally:
        with db.pool.connection() as c:
            c.execute("UPDATE resources SET link_ok=true")
            c.commit()


def test_env_file_inline_comments_are_stripped(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("V2_TEST_KEY=abc   # a comment\nV2_TEST_PLAIN=xyz\n# whole line\n")
    for k in ("V2_TEST_KEY", "V2_TEST_PLAIN"):
        monkeypatch.delenv(k, raising=False)
    connector._load_env_file(env)
    import os
    assert os.environ["V2_TEST_KEY"] == "abc" and os.environ["V2_TEST_PLAIN"] == "xyz"
    for k in ("V2_TEST_KEY", "V2_TEST_PLAIN"):
        os.environ.pop(k, None)
