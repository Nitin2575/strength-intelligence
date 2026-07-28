-- Strength Intelligence MkII
-- Identify whether each exercise improved compared with its previous session.

WITH exercise_sessions AS (
    SELECT
        ws.date,
        sets.exercise,
        SUM(sets.weight_lb * sets.reps) AS session_volume,
        MAX(sets.weight_lb) AS top_weight,
        AVG(sets.rpe) AS average_rpe
    FROM workout_sessions ws
    JOIN workout_sets sets
        ON ws.session_id = sets.session_id
    GROUP BY
        ws.date,
        sets.exercise
),

with_previous AS (
    SELECT
        date,
        exercise,
        session_volume,
        top_weight,
        average_rpe,
        LAG(session_volume) OVER (
            PARTITION BY exercise
            ORDER BY date
        ) AS previous_volume,
        LAG(top_weight) OVER (
            PARTITION BY exercise
            ORDER BY date
        ) AS previous_top_weight
    FROM exercise_sessions
)

SELECT
    date,
    exercise,
    session_volume,
    previous_volume,
    top_weight,
    previous_top_weight,
    average_rpe,
    CASE
        WHEN top_weight > previous_top_weight THEN 'load_progression'
        WHEN session_volume > previous_volume THEN 'volume_progression'
        WHEN top_weight = previous_top_weight
             AND session_volume = previous_volume THEN 'maintained'
        ELSE 'regressed'
    END AS progression_status
FROM with_previous
ORDER BY exercise, date;
