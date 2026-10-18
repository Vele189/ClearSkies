# Accuracy review: run 81, 2026-10-19

The §13 site gate and the §13.5 robustness checks re-run against the promoted
run, with a component-level diagnosis of every site that missed and a plan that
stays inside §13.7.

- **Run:** 81, methodology 0.2.0, promoted 2026-10-12, `dev-seed`
- **Reproduce:** `make export-run ARGS="--validation run.json --robustness values.json"`,
  then `make validate SCORES=run.json`, `make robustness VALUES=values.json`, and
  `api/.venv/bin/python scripts/diagnose_sites.py`
- **Generated output:** [runs/run-81-site-validation.md](runs/run-81-site-validation.md),
  [runs/run-81-robustness.md](runs/run-81-robustness.md)

`site-validation.md` and `robustness.md` still report run 11. Run 81 has
replaced it as the run the map serves, and its per-hex rows are the only ones
left in the database.

---

## 1. Scorecard

| Check | Gating | run 11 (2026-09-21) | **run 81 (now)** | Required |
|---|---|---|---|---|
| Primary sites in top decile | yes | 7 of 10 | **8 of 10, met** | 8 of 10 |
| Negative controls below 50th | yes | 2 of 4 | **1 of 4** | 4 of 4 |
| Stress A in 40–75 band | reported | 1 of 3 | 0 of 3 | – |
| Stress B below 90th | reported | 3 of 3 | 3 of 3 | – |
| Alt. specs, Spearman ≥ 0.85 | yes | pass (0.978 / 0.960) | pass (0.980 / 0.958) | 0.85 |
| Leave-one-out ≤ 10% moved | yes | 4 over (E1, E2, S1, S2) | **2 over (S1 31.6%, S2 32.6%)** | 10% |
| Interpolation sensitivity | reported | did not run | did not run | – |
| Confident hexes | – | 17,263 | **15,811** | – |

**Overall: FAIL.** The primary gate now passes and E1/E2 no longer dominate,
but the negative controls are worse and the confident universe has shrunk by
1,452 hexes. Under §13.7 none of these may be answered by moving a weight.

## 2. What moved between run 11 and run 81

| Site | run 11 | run 81 | Why |
|---|---|---|---|
| 7 Chalmette | 83.0 fail | 93.0 pass | Score change |
| 9 Gordon Plaza | 85.2 fail | 93.1 pass | Score change |
| 2 Welcome / 5th District | 91.0 pass | **60.6 fail** | Confidence, not score (§3.2) |
| N2 Old Metairie | 86.9 fail | 94.9 fail | Worse |
| N4 South Lafayette | 41.3 pass | **54.9 fail** | One cell crossed the median |

The commits between the two runs' SHAs (`c4689df`..`cd54bd9`) include AUD-05
("feed the scorer what the methodology specifies"), CP-02 (data defects) and
CP-03 (unobserved rows). Those are the candidates for both the gains and the
confidence loss. The run 11 rows are gone, so a cell-level diff is no longer
possible.

---

## 3. Where the model is not good, and why

### 3.1 In the industrial corridor, the rank is decided by demographics (negative controls)

This is the main defect. The pollution half saturates: Pollution Burden for
the whole corridor, Baton Rouge, and inner Jefferson Parish sits between 7 and
9.7 out of 10. Once that happens, Population Characteristics decides the order.

Among the 1,095 confident hexes with Pollution Burden ≥ 8, here is how each
indicator's percentile correlates with the final percentile:

| Tracks rank | r | | Does not | r |
|---|---|---|---|---|
| P4 unemployment | +0.58 | | F1 major-source proximity | −0.19 |
| **S1 under 5** | +0.49 | | F3 enforcement | −0.13 |
| P5 housing cost | +0.45 | | E1 cancer risk | −0.12 |
| E4 measured PM2.5 | +0.44 | | E3 TRI proximity | −0.10 |
| **S2 65 and over** | +0.35 | | E2 respiratory hazard | −0.06 |

The facility and air-toxics indicators carry no rank information at the top,
and slightly negative information. Two consequences:

