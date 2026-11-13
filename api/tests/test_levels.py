"""Pure level rules (LLD_next C4.2/C4.3). Inputs are scores only: a guard test enforces that (RB 5.2)."""
import inspect
from datetime import date
from itertools import product

import pytest

from app import analytics
from app.connector import Row


@pytest.mark.parametrize("b,s,m", list(product(range(3), range(3), range(2))))
def test_level_truth_table_over_all_18_combinations(b, s, m):
    total = b + s + m
    if total <= 1:
        want = "foundation"
    elif (b, s, m) == (2, 2, 1):
        want = "advanced"
    elif b >= 1 and s >= 1 and total >= 3:
        want = "intermediate"
    else:
        want = "beginner"
    assert analytics.level(b, s, m) == want


@pytest.mark.parametrize("pct,gap,want", [
    (39.9, False, "foundation"), (40.0, False, "beginner"), (59.9, False, "beginner"), (60.0, False, "intermediate"),
    (79.9, False, "intermediate"), (80.0, False, "advanced"), (90.0, True, "foundation")])
def test_level_from_records_band_edges(pct, gap, want):
    assert analytics.level_from_records(pct, gap) == want


def test_fairness_guard_signatures_have_no_non_score_inputs():
    assert list(inspect.signature(analytics.level).parameters) == ["basic", "standard", "multi"]
    assert list(inspect.signature(analytics.level_from_records).parameters) == ["pct", "prereq_gap"]


def rows(topic, pcts):
    return [Row(topic, "quiz", p / 10, 10.0, date(2026, 8, 1 + i)) for i, p in enumerate(pcts)]


def test_check_beats_records_and_one_assessment_is_unknown():
    chk = {"Trees": analytics.Check("Trees", "advanced", date(2026, 11, 14), 5)}
    out = {t.topic: t for t in analytics.topic_levels(rows("Trees", [30, 30]) + rows("Graphs", [90]), [], chk, {"Trees"})}
    assert out["Trees"].level == "advanced" and out["Trees"].source == "check" and out["Trees"].has_check is True
    assert out["Graphs"].level is None and out["Graphs"].source is None      # n = 1 and no check: unknown, offer a check
    recs = {t.topic: t for t in analytics.topic_levels(rows("Trees", [30, 30]), [], {}, set())}
    assert recs["Trees"].level == "foundation" and recs["Trees"].source == "records" and recs["Trees"].has_check is False
