# Data

Replace these files with your own data using the same column names. No code
changes needed. Blank cells are treated as missing (not zero) and flow into
insufficient-evidence findings rather than skewing averages.

## workouts.csv
`date, exercise, sets, reps, weight, rpe`
One row per exercise per session. `rpe` is optional. Dates are `YYYY-MM-DD`.

## nutrition.csv
`date, calories, protein, carbs, fat, preworkout_carbs, preworkout_protein, workout_time`
One row per day. The `preworkout_*` and `workout_time` columns are only meaningful
on training days; leave them blank otherwise. Macros are grams.

## daily_context.csv
`date, body_weight, sleep_hours, steps`
One row per day. Daily scale noise is expected — body weight is smoothed to a
7-day average and the rate of change is a least-squares slope.

## profile.json
```json
{
  "goal_type": "cut",            // cut | maintain | gain
  "starting_weight": 155.0,
  "target_weight": 145.0,
  "target_rate_of_change": -0.75, // lb/week; negative on a cut
  "calorie_target": 2200,
  "protein_target": 170,
  "carb_target": 210,
  "fat_target": 76,
  "key_lifts": ["Bench Press", "Squat"],
  "session_types": { "push": ["Bench Press"], "legs": ["Squat"] }
}
```
`key_lifts` selects which exercises get tracked on the dashboard; if omitted, the
four most-logged exercises are used. Exercise names must match `workouts.csv`.

Regenerate the sample dataset any time with:
```bash
python scripts/generate_sample_data.py
```
