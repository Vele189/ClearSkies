# Robustness checks — CS-212

**Implemented 2026-09-11 against methodology v0.1.3. First run against real data
2026-09-21. Latest: run 85, methodology v0.5.0, served from 2026-10-19. Outcome:
FAIL, on S1 alone (13.3%). Full output in `runs/run-85-robustness.md`. §8 is run
81 and §7 is run 11, kept because audits and tickets cite them.**

Methodology §13.5 specifies three checks that ask whether the score is measuring
Louisiana or measuring the choices made in §10. All three are implemented, unit
tested, and runnable in one command.

Two of the three have now run against a populated database. The alternative
specifications pass comfortably. The leave-one-out check fails on four
indicators, and the interpolation sensitivity check could not be built. §7
records the result in full.

---

## 1. Why §13.5 is separate from the rest of §13

§13.2 through §13.4 ask whether the score finds the right places. They are
answered against a set of sites frozen before any scoring code existed, which is
what makes them falsifiable.

They are not sufficient. A score can flag every pre-registered site and still be
an artifact: if its ordering flips when one weight moves from 0.5 to 1.0, then it
agrees with the sites under one arbitrary choice and would have disagreed under
another that nobody argued against. Passing the site check would then be a fact
about the choice rather than about Louisiana.

§13.5 is the check on that. It is the only part of §13 that cannot be answered by
looking at the score, because it requires building the score a different way.

## 2. The three checks, and which of them gate

**Alternative specifications.** Spearman rank correlation of at least 0.85
between the score and each of three variants.

| Variant | What changes | Gating |
|---|---|---|
| `equal_weights` | Environmental Effects weighted 1.0 rather than 0.5 | yes |
| `exposures_only` | Pollution Burden from Exposures alone | yes |
| `additive` | Components added rather than multiplied | reported |

The additive variant is reported rather than required, as §13.5 states. §3
rejects the additive model *because* it makes a different claim about what
cumulative burden means, so a high correlation with it would be the surprising
result. Requiring one would quietly assert that the choice between the two models
does not matter, which is the opposite of what §3 argues.

**Leave-one-indicator-out.** One run per indicator in §8, each built without that
indicator. No single removal may move more than 10% of hexes by more than one
decile. An indicator that fails is doing too much work alone, and §13.5 sends its
inclusion back to this paper to be re-argued rather than fixing it in code.

Two things that look identical in the movement figure are reported apart, because
they mean opposite things. A hex can move because the indicator carried
information, or because its group fell under the §11 rule 2 minimum once the
indicator was gone. Only the first is evidence about the indicator. The `Group
lost` column is the second.

A hex that loses its score entirely counts as moved. Dropping it from the
denominator instead would let an indicator that destroys part of the map look
like one that changes nothing.

**Interpolation sensitivity.** The score recomputed with simple areal weighting
in place of the dasymetric weighting of §7, to quantify how much that machinery
actually changes. Reported, never gating. §7 argues for the block ancillary layer
on evidentiary grounds, so a large divergence vindicates the argument rather than
failing the score, and a small one is worth publishing because it would tell a
reader that the most expensive step in the pipeline bought less than it cost.

## 3. How each is built

**Every variant goes through the production code.** `compute` in
`scoring/burden/component.py` takes the group specification as an argument, so a
variant is a different `ComponentSpec` handed to the same function rather than a
second copy of the arithmetic. A robustness check that re-derived the score in
order to compare against it would be comparing two implementations, and would
report a difference in its own comparison code as a property of the methodology.
`test_the_baseline_specification_reproduces_cs_204` holds the baseline to
`burden_score` with exact equality, and is what makes "the same code path" a fact
rather than an intention.

**The comparison universe is fixed once.** §12 bars insufficient-confidence hexes
from validation statistics, and §13.5 is a validation statistic, so the bands are
a required argument and the filter runs before anything is ranked. A scored hex
with no band is refused rather than assumed trustworthy. Every variant is then
ranked against that same denominator: percentiles drawn from two different
denominators are not comparable, and a robustness check built on them would be
measuring its own bookkeeping.

**The correlation is Spearman's, with ties taking the mean of their ranks.** This
is not a detail here. E3 and F1 through F4 are exactly zero for every hex with no
qualifying facility within 10 km, which will be a large share of Louisiana, so
one enormous tie block sits in the middle of the data. The familiar
`1 − 6Σd²/(n³−n)` shortcut is wrong in the presence of ties by an amount that
grows with the size of that block, so the implementation is Pearson's correlation
on §9's own mid-rank percentiles instead.

