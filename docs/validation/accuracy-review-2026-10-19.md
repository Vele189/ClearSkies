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
| Interpolation sensitivity | reported | did not run | ρ 0.987, 2.2% moved (§5.3) | – |
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
| B5 | **Ratify `c_spatial`.** Write its functional form into §12 (it is still only in `confidence.py`), and decide how the CV rule treats rate estimates for rare categories | §12 cannot be applied as written to P3 and P4, whose CVs exceed 0.30 almost everywhere (§5.1); AUD-05 rejected the "any estimate" reading for exactly this reason, and the per-estimate reading partly reproduces it | Changes which hexes count for validation. State the expected confident-universe size in advance. |

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

---

## 5. Phase A results (2026-10-19)

| # | Status | Result |
|---|---|---|
| A1 | done | Not a defect. The confidence drop is AUD-05's corrected `c_spatial` input. It becomes methodology item B5. |
| A2 | done | Not a defect. E4 follows §8.1 and the adapter's rules. Two data-handling notes below. |
| A3 | done | The interpolation sensitivity check ran for the first time. ρ = 0.987 on 11,747 shared hexes, 2.2% moved more than a decile, and 4,064 confident hexes are scored only under dasymetric weighting. No database write was needed (§5.3). |
| A4 | done | Gate summary line fixed. |
| A5 | done | `site-validation.md`, `robustness.md` §8, and a dated record in methodology §18. |

### 5.1 A1: the confident universe shrank because the `c_spatial` input was corrected

`c_spatial = (1 − high_cv_share) · min(1, 0.737 km² / mean_block_area)`.
Before AUD-05, the first factor used the CV of the *total-population* estimate,
which is small almost everywhere. AUD-05 (M3) made it the share of a hex's
population drawn from the seven ACS rate estimates (S1, S2, P1–P5) whose CV
exceeds 0.30, which is what §12 says.

Recomputing every scored hex's band from the stored terms (script
`spatial_sim.py`, not committed):

| `c_spatial` input | High | Moderate | Low | Insufficient |
|---|---|---|---|---|
| As stored in run 81 (reproduced exactly, 0 of 19,881 differ) | 423 | 5,237 | 10,151 | **4,070** |
| Pre-AUD-05 input (total-population CV) | 3,203 | 6,085 | 8,542 | 2,051 |
| Block-area factor only | 3,592 | 6,444 | 8,048 | 1,797 |
| CV-share factor only | 704 | 9,132 | 9,932 | 113 |

So the change explains the whole jump. In most of the state, which hexes
are Insufficient now depends on the two factors *together*. Neither alone
produces many.

The CV-share factor is dominated by indicators that are noisy everywhere:

| Estimate | Tracts with CV > 0.30 | Median CV |
|---|---|---|
| P3 linguistic isolation | 713 of 721 | 1.03 |
| P4 unemployment | 1,267 of 1,321 | 0.53 |
| S1 under 5 | 973 of 1,339 | 0.37 |
| P2 no diploma | 751 of 1,355 | 0.32 |
| P5 housing burden | 238 of 1,362 | 0.17 |
| P1 poverty | 184 of 1,366 | 0.21 |
| S2 65 and over | 71 of 1,362 | 0.16 |

P3 is defined in only 721 tracts because a zero rate has no CV and takes no
part. A tract with *some* linguistically isolated households is therefore
penalised, and a tract with none is not. That asymmetry, and P4's
near-universal flag, are why this is a methodology question (B5) and not a
code fix. Changing it now to recover Welcome's cells would be exactly what
§13.7 forbids.

### 5.2 A2: E4 is an urban indicator, by construction

- 18 of the 32 PM2.5 monitors have at least the 274 days that the annual
  mean requires (16 regulatory, 2 low-cost). These are raw day counts, before
  the adapter's screening. Ten of the regulatory ones are in Louisiana, all
  in metro areas; the rest are in Mississippi and Texas. E4 has a value for
  7,978 of 19,881 scored hexes.
