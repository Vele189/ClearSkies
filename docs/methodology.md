# ClearSkies Methodology

**Version:** 0.1.1 (draft, pre-implementation)
**Status:** Phase 0 deliverable. Written before any scoring code exists, by design.
**Pilot geography:** Louisiana
**Last revised:** 2026-09-10

---

## 1. Purpose and scope

This document defines how ClearSkies turns five public datasets into a cumulative environmental burden score for every populated hexagon in Louisiana, how it quantifies its own uncertainty, and how the result will be tested.

It is written before the scoring code so that the validation targets cannot be reverse-engineered from the output. That ordering is the point. A cumulative burden score has enormous latitude in indicator choice, weighting, and normalization, and a score tuned until it agrees with the analyst's priors proves nothing. Fixing the specification and the test set first is what makes a passing validation run informative.

Everything here is a decision with a stated rationale. Where a choice is arbitrary, this document says so rather than dressing it up.

**Scope.** Louisiana only, air pollution and industrial facility burden only, using the five sources listed in §6. Water quality, soil contamination, drinking water, pesticides, traffic, and health outcomes are out of scope for v0 and noted in §16 where they would belong.

---

## 2. Design principles

1. **Every number decomposes.** A user must be able to walk from a final score back to individual source records without leaving the interface. Any indicator that cannot be traced to a public record is not eligible for inclusion.
2. **The validation set is fixed before the scoring code.** See §13. Weights are never adjusted to make a validation case pass.
3. **Absence of data is never evidence of absence of harm.** An unmonitored area is uncertain, not clean. This principle drives the missing-data rules in §11 and the confidence score in §12.
4. **Equal weights unless there is a reason.** Within an indicator group, equal weighting is the default. Deviating requires a documented justification in this file, not a code comment.
5. **The score describes exposure and vulnerability, not culpability.** No indicator, and no downstream document, asserts intent.
6. **Reproducible from source.** Given the same input vintages, the pipeline produces bit-identical scores. Vintages are pinned and recorded in `docs/provenance.md`.

---

## 3. Prior art

ClearSkies is a deliberate re-use of two established designs rather than a novel scoring theory.

**CalEnviroScreen 4.0** (OEHHA, 2021) supplies the structural model: a Pollution Burden component and a Population Characteristics component, each built from percentile-ranked indicators, multiplied together. The multiplication is the substantive claim, and ClearSkies adopts it: pollution in a place with low vulnerability and vulnerability in a place with low pollution are both treated as less severe than the two occurring together. An additive model would let a high score in one component fully compensate for a low score in the other, which is not what "cumulative burden" is meant to describe.

**EJScreen** (US EPA) supplies the convention of pairing a single environmental indicator with a demographic index and reporting percentiles rather than raw units. ClearSkies departs from EJScreen on the treatment of race, for reasons given in §14.

**Where ClearSkies is necessarily weaker.** CalEnviroScreen draws on California state health department data for asthma emergency visits, low birth weight, and cardiovascular disease, plus state drinking water, pesticide, and cleanup-site databases. None of those have a free national equivalent at tract resolution. ClearSkies has no health-outcome indicators at all in v0. Its Sensitive Populations group is therefore thin, resting on age structure alone. This is the single largest gap in the specification and §16 records it as such.

---

## 4. Pilot geography: Louisiana

Louisiana was selected for four reasons.

**Documented cases inside one state.** Because indicators are percentile-ranked against the rest of the state (§9), validation cases must also lie inside the state. Louisiana supplies ten independently documented environmental justice sites without borrowing from elsewhere, which no other single state matches at this density. The pre-registered set is in Appendix A.

**Tractable size.** Roughly 111,900 km² of land, about 150,000 populated hexagons at the chosen resolution, and a population of about 4.66 million. The scored dataset fits comfortably in a small Postgres instance with room for the statute corpus and its vector index. Raw source snapshots are archived as Parquet in object storage rather than in Postgres, so the database holds only derived tables.

**Dynamic range.** The lower Mississippi industrial corridor and the Lake Charles complex produce some of the highest modeled air toxics risk in the country, while the northern and Florida parishes are largely rural. A score needs both tails to be legible.

**A concrete legal hook.** Louisiana's constitutional public trust duty over natural resources, and the body of Title VI complaints filed against state permitting decisions, give the drafting assistant's statute corpus real state-specific material rather than federal statutes alone. See Appendix B.

Scoring is statewide. All percentiles in this document are Louisiana percentiles, and a Louisiana 90th percentile is not a national 90th percentile. §15 states this again because it is the most common way a score like this gets misread.

---

## 5. Spatial unit

**H3 resolution 8.** Average cell area 0.737 km², average edge length about 461 m.

Why hexagons rather than census tracts. Tracts vary in area by more than three orders of magnitude within Louisiana, from a few city blocks in New Orleans to hundreds of square kilometres in the Atchafalaya Basin. A tract-level score makes a rural tract's single number stand for an area where exposure varies enormously across it, and it makes visual comparison misleading because area reads as importance on a choropleth map. Hexagons hold area constant, have uniform adjacency, and nest hierarchically for aggregation.

