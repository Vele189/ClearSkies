# ClearSkies validation run

- Methodology version: 0.5.0
- Scores from: run 85
- Outcome: **FAIL**

## Primary gate: high-burden sites

Gating. 8 of 10 passed, 8 required: met.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| 1 Reserve / LaPlace | pass | 6 of 7 | 98.6 | 96.3 | best cell at the 98.6th percentile, at or above the 90th |
| 2 Welcome, 5th District | fail | 4 of 19 | 87.9 | 37.7 | best cell only reached the 87.9th percentile, short of the 90th; the site scored but did not rank |
| 3 Mossville | pass | 6 of 19 | 96.9 | 39.6 | best cell at the 96.9th percentile, at or above the 90th |
| 4 Alsen / North Baton Rouge | pass | 5 of 19 | 98.7 | 98.6 | best cell at the 98.7th percentile, at or above the 90th |
| 5 Norco | pass | 5 of 7 | 98.8 | 98.8 | best cell at the 98.8th percentile, at or above the 90th |
| 6 Plaquemine | pass | 14 of 19 | 99.5 | 97.5 | best cell at the 99.5th percentile, at or above the 90th |
| 7 Chalmette | pass | 7 of 7 | 94.8 | 92.9 | best cell at the 94.8th percentile, at or above the 90th |
| 8 Geismar | fail | 2 of 19 | 65.1 | 56.5 | best cell only reached the 65.1th percentile, short of the 90th; the site scored but did not rank |
| 9 Gordon Plaza, New Orleans | pass | 7 of 7 | 92.4 | 86.8 | best cell at the 92.4th percentile, at or above the 90th |
| 10 Port Allen / Brusly | pass | 13 of 19 | 98.5 | 98.1 | best cell at the 98.5th percentile, at or above the 90th |

## Negative controls

Gating. 2 of 4 passed, 4 required: NOT met.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| N1 Mandeville | pass | 7 of 7 | 18.8 | 14.4 | every scored cell below the 50th, the highest at 18.8 |
| N2 Old Metairie | fail | 7 of 7 | 90.0 | 84.8 | 7 of 7 scored cells reached the 50th percentile or above, the highest at 90.0; a control passes only if the score declines to flag any part of it |
| N3 Bocage | fail | 7 of 7 | 93.4 | 59.0 | 4 of 7 scored cells reached the 50th percentile or above, the highest at 93.4; a control passes only if the score declines to flag any part of it |
| N4 South Lafayette | pass | 7 of 7 | 38.0 | 16.8 | every scored cell below the 50th, the highest at 38.0 |

## Stress case A: not a poverty map

Reported, not gating. 2 of 3 inside the expected range.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| SA1 Lake Providence | fail | 12 of 19 | 33.6 | 31.2 | highest cell at 33.6, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment |
| SA2 Tallulah | pass | 18 of 19 | 73.9 | 59.5 | highest cell at 73.9, inside the expected 40–75 |
| SA3 St. Joseph | pass | 5 of 19 | 50.6 | 46.7 | highest cell at 50.6, inside the expected 40–75 |

## Stress case B: not an emissions map

Reported, not gating. 3 of 3 inside the expected range.

| Site | Outcome | Cells scored | Best | Median | Notes |
|---|---|---|---|---|---|
| SB1 Alliance Refinery vicinity | pass | 2 of 19 | 21.3 | 20.9 | highest cell at 21.3, below the 90th as expected |
| SB2 Krotz Springs | pass | 4 of 19 | 60.3 | 59.9 | highest cell at 60.3, below the 90th as expected |
| SB3 Port Hudson mill vicinity | pass | 6 of 19 | 47.2 | 44.4 | highest cell at 47.2, below the 90th as expected |

## Sites that did not pass

- **2 Welcome, 5th District** (high_burden): best cell only reached the 87.9th percentile, short of the 90th; the site scored but did not rank
- **8 Geismar** (high_burden): best cell only reached the 65.1th percentile, short of the 90th; the site scored but did not rank
- **N2 Old Metairie** (negative_control): 7 of 7 scored cells reached the 50th percentile or above, the highest at 90.0; a control passes only if the score declines to flag any part of it
- **N3 Bocage** (negative_control): 4 of 7 scored cells reached the 50th percentile or above, the highest at 93.4; a control passes only if the score declines to flag any part of it
- **SA1 Lake Providence** (stress_not_a_poverty_map): highest cell at 33.6, below the expected 40–75; reported, not gating, and section 13 asks for a documented investigation rather than an adjustment

## If this run failed

Section 13.7 permits three responses: fix a defect in the code, fix a defect in the data handling, or revise the methodology with a rationale that stands independently of this outcome, then re-run every check from the beginning. Adjusting a weight because it makes a site pass is not one of them, and the validation set itself is never edited.
