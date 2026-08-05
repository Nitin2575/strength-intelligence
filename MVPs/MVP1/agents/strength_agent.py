"""Strength Agent: interprets the computed strength metrics.

Two interchangeable paths produce the same output shape:
  - `_llm_read`  -- Claude interprets the metrics (used when an API key is set)
  - `_rule_read` -- a deterministic reviewer over the same metrics

The deterministic path exists so the system demonstrates end-to-end without a
key, and so the eval suite has a stable baseline to compare the model against.
"""
from __future__ import annotations

from typing import Any

from prompts import STRENGTH_SYSTEM

from .evidence import strength_confidence
from .llm import LLMUnavailable, complete_json

AGENT_NAME = "strength_agent"


def _relevant_lifts(strength: dict[str, Any], focus: list[str] | None) -> list[dict[str, Any]]:
    lifts = strength.get("lifts", [])
    if not focus:
        return lifts
    wanted = {f.lower() for f in focus}
    matched = [l for l in lifts if l["exercise"].lower() in wanted]
    return matched or lifts


def analyze(snapshot: dict[str, Any], focus: list[str] | None = None) -> dict[str, Any]:
    strength = snapshot.get("strength", {})
    lifts = _relevant_lifts(strength, focus)

    if not lifts:
        return {
            "agent": AGENT_NAME, "path": "deterministic",
            "headline": "No workout data is available to analyse.",
            "per_lift": [], "observed": [], "inferred": [],
            "uncertainties": ["No logged training sessions."],
            "confidence": "low", "confidence_reason": "No workout data.",
        }

    # Confidence ceilings are computed in code, per lift, and handed to the model.
    ceilings = {l["exercise"]: strength_confidence(l) for l in lifts}
    payload = {
        "as_of": strength.get("as_of"),
        "goal": snapshot.get("profile", {}).get("goal_type"),
        "training_days_last_30d": strength.get("training_days_last_30d"),
        "sessions_per_week_last_30d": strength.get("sessions_per_week_last_30d"),
        "focus_lifts": focus,
        "lifts": lifts,
        "summary_flags": {
            k: strength.get(k) for k in
            ("lifts_progressing", "lifts_maintaining", "lifts_regressing",
             "fastest_progressing", "slowest_progressing")
        },
        "confidence_ceiling_per_lift": {k: v[0] for k, v in ceilings.items()},
        "confidence_reasoning_per_lift": {k: v[1] for k, v in ceilings.items()},
    }

    try:
        out = complete_json(STRENGTH_SYSTEM, payload)
        out["path"] = "llm"
    except LLMUnavailable as exc:
        out = _rule_read(strength, lifts, ceilings)
        out["path"] = "deterministic"
        out["_fallback_reason"] = str(exc)

    out["agent"] = AGENT_NAME
    out["lifts_considered"] = [l["exercise"] for l in lifts]
    return out


# --------------------------------------------------------------------------- #
# Deterministic reviewer
# --------------------------------------------------------------------------- #
def _lift_sentence(l: dict[str, Any]) -> str:
    name = l["exercise"]
    change = l.get("e1rm_change_30d_pct")
    noise = l.get("session_variability_pct")
    recent = l.get("recent_exposures") or {}
    status = l.get("status")

    if status == "insufficient_data":
        return (f"{name}: only {l.get('sessions_last_30d', 0)} exposure(s) logged in the last "
                f"30 days, which is not enough to establish a trend.")

    parts = []
    if change is not None:
        direction = "increased" if change > 0 else "decreased" if change < 0 else "held flat"
        parts.append(f"estimated 1RM {direction} {abs(change)}% over the last 30 days "
                     f"(now {l.get('current_e1rm')} lb from {l.get('current_working_weight')})")
    if noise is not None:
        parts.append(f"session-to-session variability is {noise}%")

    sentence = f"{name}: " + "; ".join(parts) + "."

    if recent.get("single_poor_session"):
        sentence += (f" The most recent session came in {abs(recent.get('outlier_deficit', 0))} lb "
                     f"below the trend line while the sessions before it were on trend, which is "
                     f"consistent with one poor session rather than a change in trend.")
    elif recent.get("persistent_decline"):
        sentence += (f" The last {recent.get('exposures_in_window')} exposures trend "
                     f"{recent.get('recent_change_pct')}%, a decline beyond normal variability.")
    elif recent.get("stalled") and status == "progressing":
        retained = recent.get("progression_rate_retained_pct")
        sentence += (f" However, the last {recent.get('exposures_in_window')} exposures have "
                     f"added little further progress")
        if retained is not None:
            sentence += (f" — the recent rate is {recent.get('rate_recent_lb_per_week')} lb/week "
                         f"against a 30-day rate of {recent.get('rate_30d_lb_per_week')} lb/week")
        sentence += "."
    elif not recent.get("sufficient_recent_data", True):
        sentence += " " + str(recent.get("note", ""))
    return sentence