Why resolution 8 specifically. Resolution 7 cells average 5.16 km², which is coarser than the distance over which facility proximity effects vary. Resolution 9 cells average 0.105 km², which is finer than the tract-level inputs can support and multiplies storage by seven for no additional information. Resolution 8 is roughly the scale of a neighbourhood and roughly the scale at which the underlying data has real content.

**Boundaries.** The hex grid covers Louisiana's land area plus coastal water out to the state boundary. Hexes intersecting the state line are included if their centroid falls inside Louisiana; percentiles are computed over included hexes only. Facility contributions from out-of-state sources within the interaction radius are counted, so a hex on the Texas line near a Beaumont-area facility is not artificially clean.

**Unpopulated hexes.** Hexes with an estimated population below 25 are not scored. They receive a `no_score` status with reason `low_population`, and they are excluded from every percentile denominator. Scoring an uninhabited swamp cell distorts the distribution and means nothing.

---

## 6. Data sources

Each source is pinned to a vintage at ingest. `docs/provenance.md` records the exact release, retrieval timestamp, and record counts for every pipeline run.

| Source | Provides | Native geography | Cadence |
|---|---|---|---|
| EPA ECHO / ICIS | Regulated facilities, permits, inspections, violations, formal enforcement actions, penalties | Point (facility lat/lon) | Weekly refresh upstream |
| EPA TRI | Annual on-site air releases by chemical and facility | Point (facility lat/lon) | Annual, ~18-month lag |
| EPA AirToxScreen | Modeled lifetime cancer risk and respiratory hazard index from ~180 air toxics | Census tract | Every 1–2 years, ~3-year lag |
| OpenAQ | Measured PM2.5 and other criteria pollutants | Point (monitor) | Daily |
| US Census ACS 5-year | Income, poverty, education, unemployment, language, age, housing cost burden, race and ethnicity | Census tract | Annual, 5-year pooled |

**Vintage lag is real and is scored.** AirToxScreen's most recent release reflects an emissions inventory several years old. ACS 5-year estimates describe a five-year window whose midpoint is roughly three years before publication. Neither is current, both are the best available, and the recency term in the confidence score (§12) reflects the gap rather than hiding it.

**Availability risk.** Several EPA environmental justice tools and datasets were withdrawn from public EPA hosting during 2025. Adapters must therefore treat upstream availability as unreliable: each adapter records the exact URL and retrieval date it used, checksums what it downloaded, and can be pointed at an archived mirror without code changes. If a source becomes unavailable, the pipeline continues on the last good snapshot and the recency term degrades accordingly. It does not silently substitute.

**Positional accuracy.** ECHO and TRI facility coordinates are self-reported and are known to contain errors, including coordinates that fall in the wrong parish or in open water. Facilities whose coordinates fall outside Louisiana's boundary buffer, or more than 2 km from the centroid of their reported ZIP code, are flagged and excluded from proximity indicators, with the exclusion count published in the provenance page. This trades a small amount of coverage for not attributing a refinery's releases to the wrong neighbourhood.

---

## 7. From tracts to hexagons

Three of the five sources are tract-level. Moving them to hexagons is the most consequential transformation in the pipeline, and doing it naively by area share would assign an unpopulated third of a rural tract the same per-area population as its town.

**Ancillary layer.** 2020 Decennial Census block population counts (PL 94-171). Blocks are roughly two orders of magnitude finer than tracts and their populations are counts, not estimates.

**Procedure.**

1. For each tract `t`, distribute its ACS estimate across its constituent blocks in proportion to 2020 block population.
2. Intersect blocks with the hex grid. Assign each block's value to hexes in proportion to the block's area share falling in each hex.
3. Aggregate to the hex.

**Extensive versus intensive variables must be handled differently.** This distinction is the most common source of error in this step.

*Extensive* quantities are counts and sum across space: population, households, number of people in poverty. These are apportioned proportionally.

```
V(h) = Σ_t Σ_{b ∈ t}  V(t) · [ P(b) / P(t) ] · [ area(b ∩ h) / area(b) ]
```

*Intensive* quantities are rates, ratios, and modeled risks and do not sum: poverty rate, AirToxScreen cancer risk, percent without a high school diploma. These are combined as a population-weighted mean of the source values overlapping the hex.

```
R(h) = [ Σ_t R(t) · P(t ∩ h) ] / [ Σ_t P(t ∩ h) ]
```

Rates are never recomputed from independently interpolated numerators and denominators, which would introduce inconsistent rounding. Where a rate has a published numerator and denominator, both are interpolated as extensive quantities and the rate is derived once at the end.

**ACS uncertainty propagates.** ACS 5-year estimates carry published margins of error, and at tract level for small subgroups those margins are frequently larger than the estimate. Margins are combined in quadrature under the Census Bureau's approximation for derived sums, and the resulting coefficient of variation travels with the value into §12. Estimates with a coefficient of variation above 0.30 are usable but degrade the hex's confidence; there is no threshold above which an estimate is silently dropped, because dropping high-uncertainty estimates preferentially removes small and rural populations.

**Known error.** Step 2 assumes population is uniform within a census block. For large rural blocks this is wrong. It is a far smaller error than assuming uniformity within a tract, and blocks are the finest free geography available. The residual error is largest exactly where blocks are largest, which is where the spatial term of the confidence score is already lowest.

---

## 8. Indicators

Fifteen indicators in four groups. Every indicator is percentile-ranked statewide before it enters any average (§9).

