# Strength Intelligence

Strength Intelligence is an agentic AI system designed to understand how training,
fueling, body weight, and recovery context interact with strength progression.

---

## Problem

Strength trackers tell users what they lifted.
Nutrition apps tell users what they ate.
Wearables tell users how they recovered.

But lifters still have to determine:

> "Why is my strength changing?"

Nothing connects those signals around the outcome that actually matters. Strength
Intelligence connects them around one dependent variable:

**Strength progression.**

Training, fueling, body weight, and recovery are treated as explanatory inputs.
The user's body-weight goal and calorie/macro targets are treated as constraints.
The clearest use case — and the one the sample data demonstrates — is *maintaining
or progressing strength while in a calorie deficit*.

---

## Quickstart

```bash
cd strength-intelligence
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_sample_data.py
python -m uvicorn app.server:app --port 8100
```

Open http://localhost:8100 and ask *"I'm currently cutting. Why has my bench stalled?"*

It runs with **zero setup and no API key**. Without a key, interpretation comes from
a deterministic reviewer instead of a model; every metric is byte-identical either
way, because no metric was ever the model's job. To enable model-written
interpretation:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

The dashboard labels which path produced the reasoning, so the distinction is never
ambiguous. Model defaults to `claude-sonnet-5`; override with
`STRENGTH_INTELLIGENCE_MODEL`.

Run the checks:

```bash
python -m pytest tests/ -q      # 21 analytics unit tests
python evals/run_evals.py -v    # 12 end-to-end eval cases
```

---

## System

```
data/workouts.csv ──────────► Strength Agent ──┐
data/nutrition.csv ─────────► Fueling Agent ───┤
data/daily_context.csv ─────► health context ──┤
data/profile.json ──────────► goals/constraints┤
                                               ▼
                              Strength Intelligence Orchestrator
                                               │
                     ┌─────────────────────────┼──────────────────────┐
                     ▼            ▼            ▼           ▼          ▼
                Observation  Explanation  Confidence  Recommendation  Reassessment
```

A question enters through **Ask Strength Intelligence**, is routed to the
specialists that can answer it, and always returns through the orchestrator — so
the experience is one coherent system, not three chatbots taking turns.

| Layer | Responsibility |
| --- | --- |
| `analytics/strength_metrics.py` | e1RM, volume, trends, PRs, trend classification |
| `analytics/nutrition_metrics.py` | Intake averages, target adherence, fueling↔performance comparisons |
| `analytics/weight_metrics.py` | Smoothed weight, observed vs intended rate of change |
| `analytics/context_metrics.py` | Sleep, steps, training frequency — and their *stability* |
| `analytics/snapshot.py` | Assembles the one structured object agents reason over |
| `agents/strength_agent.py` | Interprets strength metrics |
| `agents/fueling_agent.py` | Interprets fueling, adherence, weight trajectory |
| `agents/orchestrator.py` | Reconciles specialists into one answer |
| `agents/router.py` | Question → agents + intent + focus lifts |
| `agents/evidence.py` | Confidence derived from data coverage |
| `prompts/` | System prompts, with grounding and language rules shared |
| `evals/` | Test cases and scoring runner |

---

## Design Principle

> **Code calculates. AI interprets.**

Every quantitative claim is computed deterministically in Python *before* any model
is invoked. Agents receive the structured output of the analytics layer — never raw
CSV rows. The model's job is interpretation, evidence synthesis, explanation,
uncertainty, and recommendation generation.

This separation is not stylistic. It buys four things:

1. **No hallucinated statistics.** A number that was never computed cannot be
   cited. The eval suite enforces this mechanically (see Evaluation).
2. **Reproducibility.** The same data produces the same trend verdict every time.
   "Is my bench progressing?" is a statistical question, and statistical questions
   should not have temperature.
3. **Testability.** `lift_summary()` is a pure function over a DataFrame, so edge
   cases get unit tests rather than prompt tweaks.
4. **Auditability.** When a recommendation looks wrong, the arithmetic and the
   interpretation fail in different files.

Two judgments deliberately live in code rather than in a prompt, because both must
be reproducible:

**Trend classification.** Whether a lift is progressing, maintaining, regressing,
or stalled is decided by comparing a change against *that lift's own measured noise
floor* (the residual coefficient of variation around its trend line). A 2% move on
a lift that swings 4% between sessions is noise; the same move on a lift that
swings 0.6% is signal. The model receives the verdict plus the numbers behind it
and explains what it means — it does not get to overturn it.

**Confidence.** Confidence is derived from evidence coverage — how many comparable
sessions actually underpin a claim — and handed to the model as a *ceiling* it may
lower but never raise. Fluency is not evidence, and an observational association in
one person's data never earns "high".

A worked example of why this matters: detecting a *stall* compares the recent rate
of change (lb/week) against the 30-day rate. An earlier version compared raw
percentages over a two-week window, which flagged every slowly-progressing lift as
stalled — a lift gaining 1.7% per month simply cannot show much movement across
three sessions. That is a statistics bug, and it was fixable precisely because the
logic was in `strength_metrics.py` and not buried in a prompt. `tests/` has a
regression test for it.

---

## Safety / Scientific Reasoning

**Correlation is not causation.** This is observational data from a single person,
with no control condition. The system is constrained to associative language —
"associated with", "consistent with", "may be contributing", "one plausible
explanation" — and prohibited from asserting that one variable caused another.

