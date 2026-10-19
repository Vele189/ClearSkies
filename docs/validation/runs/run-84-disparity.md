# Disparity analysis

Run `84` analysed at 2026-10-19 11:00 UTC against methodology 0.4.0, ACS 2020-2024.

## How to read this

This is a reported result, not a validation target. There is no threshold it must meet. A weaker correlation than expected is a finding worth publishing, not a defect to fix, and no weight in the score may be adjusted on the strength of what is reported here.

Race and ethnicity are not inputs to the burden score. The score is built from emissions, modelled risk, facility proximity, compliance records, age structure and economic hardship; racial composition enters neither an indicator, nor a weight, nor a tiebreak, and the schema keeps it in a separate table that no scoring query reads. Any correlation reported here is therefore a property of the pollution and vulnerability data rather than an artifact of how the score was constructed. That is what makes it evidence: had race been an ingredient, the correlation would be guaranteed by construction and would prove nothing. See methodology sections 13.6 and 14.

## Correlations

| Cohort | Measure | Method | Coefficient | 95% CI | Fisher CI (independence assumed) |
|---|---|---|---|---|---|
| confident | Black population share | pearson | +0.373 | +0.211 to +0.490 | +0.348 to +0.397 |
| confident | Black population share | spearman | +0.378 | +0.197 to +0.508 | +0.353 to +0.402 |
| confident | people-of-colour share | pearson | +0.436 | +0.321 to +0.511 | +0.413 to +0.459 |
| confident | people-of-colour share | spearman | +0.448 | +0.328 to +0.525 | +0.425 to +0.471 |
| all_scored | Black population share | pearson | +0.376 | +0.218 to +0.489 | +0.352 to +0.400 |
| all_scored | Black population share | spearman | +0.383 | +0.203 to +0.509 | +0.359 to +0.406 |
| all_scored | people-of-colour share | pearson | +0.438 | +0.333 to +0.510 | +0.415 to +0.460 |
| all_scored | people-of-colour share | spearman | +0.451 | +0.337 to +0.524 | +0.429 to +0.473 |

## Top decile against the rest of the state

| Cohort | Measure | Top decile | Elsewhere | Difference | Ratio | 95% CI on ratio |
|---|---|---|---|---|---|---|
| confident | Black population share | 45.8% | 28.9% | +16.9 pp | 1.58 | 1.17 to 2.02 |
| confident | people-of-colour share | 62.6% | 42.4% | +20.2 pp | 1.48 | 1.28 to 1.69 |
| all_scored | Black population share | 45.7% | 28.2% | +17.6 pp | 1.62 | 1.19 to 2.08 |
| all_scored | people-of-colour share | 62.5% | 41.4% | +21.0 pp | 1.51 | 1.30 to 1.72 |

## Cohorts

| Cohort | Hexes | Population | Parishes | Effective n | What it is |
|---|---|---|---|---|---|
| confident | 15882 | 3928499 | 64 | 4643 | Scored hexes outside the insufficient confidence band. Reported. |
| all_scored | 19881 | 4137096 | 64 | 5106 | Every scored hex, including low-confidence ones. Sensitivity check. |

Excluded from `confident`:

- 3999 hexes in the insufficient confidence band, per section 12
