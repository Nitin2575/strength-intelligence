"""Starter analysis for Strength Intelligence MkII.

This file joins daily Apple Health context with workout-session performance,
creates a simple performance score, and summarizes sleep-related differences.
"""

from __future__ import annotations

import pandas as pd


REQUIRED_HEALTH_COLUMNS = {
    "date",
    "sleep_hours",
    "hrv_ms",
    "resting_hr",
}

REQUIRED_SESSION_COLUMNS = {
    "date",
    "planned_sets",
    "completed_sets",
    "total_volume",
    "session_rpe",
}


def validate_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")


def build_session_dataset(
    daily_health: pd.DataFrame,
    sessions: pd.DataFrame,
) -> pd.DataFrame:
    validate_columns(daily_health, REQUIRED_HEALTH_COLUMNS, "daily_health")
    validate_columns(sessions, REQUIRED_SESSION_COLUMNS, "sessions")

    health = daily_health.copy()
    workout = sessions.copy()

    health["date"] = pd.to_datetime(health["date"])
    workout["date"] = pd.to_datetime(workout["date"])

    merged = workout.merge(health, on="date", how="left")

    merged["completion_rate"] = (
        merged["completed_sets"] / merged["planned_sets"].replace(0, pd.NA)
    )

    rolling_volume = (
        merged.sort_values("date")["total_volume"]
        .rolling(window=5, min_periods=2)
        .mean()
    )

    merged["volume_vs_baseline"] = (
        merged["total_volume"] / rolling_volume.replace(0, pd.NA)
    )

    effort_penalty = ((merged["session_rpe"] - 8).clip(lower=0) * 0.03)

    merged["performance_score"] = (
        0.55 * merged["volume_vs_baseline"].fillna(1)
        + 0.45 * merged["completion_rate"].fillna(0)
        - effort_penalty
    )

    return merged


def summarize_sleep_effect(session_data: pd.DataFrame) -> pd.DataFrame:
    data = session_data.dropna(subset=["sleep_hours", "performance_score"]).copy()
    data["sleep_group"] = data["sleep_hours"].ge(7).map(
        {True: "7+ hours", False: "Under 7 hours"}
    )

    return (
        data.groupby("sleep_group", as_index=False)
        .agg(
            sessions=("performance_score", "size"),
            avg_performance=("performance_score", "mean"),
            avg_completion=("completion_rate", "mean"),
            avg_rpe=("session_rpe", "mean"),
        )
        .sort_values("sleep_group")
    )


if __name__ == "__main__":
    health = pd.read_csv("data/daily_health.csv")
    sessions = pd.read_csv("data/workout_sessions.csv")

    dataset = build_session_dataset(health, sessions)
    summary = summarize_sleep_effect(dataset)

    print(summary.to_string(index=False))