### 8.1 Pollution Burden → Exposures (group weight 1.0)

| ID | Indicator | Definition | Source | Type |
|---|---|---|---|---|
| E1 | Air toxics cancer risk | Modeled lifetime cancer risk per million from inhalation of air toxics | AirToxScreen | Intensive, tract |
| E2 | Air toxics respiratory hazard | Modeled respiratory hazard index | AirToxScreen | Intensive, tract |
| E3 | Toxic release proximity | Toxicity-weighted, distance-decayed on-site air releases | TRI | Point |
| E4 | Measured PM2.5 | Annual mean of daily PM2.5, inverse-distance interpolated | OpenAQ | Point |

**E3 formula.** For hex `h`, over facilities `f` with an air release in the reporting year:

```
E3(h) = Σ_f  [ Σ_c  w_c · m_{f,c} ]  /  max(d_{h,f}, 250 m)²
```

where `m_{f,c}` is pounds of chemical `c` released to air by facility `f`, `w_c` is the EPA RSEI chemical toxicity weight, and `d_{h,f}` is the distance from the hex centroid to the facility. Facilities beyond 10 km contribute nothing; at that distance the inverse-square term has fallen far enough that including them costs computation without changing ranks. The 250 m floor prevents a singularity when a facility sits inside the hex.

Inverse-square decay is a modelling assumption, not a dispersion model. It ignores wind, stack height, and terrain. It is used because it is transparent and reproducible from public data; a real dispersion model is what AirToxScreen already provides, which is why E1 and E2 carry the primary weight and E3 is best read as "how much toxic material is released nearby."

**E4 and the monitor problem.** Louisiana has on the order of two dozen regulatory PM2.5 monitors for 150,000 hexes. E4 is interpolated by inverse-distance weighting from monitors within 25 km. **Hexes with no monitor within 25 km receive no E4 value and it is treated as missing, never as zero and never as the state median.** This is the single rule most responsible for keeping the score honest: an unmonitored rural parish must not be rewarded for having no sensor. The consequence is that E4 is present for a minority of hexes and, per §11, the Exposures group is usually carried by E1 through E3.

### 8.2 Pollution Burden → Environmental Effects (group weight 0.5)

| ID | Indicator | Definition | Source | Type |
|---|---|---|---|---|
| F1 | Major source proximity | Distance-decayed count of active Clean Air Act major-source and Title V permitted facilities | ECHO | Point |
| F2 | Non-compliance burden | Distance-decayed count of facility-quarters in non-compliance over the trailing 12 quarters | ECHO | Point |
| F3 | Enforcement burden | Distance-decayed count of formal enforcement actions over the trailing 5 years, with log-scaled penalties | ECHO | Point |
| F4 | Hazardous waste proximity | Distance-decayed count of RCRA large-quantity generators and treatment, storage, and disposal facilities | ECHO | Point |

F1 through F4 use the same inverse-square decay and 10 km cutoff as E3, without toxicity weighting.

**Why this group is weighted 0.5.** Two reasons, and the second is the important one.

First, following CalEnviroScreen, these describe the presence of pollution sources and regulatory problems rather than measured or modeled exposure, so they are one step further from the harm.

Second, and specific to this design: **F2 and F3 partly measure regulatory attention rather than pollution.** A facility accumulates violations and enforcement actions when it is inspected. Better-inspected facilities generate more records, and inspection frequency is itself unevenly distributed. An area whose facilities are rarely inspected can look compliant because nobody looked. Weighting this group at 0.5 limits how far that confounder can move a score, and §16 records it as an unresolved bias rather than a solved one.

### 8.3 Population Characteristics → Sensitive Populations (subgroup weight 1.0)

| ID | Indicator | Definition | Source |
|---|---|---|---|
| S1 | Young children | Percent of population under 5 | ACS |
| S2 | Older adults | Percent of population 65 and over | ACS |

Both groups are physiologically more susceptible to air pollution. This subgroup is thin, and deliberately so rather than accidentally: the health-outcome indicators that would belong here have no free tract-level national source. See §16.

### 8.4 Population Characteristics → Socioeconomic Factors (subgroup weight 1.0)

| ID | Indicator | Definition | Source |
|---|---|---|---|
| P1 | Poverty | Percent of population below 200% of the federal poverty level | ACS |
| P2 | Educational attainment | Percent of adults 25+ without a high school diploma | ACS |
| P3 | Linguistic isolation | Percent of households with no member 14+ speaking English "very well" | ACS |
| P4 | Unemployment | Percent of civilian labour force unemployed | ACS |
| P5 | Housing cost burden | Percent of low-income households paying more than 50% of income on housing | ACS |

200% of the federal poverty level is used rather than 100% because the official poverty threshold badly understates material hardship and, more practically, because at 100% the tract-level ACS margins of error become severe.

### 8.5 Recorded but not scored

Race and ethnicity are ingested, stored, and displayed on every hex, and are used in the disparity analysis of §13.5. They are **not** inputs to the score. §14 explains why at length.

---

## 9. Normalization

Every indicator is converted to a Louisiana percentile before it is combined with anything else. Raw units are not comparable, and percentiles make the multiplication in §10 meaningful.

