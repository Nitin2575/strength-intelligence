"""Routes a question to the agents that can answer it.

Deliberately simple and inspectable: keyword scoring over intent vocabularies,
with a bias toward invoking both specialists when a question implies a
*relationship* between performance and fueling. Routing decisions are returned
with their rationale so the eval suite can assert on them and the UI can show
which agents ran.

A learned classifier would be the obvious upgrade, but it would also make
routing failures much harder to explain -- and at this vocabulary size it would
not measurably outperform the keyword pass.
"""
from __future__ import annotations

import re
from typing import Any

STRENGTH_TERMS = {
    "bench", "squat", "deadlift", "rdl", "romanian", "press", "ohp", "overhead",
    "lift", "lifts", "lifting", "strength", "stronger", "weaker", "1rm", "e1rm",
    "pr", "prs", "progress", "progressing", "progression", "plateau", "plateaued",
    "stall", "stalled", "stalling", "regress", "regressing", "volume", "sets",
    "reps", "rpe", "workout", "workouts", "session", "sessions", "training",
    "weight on the bar", "working weight",
}

FUELING_TERMS = {
    "calorie", "calories", "kcal", "deficit", "surplus", "maintenance", "eat",
    "eating", "ate", "food", "fuel", "fueling", "fuelling", "nutrition", "diet",
    "macro", "macros", "protein", "carb", "carbs", "carbohydrate", "carbohydrates",
    "fat", "fats", "preworkout", "pre-workout", "meal", "meals", "cut", "cutting",
    "bulk", "bulking", "weigh", "weight", "bodyweight", "body-weight", "lb", "lbs",
    "pounds", "scale", "losing", "lose", "gaining", "gain", "leaner",
}

# Questions about a relationship need both specialists plus synthesis.
RELATIONAL_PATTERNS = [
    r"\bwhy\b", r"\bhurt(ing)?\b", r"\baffect(ing|ed)?\b", r"\bimpact(ing|ed)?\b",
    r"\bcaus(e|ing)\b", r"\bbecause\b", r"\bdue to\b", r"\brelated\b",
    r"\bassociat(ed|ion)\b", r"\bexplain\b", r"\bdriv(e|ing|er)\b",
    r"\bshould i\b", r"\bwhat should\b", r"\bwhat.*chang", r"\bbefore my\b",
    r"\bbest workouts?\b", r"\bworse\b", r"\bbetter\b", r"\bfueling before\b",
]

LIFT_ALIASES = {
    "bench": "Bench Press", "bench press": "Bench Press", "benching": "Bench Press",
    "squat": "Squat", "squats": "Squat", "squatting": "Squat",
    "rdl": "Romanian Deadlift", "romanian deadlift": "Romanian Deadlift",
    "romanian": "Romanian Deadlift", "deadlift": "Romanian Deadlift",
    "ohp": "Overhead Press", "overhead press": "Overhead Press",
    "overhead": "Overhead Press", "shoulder press": "Overhead Press",
}

PUSH_TERMS = {"push", "pushing", "press", "pressing", "upper"}

