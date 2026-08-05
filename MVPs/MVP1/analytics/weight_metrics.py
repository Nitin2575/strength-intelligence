"""Body-weight trajectory: smoothed current weight, observed rate, goal adherence.

Daily scale readings are noisy (water, sodium, glycogen), so every "current
weight" figure here is a 7-day average, and the rate of change is a
least-squares slope rather than a first-vs-last difference.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .loaders import Dataset
from .util import ols_slope, round_or_none

# How far the observed rate may sit from the target rate before we call it out.
RATE_TOLERANCE_LB_PER_WEEK = 0.35


def _series(ds: Dataset, as_of: date, days: int) -> list[tuple[date, float]]:
    cutoff = as_of - timedelta(days=days - 1)
    df = ds.context.dropna(subset=["body_weight"])
    df = df[(df["date"].dt.date >= cutoff) & (df["date"].dt.date <= as_of)]
    return [(d.date(), float(w)) for d, w in zip(df["date"], df["body_weight"])]


def _rate_lb_per_week(points: list[tuple[date, float]]) -> float | None:
    if len(points) < 4:
        return None
    day0 = points[0][0]
    xs = [(d - day0).days for d, _ in points]
    ys = [w for _, w in points]
    slope, _ = ols_slope(xs, ys)
    return slope * 7


def weight_summary(ds: Dataset, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or ds.as_of
    profile = ds.profile
    if as_of is None:
        return {"has_data": False, "note": "No body-weight data available."}

    all_points = _series(ds, as_of, 365)
    if not all_points:
        return {"has_data": False, "note": "No body-weight data available."}

    last7 = _series(ds, as_of, 7)
    prev7 = [p for p in _series(ds, as_of, 14) if p[0] < as_of - timedelta(days=6)]
    last30 = _series(ds, as_of, 30)

    avg7 = round(sum(w for _, w in last7) / len(last7), 1) if last7 else None
    avg_prev7 = round(sum(w for _, w in prev7) / len(prev7), 1) if prev7 else None
    rate_30 = _rate_lb_per_week(last30)
    rate_all = _rate_lb_per_week(all_points)

    change_30 = None
    if len(last30) >= 8:
        head = last30[:4]
        tail = last30[-4:]
        change_30 = round(sum(w for _, w in tail) / len(tail) - sum(w for _, w in head) / len(head), 1)

    target_rate = profile.get("target_rate_of_change")
    target_weight = profile.get("target_weight")
    goal_type = profile.get("goal_type", "maintain")

    rate_verdict, rate_note = "unknown", "Not enough body-weight data to judge the rate."
    if rate_30 is not None and target_rate is not None:
        delta = rate_30 - float(target_rate)
        if abs(delta) <= RATE_TOLERANCE_LB_PER_WEEK:
            rate_verdict = "on_target"
            rate_note = (f"Observed {rate_30:+.2f} lb/week vs target {float(target_rate):+.2f} "
                         f"lb/week — within tolerance.")
        elif goal_type == "cut" and rate_30 < float(target_rate):
            rate_verdict = "faster_than_intended"
            rate_note = (f"Losing {abs(rate_30):.2f} lb/week vs an intended "
                         f"{abs(float(target_rate)):.2f} lb/week — faster than planned.")
        elif goal_type == "cut":
            rate_verdict = "slower_than_intended"
            rate_note = (f"Losing {abs(rate_30):.2f} lb/week vs an intended "
                         f"{abs(float(target_rate)):.2f} lb/week — slower than planned.")
        elif goal_type == "gain" and rate_30 > float(target_rate):
            rate_verdict = "faster_than_intended"
            rate_note = (f"Gaining {rate_30:.2f} lb/week vs an intended "
                         f"{float(target_rate):.2f} lb/week — faster than planned.")
        elif goal_type == "gain":
            rate_verdict = "slower_than_intended"
            rate_note = (f"Gaining {rate_30:.2f} lb/week vs an intended "
                         f"{float(target_rate):.2f} lb/week — slower than planned.")
        else:
            rate_verdict = "drifting"
            rate_note = f"Goal is maintenance but weight is trending {rate_30:+.2f} lb/week."

    weeks_to_target = None
    if avg7 is not None and target_weight and rate_30 and abs(rate_30) > 0.05:
        remaining = float(target_weight) - avg7
        if (remaining < 0) == (rate_30 < 0):
            weeks_to_target = round(abs(remaining / rate_30), 1)

    return {
        "has_data": True,
        "as_of": as_of.isoformat(),
        "goal_type": goal_type,
        "current_weight_7d_avg": avg7,
        "previous_week_avg": avg_prev7,
        "week_over_week_change": round_or_none(
            None if (avg7 is None or avg_prev7 is None) else avg7 - avg_prev7, 1),
        "change_last_30d": change_30,
        "observed_rate_lb_per_week_30d": round_or_none(rate_30, 2),
        "observed_rate_lb_per_week_all": round_or_none(rate_all, 2),
        "target_rate_lb_per_week": target_rate,
        "starting_weight": profile.get("starting_weight"),
        "target_weight": target_weight,
        "lb_to_target": round_or_none(
            None if (avg7 is None or not target_weight) else avg7 - float(target_weight), 1),
        "estimated_weeks_to_target": weeks_to_target,
        "rate_verdict": rate_verdict,
        "rate_note": rate_note,
        "days_logged_last_30d": len(last30),
        "history": [{"date": d.isoformat(), "body_weight": w} for d, w in last30],
    }
