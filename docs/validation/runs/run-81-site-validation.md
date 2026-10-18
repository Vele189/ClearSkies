# ClearSkies validation run

- Methodology version: 0.2.0
- Scores from: run 81
- Outcome: **FAIL**

## Primary gate: high-burden sites

Gating. 8 of 10 passed, 8 required: met.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| 1 Reserve / LaPlace | pass | 6 of 7 | 98.1 | 95.4 | best cell at the 98.1th percentile, at or above the 90th |
| 2 Welcome, 5th District | fail | 2 of 19 | 60.6 | 60.4 | best cell only reached the 60.6th percentile, short of the 90th; the site scored but did not rank |
| 3 Mossville | pass | 6 of 19 | 97.6 | 35.0 | best cell at the 97.6th percentile, at or above the 90th |
| 4 Alsen / North Baton Rouge | pass | 5 of 19 | 96.3 | 96.1 | best cell at the 96.3th percentile, at or above the 90th |
| 5 Norco | pass | 5 of 7 | 98.6 | 98.6 | best cell at the 98.6th percentile, at or above the 90th |
| 6 Plaquemine | pass | 14 of 19 | 99.4 | 96.2 | best cell at the 99.4th percentile, at or above the 90th |
| 7 Chalmette | pass | 7 of 7 | 93.0 | 89.6 | best cell at the 93.0th percentile, at or above the 90th |
| 8 Geismar | fail | 2 of 19 | 85.6 | 81.0 | best cell only reached the 85.6th percentile, short of the 90th; the site scored but did not rank |
| 9 Gordon Plaza, New Orleans | pass | 7 of 7 | 93.1 | 84.1 | best cell at the 93.1th percentile, at or above the 90th |
| 10 Port Allen / Brusly | pass | 13 of 19 | 96.3 | 95.3 | best cell at the 96.3th percentile, at or above the 90th |

## Negative controls

Gating. 1 of 4 passed, 4 required: NOT met.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| N1 Mandeville | pass | 7 of 7 | 33.0 | 28.4 | every scored cell below the 50th, the highest at 33.0 |
| N2 Old Metairie | fail | 7 of 7 | 94.9 | 91.4 | 7 of 7 scored cells reached the 50th percentile or above, the highest at 94.9; a control passes only if the score declines to flag any part of it |
| N3 Bocage | fail | 7 of 7 | 96.8 | 67.2 | 4 of 7 scored cells reached the 50th percentile or above, the highest at 96.8; a control passes only if the score declines to flag any part of it |
| N4 South Lafayette | fail | 7 of 7 | 54.9 | 26.2 | 1 of 7 scored cells reached the 50th percentile or above, the highest at 54.9; a control passes only if the score declines to flag any part of it |

## Stress case A: not a poverty map

Reported, not gating. 0 of 3 inside the expected range.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| SA1 Lake Providence | fail | 12 of 19 | 24.0 | 21.9 | highest cell at 24.0, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment |
| SA2 Tallulah | fail | 18 of 19 | 75.0 | 57.8 | highest cell at 75.0, above the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment |
| SA3 St. Joseph | fail | 5 of 19 | 38.2 | 31.8 | highest cell at 38.2, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment |

## Stress case B: not an emissions map

Reported, not gating. 3 of 3 inside the expected range.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| SB1 Alliance Refinery vicinity | pass | 2 of 19 | 31.7 | 31.1 | highest cell at 31.7, below the 90th as expected |
| SB2 Krotz Springs | pass | 4 of 19 | 52.9 | 52.0 | highest cell at 52.9, below the 90th as expected |
| SB3 Port Hudson mill vicinity | pass | 5 of 19 | 37.6 | 36.5 | highest cell at 37.6, below the 90th as expected |

## Sites that did not pass

- **2 Welcome, 5th District** (high_burden): best cell only reached the 60.6th percentile, short of the 90th; the site scored but did not rank
- **8 Geismar** (high_burden): best cell only reached the 85.6th percentile, short of the 90th; the site scored but did not rank
- **N2 Old Metairie** (negative_control): 7 of 7 scored cells reached the 50th percentile or above, the highest at 94.9; a control passes only if the score declines to flag any part of it
- **N3 Bocage** (negative_control): 4 of 7 scored cells reached the 50th percentile or above, the highest at 96.8; a control passes only if the score declines to flag any part of it
- **N4 South Lafayette** (negative_control): 1 of 7 scored cells reached the 50th percentile or above, the highest at 54.9; a control passes only if the score declines to flag any part of it
- **SA1 Lake Providence** (stress_not_a_poverty_map): highest cell at 24.0, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment
- **SA2 Tallulah** (stress_not_a_poverty_map): highest cell at 75.0, above the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment
- **SA3 St. Joseph** (stress_not_a_poverty_map): highest cell at 38.2, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment

## If this run failed

Section 13.7 permits three responses: fix a defect in the code, fix a defect in the data handling, or revise the methodology with a rationale that stands independently of this outcome, then re-run every check from the beginning. Adjusting a weight because it makes a site pass is not one of them, and the validation set itself is never edited.
