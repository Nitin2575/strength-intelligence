"""Confidence as a function of evidence coverage, computed in code.

Confidence is not left to the model's discretion. It is derived from how much
comparable data actually underpins a claim, and passed to the model as a
*ceiling* it may lower but never raise. This is what stops a fluent-sounding
explanation from arriving with unearned certainty.
"""
from __future__ import annotations

from typing import Any

LEVELS = ("low", "moderate", "high")


def _cap(level: str, ceiling: str) -> str:
    return LEVELS[min(LEVELS.index(level), LEVELS.index(ceiling))]


def strength_confidence(lift: dict[str, Any]) -> tuple[str, str]:
    """How much can we trust a claim about this lift's trend?"""
    n30 = lift.get("sessions_last_30d") or 0
    recent = lift.get("recent_exposures") or {}
    noise = lift.get("session_variability_pct")

    if n30 < 3:
        return "low", f"Only {n30} logged exposure(s) in the last 30 days."
    if n30 < 5:
        level, why = "moderate", f"{n30} exposures in the last 30 days is a thin but usable trend."
    else:
        level, why = "high", f"{n30} logged exposures in the last 30 days support the trend estimate."

    if noise is not None and noise > 4.0:
        level = _cap(level, "moderate")
        why += f" Session-to-session variability is high ({noise}%), which widens the uncertainty."
    if not recent.get("sufficient_recent_data", True):
        level = _cap(level, "moderate")
        why += " " + str(recent.get("note", "")).strip()
    return level, why.strip()


def fueling_confidence(link: dict[str, Any]) -> tuple[str, str]:
    """How much can we trust a fueling/performance association for one lift?"""
    if not link.get("sufficient_evidence"):
        return "low", link.get("note", "Not enough pre-workout nutrition logged.")

    n = link.get("sessions_with_preworkout_data") or 0
    rv = link.get("recent_vs_earlier") or {}
    strength = link.get("correlation_strength")

    if n < 8:
        level = "low"
        why = f"Only {n} sessions have pre-workout nutrition logged."
    elif n < 14:
        level = "moderate"
        why = f"{n} sessions with pre-workout nutrition logged — enough to compare, not to confirm."
    else:
        level = "moderate"
        why = (f"{n} sessions with pre-workout nutrition logged. This remains observational "
               f"data, so an association is the strongest available claim.")

    change = rv.get("preworkout_carb_change_pct")
    if change is not None and abs(change) >= 25:
        why += (f" The recent phase differs clearly from the earlier phase "
                f"({change:+.0f}% pre-workout carbohydrate).")
    elif strength in ("negligible", "weak"):
        level = _cap(level, "low")
        why += f" Session-level correlation is {strength}."

    # An observational association never earns "high" in this system.
    return _cap(level, "moderate"), why


def combined_confidence(*levels: str) -> str:
    """Confidence of a multi-signal conclusion is bounded by its weakest link."""
    present = [l for l in levels if l in LEVELS]
    if not present:
        return "low"
    return LEVELS[min(LEVELS.index(l) for l in present)]


def coverage_note(snapshot: dict[str, Any]) -> str:
    cov = snapshot.get("data_coverage", {})
    return (f"{cov.get('workout_rows', 0)} workout rows, "
            f"{cov.get('nutrition_days', 0)} nutrition days, "
            f"{cov.get('context_days', 0)} context days "
            f"through {cov.get('last_date')}.")