- **Sensitive Populations is two thin age-share indicators.** S1 and S2 are
  anti-correlated statewide (r = −0.21), and §11 lets either one stand in for
  the whole subgroup, which is half of Population Characteristics. Leave-one-out
  moves 31.6% / 32.6% of the state for each. Affluent neighbourhoods with many
  older residents score as "sensitive". **Old Metairie:** S2 at the 92.5th
  percentile, sensitive mean 71–86, while poverty (P1 7.0) and education (P2
  13.6) are correctly low. The result is 82.8–94.9 on every cell.
  **Bocage:** the two cells that fail have sensitive means of 70 and 72. The
  cells that pass have 8–16. The pollution half is identical across all seven.
- **Bocage and Old Metairie really are near industry**, with E around 85 and
  61–65, and F around 85 and 80. The score is not wrong that the air there is
  worse. It is wrong to rank them as burdened as Reserve, because of how
  little the population half has to work with.

§13.5 already ruled out reweighting Environmental Effects (0.980 / 0.958), and
this data agrees: the problem is in what Population Characteristics measures.

### 3.2 Welcome fails on confidence, not on score

Seven of Welcome's cells score at the **91.4–94.2th percentile**, which is a
pass, but every one is in the Insufficient band (confidence 0.33–0.39), so §12
excludes them. The two cells left score 60.6.

| Term | Welcome cells | Statewide "high" mean |
|---|---|---|
| `c_spatial` | **0.05–0.11** | 0.72 |
| `c_monitor` | 0.33–0.36 (29 km to a monitor) | 0.98 |
| `c_coverage` | 0.92 | 1.00 |

This is a statewide pattern, not specific to Welcome:

| Residents per hex | Scored hexes | Mean `c_spatial` | Insufficient |
|---|---|---|---|
| 25–120 | 12,838 (65%) | 0.27 | **3,881** |
| 120–500 | 4,804 | 0.44–0.52 | 173 |
| 500+ | 2,239 | 0.52 | 16 |

95% of Insufficient hexes are sparsely populated cells that inherit identical
tract values. Run 11 had 2,618 Insufficient hexes and run 81 has 4,070. The
methodology did not change between them, so the jump needs an explanation
before anything else is concluded.

### 3.3 The primary pass has almost no margin

8 of 10 is exactly the threshold. Chalmette (93.0) and Gordon Plaza (93.1) are
3 points above the line, and in run 11 both were below it. One site slipping
fails the gate again. The primary gate is better described as fragile than as
fixed.

### 3.4 Structural misses that should be documented, not fixed

- **Geismar (85.6).** Pollution Burden is 9.7, the highest of any site. 17 of
  its 19 cells hold fewer than 25 people, and the two that score have very low
  poverty (P1 0.7) and S2 at 0.7. A score of burden on people cannot rank a
  plant complex where nobody lives. §16 should state this.
- **Gordon Plaza** is a soil pathway (former landfill). No indicator measures
  contaminated land, so it passes on air and proximity alone, by 3 points.
- **Stress A, Lake Providence (24.0) and St. Joseph (38.2).** Their pollution
  percentiles are at the zero-facility tie block (F ≈ 33.6, E3 = 39.3), and
  E1 is at 18–31. This is the multiplicative model working as §10's worked
  example says. §13.4 asks for a documented investigation, which has not been
  written.
- **Tallulah at 75.004** is outside the 40–75 band by four thousandths of a
  point, which is a boundary artefact.

### 3.5 Other observations

- **E4 (measured PM2.5) is missing at many sites** (Reserve, Welcome, Mandeville,
  every Stress A and B site), yet it is the pollution indicator that most
  tracks rank in the polluted band (+0.44). Where monitors are placed is
  probably shaping rank among urban hexes. This needs a check.
- **Percentiles count hexes, not people.** 65% of the denominator is cells of
  25–120 residents, and many of them repeat one tract's values. Rural tracts
  that split into many hexes weigh more in every percentile than the people
  in them justify.
- **Interpolation sensitivity (§13.5 third check) still has not run.** It was
  blocked on branch storage. `dev-seed` is now 584 MB against a 1 GiB cap
  (expansion.md §7), so the block reload CP-06 needs may now fit.