**Recommendations are evidence-ranked, and prefer the smallest intervention.**
The orchestrator implements an explicit intervention ladder:

| Rung | Condition | Action |
| --- | --- | --- |
| 0 | Not enough data to establish a trend | Keep logging; recommend nothing |
| 1 | Everything tracking as intended | No change |
| 2 | Recent stall, 30-day trend still positive | Small reversible experiment (redistribute existing calories) |
| 3 | Weight falling faster than intended | Correct the rate of loss first |
| 4 | Strength regressing **and** weight falling too fast | Revisit the calorie target |

One poor session never escalates. It is classified as a single poor session against
a stable trend, which is a different finding from a decline.

**Confidence reflects available evidence**, not the confidence of the prose. Levels
are `high` / `moderate` / `low`; fabricated percentages are prohibited and the eval
suite fails any response containing one.

**Insufficient data produces uncertainty rather than a fabricated explanation.**
Asked about a lift with two logged sessions, the system says so and names what to
collect, rather than assembling a plausible story. One eval case runs against a
deliberately sparse dataset purely to assert this, including that no intervention
is prescribed.

**Ruling things out is a first-class output.** The context layer reports whether
sleep, steps, and training frequency have been *stable*, because a stable input is
evidence *against* that input being the explanation. Narrowing the explanation
space is most of the analytical value.

**This is a performance-analysis prototype, not medical advice.** It does not
diagnose and does not discuss clinical conditions.

---

## Evaluation

The purpose of `evals/` is to demonstrate this is an evaluated AI product rather
than an LLM wrapper. `evals/test_cases.json` holds 12 cases; each is scored on
five dimensions:

| Dimension | What it checks |
| --- | --- |
| **Routing** | Were the expected agents invoked, with the right intent and focus lifts |
| **Groundedness** | Does every number in the response trace to a computed value |
| **Numerical accuracy** | Are the specific metrics the question hinges on actually cited |
| **Appropriate uncertainty** | Is confidence within bounds; is causal/overclaiming language absent |
| **Actionability** | Is there a concrete next action, a hold-constant set, and a reassessment trigger |

Groundedness is the load-bearing check. It extracts every number from the response
and verifies each appears in the snapshot the agents were actually given — so it
would catch a hallucinated statistic on either reasoning path.

Getting that check to *mean* something took two corrections worth recording. It
originally compared against the full snapshot with a proportional tolerance, and
passed a response claiming a 47.3% e1RM gain and 3.9 hours of sleep: with thousands
of candidate values spanning several orders of magnitude, nearly any number falls
within tolerance of *something*. It now compares against the slim snapshot the
agents receive (255 values, not thousands) using exact matching at 0/1/2-decimal
roundings. A suite that passes everything on the first run is not evidence of
correctness, so the scorers are themselves fault-injection tested — hallucinated
statistics, causal overclaiming, fabricated confidence percentages, over-escalated
recommendations, and acting on thin evidence are all confirmed to fail.

```
cases fully passing: 12/12
  routing                  12/12
  groundedness             12/12
  numerical_accuracy       12/12
  appropriate_uncertainty  12/12
  actionability            12/12
```

Results are written to `evals/results/` with a `latest.json` for diffing runs.

**A known limit, stated plainly:** groundedness verifies a cited number *exists*
among the computed values; it does not verify the number was attached to the right
claim. A response citing a real figure for the wrong metric can still pass. Closing
that gap needs claim-level attribution, which is the natural next step for the
harness.

---

## Data

Replace the sample data with your own by overwriting four files — same column
names, no code changes:

**`data/workouts.csv`** — `date, exercise, sets, reps, weight, rpe`
**`data/nutrition.csv`** — `date, calories, protein, carbs, fat, preworkout_carbs, preworkout_protein, workout_time`
**`data/daily_context.csv`** — `date, body_weight, sleep_hours, steps`
**`data/profile.json`** — `goal_type` (`cut`/`maintain`/`gain`), `starting_weight`,
`target_weight`, `target_rate_of_change`, `calorie_target`, `protein_target`,
`carb_target`, `fat_target`, `key_lifts`, `session_types`

Blank cells are treated as missing, not zero, and propagate into
insufficient-evidence findings rather than skewing an average. The dataset is
re-read per request, so refreshing the page picks up edited CSVs. Analysis windows
are measured from the latest date *in the data*, not the wall clock, so a stale
dataset stays interpretable.

`scripts/generate_sample_data.py` writes 90 days of realistic data containing:
body weight declining ~0.6 lb/week, bench e1RM up ~3.4% over 30 days, a bench
plateau across the most recent exposures, pre-workout carbohydrate ~49% lower
during those recent sessions, squat still progressing with fueling unchanged, and
stable sleep. The demo insight is *derived from these numbers, not hardcoded* —
regenerate with a different seed and the narrative shifts with the data.

---

## Future Direction

- Apple Health and wearable integrations (WHOOP, Oura) to replace manual CSVs
- Automated workout logging
- More sophisticated longitudinal modelling (mixed-effects, per-lift fatigue curves)
- Travel / off-routine adaptation
- Restaurant and menu recommendations from goals, macros, training schedule, and
  dietary constraints
- Claim-level attribution in the eval harness

---

## License

Prototype / portfolio project.