**The areal counterfactual changes exactly one thing.**
`etl/pipeline/dasymetric/areal.py` rebuilds the crosswalk with the population
estimator replaced and both §7 formulas left alone:

```
P_areal(t ∩ h) = P(t) · area(t ∩ h) / area(t)
```

Extensive quantities are then apportioned through that share, which is simple
areal weighting written out. Intensive quantities stay a population-weighted mean
and are weighted by the uniform-density estimate. Weighting a rate by raw overlap
area instead would change the estimator *and* the formula, and the resulting
divergence could not be attributed to either.

Two consequences are worth stating in advance of any result. The tract total is
conserved under both methods, so the §7 reconciliation closes for both and the
two differ in *where* people go, never in how many there are. And because the
population estimate itself changes, so does which cells clear the 25-person line
of §5 — that is the largest single consequence of the choice, and it is reported
as its own number rather than folded into an average over the hexes both methods
happened to score.

## 4. What is needed to produce a result

1. A populated database: the five adapters run against live sources, the §7
   crosswalk built, and `hex_score` written by CS-204.
2. Confidence computed for every scored hex by CS-205, because the §12 exclusion
   cannot be applied without it and this run refuses to proceed without it.
3. A second ACS and AirToxScreen interpolation through
   `dasymetric.areal_counterpart`, for the third check. Without it the first two
   still run and the third reports that it did not, which is a different thing
   from reporting that it found no divergence.
4. `make robustness VALUES=...`, and the output recorded in §18 whatever it says.

## 5. Running it

```
make robustness VALUES=path/to/values.json          # print the write-up
make robustness VALUES=... REQUIRE_PASS=1           # exit non-zero on a gating miss
make robustness-harness                             # the synthetic fixture, no database
```

The values file is a JSON object with `source`, `methodology_version`, a `hexes`
map carrying each cell's population and confidence band, and an `indicators` map
of raw values. A null value is an absence and stays one. An optional `areal`
block carries the same two things computed with area share.

`make robustness-harness` runs in CI on every push. Its values are invented and
its fixture is built to fail both gating checks, so it asserts that the four
scoring paths still run end to end and never that they passed. It is regenerated
by `scripts/make_robustness_fixture.py`.

## 6. If a check fails

§13.7 applies in full and permits three responses: fix a defect in the code, fix
a defect in the data handling, or revise this document with a rationale that
stands independently of the outcome, then re-run every check from the beginning.

Moving the 0.85 or the 10% because a check missed them is not one of them. Both
arrive from §13.5 as constants in `scoring/burden/robustness.py` rather than as
arguments a caller can pass, so loosening either is an edit to a named file with
a test against it rather than a flag on a command line.

---

## 7. Result — run 11, 2026-09-21

- Methodology version: 0.2.0
- Comparison universe: 17,263 hexes, after 2,618 excluded as insufficient confidence per §12
- Values file: `scripts/export_run.py --robustness`
- **Outcome: FAIL.** Four indicators are over the leave-one-out bar.

Run 11 supersedes an earlier run 7 whose §12 recency term was computing as zero
for every hexagon, which left only 6,093 hexes clearing the confidence bar. The
fix changed no weight and no percentile; it widened the comparison universe to
17,263. The conclusions below are unchanged in direction and firmer in support.

### 7.1 Alternative specifications — all three clear

| Specification | Gating | Spearman | Verdict |
|---|---|---|---|
| `equal_weights` | yes | 0.978 | clears 0.85 |
| `exposures_only` | yes | 0.960 | clears 0.85 |
| `additive` | reported | 0.983 | reported, not required |

This is the part of §13.5 that asks whether the ordering is an artifact of §10's
weights, and the answer is that it is not. Moving Environmental Effects from 0.5
to 1.0 leaves a 0.978 rank correlation; dropping the group entirely still leaves
0.960. **Whatever is wrong with this score, it is not the F-group weighting**,
and a proposal to fix the §13.2 site failures or the §13.4 control failures by
reweighting that group should expect to change almost nothing.

The additive variant correlating at 0.983 is worth reading with §2's warning in
hand. It is reported rather than required because §3 rejects the additive model
for making a *different claim*, not a worse one, and a high correlation is not
evidence that the multiplicative model is unnecessary.

### 7.2 Leave-one-indicator-out — four over the bar

No single removal may move more than 10% of hexes by more than one decile.

