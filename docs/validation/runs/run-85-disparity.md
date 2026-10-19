# Disparity analysis

Run `85` analysed at 2026-10-19 11:34 UTC against methodology 0.5.0, ACS 2020-2024.

## How to read this

This is a reported result, not a validation target. There is no threshold it must meet. A weaker correlation than expected is a finding worth publishing, not a defect to fix, and no weight in the score may be adjusted on the strength of what is reported here.

Race and ethnicity are not inputs to the burden score. The score is built from emissions, modelled risk, facility proximity, compliance records, age structure and economic hardship; racial composition enters neither an indicator, nor a weight, nor a tiebreak, and the schema keeps it in a separate table that no scoring query reads. Any correlation reported here is therefore a property of the pollution and vulnerability data rather than an artifact of how the score was constructed. That is what makes it evidence: had race been an ingredient, the correlation would be guaranteed by construction and would prove nothing. See methodology sections 13.6 and 14.

## Correlations

| Cohort | Measure | Method | Coefficient | 95% CI | Fisher CI (independence assumed) |
|---|---|---|---|---|---|
| confident | Black population share | pearson | +0.435 | +0.278 to +0.547 | +0.412 to +0.458 |
| confident | Black population share | spearman | +0.450 | +0.280 to +0.574 | +0.427 to +0.473 |
| confident | people-of-colour share | pearson | +0.494 | +0.382 to +0.568 | +0.472 to +0.515 |
| confident | people-of-colour share | spearman | +0.511 | +0.390 to +0.583 | +0.489 to +0.532 |
| all_scored | Black population share | pearson | +0.434 | +0.282 to +0.546 | +0.412 to +0.456 |
| all_scored | Black population share | spearman | +0.450 | +0.279 to +0.569 | +0.428 to +0.471 |
| all_scored | people-of-colour share | pearson | +0.491 | +0.386 to +0.561 | +0.470 to +0.512 |
| all_scored | people-of-colour share | spearman | +0.508 | +0.394 to +0.577 | +0.488 to +0.528 |

## Top decile against the rest of the state

| Cohort | Measure | Top decile | Elsewhere | Difference | Ratio | 95% CI on ratio |
|---|---|---|---|---|---|---|
| confident | Black population share | 50.8% | 27.8% | +23.0 pp | 1.83 | 1.38 to 2.25 |
| confident | people-of-colour share | 66.2% | 41.7% | +24.6 pp | 1.59 | 1.37 to 1.80 |
| all_scored | Black population share | 50.7% | 27.3% | +23.4 pp | 1.86 | 1.39 to 2.28 |
| all_scored | people-of-colour share | 66.2% | 41.0% | +25.2 pp | 1.61 | 1.40 to 1.82 |

## Cohorts

| Cohort | Hexes | Population | Parishes | Effective n | What it is |
|---|---|---|---|---|---|
| confident | 16407 | 3966345 | 64 | 4719 | Scored hexes outside the insufficient confidence band. Reported. |
| all_scored | 19881 | 4137096 | 64 | 5106 | Every scored hex, including low-confidence ones. Sensitivity check. |

Excluded from `confident`:

- 3474 hexes in the insufficient confidence band, per section 12