# Question intent. Beyond choosing agents, the orchestrator uses this to lead with
# the answer the athlete actually asked for rather than a generic status report.
INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    # Ordered: earlier patterns win, so the more specific intents come first.
    ("explain_change", [r"\bwhy\b", r"what('?s| is) driving", r"what.*\bcaus", r"\bexplain\b",
                        r"what happened", r"\breason\b"]),
    ("next_session", [r"before my next", r"what should i (do|change|eat) (before|for)",
                      r"next (push|leg|pull|workout|session)"]),
    ("weight_rate", [r"losing .*(too )?(fast|quick)", r"(too )?(fast|quick)ly",
                     r"\blosing weight\b", r"\bgaining .*(too )?(fast|quick)",
                     r"rate of (weight )?(loss|change|gain)", r"\bweigh(ing)? (too|in)\b",
                     r"\bon track\b.*weight", r"weight.*\bon track\b"]),
    ("calorie_decision", [r"should i (increase|raise|add|decrease|lower|drop|cut|change|eat)",
                          r"(increase|raise|lower|change|adjust) my (calorie|kcal|intake|deficit)",
                          r"\beat more\b", r"\beat less\b", r"more calories", r"fewer calories"]),
    ("fueling_comparison", [r"fueling before", r"before my (best|worst|good|bad)",
                            r"(best|worst) (workout|session|lift)", r"what did i eat before"]),
    ("lift_ranking", [r"which lift", r"which exercise", r"\bfastest\b", r"\bslowest\b",
                      r"progressing the most", r"\bcompare\b.*lift", r"\brank\b"]),
    ("deficit_impact", [r"deficit .*(hurt|affect|impact|cost|limit)",
                        r"(hurt|affect|impact|limit)(ing)? my (strength|bench|squat|lift)",
                        r"is my (cut|deficit|diet)"]),
    ("lift_status", [r"how is my", r"how'?s my", r"\bprogress(ing|ion)?\b", r"\bstall",
                     r"\bplateau", r"\bregress", r"\bgetting (stronger|weaker)\b"]),
]


def detect_intent(question: str) -> str:
    q = question.lower()
    for intent, patterns in INTENT_PATTERNS:
        if any(re.search(p, q) for p in patterns):
            return intent
    return "general"


def _tokens(question: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\-]+", question.lower()))


def detect_lifts(question: str) -> list[str]:
    """Which specific lifts the question is about, if any."""
    q = question.lower()
    found: list[str] = []
    for alias, canonical in LIFT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q) and canonical not in found:
            found.append(canonical)
    if not found and _tokens(question) & PUSH_TERMS:
        found = ["Bench Press", "Overhead Press"]
    return found


def route(question: str) -> dict[str, Any]:
    """Decide which agents to run. Returns agents + rationale + detected focus."""
    toks = _tokens(question)
    q = question.lower()

    strength_hits = sorted(toks & STRENGTH_TERMS)
    fueling_hits = sorted(toks & FUELING_TERMS)
    relational = [p for p in RELATIONAL_PATTERNS if re.search(p, q)]

    agents: list[str] = []
    if strength_hits:
        agents.append("strength_agent")
    if fueling_hits:
        agents.append("fueling_agent")

    # A relational question always needs both specialists: to reason about a
    # relationship between two domains, findings from both must be on the table.
    if relational and len(agents) < 2:
        agents = ["strength_agent", "fueling_agent"]

    if not agents:
        agents = ["strength_agent", "fueling_agent"]
        rationale = ("No domain keywords matched, so both specialists were invoked and the "
                     "orchestrator was left to synthesise a general answer.")
    elif len(agents) == 2:
        if relational:
            rationale = (f"Question implies a relationship (matched {len(relational)} relational "
                         f"pattern(s)), so both specialists ran and the orchestrator reconciled them.")
        else:
            rationale = ("Question spans both strength and fueling vocabulary, so both specialists "
                         "ran and the orchestrator reconciled them.")
    elif agents == ["strength_agent"]:
        rationale = f"Strength-specific question (matched: {', '.join(strength_hits)})."
    else:
        rationale = f"Fueling/body-weight question (matched: {', '.join(fueling_hits)})."

    intent = detect_intent(question)

    # Some intents inherently need both specialists regardless of vocabulary:
    # "am I losing weight too fast" is a fueling question, but answering it
    # responsibly requires knowing whether strength is holding.
    if intent in ("deficit_impact", "calorie_decision", "fueling_comparison",
                  "next_session", "weight_rate", "explain_change"):
        agents = ["strength_agent", "fueling_agent"]
        rationale = (f"Intent '{intent}' requires weighing strength against fueling, so both "
                     f"specialists ran and the orchestrator reconciled them.")

    return {
        "agents": agents,
        "needs_orchestration": True,  # the user always hears one voice
        "intent": intent,
        "rationale": rationale,
        "focus_lifts": detect_lifts(question),
        "matched": {"strength": strength_hits, "fueling": fueling_hits,
                    "relational": len(relational)},
    }
