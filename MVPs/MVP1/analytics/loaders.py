"""Reads the CSV/JSON data layer into typed DataFrames.

Tolerant of missing files and missing columns so a partially-filled dataset
degrades into "insufficient evidence" downstream rather than crashing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

WORKOUT_COLS = ["date", "exercise", "sets", "reps", "weight", "rpe"]
NUTRITION_COLS = [
    "date", "calories", "protein", "carbs", "fat",
    "preworkout_carbs", "preworkout_protein", "workout_time",
]
CONTEXT_COLS = ["date", "body_weight", "sleep_hours", "steps"]

DEFAULT_PROFILE: dict[str, Any] = {
    "goal_type": "maintain",
    "starting_weight": None,
    "target_weight": None,
    "target_rate_of_change": 0.0,
    "calorie_target": None,
    "protein_target": None,
    "carb_target": None,
    "fat_target": None,
    "key_lifts": [],
    "session_types": {},
}


@dataclass
class Dataset:
    """The full loaded dataset plus the reference date all windows are measured from."""

    workouts: pd.DataFrame
    nutrition: pd.DataFrame
    context: pd.DataFrame
    profile: dict[str, Any] = field(default_factory=dict)

    @property
    def as_of(self) -> date | None:
        """Latest date present anywhere in the data -- treated as 'now'.

        Anchoring to the data rather than the wall clock keeps the analysis
        stable and honest when a dataset is a few days stale.
        """
        candidates = [
            df["date"].max()
            for df in (self.workouts, self.nutrition, self.context)
            if not df.empty
        ]
        if not candidates:
            return None
        return max(candidates).date()

    def key_lifts(self) -> list[str]:
        """Configured key lifts, falling back to the most-logged exercises."""
        configured = [str(x) for x in self.profile.get("key_lifts") or []]
        if configured:
            return configured
        if self.workouts.empty:
            return []
        return self.workouts["exercise"].value_counts().head(4).index.tolist()


def _read_csv(path: Path, expected: list[str], numeric: list[str]) -> pd.DataFrame:
    # A missing file still goes through dtype coercion below. Returning a bare
    # empty frame would leave `date` as object dtype, and every downstream `.dt`
    # access would raise instead of yielding an empty result.
    df = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=expected)
    for col in expected:
        if col not in df.columns:
            df[col] = pd.NA
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df[expected]


def load_profile(data_dir: Path | None = None) -> dict[str, Any]:
    path = (data_dir or DATA_DIR) / "profile.json"
    profile = dict(DEFAULT_PROFILE)
    if path.exists():
        profile.update(json.loads(path.read_text()))
    return profile


def load_dataset(data_dir: Path | None = None) -> Dataset:
    d = data_dir or DATA_DIR
    workouts = _read_csv(d / "workouts.csv", WORKOUT_COLS, ["sets", "reps", "weight", "rpe"])
    workouts["exercise"] = workouts["exercise"].astype(str).str.strip()
    nutrition = _read_csv(
        d / "nutrition.csv", NUTRITION_COLS,
        ["calories", "protein", "carbs", "fat", "preworkout_carbs", "preworkout_protein"],
    )
    context = _read_csv(d / "daily_context.csv", CONTEXT_COLS, ["body_weight", "sleep_hours", "steps"])
    return Dataset(workouts=workouts, nutrition=nutrition, context=context, profile=load_profile(d))