def _rule_read(strength: dict[str, Any], lifts: list[dict[str, Any]],
               ceilings: dict[str, tuple[str, str]]) -> dict[str, Any]:
    progressing = [l for l in lifts if l["status"] == "progressing"]
    regressing = [l for l in lifts if l["status"] == "regressing"]
    stalled = [l for l in lifts
               if (l.get("recent_exposures") or {}).get("stalled") and l["status"] == "progressing"]

    thin = [l for l in lifts if l["status"] == "insufficient_data"]

    if thin and len(thin) == len(lifts):
        headline = (f"There is not enough logged training data to characterise strength "
                    f"progression yet ({', '.join(l['exercise'] for l in thin)}).")
    elif regressing:
        headline = (f"{len(regressing)} of {len(lifts)} tracked lifts are regressing over 30 days "
                    f"({', '.join(l['exercise'] for l in regressing)}).")
    elif progressing and stalled:
        headline = (f"Strength is progressing overall over 30 days, but "
                    f"{', '.join(l['exercise'] for l in stalled)} "
                    f"{'has' if len(stalled) == 1 else 'have'} stalled across recent exposures.")
    elif progressing:
        headline = (f"{len(progressing)} of {len(lifts)} tracked lifts are progressing over the "
                    f"last 30 days.")
    elif thin:
        headline = (f"Tracked lifts are holding roughly steady, though "
                    f"{', '.join(l['exercise'] for l in thin)} "
                    f"{'lacks' if len(thin) == 1 else 'lack'} enough data to judge.")
    else:
        headline = "Tracked lifts are holding roughly steady over the last 30 days."

    per_lift = [{
        "exercise": l["exercise"],
        "status": l["status"],
        "read": _lift_sentence(l),
        "confidence": ceilings[l["exercise"]][0],
    } for l in lifts]

    observed: list[str] = []
    for l in lifts:
        if l.get("e1rm_change_30d_pct") is not None:
            observed.append(
                f"{l['exercise']} estimated 1RM trend is {l['e1rm_change_30d_pct']:+}% over 30 "
                f"days, against a session variability of {l.get('session_variability_pct')}%.")
        pr = l.get("pr") or {}
        if pr.get("pr_in_last_14_days"):
            observed.append(f"{l['exercise']} set a best estimated 1RM of {pr['best_e1rm']} lb "
                            f"on {pr['best_e1rm_date']} ({pr['days_since_pr']} days ago).")
    if strength.get("sessions_per_week_last_30d") is not None:
        observed.append(f"Training frequency averaged "
                        f"{strength['sessions_per_week_last_30d']} sessions/week over 30 days.")

    inferred: list[str] = []
    for l in stalled:
        r = l.get("recent_exposures") or {}
        inferred.append(
            f"{l['exercise']} shows a pattern consistent with a plateau rather than a regression: "
            f"the 30-day trend remains positive ({l['e1rm_change_30d_pct']:+}%) while the last "
            f"{r.get('exposures_in_window')} exposures have added little. This may reflect "
            f"accumulated fatigue, a fueling change, or simply the normal flattening of a "
            f"progression block.")
    for l in regressing:
        inferred.append(f"{l['exercise']} is declining beyond its own noise floor, which warrants "
                        f"looking at recovery and fueling inputs.")

    uncertainties: list[str] = []
    for l in lifts:
        r = l.get("recent_exposures") or {}
        if not r.get("sufficient_recent_data", True):
            uncertainties.append(f"{l['exercise']}: {r.get('note')}")
        if l["status"] == "insufficient_data":
            uncertainties.append(f"{l['exercise']}: {l.get('status_reason')}")
    uncertainties.append("Strength metrics describe what changed, not why. Fueling, recovery, and "
                         "programming inputs are analysed separately.")

    levels = [ceilings[l["exercise"]][0] for l in lifts]
    from .evidence import combined_confidence
    overall = combined_confidence(*levels)
    reason = "; ".join(f"{l['exercise']}: {ceilings[l['exercise']][1]}" for l in lifts[:3])

    return {
        "headline": headline,
        "per_lift": per_lift,
        "observed": observed,
        "inferred": inferred,
        "uncertainties": uncertainties,
        "confidence": overall,
        "confidence_reason": reason,
    }
