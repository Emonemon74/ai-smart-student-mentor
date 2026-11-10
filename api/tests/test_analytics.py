"""Pure rule tests: no DB. Each rule fires at its threshold and not just past it."""
from datetime import date

from app import analytics
from app.connector import Row, StudentRecords, SubjectRecords

TODAY = date(2026, 11, 11)


def rows_for(pcts, kind="quiz", topics=None):
    return [Row((topics or ["T"] * len(pcts))[i], kind, p / 10 * 1.0, 10.0, date(2026, 8, 1 + i)) for i, p in enumerate(pcts)]


def rec(*subjects):
    return StudentRecords(1, list(subjects))


def sub(code, rows, att=(50, 60), name=None):
    return SubjectRecords(code, name or code, rows, att[0], att[1])


def codes(summary):
    return [f.code for f in summary.flags]


def test_pct_ignores_none_and_weights_by_max():
    assert analytics.pct([Row("t", "quiz", None, 10, TODAY)]) is None
    assert analytics.pct([Row("t", "quiz", 5, 10, TODAY), Row("t", "internal", 15, 30, TODAY), Row("t", "quiz", None, 10, TODAY)]) == 50.0


def test_low_vs_self_threshold():
    good = sub("A", rows_for([80] * 5))
    at = sub("B", rows_for([70] * 5))   # overall = 75 -> 70 is exactly 5 below
    s = analytics.analyse(rec(good, at), {}, TODAY)
    assert "LOW_VS_SELF" not in [c for x in s for c in codes(x)]
    # overall (80*5 + 64*5)/10 = 72, subject at 61 is 11 below -> fires
    s = analytics.analyse(rec(sub("A", rows_for([83] * 5)), sub("B", rows_for([61] * 5))), {}, TODAY)
    assert "LOW_VS_SELF" in codes(next(x for x in s if x.code == "B"))


def test_low_vs_class_threshold():
    r = rec(sub("A", rows_for([60] * 5)))
    assert "LOW_VS_CLASS" not in codes(analytics.analyse(r, {"A": 70.0}, TODAY)[0])   # exactly 10 below: no
    assert "LOW_VS_CLASS" in codes(analytics.analyse(r, {"A": 70.5}, TODAY)[0])


def test_declining_needs_four_quizzes_and_a_ten_point_fall():
    fall = rows_for([80, 80, 70, 70, 60, 60])        # first two 80, last two 60 -> fell 20
    assert "DECLINING" in codes(analytics.analyse(rec(sub("A", fall)), {}, TODAY)[0])
    mild = rows_for([80, 80, 70, 70, 71, 71])        # 80 -> 71 (9 points)
    assert "DECLINING" not in codes(analytics.analyse(rec(sub("A", mild)), {}, TODAY)[0])
    few = rows_for([90, 90, 40])
    assert "DECLINING" not in codes(analytics.analyse(rec(sub("A", few)), {}, TODAY)[0])


def test_low_attendance_threshold():
    assert "LOW_ATTENDANCE" not in codes(analytics.analyse(rec(sub("A", rows_for([70]), att=(45, 60))), {}, TODAY)[0])  # exactly 75
    f = analytics.analyse(rec(sub("A", rows_for([70]), att=(41, 60))), {}, TODAY)[0].flags
    assert [x.code for x in f] == ["LOW_ATTENDANCE"] and f[0].values["n"] == 60 and "41 of 60" in f[0].reason


def test_missing_vs_upcoming():
    rows = rows_for([70]) + [Row("All", "internal", None, 30, date(2026, 10, 10)), Row("All", "internal", None, 30, date(2026, 11, 24))]
    s = analytics.analyse(rec(sub("A", rows)), {}, TODAY)[0]
    assert codes(s) == ["MISSING"] and "2026-10-10" in s.flags[0].reason
    up = analytics.upcoming(rec(sub("A", rows)), TODAY)
    assert [(u.kind, u.on) for u in up] == [("internal", date(2026, 11, 24))]


def test_weak_topic_only_inside_a_flagged_subject():
    topics = ["Graphs", "Graphs", "Trees", "Trees"]
    weak = rows_for([40, 40, 60, 60], topics=topics)   # rising over time, so DECLINING cannot fire
    unflagged = analytics.analyse(rec(sub("A", weak)), {"A": 55.0}, TODAY)[0]
    assert "WEAK_TOPIC" not in codes(unflagged)
    flagged = analytics.analyse(rec(sub("A", weak)), {"A": 70.0}, TODAY)[0]
    wt = [f for f in flagged.flags if f.code == "WEAK_TOPIC"]
    assert [f.topic for f in wt] == ["Graphs"] and wt[0].values["n"] == 2


def test_cs23001_like_dsa():
    topics = ["Arrays", "Arrays", "Trees", "Trees", "Graphs", "Graphs"]
    dsa = sub("DSA", rows_for([70, 70, 55, 55, 40, 40], topics=topics), name="Data Structures")
    other = sub("OS", rows_for([85] * 6))
    s = next(x for x in analytics.analyse(rec(dsa, other), {"DSA": 68.0}, TODAY) if x.code == "DSA")
    assert {"LOW_VS_SELF", "DECLINING", "WEAK_TOPIC", "LOW_VS_CLASS"} <= set(codes(s))
    assert [f.topic for f in s.flags if f.code == "WEAK_TOPIC"] == ["Graphs"]


def test_readiness_is_mean_of_role_subjects():
    s = analytics.analyse(rec(sub("DSA", rows_for([60] * 4)), sub("DBMS", rows_for([80] * 4))), {}, TODAY)
    r = analytics.readiness(s, {"Dev": ["DSA", "DBMS"], "Net": ["CN"]})
    assert r[0].pct == 70.0 and r[0].weakest_subject == "DSA"
    assert r[1].pct is None and r[1].weakest_subject is None


def test_topic_pcts_excludes_all_and_unscored():
    rows = [Row("Trees", "quiz", 5, 10, TODAY), Row("Trees", "quiz", 7, 10, TODAY), Row("All", "internal", 20, 30, TODAY), Row("Graphs", "quiz", None, 10, TODAY)]
    assert analytics.topic_pcts(rows) == {("Trees", "quiz"): (60.0, 2)}
