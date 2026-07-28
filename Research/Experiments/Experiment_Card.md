# Experiment: Sleep and Session Performance

## Question

Does sleeping at least seven hours lead to better resistance-training sessions?

## Hypothesis

Sessions after at least seven hours of sleep will have a higher average performance score than sessions after less than seven hours.

## Groups

- **Control condition:** Sleep below seven hours
- **Comparison condition:** Sleep at least seven hours

## Primary Metric

Session Performance Score

## Supporting Metrics

- Plan completion
- Average RPE
- Total volume
- Number of failed sets

## Analysis Plan

1. Match Apple Health sleep records to workout dates.
2. Remove sessions with missing sleep data.
3. Compare average performance scores.
4. Control for exercise type and recent training load.
5. Report the effect size and uncertainty.
6. Avoid claiming causation from observational data alone.

## Example Result Format

| Condition | Sessions | Avg. Performance | Avg. Completion |
|---|---:|---:|---:|
| Under 7 hours | 18 | 0.96 | 84% |
| 7+ hours | 24 | 1.04 | 93% |

## Product Decision

If the pattern is meaningful and stable, show an exercise-specific message:

> Your pressing sessions have performed better after at least seven hours of sleep. Consider avoiding heavy progression attempts after shorter sleep nights.

## Limitation

Sleep may be related to other variables, including stress, workout timing, nutrition, and previous training load.
