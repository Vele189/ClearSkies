# ClearSkies robustness checks

- Methodology version: 0.2.0
- Scores from: run 81
- Hexes in the comparison universe: 15811
- Excluded as insufficient confidence: 4070
- Outcome: **FAIL**

## 13.5 Alternative specifications

Spearman rank correlation against the score as section 10 builds it. At least 0.85 is required of the gating variants.

| Specification | Gating | Correlation | Hexes compared | Notes |
|---|---|---|---|---|
| equal_weights | yes | 0.980 | 15811 | Environmental Effects weighted 1.0 rather than 0.5; rank correlation 0.980, at or above 0.85 |
| exposures_only | yes | 0.958 | 15811 | Pollution Burden from Exposures alone, Environmental Effects dropped; rank correlation 0.958, at or above 0.85 |
| additive | reported | 0.982 | 15811 | components added rather than multiplied; rank correlation 0.982. Reported, not gating: section 13.5 expects this to be low and treats it as informative, because section 3 rejects this model for making a different claim rather than a worse one |

## 13.5 Leave-one-indicator-out

Removing any single indicator must not move more than 10% of hexes by more than one decile.

| Indicator | Group | Moved > 1 decile | Share | Lost score | Group lost | Verdict |
|---|---|---|---|---|---|---|
| E1 | exposures | 320 of 15811 | 2.0% | 0 | 0 | within |
| E2 | exposures | 317 of 15811 | 2.0% | 0 | 0 | within |
| E3 | exposures | 1124 of 15811 | 7.1% | 0 | 0 | within |
| E4 | exposures | 131 of 15811 | 0.8% | 0 | 0 | within |
| F1 | environmental_effects | 22 of 15811 | 0.1% | 0 | 0 | within |
| F2 | environmental_effects | 0 of 15811 | 0.0% | 0 | 0 | within |
| F3 | environmental_effects | 53 of 15811 | 0.3% | 0 | 0 | within |
| F4 | environmental_effects | 13 of 15811 | 0.1% | 0 | 0 | within |
| S1 | sensitive_populations | 5002 of 15811 | 31.6% | 0 | 0 | ABOVE THE BAR |
| S2 | sensitive_populations | 5148 of 15811 | 32.6% | 0 | 0 | ABOVE THE BAR |
| P1 | socioeconomic_factors | 33 of 15811 | 0.2% | 0 | 1 | within |
| P2 | socioeconomic_factors | 94 of 15811 | 0.6% | 0 | 1 | within |
| P3 | socioeconomic_factors | 162 of 15811 | 1.0% | 0 | 1 | within |
| P4 | socioeconomic_factors | 116 of 15811 | 0.7% | 0 | 1 | within |
| P5 | socioeconomic_factors | 380 of 15811 | 2.4% | 0 | 0 | within |

## 13.5 Interpolation sensitivity

- Rank correlation: 0.987
- Hexes scored by both methods: 11747
- Scored only under dasymetric weighting: 4064
- Scored only under areal weighting: 0
- Moved more than one decile: 253 (2.2%)
- Largest decile move: 8
- Median absolute decile move: 0.0
- Median absolute score change: 0.549

areal weighting against dasymetric: rank correlation 0.987, 253 of 11747 shared hexes moved more than one decile; 4064 hexes scored only under dasymetric weighting and 0 only under areal, because the two disagree about which cells clear the 25-person line of section 5. Reported, not gating: section 13.5 asks this check to quantify how much the section 7 machinery changes, and section 7 argues for dasymetric weighting on grounds that do not depend on the answer

## If this run failed

Checks that did not clear: S1, S2.

Section 13.7 permits three responses: fix a defect in the code, fix a defect in the data handling, or revise the methodology with a rationale that stands independently of this outcome, then re-run every check from the beginning. Moving the 0.85 or the 10% because a check missed them is not one of them. Section 13.5 is specific about the leave-one-out case: an indicator that fails is re-argued in the methodology paper, and the paper is where that argument has to stand.
