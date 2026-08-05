"""Eval runner for Strength Intelligence.

Scores every case on five dimensions. The load-bearing one is **groundedness**:
it extracts every number from the response text and checks that each appears in
the deterministically computed snapshot. That is the check that would actually
catch a hallucinated statistic, and it works identically against the LLM path
and the deterministic path.

Usage:
    python evals/run_evals.py                # run all cases
    python evals/run_evals.py --case bench_progression
    python evals/run_evals.py --verbose      # show per-case detail
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from agents import ask  # noqa: E402
from agents.llm import llm_enabled, model_name  # noqa: E402
from analytics import build_snapshot, load_dataset  # noqa: E402

CASES_PATH = Path(__file__).parent / "test_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"

# Small integers are structural ("the last 3 exposures", window sizes) rather than
# claims about magnitude, so they are exempt from the groundedness check.
GROUNDING_EXEMPT = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 30, 60, 90, 95, 100}


# --------------------------------------------------------------------------- #
# Sparse dataset for the insufficient-evidence guard case
# --------------------------------------------------------------------------- #
def _sparse_snapshot() -> dict[str, Any]:
    """A deliberately thin dataset: two sessions, two logged days."""
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    (tmp / "profile.json").write_text((ROOT / "data" / "profile.json").read_text())
    pd.DataFrame([
        {"date": "2026-07-28", "exercise": "Bench Press", "sets": 3, "reps": 5,
         "weight": 185, "rpe": 8},
        {"date": "2026-08-04", "exercise": "Bench Press", "sets": 3, "reps": 5,
         "weight": 180, "rpe": 9},
    ]).to_csv(tmp / "workouts.csv", index=False)
    pd.DataFrame([
        {"date": "2026-07-28", "calories": 2100, "protein": 160, "carbs": 200, "fat": 70,
         "preworkout_carbs": 60, "preworkout_protein": 20, "workout_time": "07:00"},
        {"date": "2026-08-04", "calories": 2050, "protein": 155, "carbs": 190, "fat": 72,
         "preworkout_carbs": 25, "preworkout_protein": 15, "workout_time": "07:00"},
    ]).to_csv(tmp / "nutrition.csv", index=False)
    pd.DataFrame([
        {"date": "2026-08-04", "body_weight": 150, "sleep_hours": 7.1, "steps": 8000},
    ]).to_csv(tmp / "daily_context.csv", index=False)
    return build_snapshot(load_dataset(tmp))


# --------------------------------------------------------------------------- #
# Scoring helpers
# --------------------------------------------------------------------------- #
def _collect_numbers(obj: Any, out: set[float]) -> None:
    """Every numeric value anywhere in the snapshot, plus common derived forms."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 4))
        out.add(round(abs(float(obj)), 4))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_numbers(v, out)
    elif isinstance(obj, str):
        for m in re.findall(r"-?\d+\.?\d*", obj):
            try:
                out.add(round(float(m), 4))
                out.add(round(abs(float(m)), 4))
            except ValueError:
                pass


def _response_text(response: dict[str, Any]) -> str:
    """Flatten the user-visible parts of a response into one string."""
    parts: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, str):
            parts.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k.startswith("_") or k in ("agent_findings", "routing", "metrics_cited"):
                    continue
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(response)
    return " ".join(parts)


