"""Fueling math: intake averages, target adherence, and pre-workout comparisons.

The interesting computation here is `fueling_performance_link`: it splits
training sessions into higher- and lower-performing groups using the *residual*
from each lift's own trend line (so a session on a strong week isn't
automatically "good"), then compares fueling between those groups.

It also reports how many comparable sessions the comparison rests on, because
the honest answer to "is my fueling hurting my bench" is often "there isn't
enough data yet" -- and the agents need that number to say so.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from .loaders import Dataset
from .strength_metrics import _sessions_for_lift, _trend, _window
from .util import mean_or_none, ols_slope, pct_change, pearson_r, round_or_none

# Minimum sessions per group before a fueling/performance comparison is
# reported as usable evidence rather than "insufficient".
MIN_SESSIONS_PER_GROUP = 3
# Calorie intake within this fraction of target counts as "on target" for a day.
CALORIE_BAND = 0.10
# Window for the fueling/performance comparison. Long enough for statistical
# weight, short enough that a straight-line trend fit stays a fair approximation
# of a training block (over a full year, curvature would swamp the residuals).
LINK_WINDOW_DAYS = 60
# Protein at or above this fraction of target counts as a hit.
PROTEIN_HIT_RATIO = 0.95


def _macro_window(ds: Dataset, as_of: date, days: int) -> pd.DataFrame:
    cutoff = as_of - timedelta(days=days - 1)
    df = ds.nutrition
    return df[(df["date"].dt.date >= cutoff) & (df["date"].dt.date <= as_of)]


def _averages(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"days_logged": int(df["calories"].notna().sum())}
    for col in ("calories", "protein", "carbs", "fat"):
        vals = df[col].dropna()
        out[f"avg_{col}"] = round(float(vals.mean()), 0 if col == "calories" else 1) if len(vals) else None
    return out


def _adherence(df: pd.DataFrame, profile: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cal_target = profile.get("calorie_target")
    cals = df["calories"].dropna()
    if cal_target and len(cals):
        lo, hi = float(cal_target) * (1 - CALORIE_BAND), float(cal_target) * (1 + CALORIE_BAND)
        within = ((cals >= lo) & (cals <= hi)).sum()
        out["calorie_target"] = float(cal_target)
        out["calorie_days_within_10pct"] = int(within)
        out["calorie_adherence_pct"] = round(100 * within / len(cals), 0)
        out["avg_calorie_deviation"] = round(float(cals.mean()) - float(cal_target), 0)

    for macro, ratio in (("protein", PROTEIN_HIT_RATIO), ("carbs", None), ("fat", None)):
        target = profile.get(f"{macro if macro != 'carbs' else 'carb'}_target")
        vals = df[macro].dropna()
        if not target or not len(vals):
            continue
        out[f"{macro}_target"] = float(target)
        out[f"avg_{macro}_vs_target"] = round(float(vals.mean()) - float(target), 1)
        if ratio is not None:
            hits = (vals >= float(target) * ratio).sum()
            out[f"{macro}_hit_days"] = int(hits)
            out[f"{macro}_adherence_pct"] = round(100 * hits / len(vals), 0)
    return out


def _session_group_lifts(profile: dict[str, Any], group: str | None) -> list[str] | None:
    if not group:
        return None
    mapping = {k.lower(): v for k, v in (profile.get("session_types") or {}).items()}
    return mapping.get(group.lower())


def _sessions_with_fueling(ds: Dataset, exercise: str, as_of: date) -> list[dict[str, Any]]:
    """Sessions for a lift, each annotated with its performance residual and fueling.

    The residual is the session's e1RM minus the value predicted by the lift's
    own 90-day trend line. Positive = performed above where the trend expected.
    """
    lo = as_of - timedelta(days=LINK_WINDOW_DAYS - 1)
    sessions = [s for s in _sessions_for_lift(ds.workouts, exercise)
                if lo <= date.fromisoformat(s["date"]) <= as_of]
    if len(sessions) < 4:
        return []

    day0 = date.fromisoformat(sessions[0]["date"])
    xs = [(date.fromisoformat(s["date"]) - day0).days for s in sessions]
    ys = [s["e1rm"] for s in sessions]
    slope, intercept = ols_slope(xs, ys)

    nutri = ds.nutrition.set_index(ds.nutrition["date"].dt.date)
    annotated: list[dict[str, Any]] = []
    for x, s in zip(xs, sessions):
        d = date.fromisoformat(s["date"])
        expected = intercept + slope * x
        row = nutri.loc[d] if d in nutri.index else None
        prev = nutri.loc[d - timedelta(days=1)] if (d - timedelta(days=1)) in nutri.index else None

        def val(r, col):
            if r is None:
                return None
            v = r[col]
            return None if pd.isna(v) else float(v)

        annotated.append({
            **s,
            "expected_e1rm": round(expected, 1),
            "residual": round(s["e1rm"] - expected, 1),
            "residual_pct": round(100 * (s["e1rm"] - expected) / expected, 1) if expected else None,
            "preworkout_carbs": val(row, "preworkout_carbs"),
            "preworkout_protein": val(row, "preworkout_protein"),
            "workout_time": (None if row is None or pd.isna(row["workout_time"])
                             else str(row["workout_time"])),
            "day_calories": val(row, "calories"),
            "day_protein": val(row, "protein"),
            "day_carbs": val(row, "carbs"),
            "prev_day_calories": val(prev, "calories"),
            "prev_day_carbs": val(prev, "carbs"),
        })
    return annotated


def _compare(group_a: list[dict[str, Any]], group_b: list[dict[str, Any]],
             field: str) -> dict[str, Any]:
    a = mean_or_none([s.get(field) for s in group_a])
    b = mean_or_none([s.get(field) for s in group_b])
    return {
        "higher_performing_avg": round_or_none(a, 1),
        "lower_performing_avg": round_or_none(b, 1),
        "difference": round_or_none(None if (a is None or b is None) else a - b, 1),
        "n_higher": sum(1 for s in group_a if s.get(field) is not None),
        "n_lower": sum(1 for s in group_b if s.get(field) is not None),
    }


def fueling_performance_link(ds: Dataset, exercise: str,
                             as_of: date | None = None) -> dict[str, Any]:
    """Compare fueling between higher- and lower-performing sessions for one lift."""
    as_of = as_of or ds.as_of
    if as_of is None:
        return {"exercise": exercise, "sufficient_evidence": False,
                "note": "No data available."}

    # Count coverage independently of the trend fit, so the "insufficient" message
    # reports what is actually logged rather than what survived the fit.
    lo = as_of - timedelta(days=LINK_WINDOW_DAYS - 1)
    in_window = [s for s in _sessions_for_lift(ds.workouts, exercise)
                 if lo <= date.fromisoformat(s["date"]) <= as_of]
    dates_with_carbs = set(
        ds.nutrition.dropna(subset=["preworkout_carbs"])["date"].dt.date)
    logged = [s for s in in_window if date.fromisoformat(s["date"]) in dates_with_carbs]

    out: dict[str, Any] = {
        "exercise": exercise,
        "sessions_in_window": len(in_window),
        "sessions_with_preworkout_data": len(logged),
        "window_days": LINK_WINDOW_DAYS,
    }

    annotated = _sessions_with_fueling(ds, exercise, as_of)
    with_carbs = [s for s in annotated if s["preworkout_carbs"] is not None]
    out["sessions_analysed"] = len(annotated)

    if len(with_carbs) < MIN_SESSIONS_PER_GROUP * 2:
        out["sufficient_evidence"] = False
        needed = MIN_SESSIONS_PER_GROUP * 2
        if len(in_window) < 4:
            out["note"] = (
                f"Only {len(in_window)} {exercise} session(s) logged in the last "
                f"{LINK_WINDOW_DAYS} days. At least 4 are needed to establish a performance "
                f"trend to compare fueling against, and at least {needed} with pre-workout "
                f"nutrition logged to compare higher- and lower-performing sessions.")
        else:
            out["note"] = (
                f"Only {len(logged)} of {len(in_window)} {exercise} sessions in the last "
                f"{LINK_WINDOW_DAYS} days have pre-workout nutrition logged. At least "
                f"{needed} are needed to compare higher- and lower-performing sessions.")
        return out

    ranked = sorted(with_carbs, key=lambda s: s["residual"], reverse=True)
    cut = max(MIN_SESSIONS_PER_GROUP, len(ranked) // 3)
    higher, lower = ranked[:cut], ranked[-cut:]

    out["sufficient_evidence"] = True
    out["window_days"] = LINK_WINDOW_DAYS
    out["grouping"] = (
        f"Sessions in the last {LINK_WINDOW_DAYS} days ranked by performance relative to "
        f"this lift's own trend line; top {len(higher)} vs bottom {len(lower)} of "
        f"{len(ranked)} logged sessions.")

    # Session-level correlation, so a weak signal can be reported as weak rather
    # than left implicit in the group means.
    pairs = [(s["preworkout_carbs"], s["residual"]) for s in with_carbs]
    r = pearson_r([p[0] for p in pairs], [p[1] for p in pairs])
    out["preworkout_carbs_vs_performance_r"] = round_or_none(r, 2)
    out["correlation_strength"] = (
        None if r is None else
        "negligible" if abs(r) < 0.2 else
        "weak" if abs(r) < 0.4 else
        "moderate" if abs(r) < 0.6 else "strong")
    out["correlation_note"] = (
        "Correlation could not be computed." if r is None else
        f"Across {len(pairs)} sessions in the window, pre-workout carbohydrate intake and "
        f"session performance relative to trend correlate r={r:.2f} "
        f"({out['correlation_strength']}). Correlation across sessions is a separate "
        f"question from whether the recent phase differed.")
    out["higher_performing_dates"] = [s["date"] for s in higher]
    out["lower_performing_dates"] = [s["date"] for s in lower]
    out["higher_performing_avg_residual"] = round(
        sum(s["residual"] for s in higher) / len(higher), 1)
    out["lower_performing_avg_residual"] = round(
        sum(s["residual"] for s in lower) / len(lower), 1)
    out["comparisons"] = {
        "preworkout_carbs_g": _compare(higher, lower, "preworkout_carbs"),
        "preworkout_protein_g": _compare(higher, lower, "preworkout_protein"),
        "day_calories": _compare(higher, lower, "day_calories"),
        "day_protein_g": _compare(higher, lower, "day_protein"),
        "prev_day_calories": _compare(higher, lower, "prev_day_calories"),
    }

    # Recent exposures vs everything before them -- the "what changed lately" view.
    recent, earlier = with_carbs[-3:], with_carbs[:-3]
    if earlier:
        out["recent_vs_earlier"] = {
            "recent_dates": [s["date"] for s in recent],
            "recent_avg_preworkout_carbs": round_or_none(
                mean_or_none([s["preworkout_carbs"] for s in recent]), 1),
            "earlier_avg_preworkout_carbs": round_or_none(
                mean_or_none([s["preworkout_carbs"] for s in earlier]), 1),
            "recent_avg_day_calories": round_or_none(
                mean_or_none([s["day_calories"] for s in recent]), 0),
            "earlier_avg_day_calories": round_or_none(
                mean_or_none([s["day_calories"] for s in earlier]), 0),
            "recent_avg_day_protein": round_or_none(
                mean_or_none([s["day_protein"] for s in recent]), 1),
            "earlier_avg_day_protein": round_or_none(
                mean_or_none([s["day_protein"] for s in earlier]), 1),
        }
        rv = out["recent_vs_earlier"]
        rv["preworkout_carb_change_pct"] = round_or_none(
            pct_change(rv["earlier_avg_preworkout_carbs"], rv["recent_avg_preworkout_carbs"]), 1)

    out["session_detail"] = [
        {k: s[k] for k in ("date", "e1rm", "residual", "residual_pct", "preworkout_carbs",
                           "preworkout_protein", "workout_time", "day_calories", "rpe")}
        for s in with_carbs[-12:]
    ]
    return out


def nutrition_summary(ds: Dataset, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or ds.as_of
    if as_of is None or ds.nutrition.empty:
        return {"has_data": False, "note": "No nutrition data available."}

    w7, w30 = _macro_window(ds, as_of, 7), _macro_window(ds, as_of, 30)
    profile = ds.profile

    # Is protein intake itself consistent, or swinging around?
    protein_30 = w30["protein"].dropna()
    protein_cv = (round(100 * float(protein_30.std()) / float(protein_30.mean()), 1)
                  if len(protein_30) > 2 and protein_30.mean() else None)

    links = {lift: fueling_performance_link(ds, lift, as_of) for lift in ds.key_lifts()}

    return {
        "has_data": True,
        "as_of": as_of.isoformat(),
        "goal_type": profile.get("goal_type"),
        "last_7_days": _averages(w7),
        "last_30_days": _averages(w30),
        "adherence_30d": _adherence(w30, profile),
        "adherence_7d": _adherence(w7, profile),
        "protein_variability_pct_30d": protein_cv,
        "targets": {
            "calories": profile.get("calorie_target"),
            "protein": profile.get("protein_target"),
            "carbs": profile.get("carb_target"),
            "fat": profile.get("fat_target"),
        },
        "fueling_performance_links": links,
    }
