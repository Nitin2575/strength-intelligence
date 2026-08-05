"""Strength Intelligence Orchestrator: the single user-facing voice.

Receives the specialists' findings plus body-weight and recovery context, and
reconciles them into one answer. Two responsibilities are handled in code rather
than left to the model:

  - the confidence ceiling, derived from the specialists' own coverage-based
    confidence (a synthesis is never more certain than its weakest input)
  - the intervention ladder, which encodes the rule that a recent stall against
    a progressing trend warrants a reversible experiment, not a change to the
    energy target
"""
from __future__ import annotations

from typing import Any

from prompts import ORCHESTRATOR_SYSTEM

from . import fueling_agent, strength_agent
from .evidence import (combined_confidence, coverage_note, fueling_confidence,
                       strength_confidence)
from .llm import LLMUnavailable, complete_json
from .router import route

AGENT_NAME = "orchestrator"


def ask(question: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Answer a question end to end: route, run specialists, synthesise."""
    routing = route(question)
    focus = routing["focus_lifts"] or None

    findings: dict[str, Any] = {}
    if "strength_agent" in routing["agents"]:
        findings["strength"] = strength_agent.analyze(snapshot, focus)
    if "fueling_agent" in routing["agents"]:
        findings["fueling"] = fueling_agent.analyze(snapshot, focus)

    subject = _subject_lifts(snapshot, focus)
    ceiling, ceiling_reason = _subject_confidence(snapshot, subject, findings)

    payload = {
        "question": question,
        "as_of": snapshot.get("as_of"),
        "profile": snapshot.get("profile"),
        "routing": routing,
        "strength_agent_findings": findings.get("strength"),
        "fueling_agent_findings": findings.get("fueling"),
        "body_weight": {k: v for k, v in (snapshot.get("weight") or {}).items() if k != "history"},
        "recovery_context": {k: v for k, v in (snapshot.get("context") or {}).items()
                             if k != "sleep_history"},
        "confidence_ceiling": ceiling,
        "confidence_ceiling_reason": ceiling_reason,
        "subject_lifts": subject,
        "data_coverage": coverage_note(snapshot),
    }

    try:
        out = complete_json(ORCHESTRATOR_SYSTEM, payload)
        out["path"] = "llm"
    except LLMUnavailable as exc:
        out = _rule_synthesis(question, snapshot, findings, ceiling, ceiling_reason)
        out["path"] = "deterministic"
        out["_fallback_reason"] = str(exc)

    out["agent"] = AGENT_NAME
    out["routing"] = routing
    out["agents_consulted"] = list(findings.keys())
    out["agent_findings"] = findings
    out["as_of"] = snapshot.get("as_of")
    return out


def current_intelligence(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The dashboard's standing read, with no question asked.

    Uses the same pipeline as a chat question so the dashboard headline and the
    chat answer can never disagree with each other.
    """
    return ask("What is driving my strength progression, and what should I change next?", snapshot)


# --------------------------------------------------------------------------- #
# Deterministic synthesis
# --------------------------------------------------------------------------- #
def _stalled_lifts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [l for l in snapshot.get("strength", {}).get("lifts", [])
            if (l.get("recent_exposures") or {}).get("stalled") and l.get("status") == "progressing"]


def _regressing_lifts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [l for l in snapshot.get("strength", {}).get("lifts", [])
            if l.get("status") == "regressing"]


def _subject_lifts(snapshot: dict[str, Any], focus: list[str] | None) -> list[str]:
    """Which lifts the answer is actually about.

    Confidence must describe the claim being made, not the whole dataset. Without
    this scoping, one incidental lift with a weak signal would drag the confidence
    of a well-evidenced statement about a different lift down with it.
    """
    if focus:
        return list(focus)
    notable = _stalled_lifts(snapshot) + _regressing_lifts(snapshot)
    if notable:
        return [l["exercise"] for l in notable]
    return [l["exercise"] for l in snapshot.get("strength", {}).get("lifts", [])]


def _subject_confidence(snapshot: dict[str, Any], subject: list[str],
                        findings: dict[str, Any]) -> tuple[str, str]:
    """Confidence ceiling and a concise reason, scoped to the subject lifts."""
    lifts = {l["exercise"]: l for l in snapshot.get("strength", {}).get("lifts", [])}
    links = snapshot.get("nutrition", {}).get("fueling_performance_links", {}) or {}

    levels: list[str] = []
    reasons: list[str] = []

    if "strength" in findings:
        for name in subject:
            lift = lifts.get(name)
            if not lift:
                continue
            level, why = strength_confidence(lift)
            levels.append(level)
            reasons.append(f"{name}: {why}")

    if "fueling" in findings:
        for name in subject:
            link = links.get(name)
            if not link:
                continue
            level, why = fueling_confidence(link)
            levels.append(level)
            reasons.append(f"{name} fueling: {why}")

    if not levels:
        return "low", "No subject lift had enough data to assess."
    return combined_confidence(*levels), " ".join(reasons[:2])


def _next_action(snapshot: dict[str, Any], findings: dict[str, Any]) -> dict[str, Any]:
    """The intervention ladder: escalate only as far as the evidence justifies."""
    weight = snapshot.get("weight") or {}
    fueling = findings.get("fueling") or {}
    stalled = _stalled_lifts(snapshot)
    regressing = _regressing_lifts(snapshot)
    losing_too_fast = weight.get("rate_verdict") == "faster_than_intended"

    # Rung 0: not enough data to justify any intervention. Collect, don't act.
    lifts = snapshot.get("strength", {}).get("lifts", [])
    thin = [l for l in lifts if l.get("status") == "insufficient_data"]
    if not lifts or len(thin) == len(lifts):
        detail = ("No tracked lift has enough logged exposures in the last 30 days to establish a "
                  "trend. Continue logging training and pre-workout nutrition; a recommendation "
                  "based on this little data would be guesswork." if lifts else
                  "There is no logged training data yet. Add workouts to data/workouts.csv, or run "
                  "scripts/generate_sample_data.py to populate the sample dataset.")
        return {
            "action": "Keep logging — not enough data to recommend a change",
            "detail": detail,
            "hold_constant": ["total daily calories", "training volume and programming"],
            "rationale": ("The system will not propose an intervention it cannot justify from the "
                          "available evidence."),
        }

    # Rung 4: performance falling AND weight dropping faster than intended.
    if regressing and losing_too_fast:
        return {
            "action": "Raise the calorie target modestly",
            "detail": (f"Strength is regressing while body weight is falling at "
                       f"{weight.get('observed_rate_lb_per_week_30d')} lb/week against an intended "
                       f"{weight.get('target_rate_lb_per_week')} lb/week. Add roughly 150-200 kcal/day, "
                       f"primarily as carbohydrate, and re-check in two weeks."),
            "hold_constant": ["training volume and programming", "protein intake"],
            "rationale": ("This is the one pattern that justifies changing the energy target: the "
                          "performance signal and the body-weight signal both point the same way."),
        }

    # Rung 3: weight dropping too fast, performance not yet clearly hurt.
    if losing_too_fast:
        return {
            "action": "Slow the rate of weight loss before changing anything else",
            "detail": (f"Body weight is moving at {weight.get('observed_rate_lb_per_week_30d')} lb/week "
                       f"against an intended {weight.get('target_rate_lb_per_week')} lb/week. Bring the "
                       f"rate back toward target first, since a faster-than-planned deficit is the more "
                       f"likely constraint on strength retention."),
            "hold_constant": ["training volume and programming"],
            "rationale": "Correcting the deficit rate is a smaller change than restructuring fueling timing.",
        }

    # Rung 2: a recent stall against a progressing trend -> reversible experiment.
    if stalled:
        experiment = fueling.get("suggested_experiment") or {}
        if experiment.get("change"):
            return {
                "action": "Run a targeted pre-workout fueling experiment",
                "detail": experiment["change"],
                "hold_constant": experiment.get("hold_constant") or ["total daily calories"],
                "rationale": ("The 30-day trend is still positive and body weight is tracking to plan, "
                              "so the smallest interpretable step is to redistribute existing calories "
                              "rather than change the energy target."),
            }
        names = ", ".join(l["exercise"] for l in stalled)
        # Only claim fueling was examined if the Fueling Agent actually ran.
        cause_clause = ("but no fueling or recovery input has changed enough to point at a specific "
                        "cause" if fueling else "and fueling was not examined for this question")
        return {
            "action": "Hold the current plan and collect two more exposures",
            "detail": (f"{names} has flattened recently, {cause_clause}. Keep calories and training "
                       f"unchanged and log pre-workout nutrition for the next two sessions."),
            "hold_constant": ["total daily calories", "training volume and programming"],
            "rationale": "A stall with no identified driver calls for better data, not an intervention.",
        }

    # Rung 1: nothing warrants a change.
    return {
        "action": "No change",
        "detail": ("Strength, body weight, and fueling are all tracking as intended. Continue the "
                   "current plan and keep logging."),
        "hold_constant": ["total daily calories", "training volume and programming", "protein intake"],
        "rationale": "No signal currently exceeds normal variability, so intervening would add noise.",
    }


def _direct_answer(intent: str, snapshot: dict[str, Any], findings: dict[str, Any],
                   focus: list[str]) -> str | None:
    """The lead sentence for the athlete's actual question.

    Without this, a fallback answer tends to recite the most interesting finding
    in the dataset rather than responding to what was asked.
    """
    weight = snapshot.get("weight") or {}
    strength = snapshot.get("strength") or {}
    fueling = findings.get("fueling") or {}
    lifts = strength.get("lifts", [])
    by_name = {l["exercise"]: l for l in lifts}

    if intent == "weight_rate" and weight.get("has_data"):
        verdict = {
            "on_target": "No — your rate of weight change is tracking your intended rate.",
            "faster_than_intended": "Yes — you are losing weight faster than you intended.",
            "slower_than_intended": "No — you are losing weight more slowly than intended.",
            "drifting": "Your weight is drifting despite a maintenance goal.",
        }.get(weight.get("rate_verdict"), "There is not enough body-weight data to judge the rate.")
        return (f"{verdict} {weight.get('rate_note')} Current 7-day average is "
                f"{weight.get('current_weight_7d_avg')} lb, "
                f"{weight.get('lb_to_target')} lb from your {weight.get('target_weight')} lb target.")

    if intent == "lift_ranking" and lifts:
        ranked = sorted([l for l in lifts if l.get("e1rm_change_30d_pct") is not None],
                        key=lambda l: l["e1rm_change_30d_pct"], reverse=True)
        if ranked:
            parts = [f"{l['exercise']} ({l['e1rm_change_30d_pct']:+}%)" for l in ranked]
            return (f"Ranked by 30-day estimated 1RM trend: {', '.join(parts)}. "
                    f"{ranked[0]['exercise']} is progressing fastest.")

    if intent == "calorie_decision":
        action = _next_action(snapshot, findings)
        lead = ("Yes — but not yet as a first step." if "calorie target" in action["action"].lower()
                else "Not yet, based on the current evidence.")
        return f"{lead} {action['rationale']}"

    if intent == "fueling_comparison":
        for lift, link in (snapshot.get("nutrition", {})
                           .get("fueling_performance_links", {}) or {}).items():
            if focus and lift not in focus:
                continue
            if not link.get("sufficient_evidence"):
                continue
            c = (link.get("comparisons") or {}).get("preworkout_carbs_g") or {}
            if c.get("higher_performing_avg") is None:
                continue
            return (f"Across the last {link.get('window_days')} days, your higher-performing {lift} "
                    f"sessions averaged {c['higher_performing_avg']} g of pre-workout carbohydrate "
                    f"versus {c['lower_performing_avg']} g on lower-performing sessions "
                    f"({c['difference']:+} g). Session-level correlation is "
                    f"{link.get('correlation_strength')} (r={link.get('preworkout_carbs_vs_performance_r')}).")

    if intent == "lift_status" and focus:
        l = by_name.get(focus[0])
        if l:
            r = l.get("recent_exposures") or {}
            base = (f"{l['exercise']} is {l['status'].replace('_', ' ')}: estimated 1RM trend is "
                    f"{l['e1rm_change_30d_pct']:+}% over 30 days, currently "
                    f"{l.get('current_e1rm')} lb from {l.get('current_working_weight')}.")
            if r.get("stalled"):
                base += (f" The last {r.get('exposures_in_window')} exposures have added little "
                         f"further progress.")
            return base

    if intent == "next_session":
        action = _next_action(snapshot, findings)
        return f"{action['detail']}"

    return None


def _rule_synthesis(question: str, snapshot: dict[str, Any], findings: dict[str, Any],
                    ceiling: str, ceiling_reason: str) -> dict[str, Any]:
    strength = findings.get("strength") or {}
    fueling = findings.get("fueling") or {}
    weight = snapshot.get("weight") or {}
    context = snapshot.get("context") or {}

    stalled = _stalled_lifts(snapshot)
    regressing = _regressing_lifts(snapshot)

    lifts = snapshot.get("strength", {}).get("lifts", [])
    thin = [l for l in lifts if l.get("status") == "insufficient_data"]

    # Observation
    if lifts and len(thin) == len(lifts):
        observation = ("There is not enough logged training data to characterise strength "
                       "progression yet.")
    elif regressing:
        observation = (f"{', '.join(l['exercise'] for l in regressing)} "
                       f"{'is' if len(regressing) == 1 else 'are'} regressing beyond normal "
                       f"session-to-session variability.")
    elif stalled:
        names = ", ".join(l["exercise"] for l in stalled)
        first = stalled[0]
        observation = (f"Strength is progressing over the 30-day window, but {names} "
                       f"{'has' if len(stalled) == 1 else 'have'} stalled across the last "
                       f"{(first.get('recent_exposures') or {}).get('exposures_in_window')} exposures.")
    elif strength.get("headline"):
        observation = strength["headline"]
    else:
        observation = "Not enough training data to characterise strength progression."

    # Evidence: pull the specific numbers the specialists surfaced.
    evidence: list[str] = []
    for l in stalled + regressing:
        r = l.get("recent_exposures") or {}
        evidence.append(
            f"{l['exercise']} estimated 1RM trend is {l['e1rm_change_30d_pct']:+}% over 30 days "
            f"(session variability {l.get('session_variability_pct')}%), but the recent rate is "
            f"{r.get('rate_recent_lb_per_week')} lb/week against a 30-day rate of "
            f"{r.get('rate_30d_lb_per_week')} lb/week.")
    if weight.get("has_data"):
        evidence.append(
            f"Body weight is {weight.get('current_weight_7d_avg')} lb (7-day average), "
            f"{weight.get('change_last_30d')} lb over 30 days. {weight.get('rate_note')}")
    evidence.extend((fueling.get("observed") or [])[:3])
    for m in (context.get("sleep"), context.get("training_frequency")):
        if m and m.get("note"):
            evidence.append(m["note"])

    # Interpretation
    candidates = fueling.get("candidate_explanations") or []
    if lifts and len(thin) == len(lifts):
        interpretation = ("With this little training data, any explanation would be speculation. "
                          "The honest read is that the evidence base is too thin to interpret.")
        candidates = []
    elif candidates:
        interpretation = (f"{candidates[0]['explanation']} This rests on observational data from a "
                          f"single athlete ({candidates[0]['supporting_metric']}), so it is one "
                          f"plausible contributor rather than an established cause.")
    elif stalled:
        interpretation = ("The flattening is consistent with the normal end of a progression block. "
                          "No fueling or recovery input has changed enough to single out a driver.")
    else:
        interpretation = ("The available data does not indicate a specific constraint on strength "
                          "progression at this point.")

    alternatives = [c["explanation"] for c in candidates[1:]]
    if stalled and not alternatives:
        alternatives.append("Accumulated fatigue from the current training block, independent of fueling.")
    if stalled:
        alternatives.append("Normal flattening at the end of a progression block, requiring a "
                            "programming change rather than a fueling change.")

    # Ruled out: stable inputs are evidence *against* an explanation.
    ruled_out: list[str] = []
    for m in (context.get("sleep"), context.get("steps"), context.get("training_frequency")):
        if m and m.get("stable"):
            ruled_out.append(m["note"])

    action = _next_action(snapshot, findings)

    # Reassess
    if action["action"] == "No change":
        reassess = ("Re-evaluate in two weeks. A 30-day trend turning negative on any tracked lift, "
                    "or the body-weight rate drifting outside its target band, would change this read.")
    elif stalled and "fueling experiment" in action["action"]:
        target = stalled[0]["exercise"]
        reassess = (f"After two comparable {target} sessions. If estimated 1RM resumes rising, the "
                    f"fueling association is supported. If performance keeps flattening while body "
                    f"weight continues falling faster than "
                    f"{weight.get('target_rate_lb_per_week')} lb/week, the calorie target itself "
                    f"should be reassessed next.")
    else:
        reassess = ("After two weeks of body-weight and training data. If strength recovers as the "
                    "rate of loss slows, the deficit was the binding constraint.")

    # Answer: lead with the response to the question that was actually asked,
    # then supply the standing observation and the recommendation.
    routing = route(question)
    intent = routing.get("intent", "general")
    lead = _direct_answer(intent, snapshot, findings, routing.get("focus_lifts") or [])

    answer_bits = [lead] if lead else [observation]
    if candidates and intent in ("general", "explain_change", "deficit_impact", "lift_status"):
        answer_bits.append(f"Most plausible contributor: {candidates[0]['explanation']}")
    if intent != "next_session":
        answer_bits.append(f"Recommended next step: {action['detail']}")
    answer = " ".join(answer_bits)

    confidence = ceiling

    return {
        "answer": answer,
        "observation": observation,
        "evidence": evidence,
        "interpretation": interpretation,
        "alternative_explanations": alternatives,
        "ruled_out": ruled_out,
        "next_action": action,
        "confidence": confidence,
        "confidence_reason": ceiling_reason or "Based on available data coverage.",
        "reassess": reassess,
        "metrics_cited": ["e1rm_change_30d_pct", "rate_recent_lb_per_week", "rate_30d_lb_per_week",
                          "observed_rate_lb_per_week_30d", "preworkout_carbs", "sleep_hours"],
    }