def score_groundedness(response: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Every number in the response must trace to a value the agents were given.

    Two choices make this check real rather than decorative:

    1. It compares against `slim_for_prompt(snapshot)` -- exactly what the agents
       receive -- not the full snapshot. The full snapshot carries 90 days of raw
       daily rows, and a set that large makes almost any number look "present".
    2. Matching is exact against the value and its 0/1/2-decimal roundings. No
       proportional tolerance: with thousands of candidate values spanning several
       orders of magnitude, a percentage tolerance matches nearly everything and
       silently defeats the check.
    """
    from analytics.snapshot import slim_for_prompt

    raw: set[float] = set()
    _collect_numbers(slim_for_prompt(snapshot), raw)

    # Pre-expand every legitimate rendering of each allowed value.
    allowed: set[str] = set()
    for v in raw:
        for d in (0, 1, 2):
            allowed.add(f"{abs(v):.{d}f}")

    text = _response_text(response)
    # Dates are numerals but not magnitude claims.
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)
    # Prescribed ranges ("increase by 30-40 g", "add 150-200 kcal") are dosage
    # recommendations, not claims about the athlete's data, so they have no
    # snapshot value to trace back to.
    text = re.sub(r"\d+\s*[-–]\s*\d+", " ", text)
    # Require a minus sign to start a token, so "30-40" is not read as "-40".
    found = [float(m) for m in re.findall(r"(?<![\d.])-?\d+\.?\d*", text)]

    ungrounded: list[float] = []
    for n in found:
        if abs(n) in GROUNDING_EXEMPT and float(n).is_integer():
            continue
        forms = {f"{abs(n):.{d}f}" for d in (0, 1, 2)}
        if forms & allowed:
            continue
        ungrounded.append(n)

    return {
        "pass": not ungrounded,
        "numbers_checked": len(found),
        "candidate_values": len(raw),
        "ungrounded": sorted(set(ungrounded))[:8],
    }


def score_routing(response: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    expected = {a.replace("_agent", "") for a in case.get("expected_agent", [])}
    actual = set(response.get("agents_consulted", []))
    intent_ok = True
    if case.get("expected_intent"):
        intent_ok = response.get("routing", {}).get("intent") == case["expected_intent"]

    focus_ok = True
    if case.get("expected_focus_lifts"):
        focus_ok = (set(response.get("routing", {}).get("focus_lifts", []))
                    == set(case["expected_focus_lifts"]))

    return {
        "pass": expected == actual and intent_ok and focus_ok,
        "expected_agents": sorted(expected),
        "actual_agents": sorted(actual),
        "expected_intent": case.get("expected_intent"),
        "actual_intent": response.get("routing", {}).get("intent"),
        "focus_ok": focus_ok,
    }


def score_numerical_accuracy(response: dict[str, Any], case: dict[str, Any],
                             snapshot: dict[str, Any]) -> dict[str, Any]:
    """Are the specific metrics this question hinges on actually cited?

    Checked by looking for each metric's computed *value* in the response text,
    not its variable name — a response that says "+3.4% over 30 days" has cited
    e1rm_change_30d_pct even though it never uses that identifier.
    """
    wanted = case.get("important_evidence", [])
    if not wanted:
        return {"pass": True, "expected": [], "missing": [], "note": "No specific metrics required."}

    text = _response_text(response).lower()
    values_by_key: dict[str, list[float]] = {}

    def index(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    values_by_key.setdefault(k, []).append(float(v))
                else:
                    index(v)
        elif isinstance(obj, list):
            for v in obj:
                index(v)

    index(snapshot)

    missing: list[str] = []
    for key in wanted:
        candidates = values_by_key.get(key, [])
        # Some expected keys are families (e.g. "preworkout_carbs" appears under
        # several comparison shapes), so match on any key containing the name.
        if not candidates:
            for k, vals in values_by_key.items():
                if key in k:
                    candidates.extend(vals)
        if not candidates:
            missing.append(f"{key} (not present in snapshot)")
            continue
        if not any(_value_in_text(v, text) for v in candidates):
            missing.append(key)

    return {"pass": not missing, "expected": wanted, "missing": missing}


def _value_in_text(value: float, text: str) -> bool:
    for form in {f"{value:.0f}", f"{value:.1f}", f"{value:.2f}",
                 f"{abs(value):.0f}", f"{abs(value):.1f}", f"{abs(value):.2f}"}:
        if form in text:
            return True
    return False


def score_uncertainty(response: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []

    conf = (response.get("confidence") or "").lower()
    allowed = case.get("allowed_confidence")
    if allowed and conf not in allowed:
        issues.append(f"confidence '{conf}' outside allowed {allowed}")

    text = _response_text(response).lower()
    for phrase in case.get("forbidden_phrases", []):
        if phrase.lower() in text:
            issues.append(f"causal/overclaiming phrase present: '{phrase}'")

    if re.search(r"\b\d{1,3}\s?%\s?(confiden|certain|sure)", text):
        issues.append("fabricated confidence percentage")

    if case.get("expect_insufficient_evidence"):
        markers = ["insufficient", "not enough", "too few", "needed to",
                   "cannot", "would be guesswork", "not yet meaningful"]
        if not any(m in text for m in markers):
            issues.append("expected an explicit insufficient-evidence statement")

    if case.get("expect_ruled_out") and not response.get("ruled_out"):
        issues.append("expected stable inputs to be explicitly ruled out")

    return {"pass": not issues, "issues": issues, "confidence": conf}


def score_actionability(response: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    action = response.get("next_action") or {}

    if case.get("expect_action"):
        if not action.get("action"):
            issues.append("no next action provided")
        if not action.get("detail"):
            issues.append("action has no concrete detail")
    if case.get("expect_reassess") and not response.get("reassess"):
        issues.append("no reassessment trigger provided")

    text = (f"{action.get('action', '')} {action.get('detail', '')}").lower()

    if case.get("expect_smallest_intervention"):
        escalations = ["increase your calorie target", "raise the calorie target",
                       "add 300", "add 400", "eat significantly more"]
        if any(e in text for e in escalations):
            issues.append("escalated to a calorie-target change when a smaller step was available")
        if not action.get("hold_constant"):
            issues.append("no hold-constant set, so the experiment would not be interpretable")

    if case.get("expect_no_intervention"):
        prescriptive = ["increase pre-workout", "raise the calorie", "increase your calorie",
                        "add 150", "add 200"]
        if any(p in text for p in prescriptive):
            issues.append("prescribed an intervention despite insufficient evidence")

    return {"pass": not issues, "issues": issues, "action": action.get("action")}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
DIMENSIONS = ("routing", "groundedness", "numerical_accuracy",
              "appropriate_uncertainty", "actionability")


def run_case(case: dict[str, Any], snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    snapshot = snapshots["sparse" if case.get("dataset") == "sparse" else "main"]
    response = ask(case["question"], snapshot)

    scores = {
        "routing": score_routing(response, case),
        "groundedness": score_groundedness(response, snapshot),
        "numerical_accuracy": score_numerical_accuracy(response, case, snapshot),
        "appropriate_uncertainty": score_uncertainty(response, case),
        "actionability": score_actionability(response, case),
    }
    passed = sum(1 for d in DIMENSIONS if scores[d]["pass"])

    return {
        "id": case["id"],
        "question": case["question"],
        "dataset": case.get("dataset", "main"),
        "reasoning_path": response.get("path"),
        "scores": scores,
        "dimensions_passed": passed,
        "dimensions_total": len(DIMENSIONS),
        "pass": passed == len(DIMENSIONS),
        "answer": response.get("answer"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Strength Intelligence eval suite.")
    parser.add_argument("--case", help="Run a single case by id.")
    parser.add_argument("--verbose", action="store_true", help="Show per-dimension detail.")
    parser.add_argument("--no-save", action="store_true", help="Do not write a results file.")
    args = parser.parse_args()

    spec = json.loads(CASES_PATH.read_text())
    cases = spec["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"No case with id '{args.case}'.")
            return 2

    snapshots = {"main": build_snapshot(load_dataset()), "sparse": _sparse_snapshot()}

    path_label = f"llm ({model_name()})" if llm_enabled() else "deterministic (no API key set)"
    print(f"\nStrength Intelligence — eval suite")
    print(f"reasoning path: {path_label}")
    print(f"data through:   {snapshots['main']['as_of']}")
    print("=" * 78)

    results = [run_case(c, snapshots) for c in cases]

    for r in results:
        mark = "PASS" if r["pass"] else "FAIL"
        print(f"\n[{mark}] {r['id']}  ({r['dimensions_passed']}/{r['dimensions_total']} dimensions)")
        print(f"       Q: {r['question']}")
        for dim in DIMENSIONS:
            s = r["scores"][dim]
            flag = "ok  " if s["pass"] else "FAIL"
            detail = ""
            if not s["pass"]:
                if dim == "routing":
                    detail = (f"expected {s['expected_agents']}/{s['expected_intent']}, "
                              f"got {s['actual_agents']}/{s['actual_intent']}")
                elif dim == "groundedness":
                    detail = f"ungrounded numbers: {s['ungrounded']}"
                elif dim == "numerical_accuracy":
                    detail = f"missing: {s['missing']}"
                else:
                    detail = "; ".join(s.get("issues", []))
            elif args.verbose:
                if dim == "groundedness":
                    detail = f"{s['numbers_checked']} numbers verified against snapshot"
                elif dim == "appropriate_uncertainty":
                    detail = f"confidence: {s['confidence']}"
                elif dim == "actionability":
                    detail = f"action: {s['action']}"
            print(f"       {flag} {dim}{' — ' + detail if detail else ''}")
        if args.verbose:
            print(f"       answer: {r['answer'][:220]}")

    # Aggregate
    print("\n" + "=" * 78)
    total = len(results)
    full_pass = sum(1 for r in results if r["pass"])
    print(f"cases fully passing: {full_pass}/{total}")
    print("per-dimension pass rate:")
    for dim in DIMENSIONS:
        n = sum(1 for r in results if r["scores"][dim]["pass"])
        bar = "#" * round(20 * n / total)
        print(f"  {dim:24} {n}/{total}  {bar}")

    if not args.no_save:
        RESULTS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        payload = {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "reasoning_path": "llm" if llm_enabled() else "deterministic",
            "model": model_name() if llm_enabled() else None,
            "data_as_of": snapshots["main"]["as_of"],
            "cases_passing": full_pass,
            "cases_total": total,
            "per_dimension": {
                dim: sum(1 for r in results if r["scores"][dim]["pass"]) for dim in DIMENSIONS
            },
            "results": results,
        }
        out = RESULTS_DIR / f"eval_{stamp}.json"
        out.write_text(json.dumps(payload, indent=2, default=str))
        latest = RESULTS_DIR / "latest.json"
        latest.write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nresults written to {out.relative_to(ROOT)} (and results/latest.json)")

    return 0 if full_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
