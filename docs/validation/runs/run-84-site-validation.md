# ClearSkies validation run

- Methodology version: 0.4.0
- Scores from: run 84
- Outcome: **FAIL**

## Primary gate: high-burden sites

Gating. 8 of 10 passed, 8 required: met.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| 1 Reserve / LaPlace | pass | 6 of 7 | 97.9 | 95.0 | best cell at the 97.9th percentile, at or above the 90th |
| 2 Welcome, 5th District | fail | 2 of 19 | 58.1 | 57.9 | best cell only reached the 58.1th percentile, short of the 90th; the site scored but did not rank |
| 3 Mossville | pass | 6 of 19 | 97.7 | 33.8 | best cell at the 97.7th percentile, at or above the 90th |
| 4 Alsen / North Baton Rouge | pass | 5 of 19 | 96.6 | 96.5 | best cell at the 96.6th percentile, at or above the 90th |
| 5 Norco | pass | 5 of 7 | 98.3 | 98.3 | best cell at the 98.3th percentile, at or above the 90th |
| 6 Plaquemine | pass | 14 of 19 | 99.4 | 95.5 | best cell at the 99.4th percentile, at or above the 90th |
| 7 Chalmette | pass | 7 of 7 | 94.1 | 90.7 | best cell at the 94.1th percentile, at or above the 90th |
| 8 Geismar | fail | 2 of 19 | 84.1 | 78.4 | best cell only reached the 84.1th percentile, short of the 90th; the site scored but did not rank |
| 9 Gordon Plaza, New Orleans | pass | 7 of 7 | 94.4 | 85.6 | best cell at the 94.4th percentile, at or above the 90th |
| 10 Port Allen / Brusly | pass | 13 of 19 | 96.8 | 96.0 | best cell at the 96.8th percentile, at or above the 90th |

## Negative controls

Gating. 1 of 4 passed, 4 required: NOT met.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| N1 Mandeville | pass | 7 of 7 | 34.4 | 29.5 | every scored cell below the 50th, the highest at 34.4 |
| N2 Old Metairie | fail | 7 of 7 | 95.5 | 92.2 | 7 of 7 scored cells reached the 50th percentile or above, the highest at 95.5; a control passes only if the score declines to flag any part of it |
| N3 Bocage | fail | 7 of 7 | 97.2 | 67.4 | 4 of 7 scored cells reached the 50th percentile or above, the highest at 97.2; a control passes only if the score declines to flag any part of it |
| N4 South Lafayette | fail | 7 of 7 | 51.4 | 27.3 | 1 of 7 scored cells reached the 50th percentile or above, the highest at 51.4; a control passes only if the score declines to flag any part of it |

## Stress case A: not a poverty map

Reported, not gating. 1 of 3 inside the expected range.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| SA1 Lake Providence | fail | 12 of 19 | 25.0 | 22.9 | highest cell at 25.0, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment |
| SA2 Tallulah | pass | 18 of 19 | 75.0 | 57.3 | highest cell at 75.0, inside the expected 40–75 |
| SA3 St. Joseph | fail | 5 of 19 | 38.5 | 33.3 | highest cell at 38.5, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment |

## Stress case B: not an emissions map

Reported, not gating. 3 of 3 inside the expected range.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| SB1 Alliance Refinery vicinity | pass | 2 of 19 | 30.7 | 30.2 | highest cell at 30.7, below the 90th as expected |
| SB2 Krotz Springs | pass | 4 of 19 | 51.7 | 51.2 | highest cell at 51.7, below the 90th as expected |
| SB3 Port Hudson mill vicinity | pass | 6 of 19 | 44.0 | 39.8 | highest cell at 44.0, below the 90th as expected |

## Sites that did not pass

- **2 Welcome, 5th District** (high_burden): best cell only reached the 58.1th percentile, short of the 90th; the site scored but did not rank
- **8 Geismar** (high_burden): best cell only reached the 84.1th percentile, short of the 90th; the site scored but did not rank
- **N2 Old Metairie** (negative_control): 7 of 7 scored cells reached the 50th percentile or above, the highest at 95.5; a control passes only if the score declines to flag any part of it
- **N3 Bocage** (negative_control): 4 of 7 scored cells reached the 50th percentile or above, the highest at 97.2; a control passes only if the score declines to flag any part of it
- **N4 South Lafayette** (negative_control): 1 of 7 scored cells reached the 50th percentile or above, the highest at 51.4; a control passes only if the score declines to flag any part of it
- **SA1 Lake Providence** (stress_not_a_poverty_map): highest cell at 25.0, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment
- **SA3 St. Joseph** (stress_not_a_poverty_map): highest cell at 38.5, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment

## If this run failed

Section 13.7 permits three responses: fix a defect in the code, fix a defect in the data handling, or revise the methodology with a rationale that stands independently of this outcome, then re-run every check from the beginning. Adjusting a weight because it makes a site pass is not one of them, and the validation set itself is never edited.