**Formula.** For indicator `k` with `n_k` scored hexes holding a valid value, sorted ascending, ties receiving the mean of their ranks:

```
p_k(h) = 100 · ( r_k(h) − 0.5 ) / n_k
```

**Why mid-rank rather than `(r−1)/(n−1)`.** The latter assigns exactly 0 to the minimum. In a multiplicative model a zero annihilates the entire component, so a single indicator at its statewide minimum would drive a hex's Pollution Burden toward zero regardless of the other three. The Hazen convention above is bounded strictly inside 0 and 100 and is symmetric at both tails.

**Ties and zero inflation.** F1 through F4 and E3 are zero for every hex with no qualifying facility within 10 km, which will be a large share of the state. All such hexes receive the same mid-rank percentile of the zero block. The consequence is that below that percentile these indicators carry no information, and the percentile of a zero-valued hex depends on how many other hexes are also zero. This is a real interpretive limitation, published on the hex detail panel rather than smoothed over: for a hex with no nearby facilities, the facility indicators say "none within 10 km," not "cleaner than 40% of the state."

**Percentiles are computed once per pipeline run** over all scored hexes, and the run's indicator distributions are stored so a score can be recomputed and audited later.

---

## 10. Aggregation

**Step 1 — subgroup means.** Within each of the four groups, average the percentiles of the indicators that have a value for that hex.

**Step 2 — component scores.**

```
PB_raw(h) = ( 1.0 · mean(Exposures) + 0.5 · mean(EnvEffects) ) / 1.5
PC_raw(h) = ( 1.0 · mean(Sensitive) + 1.0 · mean(Socioeconomic) ) / 2.0
```

**Why average subgroup means rather than pool all indicators.** Pooling would give Socioeconomic Factors five sevenths of the Population Characteristics component purely because it happens to have five indicators to Sensitive Populations' two. Averaging the subgroup means gives the two subgroups equal influence, which is the intended design and is stable if an indicator is later added to either. The same logic applies to Pollution Burden, where the 1.0 / 0.5 ratio is then a deliberate weight rather than an artifact of indicator counts. This is a documented departure from a naive reading of CalEnviroScreen's published formula.

**Step 3 — rescale each component to 0–10.**

```
PB(h) = 10 · PB_raw(h) / max_h PB_raw(h)
PC(h) = 10 · PC_raw(h) / max_h PC_raw(h)
```

**Step 4 — combine.**

```
Score(h) = PB(h) · PC(h)          range (0, 100]
```

**Step 5 — report.** The hex detail panel shows the raw score, its statewide percentile, both component scores, and every contributing indicator percentile as a waterfall. The map colours by percentile, not raw score, because the raw score's distribution is heavily right-skewed and a linear colour ramp on it would render most of the state indistinguishable.

**A worked consequence.** A hex at the 95th percentile for pollution and the 20th for vulnerability scores roughly 9.5 × 2.0 = 19. A hex at the 60th for both scores roughly 6.0 × 6.0 = 36. The second scores higher. That is the multiplicative model working as intended, and it is the behaviour a reader is most likely to find surprising, so it is stated in the explainer text on the panel.

---

## 11. Missing data

**Rules.**

1. A missing indicator is dropped from its subgroup mean. It is not imputed to zero and not imputed to the median.
2. A subgroup is computable only if a minimum number of its indicators are present: at least 2 of 4 Exposures, at least 2 of 4 Environmental Effects, at least 1 of 2 Sensitive Populations, at least 4 of 5 Socioeconomic Factors.
3. If Exposures is not computable, Pollution Burden falls back to Environmental Effects alone and the hex's confidence is penalized heavily. If neither is computable, the hex is `no_score` with reason `insufficient_pollution_data`.
4. If either Population Characteristics subgroup is not computable, the component uses the other alone with a confidence penalty. If neither is computable, the hex is `no_score` with reason `insufficient_population_data`.
5. Every dropped indicator is recorded per hex and shown in the detail panel. A user always sees which of the fifteen were actually used.

**Direction matters.** Imputing a missing pollution indicator to the state median would systematically pull unmonitored high-burden areas down toward the middle, which is precisely the failure this project exists to avoid. Dropping and re-averaging leaves the estimate unbiased with respect to the observed indicators and pushes the cost into the confidence score, where it is visible.

**Zero versus missing.** These are different and are stored differently. Zero TRI releases within 10 km is an observation. No AirToxScreen value for the tract is an absence. The pipeline never coerces one into the other.

---

## 12. Confidence

Every scored hex carries a confidence value in (0, 1]. It measures how well-supported the score is, not how severe the burden is, and the two must never be conflated in the interface.

**Four components**, each mapped to (0.05, 1]:

| Term | Weight | Definition |
|---|---|---|
| `c_coverage` | 0.35 | Weight-weighted fraction of the fifteen indicators with an observed value for this hex |
| `c_recency` | 0.20 | `exp(−Δt / τ)` with `τ` = 4 years, `Δt` the weighted mean age of the contributing data vintages |
| `c_spatial` | 0.25 | Interpolation support: falls with the share of hex population drawn from ACS estimates whose coefficient of variation exceeds 0.30, and with the mean area of the source census blocks |
| `c_monitor` | 0.20 | `min(1, 10 km / d_nearest)` where `d_nearest` is the distance to the nearest PM2.5 monitor |