| Indicator | Group | Moved > 1 decile | Share | Lost score | Group lost | Verdict |
|---|---|---|---|---|---|---|
| E2 | exposures | 5,247 of 17,263 | 30.4% | 359 | 8,247 | **over** |
| E1 | exposures | 5,189 of 17,263 | 30.1% | 359 | 8,247 | **over** |
| S2 | sensitive_populations | 4,975 of 17,263 | 28.8% | 0 | 0 | **over** |
| S1 | sensitive_populations | 4,599 of 17,263 | 26.6% | 0 | 0 | **over** |
| E3 | exposures | 274 of 17,263 | 1.6% | 0 | 0 | within |
| E4 | exposures | 77 of 17,263 | 0.4% | 0 | 0 | within |
| F1 to F4 | environmental_effects | at most 1 | 0.0% | 0 | 0 | within |
| P1 to P5 | socioeconomic_factors | at most 48 | ≤0.8% | 0 | 0 | within |

**S1 and S2 are the cleanest finding.** Sensitive Populations holds two
indicators and §11 rule 2 sets its minimum at 1, so either alone satisfies the
group and carries roughly half of Population Characteristics by itself. Removing
either moves more than a quarter of the state by more than a decile, and the
`Group lost` column is **0** for both — so this is not the §11 artifact §2 warns
about. It is the indicator genuinely doing that much work alone.

That is a property of §8's group design rather than of the data, and §13.5 sends
it back to this paper to be re-argued rather than fixed in code. It is also the
most plausible explanation on the table for the §13.4 negative-control failures,
where affluent neighbourhoods rank higher than they should: Population
Characteristics is the half that ought to be pulling them down, and it rests on
a two-indicator group either half of which can swing a quarter of the state.

**E1 and E2 are a different case and should not be read the same way.** Their
`Group lost` column is 8,247 and `Lost score` is 359, so most of that movement is
Exposures falling below its minimum of 2 rather than the indicator's own
information. AirToxScreen is the only source covering every part of the state
evenly; with E1 or E2 removed, a hexagon with no TRI facility and no nearby
monitor has one Exposures indicator or none. §2 asks for these two columns to be
read apart for exactly this reason, and on that reading E1 and E2 are evidence
about the *group minimum* rather than about the indicators.

### 7.3 Interpolation sensitivity — did not run

§13.5's third check needs the same run recomputed with simple areal weighting,
which `dasymetric.areal_counterpart` builds. It did not run against run 11, and
the report says *did not run* rather than *found no divergence*, which is
deliberately a different statement.

**Why it did not run, corrected (AUD-20).** This section previously said the
cause was CS-112 discarding the 2020 block layer once the §7 crosswalk is built.
That was wrong, and the real cause was a defect. `areal_counterpart` reads each
tract's area shares from `tract_hex_weight`, not from the blocks, so a discarded
block layer does not stop it. What stopped it was that c5c9ac0 had stopped
emitting the overlaps of a populated tract holding none of its block population
— any tract spanning housing and marsh. §7 multiplies such a row by zero in both
of its formulas, so dropping them was right for the score; it was wrong for
§13.5, because without them a tract's `area_weight` no longer sums to 1 and the
counterpart refuses the tract rather than quietly spreading its population over
part of it. AUD-07 fixed the code and migration 0025 relaxed the constraint that
had forbidden the rows.

**What is still required, and it is not what this section used to say.** The
crosswalk in the database was built under the old code, and a count confirms it:
156,343 rows across 1,388 tracts and **not one** with `pop_weight = 0`. The rows
come back only when the crosswalk is rebuilt, and rebuilding reads the blocks —
so the block layer is reloaded once, the crosswalk is rebuilt under 0025, and
then the blocks are discarded again for good, because the geometry that was
missing now survives in `tract_hex_weight`.

**And it cannot run on the current plan.** Neon's free tier caps a branch at
512 MB and `dev-seed` is at 487 MB, so the block layer the rebuild reads does
not fit — the ceiling CS-112 discarded it for, which `backlog.md` had recorded
as gone and is not. CP-06 now carries the three ways out and the choice between
them is the owner's, because one of them is a recurring bill.

This document should not be read as having answered the question until a run
under the rebuilt crosswalk exists, and that is now further away than §7.3 used
to imply rather than nearer.

### 7.4 What §13.7 permits from here

Fix a defect in the code, fix a defect in the data handling, or revise the
methodology with a rationale that stands independently of this outcome — then
re-run every check from the beginning. Moving the 0.85 or the 10% because a
check missed them is not among the options, and neither is dropping S1 or S2
because removing one of them moves the score.

---

## 8. Result — run 81, checked 2026-10-19

- Methodology version: 0.2.0
- Comparison universe: 15,811 hexes, after 4,070 excluded as insufficient confidence per §12
- Values file: `scripts/export_run.py --robustness`; generated output in
  `runs/run-81-robustness.md`
