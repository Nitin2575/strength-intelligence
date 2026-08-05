"""Assembles the single structured snapshot every agent reasons over.

This is the boundary between the deterministic and the probabilistic halves of
the system. Everything above this line is arithmetic; everything below it is
interpretation. Agents are given slices of this object and nothing else.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .context_metrics import context_summary
from .loaders import Dataset, load_dataset
from .nutrition_metrics import nutrition_summary
from .strength_metrics import strength_summary
from .weight_metrics import weight_summary


def build_snapshot(ds: Dataset | None = None, as_of: date | None = None) -> dict[str, Any]:
    ds = ds or load_dataset()
    as_of = as_of or ds.as_of

    weight = weight_summary(ds, as_of)
    body_weight = weight.get("current_weight_7d_avg") if weight.get("has_data") else None

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "profile": ds.profile,
        "strength": strength_summary(ds, as_of, body_weight),
        "nutrition": nutrition_summary(ds, as_of),
        "weight": weight,
        "context": context_summary(ds, as_of),
        "data_coverage": {
            "workout_rows": int(len(ds.workouts)),
            "nutrition_days": int(len(ds.nutrition)),
            "context_days": int(len(ds.context)),
            "first_date": (ds.workouts["date"].min().date().isoformat()
                           if not ds.workouts.empty else None),
            "last_date": as_of.isoformat() if as_of else None,
        },
    }


def slim_for_prompt(snapshot: dict[str, Any], *, include_history: bool = False) -> dict[str, Any]:
    """Drop the row-level history a model doesn't need, keeping token cost sane.

    Charts need the per-day series; agents do not -- they reason over the
    already-computed aggregates. Dropping the series also removes the temptation
    for the model to do its own arithmetic on raw rows.
    """
    if include_history:
        return snapshot

    import copy
    s = copy.deepcopy(snapshot)
    for lift in s.get("strength", {}).get("lifts", []):
        lift.pop("session_history", None)
    s.get("weight", {}).pop("history", None)
    s.get("context", {}).pop("sleep_history", None)
    for link in s.get("nutrition", {}).get("fueling_performance_links", {}).values():
        if isinstance(link, dict):
            link.pop("session_detail", None)
    return s
