"""Strength math: estimated 1RM, volume, trends, PRs, and trend classification.

Design note: the *classification* here (progressing / plateau / regressing /
single poor session / insufficient data) is deliberately computed in code, not
delegated to the model. It is a statistical judgment about whether a change
exceeds this lift's own noise floor, and it needs to be reproducible. The model
gets the label plus the numbers behind it and explains what it means.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from .loaders import Dataset
from .util import pct_change, round_or_none, ols_slope

# A change smaller than this is treated as noise no matter how quiet the lift is.
MIN_MEANINGFUL_PCT = 1.5
# The "recent" window is a fixed span, not a fixed session count: 3 exposures of
# a twice-weekly lift cover a week, while 3 of a weekly lift cover three. Using
# days keeps the rate comparison meaningful across differently-scheduled lifts.
RECENT_WINDOW_DAYS = 14
MIN_RECENT_EXPOSURES = 3
# Fallback count used only for reporting "the last N exposures" in summaries.
RECENT_EXPOSURES = 3
# Residual SDs below trend before a single session is called an outlier.
OUTLIER_SD = 1.5


def epley_1rm(weight: float, reps: float) -> float:
    """Epley estimated 1RM. Reps above ~12 make this unreliable, so we cap it."""
    reps = min(float(reps), 12.0)
    return float(weight) * (1.0 + reps / 30.0)


def _sessions_for_lift(workouts: pd.DataFrame, exercise: str) -> list[dict[str, Any]]:
    """One record per training day for this lift: top set, best e1RM, volume, RPE."""
    df = workouts[workouts["exercise"] == exercise].dropna(subset=["weight", "reps"])
    if df.empty:
        return []
    df = df.assign(
        e1rm=[epley_1rm(w, r) for w, r in zip(df["weight"], df["reps"])],
        volume=df["sets"].fillna(1) * df["reps"] * df["weight"],
    )
    sessions: list[dict[str, Any]] = []
    for day, grp in df.groupby(df["date"].dt.date, sort=True):
        best = grp.loc[grp["e1rm"].idxmax()]
        sessions.append({
            "date": day.isoformat(),
            "top_weight": float(best["weight"]),
            "top_reps": int(best["reps"]),
            "rpe": None if pd.isna(best["rpe"]) else float(best["rpe"]),
            "e1rm": round(float(best["e1rm"]), 1),
            "volume": round(float(grp["volume"].sum()), 1),
        })
    return sessions


def _window(sessions: list[dict[str, Any]], as_of: date, days: int) -> list[dict[str, Any]]:
    cutoff = as_of - timedelta(days=days - 1)
    return [s for s in sessions if date.fromisoformat(s["date"]) >= cutoff]


def _trend(sessions: list[dict[str, Any]], key: str = "e1rm") -> dict[str, Any]:
    """Least-squares trend across a window, expressed as a % change end-to-end.

    Also returns the residual coefficient of variation, which is this lift's
    measured noise floor -- the thing a change has to beat to be meaningful.
    """
    if len(sessions) < 2:
        return {"n": len(sessions), "change_pct": None, "noise_pct": None,
                "fitted_start": None, "fitted_end": None, "residual_sd": None}
    day0 = date.fromisoformat(sessions[0]["date"])
    xs = [(date.fromisoformat(s["date"]) - day0).days for s in sessions]
    ys = [float(s[key]) for s in sessions]
    slope, intercept = ols_slope(xs, ys)
    fitted_start = intercept + slope * xs[0]
    fitted_end = intercept + slope * xs[-1]
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    mean_y = sum(ys) / len(ys)
    if len(residuals) > 2:
        var = sum(r * r for r in residuals) / (len(residuals) - 2)
        residual_sd = var ** 0.5
    else:
        residual_sd = 0.0
    return {
        "n": len(sessions),
        "change_pct": round_or_none(pct_change(fitted_start, fitted_end), 1),
        "noise_pct": round(100 * residual_sd / mean_y, 1) if mean_y else None,
        "fitted_start": round(fitted_start, 1),
        "fitted_end": round(fitted_end, 1),
        "residual_sd": round(residual_sd, 2),
        "per_week_change": round(slope * 7, 2),
    }


def _classify(trend_30: dict[str, Any]) -> tuple[str, str]:
    """Return (status, reason). Status is the deterministic verdict on this lift."""
    n = trend_30["n"]
    if n < 3:
        return "insufficient_data", f"Only {n} logged exposure(s) in the last 30 days."

    change = trend_30["change_pct"]
    noise = trend_30["noise_pct"] or 0.0
    threshold = max(MIN_MEANINGFUL_PCT, noise)

    if change is None:
        return "insufficient_data", "Trend could not be estimated."
    if change > threshold:
        status = "progressing"
        reason = f"30-day e1RM trend +{change}% exceeds this lift's noise floor ({threshold:.1f}%)."
    elif change < -threshold:
        status = "regressing"
        reason = f"30-day e1RM trend {change}% is below this lift's noise floor (-{threshold:.1f}%)."
    else:
        status = "maintaining"
        reason = (f"30-day e1RM trend {change:+}% is inside this lift's normal "
                  f"variability (±{threshold:.1f}%).")
    return status, reason


def _recent_shape(sessions: list[dict[str, Any]], trend_30: dict[str, Any],
                  as_of: date) -> dict[str, Any]:
    """Characterise the recent window: stall, decline, or one-off bad day.

    A stall is judged by comparing the recent *rate* of change (lb/week) against
    the 30-day rate, not against a fixed percentage. Over a two-week window a
    lift progressing normally but slowly shows a small absolute change, and
    would be misread as stalled if raw percentages were compared instead.
    """
    recent = _window(sessions, as_of, RECENT_WINDOW_DAYS)
    out: dict[str, Any] = {
        "window_days": RECENT_WINDOW_DAYS,
        "exposures_in_window": len(recent),
        "dates": [s["date"] for s in recent],
        "e1rms": [s["e1rm"] for s in recent],
        "stalled": False,
        "single_poor_session": False,
        "persistent_decline": False,
        "within_normal_variability": None,
        "sufficient_recent_data": len(recent) >= MIN_RECENT_EXPOSURES,
    }
    if len(recent) < MIN_RECENT_EXPOSURES:
        out["note"] = (
            f"Only {len(recent)} exposure(s) in the last {RECENT_WINDOW_DAYS} days; "
            f"{MIN_RECENT_EXPOSURES} are needed to judge a recent stall or decline.")
        return out

    recent_trend = _trend(recent)
    out["recent_change_pct"] = recent_trend["change_pct"]
    out["recent_span_days"] = (date.fromisoformat(recent[-1]["date"])
                               - date.fromisoformat(recent[0]["date"])).days

    noise = trend_30.get("noise_pct") or MIN_MEANINGFUL_PCT
    rc = recent_trend["change_pct"]
    if rc is not None:
        out["within_normal_variability"] = abs(rc) <= noise

    # Rates in lb/week, so windows of different lengths stay comparable.
    rate_30 = trend_30.get("per_week_change")
    rate_recent = recent_trend.get("per_week_change")
    out["rate_30d_lb_per_week"] = rate_30
    out["rate_recent_lb_per_week"] = rate_recent

    if rate_30 is not None and rate_recent is not None and rate_30 > 0.05:
        retained = rate_recent / rate_30
        out["progression_rate_retained_pct"] = round(100 * retained, 0)
        if retained <= 0.25:
            out["stalled"] = True
    elif rate_recent is not None and rate_30 is not None and abs(rate_30) <= 0.05:
        out["stalled"] = abs(rate_recent) <= 0.05

    if rc is not None and rc < -max(MIN_MEANINGFUL_PCT, noise):
        out["persistent_decline"] = True
        out["stalled"] = False

    # One session well below the 30-day trend line, with the ones before it on trend.
    sd = trend_30.get("residual_sd") or 0.0
    fitted_end = trend_30.get("fitted_end")
    if sd > 0 and fitted_end is not None and len(sessions) >= 4:
        last, prior = sessions[-1], sessions[-2]
        last_gap = last["e1rm"] - fitted_end
        prior_gap = prior["e1rm"] - fitted_end
        if last_gap < -OUTLIER_SD * sd <= prior_gap:
            out["single_poor_session"] = True
            out["stalled"] = False
            out["outlier_deficit"] = round(last_gap, 1)
    return out


def _pr(sessions: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    if not sessions:
        return {}
    best = max(sessions, key=lambda s: s["e1rm"])
    days_since = (as_of - date.fromisoformat(best["date"])).days
    return {
        "best_e1rm": best["e1rm"],
        "best_e1rm_date": best["date"],
        "best_set": f"{best['top_weight']:g} lb x {best['top_reps']}",
        "days_since_pr": days_since,
        "pr_in_last_14_days": days_since <= 14,
    }


def lift_summary(ds: Dataset, exercise: str, as_of: date,
                 body_weight: float | None = None) -> dict[str, Any]:
    sessions = _sessions_for_lift(ds.workouts, exercise)
    if not sessions:
        return {"exercise": exercise, "status": "no_data", "sessions_logged": 0}

    w30 = _window(sessions, as_of, 30)
    w7 = _window(sessions, as_of, 7)
    trend_30 = _trend(w30)
    trend_7 = _trend(w7)
    status, reason = _classify(trend_30)
    recent = _recent_shape(sessions, trend_30, as_of)

    latest = sessions[-1]
    previous = sessions[-2] if len(sessions) >= 2 else None

    vol_30 = [s["volume"] for s in w30]
    baseline = w30[: max(1, len(w30) // 3)] if w30 else []
    baseline_e1rm = round(sum(s["e1rm"] for s in baseline) / len(baseline), 1) if baseline else None
    recent_e1rm = round(sum(s["e1rm"] for s in sessions[-RECENT_EXPOSURES:]) /
                        len(sessions[-RECENT_EXPOSURES:]), 1)

    summary: dict[str, Any] = {
        "exercise": exercise,
        "status": status,
        "status_reason": reason,
        "sessions_logged": len(sessions),
        "sessions_last_30d": len(w30),
        "sessions_last_7d": len(w7),
        "current_working_weight": f"{latest['top_weight']:g} lb x {latest['top_reps']}",
        "current_e1rm": latest["e1rm"],
        "current_session_date": latest["date"],
        "current_session_rpe": latest["rpe"],
        "previous_working_weight": (f"{previous['top_weight']:g} lb x {previous['top_reps']}"
                                    if previous else None),
        "previous_e1rm": previous["e1rm"] if previous else None,
        "e1rm_change_30d_pct": trend_30["change_pct"],
        "e1rm_change_7d_pct": trend_7["change_pct"],
        "e1rm_per_week_change_lb": trend_30.get("per_week_change"),
        "session_variability_pct": trend_30["noise_pct"],
        "baseline_e1rm_30d": baseline_e1rm,
        "recent_avg_e1rm": recent_e1rm,
        "recent_vs_baseline_pct": round_or_none(pct_change(baseline_e1rm, recent_e1rm), 1),
        "avg_volume_per_session_30d": round(sum(vol_30) / len(vol_30), 0) if vol_30 else None,
        "total_volume_30d": round(sum(vol_30), 0) if vol_30 else None,
        "recent_exposures": recent,
        "pr": _pr(sessions, as_of),
        "session_history": sessions[-12:],
    }

    if body_weight:
        summary["relative_strength"] = round(latest["e1rm"] / body_weight, 2)
        summary["relative_strength_note"] = (
            f"e1RM {latest['e1rm']:g} lb / body weight {body_weight:g} lb")

    # The headline nuance for the demo: overall progression with a recent stall.
    if status == "progressing" and recent.get("stalled"):
        summary["qualifier"] = "progressing_but_recently_stalled"
    elif status == "progressing" and recent.get("persistent_decline"):
        summary["qualifier"] = "progressing_but_recently_declining"
    elif recent.get("single_poor_session"):
        summary["qualifier"] = "one_poor_session_against_stable_trend"
    elif status == "maintaining" and (trend_30["noise_pct"] or 0) < MIN_MEANINGFUL_PCT:
        summary["qualifier"] = "flat_and_consistent"
    else:
        summary["qualifier"] = None

    return summary


def strength_summary(ds: Dataset, as_of: date | None = None,
                     body_weight: float | None = None) -> dict[str, Any]:
    as_of = as_of or ds.as_of
    if as_of is None or ds.workouts.empty:
        return {"as_of": None, "lifts": [], "note": "No workout data available."}

    lifts = [lift_summary(ds, lift, as_of, body_weight) for lift in ds.key_lifts()]
    lifts = [l for l in lifts if l.get("status") != "no_data"]

    dates_30 = ds.workouts[ds.workouts["date"].dt.date >= as_of - timedelta(days=29)]
    session_days_30 = dates_30["date"].dt.date.nunique()

    ranked = sorted(
        [l for l in lifts if l.get("e1rm_change_30d_pct") is not None],
        key=lambda l: l["e1rm_change_30d_pct"], reverse=True,
    )

    return {
        "as_of": as_of.isoformat(),
        "training_days_last_30d": int(session_days_30),
        "sessions_per_week_last_30d": round(session_days_30 / (30 / 7), 1),
        "lifts": lifts,
        "fastest_progressing": ranked[0]["exercise"] if ranked else None,
        "slowest_progressing": ranked[-1]["exercise"] if ranked else None,
        "lifts_progressing": [l["exercise"] for l in lifts if l["status"] == "progressing"],
        "lifts_maintaining": [l["exercise"] for l in lifts if l["status"] == "maintaining"],
        "lifts_regressing": [l["exercise"] for l in lifts if l["status"] == "regressing"],
    }