- **Monroe (243 valid days) and Vinton (247)** fall short of 274, so the 738
  hexes within 25 km of them get no E4 but still use them for `c_monitor`.
  This is the adapter's documented rule and it is applied correctly.
- **Moncus Park, a low-cost sensor in Lafayette, enters the E4
  interpolation.** The adapter's own known-gap note says a low-cost sensor
  "is not interchangeable with a federal equivalent method instrument", and
  §8.1 describes the network as regulatory monitors, yet nothing filters on
  `is_regulatory`. The effect is small, because it sits beside the Lafayette
  regulatory monitor, and §8.1 does not actually forbid it. **Recommendation:**
  §8.1 should say which instruments count. Fondren (Jackson, MS) is the other
  low-cost sensor that qualifies; it is out of range of every Louisiana hex.
- The +0.44 correlation between E4 and rank in the polluted band reflects
  where monitors stand (the New Orleans and Baton Rouge metros), together with
  §11's drop-and-reaverage. A hex with E4 averages four Exposures indicators
  and one without averages three, so the 25 km edge is a step in the
  Exposures mean. Both are design, not defects. The step is worth a sentence
  in §16.

### 5.3 A3: the interpolation sensitivity check ran for the first time

The fork I planned to make was not needed. The block layer is already on
`dev-seed` (142,874 blocks, 197 MB), and the crosswalk has already been rebuilt
under migration 0025 (50,096 `pop_weight = 0` rows). CP-06's acceptance
conditions about data are therefore met, though the ticket still reads
BLOCKED. The check needs no database write: `run_robustness.py` scores both
interpolations itself, so what was missing was an exporter. `export_run.py
--areal` now provides it, and it refuses to write a block unless the
dasymetric recomputation reproduces the run (tests in
`api/tests/test_export_run.py`).

Result: ρ = 0.987 over 11,747 shared hexes, 253 (2.2%) moved more than a
decile, and 4,064 confident hexes clear §5 only under dasymetric weighting.
Their median population is 46 with blocks and 12 by area share. See
`robustness.md` §8.3.

Bearing on Phase B: the block layer mostly decides *which* hexes are scored,
not how they rank, and the same large-block effect is what drives the
`c_spatial` area factor (§5.1). B4 and B5 should be argued together.

**Cleanup the owner may want.** With the crosswalk rebuilt, CS-112's plan was
to discard the blocks again. They are 197 MB of the branch's 584 MB. Dropping
them is irreversible on the free plan and was not done here.

---

## 6. Phase B, first finding (2026-10-19): B1 is not admissible, and B2 does nothing alone

Nothing was scored. These findings come from the input data and CDC's
published method, before any run, so they are not shaped by a validation
result.

### 6.1 B1: CDC PLACES conflicts with §14