**Combination — weighted geometric mean.**

```
C(h) = Π_j  c_j(h) ^ ( w_j / Σ w )
```

Geometric rather than arithmetic so that one badly deficient term cannot be averaged away by three healthy ones. A hex with excellent coverage, recency, and spatial support but no monitor within 100 km should read as less certain than its arithmetic mean would suggest. Each term is floored at 0.05 so that a single zero cannot annihilate the product.

**Bands.**

| Band | Range | Treatment |
|---|---|---|
| High | ≥ 0.80 | Full opacity on the map |
| Moderate | 0.60 – 0.79 | Full opacity, confidence noted on the panel |
| Low | 0.40 – 0.59 | Hatched fill, panel leads with the confidence caveat |
| Insufficient | < 0.40 | Hidden by default behind a toggle, excluded from validation statistics and from the drafting assistant |

A hex in the Insufficient band cannot be used to generate an advocacy document. Producing a cited complaint from a score the system does not itself trust would be the most damaging thing this tool could do.

---

## 13. Validation protocol

### 13.1 Pre-registration

The validation set lives in `docs/validation/sites.yml` and is committed **before** any file under `scoring/` is committed. It is closed and read-only. CI enforces this by checking that the first commit touching `docs/validation/sites.yml` precedes the first commit touching `scoring/`, and fails the build otherwise. The mechanism is crude and easy to defeat by anyone determined to; its purpose is to make casual post-hoc tuning impossible and deliberate tuning visible in the git history.

### 13.2 Primary criterion

At least **8 of the 10** active pre-registered sites in Appendix A must have at least one scored hex, among the cells frozen for that site in `docs/validation/sites.yml`, falling in the statewide **top decile** of scores.

Each site resolves to an explicit set of resolution 8 cells rather than a radius evaluated at scoring time, so the cells a site is judged on are fixed in the fixture and cannot shift with the code that reads it. `scripts/check_validation_set.py` re-derives every cell list from its anchor and fails CI if the two disagree, which means an anchor cannot be nudged toward a better result without the committed cells contradicting it.

### 13.3 Negative controls

All **4 of 4** pre-registered negative controls, affluent low-industry areas listed in Appendix A, must fall below the statewide 50th percentile.

### 13.4 Stress cases

Two failure modes are specifically tested, because the easiest way to pass §13.2 is to build a score that is secretly something simpler.

**Not a poverty map.** Three high-poverty, low-industry rural parishes in the Delta must land between roughly the 40th and 75th percentiles. If they land in the top decile, Population Characteristics is dominating and the multiplication is not doing its job.

**Not an emissions map.** Three high-emission, low-population industrial sites must land below the top decile. If they land at the very top, Pollution Burden is dominating.

Both are stated as expectations with rationale, not as pass/fail gates, because the honest range is genuinely uncertain in advance. A result outside these bands triggers a documented investigation, recorded in §18 whatever the outcome.

### 13.5 Robustness

- **Alternative specifications.** Spearman rank correlation of at least 0.85 between the score and each of: equal weighting of Exposures and Environmental Effects; Exposures only; additive rather than multiplicative combination. A low correlation against the additive variant is expected and is informative rather than disqualifying, since the two models make different claims; it is reported, not required to pass.
- **Leave-one-indicator-out.** Removing any single indicator must not move more than 10% of hexes by more than one decile. An indicator that fails this is doing too much work alone and its inclusion is re-argued in this document.
- **Interpolation sensitivity.** Scores recomputed with simple areal weighting instead of dasymetric weighting, to quantify how much the §7 machinery actually changes.

### 13.6 Disparity analysis

The correlation between a hex's score percentile and its Black population share, and separately its overall people-of-colour share, is computed and published with confidence intervals, population-weighted.

**This is a reported result, not a validation target.** Because race is not an input to the score (§14), any correlation found is a property of the pollution and vulnerability data rather than an artifact of the construction. There is no threshold it must meet, and a weaker-than-expected correlation would be a finding worth publishing rather than a bug to fix.

### 13.7 Failure protocol

If a criterion fails, the permitted responses are: fix a defect in the code, fix a defect in the data handling, or revise this document with a rationale that stands independently of the validation outcome and re-run every check from the beginning.

Adjusting a weight because it makes a validation site pass is not permitted. Every validation run, passing or failing, is recorded in §18 with the version of this document it was run against.

---

## 14. Race and the score: a design decision

**Decision: race and ethnicity are recorded, displayed, and analyzed, but are not inputs to the burden score.**

This is a deliberate departure from EJScreen, whose demographic index averages low-income share and people-of-colour share, and an alignment with CalEnviroScreen, which excludes race from the score and reports it alongside.

**Reasoning.**

The project's central claim is that environmental burden in Louisiana falls disproportionately on Black communities. If racial composition is an input to the score, that claim becomes circular: the score is high where the population is Black partly because the formula put it there, and the correlation in §13.6 is guaranteed by construction and evidentially worthless.

By excluding race, the correlation becomes an independent empirical result. The score is built from emissions, modeled risk, facility proximity, compliance records, age structure, and economic hardship. When that score turns out to track racial composition, the finding carries weight precisely because nothing in the construction reached for it.