- **Outcome: FAIL.** Two indicators are over the leave-one-out bar, down from four.

Run 81 is the first run scored by the code AUD-05 corrected. The universe is
smaller than run 11's 17,263 because AUD-05 also corrected the input to
`c_spatial`; `site-validation.md` and `accuracy-review-2026-10-19.md` §5 give
the arithmetic.

### 8.1 Alternative specifications — all three clear, as before

| Specification | Gating | Spearman | run 11 |
|---|---|---|---|
| `equal_weights` | yes | 0.980 | 0.978 |
| `exposures_only` | yes | 0.958 | 0.960 |
| `additive` | reported | 0.982 | 0.983 |

§7.1's conclusion stands unchanged: whatever is wrong with this score, it is not
the F-group weighting.

### 8.2 Leave-one-indicator-out — S1 and S2 over the bar, E1 and E2 no longer

| Indicator | Moved > 1 decile | Share | Group lost | run 11 share |
|---|---|---|---|---|
| S2 | 5,148 of 15,811 | **32.6%** | 0 | 28.8% |
| S1 | 5,002 of 15,811 | **31.6%** | 0 | 26.6% |
| E3 | 1,124 of 15,811 | 7.1% | 0 | 1.6% |
| P5 | 380 of 15,811 | 2.4% | 0 | ≤0.8% |
| E1 | 320 of 15,811 | 2.0% | 0 | 30.1% |
| E2 | 317 of 15,811 | 2.0% | 0 | 30.4% |
| all others | at most 162 | ≤1.0% | ≤1 | |

**E1 and E2 confirm §7.2's reading.** Their run 11 movement was almost entirely
the `Group lost` column: Exposures falling below its minimum because E3 and the
F indicators were missing rather than zero. With AUD-05 writing those zeros,
`Group lost` is 0 and the movement falls from 30% to 2%. It was a defect in the
inputs, as §7.2 argued, and not evidence about E1 and E2.

**S1 and S2 are now the only finding, and stronger.** Both moved further above
the bar. §7.2's diagnosis is unchanged: Sensitive Populations is two indicators
with a §11 minimum of one, so either alone carries half of Population
Characteristics. The two are also anti-correlated across the state (r = −0.21
between their percentiles), so the subgroup mean is the average of two
measures pulling in different directions. This goes back to §8 of the
methodology to be re-argued. The negative-control failures in
`site-validation.md` are the same finding seen from the sites.

**E3 rose from 1.6% to 7.1%**, still within the bar. That is expected once
facility-free hexes hold an E3 of zero rather than nothing: removing E3 now
changes the Exposures mean of every hex rather than only the hexes near a TRI
reporter.

### 8.3 Interpolation sensitivity — ran for the first time

Reported, never gating. Produced with
`export_run.py --robustness values.json --areal`, which recomputes the
crosswalk-derived inputs (population, S1, S2, P1 to P5, E1, E2) over
`dasymetric.areal_counterpart` with the scorer's own loaders and copies the
point indicators unchanged. Before writing anything it recomputes the same
inputs over the dasymetric crosswalk and refuses if they do not reproduce run
81's stored values. They did, so the comparison isolates §7.

§7.3's obstacle was gone by the time this ran. The block layer is loaded
(142,874 blocks) and `tract_hex_weight` has been rebuilt under 0025: it holds
50,096 `pop_weight = 0` rows across all 1,388 tracts, and `areal_counterpart`
accepted every tract without raising `PartialCrosswalk`. Nothing was written to
the database.

| | |
|---|---|
| Rank correlation, hexes both methods score | **0.987** |
| Hexes compared | 11,747 |
| Moved more than one decile | 253 (2.2%), largest move 8 deciles |
| Median absolute score change | 0.55 |
| Confident hexes scored only under dasymetric weighting | **4,064** |
| Scored only under areal weighting | 0 (no band was computed for them, so §12 leaves them out) |

**Where the hexes agree, the block layer barely changes the order.** A 0.987
correlation means the ranking of the cells both methods score is close to the
same either way.

**What the block layer changes is who gets scored at all.** 4,064 of the 15,811
confident hexes, a quarter, fall below §5's 25-person line under area
weighting: their median population is 46 with blocks and 12 without, because
uniform density spreads a settlement over the whole of a large rural tract.
§2 predicted that this would be the largest consequence of the choice, and it
is. That is the result §7 argues for, and it should be read that way: the
expensive step is not re-ranking places, it is finding where in a tract the
people live.
