"""Recovery / activity context: sleep, steps, training frequency.

These are treated as *potential confounds*. The important output is not just
the averages but whether each input has been stable -- because a stable input
can be ruled out as the explanation for a change in strength, which is what
lets the orchestrator narrow down to a plausible cause.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .loaders import Dataset
from .util import mean_or_none, round_or_none

# Recent-vs-prior swing (as a fraction of the prior mean) before an input is
# considered to have changed rather than held steady.
STABILITY_THRESHOLD = 0.10


def _values(ds: Dataset, column: str, as_of: date, start_days: int, end_days: int = 0) -> list[float]:
    lo = as_of - timedelta(days=start_days - 1)
    hi = as_of - timedelta(days=end_days)
    df = ds.context.dropna(subset=[column])
    df = df[(df["date"].dt.date >= lo) & (df["date"].dt.date <= hi)]
    return [float(v) for v in df[column]]


def _stability(recent: list[float], prior: list[float], label: str, unit: str) -> dict[str, Any]:
    recent_avg = mean_or_none(recent)
    prior_avg = mean_or_none(prior)
    out: dict[str, Any] = {
        "metric": label,
        "recent_avg": round_or_none(recent_avg, 1),
        "prior_avg": round_or_none(prior_avg, 1),
        "unit": unit,
        "stable": None,
        "note": f"Insufficient {label.lower()} data.",
    }
    if recent_avg is None or prior_avg is None or prior_avg == 0:
        return out
    delta = recent_avg - prior_avg
    out["delta"] = round(delta, 1)
    out["delta_pct"] = round(100 * delta / prior_avg, 1)
    out["stable"] = abs(delta / prior_avg) <= STABILITY_THRESHOLD
    if out["stable"]:
        out["note"] = (f"{label} has been relatively stable "
                       f"({recent_avg:.1f} {unit} recently vs {prior_avg:.1f} {unit} before).")
    else:
        direction = "higher" if delta > 0 else "lower"
        out["note"] = (f"{label} is {abs(delta):.1f} {unit} {direction} recently "
                       f"({recent_avg:.1f} vs {prior_avg:.1f} {unit}).")
    return out


def context_summary(ds: Dataset, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or ds.as_of
    if as_of is None or ds.context.empty:
        return {"has_data": False, "note": "No daily context data available."}

    # "Recent" = last 14 days; "prior" = the 16 days before that, within 30 days.
    sleep_recent = _values(ds, "sleep_hours", as_of, 14)
    sleep_prior = _values(ds, "sleep_hours", as_of, 30, end_days=14)
    steps_recent = _values(ds, "steps", as_of, 14)
    steps_prior = _values(ds, "steps", as_of, 30, end_days=14)

    sleep = _stability(sleep_recent, sleep_prior, "Sleep", "h")
    steps = _stability(steps_recent, steps_prior, "Daily steps", "steps")

    train_recent_days = ds.workouts[
        (ds.workouts["date"].dt.date >= as_of - timedelta(days=13))
        & (ds.workouts["date"].dt.date <= as_of)
    ]["date"].dt.date.nunique()
    train_prior_days = ds.workouts[
        (ds.workouts["date"].dt.date >= as_of - timedelta(days=29))
        & (ds.workouts["date"].dt.date < as_of - timedelta(days=13))
    ]["date"].dt.date.nunique()

    freq_recent = round(train_recent_days / 2, 1)
    freq_prior = round(train_prior_days / (16 / 7), 1)
    freq_stable = abs(freq_recent - freq_prior) <= 0.6

    low_sleep_nights = sum(1 for v in sleep_recent if v < 6.5)

    return {
        "has_data": True,
        "as_of": as_of.isoformat(),
        "sleep": sleep,
        "steps": steps,
        "sleep_nights_under_6_5h_last_14d": low_sleep_nights,
        "training_frequency": {
            "metric": "Training frequency",
            "recent_avg": freq_recent,
            "prior_avg": freq_prior,
            "unit": "sessions/week",
            "stable": freq_stable,
            "note": (f"Training frequency {'held at' if freq_stable else 'moved to'} "
                     f"{freq_recent} sessions/week recently vs {freq_prior} before."),
        },
        "stable_inputs": [
            m["metric"] for m in (sleep, steps) if m.get("stable") is True
        ],
        "changed_inputs": [
            m["metric"] for m in (sleep, steps) if m.get("stable") is False
        ],
        "sleep_history": [
            {"date": d.date().isoformat(), "sleep_hours": None if v != v else float(v)}
            for d, v in zip(ds.context["date"], ds.context["sleep_hours"])
            if d.date() >= as_of - timedelta(days=29)
        ],
    }