This also matters downstream. A Title VI disparate-impact argument rests on showing that a facially neutral distribution of burden falls unequally by race. A burden metric that already contains race as an ingredient is far weaker evidence for that argument than one that does not.

**The cost.** Excluding race means the score does not capture burden mechanisms that operate through race independently of income, of which there are documented examples in the siting literature. The score will understate burden in a Black community that is not also poor. This is a real loss, accepted for the evidentiary reason above, and it is recorded in §16.

**Race is not hidden.** Every hex panel shows its racial and ethnic composition next to the score. The disparity analysis is a headline output, not an appendix. The decision is about what goes into the arithmetic, not about what the tool talks about.

---

## 15. What the score is not

- **Not a health risk estimate.** It is a relative ranking of burden indicators. It does not predict any individual's risk of illness.
- **Not a finding of wrongdoing.** A high score means the surrounding area has high modeled exposure, nearby permitted sources, and a vulnerable population. It says nothing about whether any facility broke any law or intended any harm. Facilities operating fully within their permits contribute to burden scores.
- **Not comparable across states.** Percentiles are Louisiana percentiles. A Louisiana 50th percentile hex may be dirtier than a top-decile hex in another state. v0 makes no national claims.
- **Not a clean bill of health at the low end.** A low score can mean low burden, or it can mean the indicators that would have caught the burden are missing. The confidence value distinguishes these and must be read with the score.
- **Not a substitute for local knowledge.** Residents know things the federal databases do not contain. The score is a starting point for an argument, not the argument.

---

## 16. Known limitations

**No health outcome indicators.** The Sensitive Populations subgroup rests on age structure alone. Asthma prevalence, low birth weight, and cardiovascular disease would materially improve it. CDC PLACES publishes model-based tract-level prevalence for several relevant conditions and is the obvious sixth data source; it is deferred rather than rejected, and adding it is the highest-value single extension to this specification.

**Enforcement indicators encode regulatory attention.** F2 and F3 rise with inspection frequency as well as with actual violation. Areas whose facilities are seldom inspected can appear compliant. The 0.5 group weight limits the damage; it does not fix it. A proper correction would require inspection-effort data and is not attempted.

**Inverse-square decay is not dispersion.** E3, F1 through F4 ignore prevailing wind, stack height, terrain, and chemistry. Along the river corridor, where wind direction is persistent, this will misplace burden relative to a real plume model.

**Air only.** Louisiana's water and soil contamination burden is substantial and entirely absent from v0. A community whose principal harm is a contaminated aquifer will not show it here.

**Race excluded from the score understates some burden.** See §14.

**ACS margins of error are large at tract level.** Particularly for linguistic isolation and unemployment in small-population tracts. Handled through §7 and §12, not eliminated.

**Block-level population uniformity.** The §7 dasymetric step assumes uniform population within a census block, which is wrong for large rural blocks. Smaller error than the tract-level alternative, and correlated with where confidence is already lowest.

**Point-in-time snapshot.** Scores describe the pinned vintages. A facility that closed last month still contributes until the next TRI and ECHO refresh.

**No temporal trend.** v0 scores a single period. Whether burden is rising or falling in a place is arguably more actionable than its level, and is not available here.

---

## 17. Revision policy

1. This document is versioned semantically. A change to any indicator definition, weight, normalization rule, or aggregation formula is a **minor** version bump at minimum.
2. No weight or formula changes without an entry in §18 stating what changed, why, and what the justification was **independent of its effect on validation results**.
3. Every published score carries the methodology version that produced it, and historical scores are not silently recomputed under a new version.
4. The pre-registered validation set in Appendix A is **closed and read-only**. Sites are never added, removed, or re-anchored, and criteria are never loosened. If a site is later found to be poorly chosen, it stays in the set with a documented note explaining the problem, and continues to be reported. Correcting an anchor that names the wrong community is a revision under this section, recorded in §18; moving one to improve a result is not permitted.
5. Flipping `active` on an out-of-state site when coverage extends is **not** a change to the set. That transition and its trigger are pre-declared in the fixture, which is the reason those sites are registered now rather than chosen later once a national score already exists.
6. Changing this document requires re-running the full §13 protocol before the new scores are published.

---

## 18. Changelog

### v0.1.1 — 2026-09-10 — validation set closed

Validation set resolved from point anchors to explicit sets of H3 resolution 8
cells, frozen in the fixture and re-derived in CI. Citations to public
documentation added for every high-burden site. Ten out-of-state sites
registered as inactive with pre-declared activation triggers, so the national
targets are fixed before a national score exists rather than chosen after one
does. `burden_pathway` recorded per site, since the v0 score covers air only
and several registered sites carry their harm through water, soil, or waste.
The set is now closed and read-only rather than append-only (§17.4).

No indicator, weight, normalization, or aggregation change. Scores are
unaffected.


### v0.1.0 — 2026-09-10 — draft, pre-implementation

Initial specification. Pilot state locked to Louisiana. Fifteen indicators across four groups defined. CalEnviroScreen multiplicative structure adopted with two documented departures: subgroup-mean averaging rather than indicator pooling (§10), and exclusion of race from the score with a stated evidentiary rationale (§14). Validation set pre-registered in Appendix A. No scoring code written, no validation runs performed.

---

## 19. References