- **The gate's stderr summary was misleading.** It printed `primary gate: 8 of
  10 passed ... -> FAIL` when the primary gate passed and the controls failed.
  Fixed on this branch, see §4.

---

## 4. Plan

§13.7 permits three responses: fix a code defect, fix a data defect, or revise
the methodology with a rationale that stands on its own, then re-run every
check from the start. Each item below says which one it is. **No item selects
a change because it makes a site pass.** Rationale is written and committed to
methodology §18 *before* the re-run.

### Phase A: defects (allowed now, no methodology change)

| # | Work | Type | Expected effect |
|---|---|---|---|
| A1 | Explain the jump from 2,618 to 4,070 Insufficient hexes between runs 11 and 81. Diff `scoring/burden/confidence.py` and the `c_spatial` inputs across `c4689df..cd54bd9`. Check that `c_spatial` follows §12 (ACS CV > 0.30 share, mean source-block area), and not, for example, a raw block-area term that is penalising every rural cell to the 0.05 floor. | code/data | If a defect: Welcome and about 1,400 hexes come back into the universe |
| A2 | Check the E4 interpolation: coverage per hex, and whether "not observed" is being treated as missing correctly under §11 | code/data | Removes monitor placement as a rank driver if it is one |
| A3 | Run §13.5 interpolation sensitivity: reload blocks, rebuild the crosswalk under 0025, score the areal counterpart, discard blocks (CP-06) | data | Closes the last unrun check |
| A4 | Gate summary line: report the primary gate and the overall gate separately | code | Done on this branch |
| A5 | Regenerate `site-validation.md` and `robustness.md` for run 81 and retire the run 11 narrative | docs | The docs describe the served run |

### Phase B: methodology revision v0.3 (argued independently, then re-run everything)

| # | Revision | Independent rationale | Risk |
|---|---|---|---|
| B1 | **Add CDC PLACES health outcomes (asthma, COPD, CHD) to Sensitive Populations.** The data is already in `tract_health` (1,367 tracts) and read by nothing. | §16 calls health outcomes "the single largest gap"; §8.3's reason for leaving them out (no free tract-level source) is no longer true; CalEnviroScreen precedent | PLACES is model-based and partly derived from age and poverty, which risks double-counting. Document it, and keep confidence intervals for `c_spatial`. Run 79 (0.3.0, 18 indicators) tried something like this, and its scores were deleted. The code is at `clearskies-api` 2d9b03c, so start from that rather than from scratch. |
| B2 | With B1, raise the §11 Sensitive minimum from 1 to at least 2 indicators | No single indicator should stand in for half of a component, which is what §13.5 LOO already flags | Fewer hexes scored. Report the count. |
| B3 | Add a contaminated-land indicator (NPL / Superfund, RCRA corrective action, brownfields proximity) to Environmental Effects | CalEnviroScreen's "Cleanup Sites"; the README promises cumulative burden, not air-only burden | Low |
| B4 | Decide on hexes versus people as the percentile denominator, or on a minimum for tract-duplicated cells | Statistical: pseudo-replicated rural cells distort every percentile | Large re-ranking. Argue it on its own merits. |

Expected direction, stated before any run so it cannot be fitted afterwards:
B1+B2 should lower Old Metairie and Bocage, whose health burden should not
match their age share, and should cut S1/S2 leave-one-out below 10%. If it
does not, that is a finding. It is not a reason to try B-variants until it does.

### Phase C: documentation only

- §16: Geismar's residential-population limit, and the zero-block floor that
  holds Stress A sites down.
- §13.4: the Stress A investigation write-up it requires.

### Phase D: a second accuracy measure, so 14 sites are not the whole story

The site set is closed and small. Add a *reported, never gating* external
benchmark: the Spearman correlation between run percentiles and EPA EJScreen
supplemental index percentiles for Louisiana block groups, aggregated to hex.
It gives a statewide agreement figure, and it shows *where* ClearSkies
disagrees with an established index, which is where to look next. Register
the expected range before computing it.

### Order

A1 → A2 → A4/A5 (in parallel) → A3 → write B1–B3 into methodology §18 →
implement → re-run validate, robustness, disparity → D.