PLACES tract figures are not survey measurements. CDC fits a multilevel model
to BRFSS responses using "individual-level age, sex, race/ethnicity, and
education level", plus county poverty and random effects, and projects it onto
2020 census-block population counts
([CDC PLACES methodology](https://www.cdc.gov/places/methodology/index.html)).
Each tract's estimate is therefore partly a function of its racial
composition.

§14 keeps race out of the arithmetic so that §13.6's disparity result is
evidence rather than a property of how the score was built. An indicator
modeled from race brings race in indirectly. That argument does not depend on
the score or the sites, and it rules B1 out as designed. The lost v0.3.0 (run
79, three PLACES indicators) had the same flaw. Its §13.6 result would have
been partly circular.

Supporting input-level evidence. These are Spearman correlations across
Louisiana tracts, PLACES 2025 crude prevalence against ACS rates:

| | S1 under 5 | S2 65+ | P1 poverty | P2 no diploma |
|---|---|---|---|---|
| Asthma | +0.05 | −0.13 | **+0.84** | +0.62 |
| COPD | +0.05 | +0.12 | +0.75 | +0.72 |
| CHD | +0.01 | +0.30 | +0.64 | +0.62 |

COPD and CHD correlate at +0.95 with each other. Mostly the three re-express
the socioeconomic subgroup rather than adding new information. The tract
release has only crude (not age-adjusted) prevalence, so age adjustment is
not available either.

**Recommendation.** Do not score PLACES. Keep `tract_health` for display on
the hex panel, labelled as modeled, the way race is shown: next to the score,
not in it. Correct §8.3's reason for excluding health outcomes from "no free
tract-level source" to "the free tract-level source is modeled from race and
is excluded under §14".

### 6.2 B2: the Sensitive minimum is never what binds

All 19,881 scored hexes have both S1 and S2. Raising §11's minimum from 1 to 2
would change no score and no leave-one-out figure. The leave-one-out failure
comes from the group's structure: two age shares, anti-correlated (−0.21), each
carrying a quarter of Population Characteristics.

### 6.3 What is left of Phase B, and what it needs from the Lead

| Item | Status | Needs |
|---|---|---|
| B1 PLACES | **rejected under §14** | Agreement, then the §8.3 correction above |
| B2 Sensitive minimum | **moot** | — |
| B3 contaminated-land indicator | admissible | A new source adapter (EPA Superfund/NPL); it does not address the control failures |
| B4 hexes or people as the denominator | open | A methodology argument; large re-ranking |
| B5 ratify `c_spatial` | admissible | A decision on rare-category CVs (§5.1) |

Without a non-race-modeled source of health or susceptibility data, nothing
admissible left in Phase B targets the main failure (S1/S2 and the negative
controls). CP-14 anticipated this: it is the point where the remaining
options are a materially different Sensitive Populations design, a revision of
the criteria themselves argued in the open, or shipping with the gate failing
and saying so. All three are the Lead's to choose under §13.7, not a code
change.

---

## 7. Phase B, implemented (2026-10-19)

The owner chose the recommendations in §6: show PLACES without scoring it,
build B3, and settle B5 by adopting `c_spatial` as implemented. Methodology
v0.4.0 was committed first (`cc08f2c`), with its expected effects registered.
It was then implemented, and run 84 was scored and put through the whole
protocol. The full record is in methodology §18, "Run 84 under v0.4.0".

- **F5** (B3): a new `epa_sems` source and migration 0032. It counts 17
  Louisiana Final or proposed NPL sites. It moved Gordon Plaza from 93.1 to
  94.4 and moved nothing much else, as registered. It does not touch the
  negative controls, and was not meant to.
- **`c_spatial`** (B5) is now defined in §12. No score changed from this item.
- **PLACES** is on the hex panel as "Estimated adult health", with a caveat
  that it is modeled using race and never used in the result. Nothing in
  scoring reads it.
- **Gate:** 8 of 10 primary, 1 of 4 controls. It still fails, on S1/S2 and
  the controls, exactly as before.

What remains is CP-14's question, unchanged by any of this, and it is the
owner's to decide: a different Sensitive Populations design with a data source
not modeled from race, a revision of the control criterion argued in the open,
or shipping with the gate failing and saying so.

---

## 8. Phase B, second revision: v0.5.0, S3 disability (2026-10-19)

The owner chose the disability design from three admissible ones. It was
registered (`514441a`), implemented (`2767cd2`), scored as run 85, and taken
through the whole protocol. Methodology §18, "Run 85 under v0.5.0", has the
full record.

| | run 81 (served) | run 85 |
|---|---|---|
| Primary sites | 8 of 10 ✅ | 8 of 10 ✅ |
| Negative controls | 1 of 4 ❌ | **2 of 4** ❌ |
| Leave-one-out over the bar | S1, S2 (~32%) | S1 only (13.3%) |
| Alternative specifications | ✅ | ✅ |
| Stress A in band | 0 of 3 | 2 of 3 |

Better on every check, and passing on none it previously failed. Old Metairie
(90.0) and Bocage (93.4) remain far above the median. Under the registration,
v0.5.0 is not tuned further.