- California Office of Environmental Health Hazard Assessment. *CalEnviroScreen 4.0 Report.* October 2021.
- US Environmental Protection Agency. *EJScreen Technical Documentation.*
- US Environmental Protection Agency. *AirToxScreen Technical Support Document.*
- US Environmental Protection Agency. *Risk-Screening Environmental Indicators (RSEI) Methodology*, for chemical toxicity weights.
- Mennis, J. (2003). "Generating Surface Models of Population Using Dasymetric Mapping." *The Professional Geographer*, 55(1), 31–42.
- US Census Bureau. *Understanding and Using American Community Survey Data*, for margin-of-error handling in derived estimates.
- Uber Technologies. *H3: A Hexagonal Hierarchical Geospatial Indexing System*, documentation.
- Bullard, R. D. (1990). *Dumping in Dixie: Race, Class, and Environmental Quality.*

Reference list is not exhaustive and grows with the document. Legal citations for the drafting assistant's corpus are separately maintained and verified in Appendix B.

---

## Appendix A — Pre-registered validation set

Machine-readable form: `docs/validation/sites.yml`. That file is authoritative; this appendix renders it. The set is closed and read-only per §17.4, and `scripts/check_validation_set.py` enforces its internal consistency in CI.

Every site resolves to an explicit set of H3 resolution 8 cells, derived once from its anchor with `grid_disk(anchor, k)` and frozen in the fixture. A res-8 cell averages 0.737 km², so `k=1` is 7 cells spanning roughly 1.2 km, `k=2` is 19 cells spanning roughly 2.1 km, and `k=3` is 37 cells spanning roughly 3.0 km. `k` reflects the physical extent of each site and was set before any score existed.

**Anchors carry `verified: false`** until each is checked against its cited documentation in Phase 1. Verification may correct an anchor that names the wrong community, which is a §17.4 revision. It may not move one to improve a result.

**`burden_pathway`** records which medium carries the harm. The v0 score covers air only, so a site whose burden is water, soil, or buried waste is not expected to score highly, and a miss there is evidence about the score's scope rather than about its quality.

### A.1 Active sites, pilot state (criterion: 8 of 10 in the statewide top decile)

| # | Site | Parish | Pathway | Cells | Anchor |
|---|---|---|---|---|---|
| 1 | Reserve / LaPlace | St. John the Baptist | air | 7 (k=1) | `88444600ddfffff` |
| 2 | Welcome, 5th District | St. James | air | 19 (k=2) | `884446aa35fffff` |
| 3 | Mossville | Calcasieu | air | 19 (k=2) | `88446e4da9fffff` |
| 4 | Alsen / North Baton Rouge | East Baton Rouge | air | 19 (k=2) | `884440cc51fffff` |
| 5 | Norco | St. Charles | air | 7 (k=1) | `8844460161fffff` |
| 6 | Plaquemine | Iberville | air | 19 (k=2) | `884440d1d7fffff` |
| 7 | Chalmette | St. Bernard | air | 7 (k=1) | `8844464367fffff` |
| 8 | Geismar | Ascension | air | 19 (k=2) | `884440db61fffff` |
| 9 | Gordon Plaza, New Orleans | Orleans | soil | 7 (k=1) | `8844464051fffff` |
| 10 | Port Allen / Brusly | West Baton Rouge | air | 19 (k=2) | `884440c1d3fffff` |

Citations for each site are in the fixture. Two carry a scope caveat worth stating here: Gordon Plaza's burden is principally contaminated soil, and Mossville's residents were largely bought out and dispersed, so its population indicators may be weak even where its exposure indicators are strong.

### A.2 Registered but inactive, out of state

Indicators are percentile-ranked within the scored state (§9), so a cell outside Louisiana has no percentile and cannot be evaluated in v0. These sites are registered anyway, so that the national targets are fixed while the project has nothing to gain from choosing them favourably. Selecting them later, once a national score exists, is exactly the post-hoc selection pre-registration is meant to prevent. Each carries a pre-declared `activate_when` trigger, and nothing else activates a site.

| # | Site | County | State | Pathway | Cells |
|---|---|---|---|---|---|
| N-FLINT | Flint | Genesee County | MI | water | 37 (k=3) |
| N-CHESTER | Chester | Delaware County | PA | air | 19 (k=2) |
| N-MANCHESTER | Manchester, Houston Ship Channel | Harris County | TX | air | 37 (k=3) |
| N-PORTARTHUR | Port Arthur | Jefferson County | TX | air | 19 (k=2) |
| N-WESTOAKLAND | West Oakland | Alameda County | CA | air | 19 (k=2) |
| N-KETTLEMAN | Kettleman City | Kings County | CA | waste | 7 (k=1) |
| N-INSTITUTE | Institute | Kanawha County | WV | air | 19 (k=2) |
| N-UNIONTOWN | Uniontown | Perry County | AL | waste | 19 (k=2) |
| N-WARREN | Afton, Warren County | Warren County | NC | waste | 19 (k=2) |
| N-EASTCHICAGO | East Chicago, Calumet | Lake County | IN | soil | 19 (k=2) |

Four of these have a burden pathway the v0 score does not measure. Flint is drinking water, Uniontown is coal ash, East Chicago is lead-contaminated soil, and Warren County is buried PCB waste. They are kept because the set should record the sites the field considers foundational, not only the ones a particular score is good at finding. Warren County in particular is where the US environmental justice movement began.

