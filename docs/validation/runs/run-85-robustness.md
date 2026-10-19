# ClearSkies robustness checks

- Methodology version: 0.5.0
- Scores from: run 85
- Hexes in the comparison universe: 16407
- Excluded as insufficient confidence: 3474
- Outcome: **FAIL**

## 13.5 Alternative specifications

Spearman rank correlation against the score as section 10 builds it. At least 0.85 is required of the gating variants.

| Specification | Gating | Correlation | Hexes compared | Notes |
|---|---|---|---|---|
| equal_weights | yes | 0.982 | 16407 | Environmental Effects weighted 1.0 rather than 0.5; rank correlation 0.982, at or above 0.85 |
| exposures_only | yes | 0.963 | 16407 | Pollution Burden from Exposures alone, Environmental Effects dropped; rank correlation 0.963, at or above 0.85 |
| additive | reported | 0.983 | 16407 | components added rather than multiplied; rank correlation 0.983. Reported, not gating: section 13.5 expects this to be low and treats it as informative, because section 3 rejects this model for making a different claim rather than a worse one |

## 13.5 Leave-one-indicator-out

Removing any single indicator must not move more than 10% of hexes by more than one decile.

| Indicator | Group | Moved > 1 decile | Share | Lost score | Group lost | Verdict |
|---|---|---|---|---|---|---|
| E1 | exposures | 349 of 16407 | 2.1% | 0 | 0 | within |
| E2 | exposures | 306 of 16407 | 1.9% | 0 | 0 | within |
| E3 | exposures | 972 of 16407 | 5.9% | 0 | 0 | within |
| E4 | exposures | 139 of 16407 | 0.8% | 0 | 0 | within |
| F1 | environmental_effects | 10 of 16407 | 0.1% | 0 | 0 | within |
| F2 | environmental_effects | 0 of 16407 | 0.0% | 0 | 0 | within |
| F3 | environmental_effects | 7 of 16407 | 0.0% | 0 | 0 | within |
| F4 | environmental_effects | 2 of 16407 | 0.0% | 0 | 0 | within |
| F5 | environmental_effects | 0 of 16407 | 0.0% | 0 | 0 | within |
| S1 | sensitive_populations | 2189 of 16407 | 13.3% | 0 | 0 | ABOVE THE BAR |
| S2 | sensitive_populations | 1580 of 16407 | 9.6% | 0 | 0 | within |
| S3 | sensitive_populations | 1624 of 16407 | 9.9% | 0 | 0 | within |
| P1 | socioeconomic_factors | 85 of 16407 | 0.5% | 0 | 0 | within |
| P2 | socioeconomic_factors | 101 of 16407 | 0.6% | 0 | 0 | within |
| P3 | socioeconomic_factors | 235 of 16407 | 1.4% | 0 | 0 | within |
| P4 | socioeconomic_factors | 145 of 16407 | 0.9% | 0 | 0 | within |
| P5 | socioeconomic_factors | 430 of 16407 | 2.6% | 0 | 0 | within |

## 13.5 Interpolation sensitivity

- Rank correlation: 0.991
- Hexes scored by both methods: 12031
- Scored only under dasymetric weighting: 4376
- Scored only under areal weighting: 0
- Moved more than one decile: 174 (1.4%)
- Largest decile move: 6
- Median absolute decile move: 0.0
- Median absolute score change: 0.586

areal weighting against dasymetric: rank correlation 0.991, 174 of 12031 shared hexes moved more than one decile; 4376 hexes scored only under dasymetric weighting and 0 only under areal, because the two disagree about which cells clear the 25-person line of section 5. Reported, not gating: section 13.5 asks this check to quantify how much the section 7 machinery changes, and section 7 argues for dasymetric weighting on grounds that do not depend on the answer

## If this run failed

Checks that did not clear: S1.

Section 13.7 permits three responses: fix a defect in the code, fix a defect in the data handling, or revise the methodology with a rationale that stands independently of this outcome, then re-run every check from the beginning. Moving the 0.85 or the 10% because a check missed them is not one of them. Section 13.5 is specific about the leave-one-out case: an indicator that fails is re-argued in the methodology paper, and the paper is where that argument has to stand.
