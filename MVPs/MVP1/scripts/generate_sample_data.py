"""Generates realistic sample data for Strength Intelligence.

Writes 90 days of workouts, nutrition, and daily context data ending on the
most recent Friday on or before today, so the "last 30 days" / "last 3
exposures" windows the analytics layer looks at always have something
interesting to say.

The narrative baked into the numbers (on purpose, so the demo produces a
real insight instead of a scripted one):
  - Body weight drifts down ~6-7 lb over 90 days (a real but moderate cut).
  - Bench Press e1RM climbs steadily for ~10 weeks, then goes flat over the
    last ~3 exposures.
  - Pre-workout carbs before Bench sessions were meaningfully higher during
    the progressing phase than during the recent plateau phase.
  - Squat keeps progressing. Romanian Deadlift holds roughly flat all along
    (a true maintenance lift, not a plateau -- nothing "changed" for it).
  - Sleep stays roughly stable throughout, so it reads as a stable input,
    not a confound.

Re-run this script any time to regenerate fresh sample data:
    python scripts/generate_sample_data.py

To use your own data instead, just replace the three CSVs in data/ and
data/profile.json with the same column names -- see data/README.md.
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DAYS = 90

# Anchor the dataset's last day to "today" so a freshly generated dataset
# always looks current. The analytics layer treats the latest date *in the
# data* as "now" -- not the wall-clock date -- so this stays correct even if
# the app is run again later without regenerating data.
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=DAYS - 1)


def epley_1rm(weight: float, reps: int) -> float:
    return weight * (1 + reps / 30)


def weight_for_target_1rm(target_1rm: float, reps: int, increment: float = 2.5) -> float:
    raw = target_1rm / (1 + reps / 30)
    return round(raw / increment) * increment


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# --------------------------------------------------------------------------- #
# Training schedule: Mon = Bench (heavy) + OHP, Wed = Squat + RDL,
# Fri = Bench (volume) + RDL. ~10% chance a session is skipped, like real life.
# --------------------------------------------------------------------------- #
def build_schedule() -> list[tuple[date, str]]:
    sessions: list[tuple[date, str]] = []
    for i in range(DAYS):
        d = START_DATE + timedelta(days=i)
        wd = d.weekday()  # Mon=0 ... Sun=6
        if wd == 0:
            sessions.append((d, "push_heavy"))
        elif wd == 2:
            sessions.append((d, "legs"))
        elif wd == 4:
            sessions.append((d, "push_volume"))
    return sessions


SCHEDULE = build_schedule()


def days_ago(d: date) -> int:
    return (END_DATE - d).days


workout_rows: list[dict] = []
nutrition_extra: dict[date, dict] = {}  # date -> preworkout fields + workout_time

WORKOUT_TIME_BY_TYPE = {"push_heavy": "07:15", "push_volume": "17:30", "legs": "07:15"}

for d, session_type in SCHEDULE:
    if random.random() < 0.08:
        continue  # skipped session

    da = days_ago(d)  # 0 = today, 89 = 90 days ago
    t = 1 - da / (DAYS - 1)  # 0 -> start of window, 1 -> today

    # ---- Bench Press: progress for ~60 days, then plateau over the last ~3 exposures.
    if session_type in ("push_heavy", "push_volume"):
        if da <= 14:
            bench_1rm = 219.0 + random.uniform(-1.6, 1.6)  # the plateau: flat, small noise
        elif da <= 30:
            bench_1rm = lerp(209, 219, 1 - (da - 14) / 16) + random.uniform(-1.2, 1.2)
        else:
            bench_1rm = lerp(180, 209, 1 - (da - 30) / (DAYS - 1 - 30))
            bench_1rm += random.uniform(-2.0, 2.0)
        bench_reps = random.choice([4, 5]) if session_type == "push_heavy" else random.choice([6, 7, 8])
        bench_weight = weight_for_target_1rm(bench_1rm, bench_reps)
        bench_rpe = round(random.uniform(8.5, 9.5) * 2) / 2 if da <= 12 else round(random.uniform(6.5, 8.5) * 2) / 2
        workout_rows.append({
            "date": d.isoformat(), "exercise": "Bench Press", "sets": random.choice([3, 4]),
            "reps": bench_reps, "weight": bench_weight, "rpe": bench_rpe,
        })

        # Pre-workout carbs: plentiful during the progressing phase, scarce recently.
        if da <= 14:
            preworkout_carbs = round(random.uniform(24, 38))
            preworkout_protein = round(random.uniform(12, 20))
        else:
            preworkout_carbs = round(random.uniform(58, 78))
            preworkout_protein = round(random.uniform(18, 28))
        nutrition_extra[d] = {
            "preworkout_carbs": preworkout_carbs,
            "preworkout_protein": preworkout_protein,
            "workout_time": WORKOUT_TIME_BY_TYPE[session_type],
        }

    # ---- Overhead Press: modest steady progression, once a week.
    if session_type == "push_heavy":
        # OHP is also a push lift, so it flattens alongside Bench in the recent window.
        if da <= 14:
            ohp_1rm = 95.0 + random.uniform(-0.9, 0.9)
        else:
            ohp_1rm = lerp(87, 95, 1 - (da - 14) / (DAYS - 1 - 14)) + random.uniform(-1.0, 1.0)
        ohp_reps = random.choice([5, 6])
        ohp_weight = weight_for_target_1rm(ohp_1rm, ohp_reps)
        workout_rows.append({
            "date": d.isoformat(), "exercise": "Overhead Press", "sets": 3,
            "reps": ohp_reps, "weight": ohp_weight,
            "rpe": round(random.uniform(7.0, 8.5) * 2) / 2,
        })

    # ---- Squat: steady progression the whole window, once a week.
    if session_type == "legs":
        squat_1rm = lerp(232, 258, t) + random.uniform(-2.0, 2.0)
        squat_reps = random.choice([3, 4, 5])
        squat_weight = weight_for_target_1rm(squat_1rm, squat_reps)
        workout_rows.append({
            "date": d.isoformat(), "exercise": "Squat", "sets": random.choice([3, 4]),
            "reps": squat_reps, "weight": squat_weight,
            "rpe": round(random.uniform(7.5, 9.0) * 2) / 2,
        })
        if d not in nutrition_extra:
            nutrition_extra[d] = {
                "preworkout_carbs": round(random.uniform(45, 70)),
                "preworkout_protein": round(random.uniform(15, 25)),
                "workout_time": WORKOUT_TIME_BY_TYPE["legs"],
            }

    # ---- Romanian Deadlift: flat maintenance lift, twice a week, tiny noise only.
    if session_type in ("legs", "push_volume"):
        rdl_1rm = 158 + random.uniform(-3.5, 3.5)
        rdl_reps = random.choice([6, 7, 8])
        rdl_weight = weight_for_target_1rm(rdl_1rm, rdl_reps)
        workout_rows.append({
            "date": d.isoformat(), "exercise": "Romanian Deadlift", "sets": 3,
            "reps": rdl_reps, "weight": rdl_weight,
            "rpe": round(random.uniform(6.5, 8.0) * 2) / 2,
        })

workout_rows.sort(key=lambda r: (r["date"], r["exercise"]))

# --------------------------------------------------------------------------- #
# Body weight: gradual decline, ~-0.75 lb/week on average, daily water-weight noise.
# --------------------------------------------------------------------------- #
context_rows: list[dict] = []
START_WEIGHT = 155.0
END_WEIGHT = 148.4

for i in range(DAYS):
    d = START_DATE + timedelta(days=i)
    t = i / (DAYS - 1)
    trend_weight = lerp(START_WEIGHT, END_WEIGHT, t)
    body_weight = round(trend_weight + random.uniform(-0.9, 0.9), 1)

    wd = d.weekday()
    base_sleep = 7.2 if wd < 5 else 7.6
    sleep_hours = round(max(4.5, min(9.0, random.gauss(base_sleep, 0.5))), 1)

    base_steps = 8600 if wd < 5 else 7200
    steps = max(2000, round(random.gauss(base_steps, 1400)))

    context_rows.append({
        "date": d.isoformat(), "body_weight": body_weight,
        "sleep_hours": sleep_hours, "steps": steps,
    })

# --------------------------------------------------------------------------- #
# Nutrition: calories/macros hover near target with normal day-to-day noise;
# weekends run a bit higher. Pre-workout fields come from nutrition_extra.
# --------------------------------------------------------------------------- #
CAL_TARGET, PROTEIN_TARGET, CARB_TARGET, FAT_TARGET = 2200, 170, 210, 76

nutrition_rows: list[dict] = []
for i in range(DAYS):
    d = START_DATE + timedelta(days=i)
    wd = d.weekday()
    weekend_bump = 220 if wd >= 5 else 0

    calories = round(random.gauss(CAL_TARGET + weekend_bump, 130))
    protein = round(max(90, random.gauss(PROTEIN_TARGET, 14)))
    fat = round(max(35, random.gauss(FAT_TARGET, 9)))
    remaining_kcal = max(400, calories - protein * 4 - fat * 9)
    carbs = round(remaining_kcal / 4)

    row = {
        "date": d.isoformat(), "calories": calories, "protein": protein,
        "carbs": carbs, "fat": fat, "preworkout_carbs": "", "preworkout_protein": "",
        "workout_time": "",
    }
    extra = nutrition_extra.get(d)
    if extra:
        row.update({k: v for k, v in extra.items()})
    nutrition_rows.append(row)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows):>4} rows -> {path.relative_to(DATA_DIR.parent)}")


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    write_csv(DATA_DIR / "workouts.csv", workout_rows, ["date", "exercise", "sets", "reps", "weight", "rpe"])
    write_csv(DATA_DIR / "nutrition.csv", nutrition_rows,
               ["date", "calories", "protein", "carbs", "fat", "preworkout_carbs", "preworkout_protein", "workout_time"])
    write_csv(DATA_DIR / "daily_context.csv", context_rows, ["date", "body_weight", "sleep_hours", "steps"])
    print(f"date range: {START_DATE} -> {END_DATE}")