### A.3 Negative controls (criterion: 4 of 4 below the statewide 50th percentile)

| # | Area | Parish | Cells |
|---|---|---|---|
| N1 | Mandeville | St. Tammany | 7 (k=1) |
| N2 | Old Metairie | Jefferson | 7 (k=1) |
| N3 | Bocage | East Baton Rouge | 7 (k=1) |
| N4 | South Lafayette | Lafayette | 7 (k=1) |

N2 is the weakest control in the set, affluent with no adjacent heavy industry but across the river from the west bank industrial strip. It is retained deliberately: a control that is merely easy tests nothing.

### A.4 Stress case A — not a poverty map

High-poverty, low-industry parishes, expected between roughly the 40th and 75th percentiles. Landing in the top decile means Population Characteristics is dominating the product.

| # | Area | Parish | Cells |
|---|---|---|---|
| SA1 | Lake Providence | East Carroll | 19 (k=2) |
| SA2 | Tallulah | Madison | 19 (k=2) |
| SA3 | St. Joseph | Tensas | 19 (k=2) |

### A.5 Stress case B — not an emissions map

High-emission sites with sparse surrounding population, expected below the top decile. Landing at the very top means Pollution Burden is dominating.

| # | Area | Parish | Cells |
|---|---|---|---|
| SB1 | Alliance Refinery vicinity | Plaquemines | 19 (k=2) |
| SB2 | Krotz Springs | St. Landry | 19 (k=2) |
| SB3 | Port Hudson mill vicinity | West Feliciana | 19 (k=2) |

Some cells at these anchors fall below the 25-person threshold in §5 and will be unscored. The criterion applies to scored cells, and a site with none is reported as `not_applicable` rather than as a pass.

---

## Appendix B — Statute corpus manifest

The drafting assistant retrieves statutory text only from this corpus. A citation to anything outside it fails verification and the draft is rejected (§3 of the README, `assistant/verifier`). The corpus is versioned; each document records its source, edition, and retrieval date.

### B.1 Federal statutes

| Authority | Citation | Relevance |
|---|---|---|
| Clean Air Act | 42 U.S.C. §§ 7401–7671q | Framework statute |
| — Hazardous air pollutants | 42 U.S.C. § 7412 | NESHAP standards; the basis for most air toxics arguments |
| — State implementation plans | 42 U.S.C. § 7410 | State obligations and adequacy |
| — Prevention of significant deterioration | 42 U.S.C. §§ 7470–7492 | New and modified major source review |
| — Operating permits | 42 U.S.C. §§ 7661–7661f | Title V permits and the public comment right they carry |
| Clean Water Act | 33 U.S.C. §§ 1251 et seq.; § 1342 | Discharge permitting |
| Resource Conservation and Recovery Act | 42 U.S.C. §§ 6901 et seq. | Hazardous waste handling |
| Emergency Planning and Community Right-to-Know Act | 42 U.S.C. §§ 11001 et seq.; § 11023 | The reporting requirement that produces TRI |
| Civil Rights Act, Title VI | 42 U.S.C. §§ 2000d–2000d-7 | Discrimination by recipients of federal funds |
| EPA Title VI implementing regulations | 40 C.F.R. Part 7 | Disparate-impact standard and the administrative complaint process |

### B.2 Louisiana authorities

| Authority | Citation | Relevance |
|---|---|---|
| Louisiana Constitution, natural resources | La. Const. art. IX, § 1 | Public trust duty over the environment |
| Louisiana Environmental Quality Act | La. R.S. 30:2001 et seq. | State framework statute |
| Louisiana Air Control Law | La. R.S. 30:2051 et seq. | State air permitting authority |
| Louisiana Administrative Code, Title 33, Part III | LAC 33:III | Air quality regulations |

### B.3 Bounded case law

Included for context only, and the assistant may cite these but may not reason from them to a legal conclusion.

| Case | Citation | Why it is here |
|---|---|---|
| *Save Ourselves, Inc. v. Louisiana Environmental Control Commission* | 452 So. 2d 1152 (La. 1984) | Establishes the state agency's affirmative public trust duty and the balancing questions a permitting decision must address |
| *Alexander v. Sandoval* | 532 U.S. 275 (2001) | Holds there is no private right of action to enforce disparate-impact regulations under Title VI |

*Sandoval* is in the corpus specifically so the assistant gets the procedural posture right. A Title VI disparate-impact claim is an administrative complaint to EPA's external civil rights office, not a lawsuit a resident can file. A draft that implies otherwise would send someone down a dead end, which is a more damaging failure than a missing citation.

### B.4 Corpus rules

1. Every document is stored with its full text, an edition or amendment date, and the URL and date it was retrieved.
2. Chunking is by section, never across section boundaries, so a retrieved passage always carries a complete citable unit.
3. The verifier checks that a cited section exists in the corpus **and** that the quoted or paraphrased proposition appears in the retrieved chunk. Existence alone is not sufficient.
4. Adding an authority requires a manifest entry here. The corpus cannot grow at runtime.
5. The corpus is not legal advice and the assistant's outputs are drafts for human review. This constraint is enforced in the prompt, in the schema, and in the interface, and is stated on every generated document.
