"""Fueling Agent: interprets nutrition, adherence, and body-weight trajectory.

Mirrors the Strength Agent's structure: an LLM path and a deterministic path
producing the same shape. The distinctive job here is refusing to over-read a
correlation -- most of the logic below is about qualifying an association rather
than asserting one.
"""
from __future__ import annotations

from typing import Any

from prompts import FUELING_SYSTEM

from .evidence import combined_confidence, fueling_confidence
from .llm import LLMUnavailable, complete_json

AGENT_NAME = "fueling_agent"

# A recent-vs-earlier swing at least this large is worth surfacing as a candidate.
NOTABLE_CARB_CHANGE_PCT = 20.0
# Adherence percentages computed over fewer days than this are not a finding.
MIN_DAYS_FOR_ADHERENCE_CLAIM = 10


def analyze(snapshot: dict[str, Any], focus: list[str] | None = None) -> dict[str, Any]:
    nutrition = snapshot.get("nutrition", {})
    weight = snapshot.get("weight", {})
    strength = snapshot.get("strength", {})

    if not nutrition.get("has_data"):
        return {
            "agent": AGENT_NAME, "path": "deterministic",
            "headline": "No nutrition data is available to analyse.",
            "observed": [], "inferred": [],
            "weight_trajectory_read": weight.get("rate_note", "No body-weight data."),
            "candidate_explanations": [],
            "insufficient_evidence_for": ["Any association between fueling and performance."],
            "suggested_experiment": {"change": None, "hold_constant": [],
                                     "reassess_after": "Once nutrition logging begins."},
            "confidence": "low", "confidence_reason": "No nutrition data.",
        }

    links = nutrition.get("fueling_performance_links", {})
    if focus:
        wanted = {f.lower() for f in focus}
        scoped = {k: v for k, v in links.items() if k.lower() in wanted}
        links = scoped or links

    ceilings = {lift: fueling_confidence(link) for lift, link in links.items()}

    # The Strength Agent's verdicts are context, not something to re-derive.
    lift_status = {l["exercise"]: {
        "status": l.get("status"),
        "qualifier": l.get("qualifier"),
        "e1rm_change_30d_pct": l.get("e1rm_change_30d_pct"),
        "stalled": (l.get("recent_exposures") or {}).get("stalled"),
    } for l in strength.get("lifts", [])}

    payload = {
        "as_of": nutrition.get("as_of"),
        "goal_type": nutrition.get("goal_type"),
        "targets": nutrition.get("targets"),
        "intake_last_7_days": nutrition.get("last_7_days"),
        "intake_last_30_days": nutrition.get("last_30_days"),
        "adherence_30d": nutrition.get("adherence_30d"),
        "adherence_7d": nutrition.get("adherence_7d"),
        "protein_variability_pct_30d": nutrition.get("protein_variability_pct_30d"),
        "body_weight": {k: v for k, v in weight.items() if k != "history"},
        "recovery_context": {k: v for k, v in (snapshot.get("context") or {}).items()
                             if k != "sleep_history"},
        "strength_agent_verdicts": lift_status,
        "fueling_performance_links": links,
        "confidence_ceiling_per_lift": {k: v[0] for k, v in ceilings.items()},
        "confidence_reasoning_per_lift": {k: v[1] for k, v in ceilings.items()},
    }

    try:
        out = complete_json(FUELING_SYSTEM, payload)
        out["path"] = "llm"
    except LLMUnavailable as exc:
        out = _rule_read(nutrition, weight, links, ceilings, lift_status)
        out["path"] = "deterministic"
        out["_fallback_reason"] = str(exc)

    out["agent"] = AGENT_NAME
    out["lifts_considered"] = list(links.keys())
    return out


