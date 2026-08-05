# Strength Intelligence

> **An AI system for understanding strength progression through the context of training, fueling, body weight, and recovery.**

Strength Intelligence explores a simple question:

## Am I actually getting stronger — and what is helping or limiting my progress?

Rather than treating workouts, nutrition, and recovery as separate dashboards, Strength Intelligence turns them into context for an AI agent that evaluates strength progression and produces grounded, actionable guidance.

---

## 🧠 The System

```text
                         ┌─────────────────────┐
                         │      USER GOAL      │
                         │                     │
                         │  Lose / Maintain /  │
                         │     Gain Weight     │
                         └──────────┬──────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────┐
│                          CONTEXT                              │
│                                                               │
│   🏋️ Training       🍚 Fueling       ⚖️ Body Weight          │
│                                                               │
│   Sets / Reps       Calories         Trend                    │
│   Load / Volume     Protein          Rate of Change           │
│   e1RM / RPE        Carbs            Goal                     │
│                     Meal Timing                               │
│                                                               │
│                     😴 Recovery                               │
│                     Sleep / Activity                          │
│                     Health Context                            │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │   STRENGTH AGENT    │
                     │                     │
                     │ Prompt + Context +  │
                     │ Tools + Knowledge   │
                     └──────────┬──────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │  STRENGTH INSIGHT   │
                     │                     │
                     │ Progressing?        │
                     │ Why?                │
                     │ What next?          │
                     └─────────────────────┘
```

### Core Principle

```text
Fueling ────────┐
Recovery ───────┼────► Strength Progression
Body Weight ────┤
Training ───────┘
```

**Strength progression is the output.**

Training, fueling, body-weight trajectory, and relevant recovery context provide the inputs used to interpret that output.

---

# 🤖 AI Product Architecture

Strength Intelligence is also an experiment in building **reliable AI product behavior**, not simply adding a chatbot to fitness data.

The development loop:

```text
┌──────────────────────┐
│ PRODUCT REQUIREMENT  │
│                      │
│ What should the AI   │
│ actually accomplish? │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│        AGENT         │
│                      │
│ Define responsibility│
│ and behavior         │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│       CONTEXT        │
│                      │
│ Give the agent only  │
│ relevant user data   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  PROMPT + KNOWLEDGE  │
│                      │
│ Instructions         │
│ Methods              │
│ Constraints          │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│     EVALUATIONS      │
│                      │
│ Does the agent behave│
│ correctly?           │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│       FAILURES       │
│                      │
│ Find where and why   │
│ behavior breaks      │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│      ITERATION       │
│                      │
│ Improve → Test →     │
│ Measure → Repeat     │
└──────────────────────┘
```

---

## 1. 🎯 Product Requirement

The initial requirement is intentionally narrow:

> **Help a lifter determine whether they are progressively overloading while operating within a calorie deficit, maintenance phase, or surplus — and explain what may be influencing that progression.**

The AI should answer three questions:

### Are you progressing?

Analyze load, repetitions, volume, estimated strength, and recent training history.

### Why?

Interpret performance using relevant fueling, body-weight, and recovery context.

### What should you do next?

Provide one clear, evidence-grounded next action.

---

## 2. 🤖 Strength Agent

The **Strength Agent** is responsible for interpreting the user's data.

```text
User Question
      │
      ▼
┌───────────────────┐
│   STRENGTH AGENT  │
├───────────────────┤
│ System Prompt     │
│ User Context      │
│ Training History  │
│ Fueling Context   │
│ Recovery Context  │
│ Knowledge         │
│ Tools             │
└─────────┬─────────┘
          │
          ▼
   Personalized
 Strength Insight
```

### Example

**User**

> Why has my bench press stalled this week?

**Agent Context**

```text
Bench Performance       ↓
Body Weight             ↓
Calories                Deficit
Protein                 On Target
Pre-Workout Carbs       ↓
Sleep                   Stable
Training Volume         Stable
```

**Desired Behavior**

The agent should identify plausible relationships without presenting correlation as causation and recommend the highest-value next action.

---

## 3. 🧩 Context

The agent should not receive every available datapoint.

It receives **relevant context for the current question.**

```text
                  USER QUESTION
                       │
                       ▼
                CONTEXT SELECTION
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       Training      Fueling     Recovery
          │            │            │
          └────────────┼────────────┘
                       │
                       ▼
                  Strength Agent
```

This keeps the system focused and reduces unnecessary context.

---

## 4. 📚 Knowledge

The agent is grounded using structured domain knowledge.

Examples include:

- Progressive overload principles
- Estimated 1RM methodology
- Training-volume interpretation
- Protein and carbohydrate guidance
- Pre/post-workout fueling principles
- Weight-loss / maintenance / surplus context
- Recovery considerations
- Known limitations of the available data

The goal is not for the model to simply **sound knowledgeable**.

The goal is for its recommendations to be **grounded, explainable, and appropriately uncertain.**

---

## 5. 🧪 Evaluations

AI behavior is tested against predefined scenarios.

