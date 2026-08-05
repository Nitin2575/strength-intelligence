"""Unit tests for the deterministic analytics layer.

The point of these is narrow: the analytics layer is the system's source of
truth, so its classifications must be reproducible and its edge cases must
degrade into "insufficient data" rather than into a confident wrong answer.

    python -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.loaders import Dataset  # noqa: E402
from analytics.strength_metrics import epley_1rm, lift_summary  # noqa: E402
from analytics.util import ols_slope, pct_change, pearson_r  # noqa: E402
from analytics.weight_metrics import weight_summary  # noqa: E402

AS_OF = date(2026, 8, 5)
PROFILE = {"goal_type": "cut", "target_weight": 145.0, "target_rate_of_change": -0.75,
           "key_lifts": ["Bench Press"], "calorie_target": 2200, "protein_target": 170}


def _frame(rows, columns) -> pd.DataFrame:
    """Build a frame with the same dtype coercion the CSV loader applies."""
    df = pd.DataFrame(rows or [], columns=columns)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def _dataset(workout_rows, context_rows=None) -> Dataset:
    w = _frame(workout_rows, ["date", "exercise", "sets", "reps", "weight", "rpe"])
    c = _frame(context_rows, ["date", "body_weight", "sleep_hours", "steps"])
    n = _frame([], ["date", "calories", "protein", "carbs", "fat",
                    "preworkout_carbs", "preworkout_protein", "workout_time"])
    return Dataset(workouts=w, nutrition=n, context=c, profile=PROFILE)


def _bench(day_offset: int, weight: float, reps: int = 5) -> dict:
    return {"date": (AS_OF - timedelta(days=day_offset)).isoformat(), "exercise": "Bench Press",
            "sets": 3, "reps": reps, "weight": weight, "rpe": 8.0}


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
def test_epley_1rm_matches_formula():
    assert epley_1rm(200, 5) == pytest.approx(200 * (1 + 5 / 30))
    assert epley_1rm(100, 1) == pytest.approx(100 * (1 + 1 / 30))


def test_epley_caps_high_reps():
    """Epley loses validity at high reps, so reps are capped rather than extrapolated."""
    assert epley_1rm(100, 20) == epley_1rm(100, 12)


def test_pct_change_guards_zero_and_none():
    assert pct_change(0, 10) is None
    assert pct_change(None, 10) is None
    assert pct_change(10, None) is None
    assert pct_change(100, 110) == pytest.approx(10.0)


def test_ols_slope_flat_when_no_x_spread():
    slope, intercept = ols_slope([5, 5, 5], [1, 2, 3])
    assert slope == 0.0
    assert intercept == pytest.approx(2.0)


def test_pearson_r_undefined_cases():
    assert pearson_r([1, 2], [1, 2]) is None          # too few points
    assert pearson_r([1, 1, 1], [1, 2, 3]) is None     # no spread
    assert pearson_r([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Trend classification
# --------------------------------------------------------------------------- #
def test_progression_detected_above_noise():
    rows = [_bench(d, w) for d, w in
            [(28, 170), (24, 172.5), (20, 175), (16, 177.5), (12, 180), (8, 182.5), (4, 185), (0, 187.5)]]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    assert s["status"] == "progressing"
    assert s["e1rm_change_30d_pct"] > 0


def test_flat_lift_classified_maintaining_not_regressing():
    """A lift bouncing inside its noise floor is maintaining, not declining."""
    rows = [_bench(d, w) for d, w in
            [(28, 180), (24, 182.5), (20, 180), (16, 177.5), (12, 180), (8, 182.5), (4, 180), (0, 177.5)]]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    assert s["status"] == "maintaining"


def test_regression_detected_below_noise():
    rows = [_bench(d, w) for d, w in
            [(28, 200), (24, 197.5), (20, 195), (16, 190), (12, 187.5), (8, 185), (4, 180), (0, 177.5)]]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    assert s["status"] == "regressing"
    assert s["e1rm_change_30d_pct"] < 0


def test_insufficient_data_below_three_exposures():
    rows = [_bench(20, 180), _bench(10, 185)]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    assert s["status"] == "insufficient_data"
    assert "2" in s["status_reason"]


def test_stall_against_progressing_trend_is_flagged():
    """The headline case: 30-day trend still positive, recent exposures flat."""
    rows = [_bench(d, w) for d, w in
            [(28, 170), (25, 172.5), (21, 175), (18, 177.5),
             (14, 180), (11, 180), (7, 180), (4, 180), (0, 180)]]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    assert s["status"] == "progressing"
    assert s["recent_exposures"]["stalled"] is True
    assert s["qualifier"] == "progressing_but_recently_stalled"


def test_recent_window_needs_three_exposures():
    """A once-weekly lift cannot be called stalled on two data points."""
    rows = [_bench(d, w) for d, w in [(28, 170), (21, 175), (14, 180), (7, 185), (0, 190)]]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    recent = s["recent_exposures"]
    assert recent["exposures_in_window"] == 2
    assert recent["sufficient_recent_data"] is False
    assert recent["stalled"] is False
    assert "needed to judge" in recent["note"]


def test_slow_steady_progress_not_misread_as_stalled():
    """Regression guard: comparing raw percentages over a short window
    would flag a normally-progressing lift as stalled."""
    rows = [_bench(d, w) for d, w in
            [(28, 180), (25, 180), (21, 182.5), (18, 182.5),
             (14, 185), (11, 185), (7, 187.5), (4, 187.5), (0, 190)]]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    assert s["status"] == "progressing"
    assert s["recent_exposures"]["stalled"] is False


def test_pr_detection():
    rows = [_bench(d, w) for d, w in [(28, 170), (21, 175), (14, 195), (7, 180), (0, 185)]]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF)
    assert s["pr"]["best_e1rm"] == pytest.approx(epley_1rm(195, 5), abs=0.1)
    assert s["pr"]["days_since_pr"] == 14
    assert s["pr"]["pr_in_last_14_days"] is True


def test_relative_strength_uses_body_weight():
    rows = [_bench(d, 180) for d in (28, 21, 14, 7, 0)]
    s = lift_summary(_dataset(rows), "Bench Press", AS_OF, body_weight=150.0)
    assert s["relative_strength"] == pytest.approx(s["current_e1rm"] / 150.0, abs=0.01)


def test_no_data_lift():
    s = lift_summary(_dataset([]), "Bench Press", AS_OF)
    assert s["status"] == "no_data"


# --------------------------------------------------------------------------- #
# Body weight
# --------------------------------------------------------------------------- #
def _weight_series(start: float, per_day: float, days: int = 30):
    return [{"date": (AS_OF - timedelta(days=days - 1 - i)).isoformat(),
             "body_weight": round(start + per_day * i, 1),
             "sleep_hours": 7.2, "steps": 8000} for i in range(days)]


def test_rate_on_target_within_tolerance():
    # -0.75 lb/week is the target; -0.107 lb/day is ~-0.75 lb/week.
    ds = _dataset([], _weight_series(155.0, -0.107))
    w = weight_summary(ds, AS_OF)
    assert w["rate_verdict"] == "on_target"


def test_rate_faster_than_intended_on_a_cut():
    ds = _dataset([], _weight_series(155.0, -0.30))   # ~-2.1 lb/week
    w = weight_summary(ds, AS_OF)
    assert w["rate_verdict"] == "faster_than_intended"
    assert w["observed_rate_lb_per_week_30d"] < -0.75


def test_rate_slower_than_intended_on_a_cut():
    ds = _dataset([], _weight_series(155.0, -0.01))   # ~-0.07 lb/week
    w = weight_summary(ds, AS_OF)
    assert w["rate_verdict"] == "slower_than_intended"


def test_weight_uses_seven_day_average_not_last_reading():
    """A single noisy reading must not move the reported current weight."""
    series = _weight_series(150.0, 0.0)
    series[-1]["body_weight"] = 158.0        # one bad scale day
    w = weight_summary(_dataset([], series), AS_OF)
    assert w["current_weight_7d_avg"] < 152.0


def test_insufficient_weight_data():
    w = weight_summary(_dataset([], []), AS_OF)
    assert w["has_data"] is False


def test_rate_unknown_with_too_few_readings():
    series = _weight_series(150.0, -0.1, days=3)
    w = weight_summary(_dataset([], series), AS_OF)
    assert w["observed_rate_lb_per_week_30d"] is None
    assert w["rate_verdict"] == "unknown"