# --------------------------------------------------------------------------- #
# Deterministic reviewer
# --------------------------------------------------------------------------- #
def _rule_read(nutrition: dict[str, Any], weight: dict[str, Any],
               links: dict[str, dict[str, Any]], ceilings: dict[str, tuple[str, str]],
               lift_status: dict[str, dict[str, Any]]) -> dict[str, Any]:
    n30 = nutrition.get("last_30_days", {})
    adh = nutrition.get("adherence_30d", {})
    targets = nutrition.get("targets", {})
    days_logged = n30.get("days_logged") or 0
    enough_days = days_logged >= MIN_DAYS_FOR_ADHERENCE_CLAIM

    observed: list[str] = []
    if n30.get("avg_calories") is not None and targets.get("calories"):
        line = (f"Calorie intake averaged {n30['avg_calories']:.0f} kcal/day across {days_logged} "
                f"logged day(s) against a {targets['calories']} kcal target "
                f"({adh.get('avg_calorie_deviation', 0):+.0f} kcal/day)")
        if enough_days:
            line += (f", landing within 10% of target on "
                     f"{adh.get('calorie_adherence_pct', 0):.0f}% of days")
        observed.append(line + ".")
    if n30.get("avg_protein") is not None and targets.get("protein"):
        line = (f"Protein averaged {n30['avg_protein']} g/day across {days_logged} logged day(s) "
                f"against a {targets['protein']} g target")
        if enough_days:
            line += (f", hitting at least 95% of target on "
                     f"{adh.get('protein_adherence_pct', 0):.0f}% of days")
        observed.append(line + ".")
    if nutrition.get("protein_variability_pct_30d") is not None:
        observed.append(f"Day-to-day protein variability was "
                        f"{nutrition['protein_variability_pct_30d']}% over 30 days.")
    if n30.get("avg_carbs") is not None and targets.get("carbs"):
        observed.append(f"Carbohydrate intake averaged {n30['avg_carbs']} g/day against a "
                        f"{targets['carbs']} g target.")

    candidates: list[dict[str, Any]] = []
    insufficient: list[str] = []
    inferred: list[str] = []

    for lift, link in links.items():
        if not link.get("sufficient_evidence"):
            insufficient.append(f"{lift}: {link.get('note')}")
            continue

        rv = link.get("recent_vs_earlier") or {}
        change = rv.get("preworkout_carb_change_pct")
        corr_strength = link.get("correlation_strength")
        r = link.get("preworkout_carbs_vs_performance_r")
        is_stalled = (lift_status.get(lift) or {}).get("stalled")

        if change is not None and abs(change) >= NOTABLE_CARB_CHANGE_PCT:
            observed.append(
                f"{lift}: pre-workout carbohydrate averaged "
                f"{rv['recent_avg_preworkout_carbs']} g across the {len(rv.get('recent_dates', []))} "
                f"most recent sessions versus {rv['earlier_avg_preworkout_carbs']} g across earlier "
                f"sessions in the window ({change:+.0f}%).")
            if is_stalled and change < 0:
                candidates.append({
                    "explanation": (f"Lower pre-workout carbohydrate availability is one plausible "
                                    f"contributor to the recent {lift} slowdown."),
                    "supporting_metric": (f"{lift} pre-workout carbs {rv['recent_avg_preworkout_carbs']} g "
                                          f"recently vs {rv['earlier_avg_preworkout_carbs']} g earlier "
                                          f"({change:+.0f}%)"),
                    "plausibility": "moderate",
                })
                inferred.append(
                    f"The recent {lift} plateau coincides with a {abs(change):.0f}% reduction in "
                    f"pre-workout carbohydrate. This is an association in observational data and "
                    f"cannot establish causality, but it is one plausible contributor.")

        if corr_strength in ("negligible", "weak") and r is not None:
            inferred.append(
                f"{lift}: across the whole window, session-level pre-workout carbohydrate and "
                f"performance relative to trend correlate only weakly (r={r}). The recent-phase "
                f"difference is therefore stronger evidence than the session-level pattern, and "
                f"the two lenses do not fully agree.")

        cals = (link.get("comparisons") or {}).get("day_calories") or {}
        if cals.get("difference") is not None and abs(cals["difference"]) >= 100:
            observed.append(
                f"{lift}: higher-performing sessions averaged {cals['higher_performing_avg']:.0f} kcal "
                f"on the training day versus {cals['lower_performing_avg']:.0f} kcal on "
                f"lower-performing sessions.")

    # Weight trajectory is its own candidate explanation when it is off-target.
    verdict = weight.get("rate_verdict")
    if verdict == "faster_than_intended":
        candidates.append({
            "explanation": ("Body weight is coming down faster than intended, which can compromise "
                            "strength retention in a deficit."),
            "supporting_metric": (f"observed {weight.get('observed_rate_lb_per_week_30d')} lb/week vs "
                                  f"target {weight.get('target_rate_lb_per_week')} lb/week"),
            "plausibility": "moderate",
        })
    protein_gap = (enough_days and adh.get("protein_adherence_pct") is not None
                   and adh["protein_adherence_pct"] < 70)
    if protein_gap:
        candidates.append({
            "explanation": ("Protein target is being missed on most days, which is worth tightening "
                            "in a deficit regardless of its link to any single session."),
            "supporting_metric": (f"protein target met on {adh['protein_adherence_pct']:.0f}% of days "
                                  f"across {days_logged} logged days (avg {n30.get('avg_protein')} g "
                                  f"vs {targets.get('protein')} g target)"),
            "plausibility": "moderate",
        })
    if not enough_days:
        insufficient.append(
            f"Adherence to calorie and macro targets: only {days_logged} day(s) of nutrition "
            f"logged in the last 30 days, so adherence percentages are not yet meaningful.")

    # Smallest supported experiment.
    experiment: dict[str, Any] = {"change": None, "hold_constant": [],
                                  "reassess_after": "Continue logging; nothing warrants a change yet."}
    carb_candidate = next((c for c in candidates if "carbohydrate availability" in c["explanation"]), None)
    if carb_candidate and verdict != "faster_than_intended":
        stalled_lifts = [lift for lift, st in lift_status.items() if st.get("stalled")]
        target_lift = stalled_lifts[0] if stalled_lifts else "the affected lift"
        experiment = {
            "change": (f"Increase pre-workout carbohydrate by approximately 30-40 g before the next "
                       f"two comparable {target_lift} sessions, reallocating those calories from "
                       f"elsewhere in the day."),
            "hold_constant": ["total daily calories", "protein intake", "training volume and programming"],
            "reassess_after": f"Two comparable {target_lift} sessions.",
        }
    elif verdict == "faster_than_intended":
        experiment = {
            "change": (f"Slow the rate of loss toward the intended "
                       f"{weight.get('target_rate_lb_per_week')} lb/week before changing anything else."),
            "hold_constant": ["training volume and programming"],
            "reassess_after": "Two weeks of body-weight data.",
        }
    elif protein_gap:
        experiment = {
            "change": (f"Close the protein gap on missed days toward the "
                       f"{targets.get('protein')} g target before adjusting calories."),
            "hold_constant": ["total daily calories", "training volume and programming"],
            "reassess_after": "Two weeks of nutrition logging.",
        }

    levels = [c[0] for c in ceilings.values()]
    confidence = combined_confidence(*levels) if levels else "low"
    reason = ("; ".join(f"{lift}: {c[1]}" for lift, c in list(ceilings.items())[:2])
              or "No fueling/performance comparison had enough data.")

    if candidates:
        headline = (f"{len(candidates)} plausible fueling factor(s) identified. Strongest: "
                    f"{candidates[0]['explanation']}")
    else:
        headline = ("Fueling looks broadly consistent with the athlete's targets; no single fueling "
                    "factor stands out in the available data.")

    return {
        "headline": headline,
        "observed": observed,
        "inferred": inferred,
        "weight_trajectory_read": weight.get("rate_note", "No body-weight data available."),
        "candidate_explanations": candidates,
        "insufficient_evidence_for": insufficient,
        "suggested_experiment": experiment,
        "confidence": confidence,
        "confidence_reason": reason,
    }