```text
                 EVALUATION SUITE

┌────────────────┬────────────────┬────────────────┐
│ Progression    │ Fueling        │ Recovery       │
│ Tests          │ Tests          │ Tests          │
├────────────────┼────────────────┼────────────────┤
│ Plateau        │ Low Carbs      │ Poor Sleep     │
│ Regression     │ Low Protein    │ High Activity  │
│ PR             │ Meal Timing    │ Missing Data   │
│ Low Volume     │ Calorie Deficit│ Conflicts      │
└────────────────┴────────────────┴────────────────┘
```

### Example Evaluation

**Scenario**

```text
Goal:              Fat Loss
Calories:          Deficit
Weight Trend:      -0.8 lb/week
Protein:           On Target
Pre-Workout Carbs: Significantly Lower
Sleep:             Stable

BENCH PRESS

Week 1    185 × 8
Week 2    185 × 8
Week 3    185 × 7
Week 4    185 × 6
```

The evaluation checks whether the agent:

- [ ] Detects the negative strength trend
- [ ] Understands the calorie-deficit context
- [ ] Identifies reduced pre-workout carbohydrate availability as a possible contributor
- [ ] Avoids claiming causation
- [ ] Does not invent missing data
- [ ] Produces an actionable recommendation
- [ ] Communicates uncertainty appropriately

---

## 6. 📊 Evaluation Dimensions

Agent responses can be scored across several dimensions:

| Metric | Question |
|---|---|
| **Correctness** | Did it correctly interpret the data? |
| **Groundedness** | Are its claims supported by available context? |
| **Personalization** | Did it appropriately use user-specific data? |
| **Actionability** | Is there a useful next step? |
| **Uncertainty** | Did it avoid overclaiming? |
| **Safety** | Is the guidance appropriate? |
| **Hallucination** | Did it invent information? |

---

## 7. 🔁 Failure → Iteration

The goal isn't to build a perfect first prompt.

The goal is to build a **measurable improvement loop.**

```text
                    Agent v1
                        │
                        ▼
                    Evaluation
                        │
                        ▼
                 Failure Analysis
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
 Prompt Problem?   Missing Context?   Bad Knowledge?
        │               │                │
        └───────────────┼────────────────┘
                        │
                        ▼
                      Change
                        │
                        ▼
                    Agent v2
                        │
                        ▼
              Re-run Evaluations
                        │
                        ▼
                 Compare Results
                        │
                        ▼
              Improve → Repeat
```

Failure analysis asks:

- Was the prompt ambiguous?
- Was relevant context missing?
- Was irrelevant context included?
- Was the knowledge insufficient?
- Did a tool fail?
- Did the model overgeneralize?
- Was the evaluation itself poorly designed?

Every meaningful agent change can then be evaluated against the same test suite to identify both **improvements and regressions.**

---

# 🔄 The Intelligence Loop

Most fitness products answer:

> **What happened?**

Strength Intelligence explores:

> **What happened, what context may explain it, and what should I do next?**

```text
┌─────────────┐
│    DATA     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   CONTEXT   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│INTERPRETATION│
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   ACTION    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  NEW DATA   │
└──────┬──────┘
       │
       └──────────────► Repeat
```

---

# 🔬 Current Scope

**Strength Intelligence is an experimental AI product prototype.**

The current focus is deliberately on the intelligence layer.

```text
┌──────────────────────────────────────┐
│         CURRENT AI SYSTEM            │
├──────────────────────────────────────┤
│                                      │
│  ✓ Structured Strength Data          │
│  ✓ Fueling Context                   │
│  ✓ Body-Weight Context               │
│  ✓ Recovery Context                  │
│                                      │
│  ✓ Strength Agent                    │
│  ✓ Prompt Architecture               │
│  ✓ Knowledge Grounding               │
│                                      │
│  ✓ Evaluation Framework              │
│  ✓ Failure Analysis                  │
│  ✓ Agent Iteration                   │
│                                      │
├──────────────────────────────────────┤
│                                      │
│  → Consumer UI                       │
│  → Deeper Integrations               │
│  → Additional Agents                 │
│                                      │
└──────────────────────────────────────┘
```

The objective at this stage is **not to build every feature of a fitness application.**

It is to demonstrate how a focused AI system can turn fragmented health and performance data into **reliable, personalized, and testable intelligence.**

---

# 🔭 Long-Term Direction

Strength Intelligence could eventually understand relationships across:

```text
              ┌──────────────┐
              │   TRAINING   │
              └──────┬───────┘
                     │
                     ▼
┌────────────┐  ┌──────────────┐  ┌────────────┐
│  FUELING   │─►│   STRENGTH   │◄─│  RECOVERY  │
└────────────┘  │ INTELLIGENCE │  └────────────┘
                └──────┬───────┘
                       ▲
                       │
              ┌────────┴────────┐
              │   BODY WEIGHT   │
              │    + GOALS      │
              └─────────────────┘
```

The system should become more useful as longitudinal data accumulates, allowing it to distinguish between short-term noise and meaningful changes in performance.

---

## ⚠️ Disclaimer

Strength Intelligence is an experimental project exploring AI-assisted strength and performance analysis.

It is **not a medical device** and does not provide medical diagnosis or treatment recommendations.

---

<div align="center">

# Strength Intelligence

### Measure progression. Understand context. Decide what comes next.

**An exploration of AI-native health and performance products.**

</div>
