# Completion tickets — 2026-09-22

What stands between the repository as it is and the Phase 2 exit condition,
then Phase 4. Written after the 2026-09-22 audit was fixed and merged, and
covering the work that audit deliberately left alone: the score does not pass
its own gate, everything downstream of it has only run on fixtures, and the
frontend is one screen.

**Where this came from.** Three documents, read together:
[site-validation.md](../validation/site-validation.md) (run 11: 7 of 10 primary
sites, 2 of 4 negative controls, FAIL), [robustness.md](../validation/robustness.md)
(run 11: FAIL on E1, E2, S1 and S2; the third §13.5 check never ran), and
[audit/tickets.md](../audit/tickets.md), whose five follow-ups — AUD-16 to
AUD-20 — were raised while fixing and never ticketed for work.

**Conventions**

- IDs: `CP-NN`. Each ticket is fixed on its own branch, `plan/cp-NN-<slug>`.
- `Closes` names the backlog or audit ticket a CP ticket discharges. Those
  documents stay the authority on what the ticket is for; this one sequences it.
- Size: S (under a day), M (a few days), L (a week or more).
- Stages run in order. Within a stage, anything without a `Depends on` can start
  immediately. Stage E is independent of A to D and should run alongside them.

---

## The shape of it

| ID | Sev | Title | Closes | Depends on |
|---|---|---|---|---|
| **Stage A — land what is already written** ||||
| CP-01 | high | Merge the audit work to master and bring the database to 0026 | — | — |
| CP-02 | high | The three data defects that must land before a rescore | AUD-16 AUD-17 AUD-18 | CP-01 |
| CP-03 | medium | Decide what an eligible-but-unscored hexagon writes | AUD-19 | CP-01 |
| CP-04 | low | Repository hygiene: the unpushed branch and the stale refs | R2 R8 | — |
| CP-05 | low | Correct the stale backlog statuses and the scaffold banner | — | CP-01 |
| **Stage B — run 12, an honest re-measurement** ||||
| CP-06 | high | Rebuild the crosswalk so the areal counterpart can run | — | CP-01 |
| CP-07 | critical | Run 12: rescore under the corrected code | CS-204 | CP-02 CP-03 CP-06 |
| CP-08 | critical | Re-run the §13 protocol against run 12 and record it | CS-206 CS-212 CS-213 AUD-20 | CP-07 |
| CP-09 | critical | Read run 12 against the bars and choose the branch | — | CP-08 |
| **Stage C — methodology v0.3.0, if the gate still fails** ||||
| CP-10 | high | CDC PLACES adapter, the sixth source | — | CP-09 |
| CP-11 | high | Indicators S3 to S5 and the Sensitive Populations group | — | CP-10 |
| CP-12 | medium | Settle the two open methodology decisions | M5 M8 | CP-09 |
| CP-13 | critical | Methodology v0.3.0, then run 13 and the whole protocol again | — | CP-11 CP-12 |
| CP-14 | high | If the controls still fail: the criteria question | — | CP-13 |
| **Stage D — re-prove Phase 3 on real scores** ||||
| CP-15 | high | Re-run the fifty-draft audit against a promoted run | CS-308 | CP-09 or CP-13 |
| **Stage E — the missing frontend, parallel with A to D** ||||
| CP-16 | high | Routing and site chrome | — | — |
| CP-17 | medium | Provenance page | CS-406 | CP-16 |
| CP-18 | medium | Methodology, model card and about pages | — | CP-16 |
| CP-19 | high | Accessibility pass | CS-401 | CP-16 |
| CP-20 | medium | Disclaimer and safe-language review | CS-407 | CP-18 |
| **Stage F — the rest of Phase 4** ||||
| CP-21 | medium | Rate limiting on the read endpoints | CS-402 | — |
| CP-22 | high | Model card | CS-405 | CP-15 CP-18 |
| CP-23 | medium | Performance and payload review | CS-408 | CP-07 |
| CP-24 | medium | Architecture write-up | CS-409 | CP-22 |
| CP-25 | medium | Score and build tiles nightly; promotion stays manual | — | CP-07 |

**Not ticketed here.** CS-403 (monitoring and uptime checks) and CS-410 (launch)
both need a live deployment and are held with the Railway and R2 work in CS-009
and CS-207. They are the only Phase 4 tickets this document leaves out.

**The rule that governs all of it.** Methodology §13.7 permits three responses to
a failing check: fix a defect in the code, fix a defect in the data handling, or
revise the paper with a rationale that stands independently of the validation
outcome — then re-run every check from the beginning. No weight moves, no
threshold moves, and no line of `sites.yml` changes in order to make a check
pass. Every ticket below is one of those three things.

---

## Stage A — land what is already written

Nothing in this stage is new thinking. It is all sitting on branches.

## CP-01 · Merge the audit work to master and bring the database to 0026 · high · S

**Files:** none. Git and the Neon branch.

`QA` carries all fifteen audit tickets, 49 commits ahead of `master` with
nothing on `master` that `QA` lacks, so it is a fast-forward. They were proved
to combine on `audit/integration-check`: `make check` green end to end, api 349
passed / 39 skipped, web 156, etl 770, scoring 260, assistant 97.

Acceptance:
- `master` is at `QA`. The merge order that keeps the migrations in sequence is
  already recorded in `docs/audit/tickets.md` and was already applied on `QA`.
- Migrations 0023 through 0026 are applied to the served Neon branch. 0023 was
  pending before the audit; 0024, 0025 and 0026 arrived with it.
- They run against a Neon dev fork of real data before they run against the
  served branch. That is what the move to Neon bought and it should be used.
- `make migrate-verify` passes against the served branch: every migration
  applied and none edited after the fact.

## CP-02 · The three data defects that must land before a rescore · high · M

**Covers** AUD-16, AUD-17 and AUD-18. **Files:** `etl/pipeline/http.py`,
`etl/pipeline/adapters/tri.py`, a migration bounding `facilities_near_hex`.

These are the follow-ups the audit raised and did not fix. All three corrupt
what the scorer reads or what the panel shows, so they land **before** run 12,
not after. A rescore that inherits them is a rescore that has to be repeated.

Acceptance:
- **AUD-16:** `HttpFetcher._record` no longer overwrites the last good snapshot
  on a pull that returns 200 and then fails validation. Snapshots are staged and
  promoted only when the pull succeeds. Harmless while the store was in memory;
  AUD-09 made it durable. Regression test: a 200 that fails validation leaves
  the previous snapshot intact and the stale fallback still serves it.
- **AUD-17:** `adapters/tri.py` sends `responseset` on every page rather than
  only on `get_qid`, which is what AUD-08 already fixed for ECHO and RCRA. Test
  mirrors the ECHO paging test.
- **AUD-18:** a migration bounds `facilities_near_hex` to the same window AUD-05
  gave F2, so the drill-down panel and the score cannot disagree about how many
  quarters a facility was out of compliance. Its down reverses it.

## CP-03 · Decide what an eligible-but-unscored hexagon writes · medium · S

**Covers** AUD-19. **Files:** `scripts/run_scoring.py` or
`scoring/burden/robustness.py`, and whichever side changes.

AUD-05 writes `observed=false` indicator rows for scored hexes. Writing them for
eligible hexes that got no score would hand `robustness.py` hexes with no
confidence band, which it refuses. One of the two sides has to change and the
audit did not say which.

Acceptance:
- The decision is written down with its reasoning, in the module that carries
  it, not in a commit message.
- Either the scorer stops writing rows for hexes it did not score, or
  `robustness.py` states what it does with a hex that has no band. Not both.
- A test fixes the choice so it cannot drift back.
- Settled before CP-07, because it changes what run 12 contains.

## CP-04 · Repository hygiene · low · S

**Covers** R2 and R8, the two audit findings marked "for the owner, not fixable
in a branch".

Acceptance:
- `neon-setup` is pushed and has an open PR.
- `origin/QA` and the stale `cs-214` ref are pruned.
- A decision is recorded on whether bc889a5 on `cs-213-disparity-command` is
  superseded, and the branch is deleted if it is.

## CP-05 · Correct the stale backlog statuses and the scaffold banner · low · S

**Files:** `docs/backlog.md`, `web/src/App.tsx`.

AUD-15 reconciled Phases 2 to 4 of the backlog against the repository and did
not reach Phases 0 and 1. Six tickets are marked "Not started" whose code is
committed under their own ticket IDs.

Acceptance:
- CS-007, CS-101, CS-102, CS-103, CS-105 and CS-112 carry an accurate status and
  a "What landed" paragraph, matching how every reconciled ticket reads.
  Their code is `etl/pipeline/grid.py`, `adapters/echo.py`, `adapters/tri.py`,
  `adapters/airtoxscreen.py`, `adapters/census_acs.py` and
  `adapters/census_block.py`.
- The `Banner` in `App.tsx` no longer says "Phase 0 scaffold". It carries what is
  actually true of the deployment it is running in.
- `docs/README.md` indexes this file.

---

## Stage B — run 12, an honest re-measurement

The most important fact in this document: **nobody knows whether the gate still
fails.** Run 11 predates AUD-05, which changed what the scorer is fed, and
AUD-07, which changed dasymetric reconciliation and the ACS rates. Every
conclusion drawn from run 11 — including the diagnosis that S1 and S2 are a
group-design problem — is provisional until it is reproduced under the corrected
code. Stage C does not begin before CP-09.

## CP-06 · Rebuild the crosswalk so the areal counterpart can run · high · M

**Files:** `etl/pipeline/dasymetric/build.py` if anything, otherwise a run.

§13.5's third check needs the same run recomputed with simple areal weighting.
`robustness.md` §7.3 says the block layer being discarded is what stopped it.
That is no longer the reason: AUD-07's migration 0025 relaxed
`tract_hex_weight.pop_weight > 0` to `>= 0` precisely so the overlaps holding
none of a tract's block population survive, and `areal_counterpart` reads them.
What is missing is that the table in the database was built under the old code
and has none of those rows. It needs one rebuild from blocks.

Acceptance:
- The 2020 Decennial block layer is reloaded, roughly a thirty-minute pull.
- The crosswalk is rebuilt under migration 0025, so the `pop_weight = 0` rows
  are written, and the statewide block total is checked against Louisiana's
  published 2020 population as CS-112 requires.
- `areal_counterpart` runs over the rebuilt crosswalk without raising
  `PartialCrosswalk`.
- The blocks are discarded again. This is a one-time cost: the geometry now
  survives in `tract_hex_weight` and the check never needs the layer again.

## CP-07 · Run 12: rescore under the corrected code · critical · S

**Files:** none. `make score`.

Acceptance:
- `make score` produces run 12 against the loaded data, **without** `--promote`.
  A run that has not cleared §13 is not the run the map serves.
- `make export-run ARGS="--validation run.json --robustness values.json"` writes
  both export files.
- The run records the methodology version it ran against, and the scored hex
  count is reported next to run 11's 19,881 so the two are comparable.

## CP-08 · Re-run the §13 protocol against run 12 and record it · critical · M

**Closes** CS-206, CS-212 and CS-213 for this run, and AUD-20.
**Files:** `docs/validation/site-validation.md`, `robustness.md`, `disparity.md`.

Acceptance:
- `make validate SCORES=run.json` regenerates §13.2 to §13.4. Ten primary sites,
  four negative controls, six stress cases.
- `make robustness VALUES=values.json` runs **all three** §13.5 checks. The
  interpolation sensitivity check runs for the first time, on the crosswalk
  CP-06 rebuilt.
- The §13.6 disparity result is recomputed, reported and not gated, with its
  independence argument intact.
- **AUD-20:** `robustness.md` §7.3 no longer blames the block layer for the check
  not running. It states what CP-06 found.
- Every result is committed as it came out, passing or failing. §13.7 does not
  permit answering a failing criterion by editing these files, and CI's
  pre-registration and validation-set guards enforce the same thing on
  `sites.yml`.

## CP-09 · Read run 12 against the bars and choose the branch · critical · S

**Files:** a decision recorded in `docs/validation/` alongside the results.

The pivot. Three outcomes and three different plans, and the choice is made in
the open rather than by whoever picks up the next ticket.

| Run 12 result | What follows |
|---|---|
| 8 of 10 sites, 4 of 4 controls, robustness within bars | Phase 2 exits. Promote run 12, skip Stage C, go to CP-15 |
| Sites pass, controls or robustness still fail | Stage C, narrowed to what failed |
| Broadly as run 11 | Stage C in full |

Acceptance:
- The decision names which outcome occurred, against the numbers, and which
  §13.7 response is being taken: code defect, data-handling defect, or revision.
- If the run clears, it is promoted and the README's status paragraph is rewritten
  to say so.

---

## Stage C — methodology v0.3.0, if the gate still fails

Enter only through CP-09. Assume run 12 still fails, because the S1 and S2
finding is structural rather than a defect: Sensitive Populations holds two
indicators — S1, percent under 5, and S2, percent 65 and over — and §11 rule 2
sets its minimum at 1, so either one alone satisfies the group and carries
roughly half of Population Characteristics. Removing either moves more than a
quarter of the state by more than a decile, with a `Group lost` of 0, which is
the indicator genuinely doing that much work alone.

**Why this is a permitted response and not tuning.** §16 of the methodology
already says CDC PLACES "is the obvious sixth data source... the highest-value
single extension to this specification", and §3 already names the thin
Sensitive Populations group as the single largest gap in the paper. Both
predate the failure by the whole life of the document. That is what §13.7 means
by a rationale that stands independently of the validation outcome.

## CP-10 · CDC PLACES adapter, the sixth source · high · L

**Files:** `etl/pipeline/adapters/places.py`, fixtures, tests, `etl/README.md`.

Acceptance:
- Implemented as `pipeline/adapters/places.py`, registered, and listed by
  `python -m pipeline sources`. It subclasses `SourceAdapter` and writes no retry
  loop, rate limiter, partial-failure rule or provenance manifest of its own;
  those come from the interface.
- Tract-level model-based prevalence loaded for the conditions §16 names: asthma,
  COPD and coronary heart disease.
- The release year is the manifest's `vintage`, so the recency term reflects the
  release and not the download date.
- **These are modeled estimates, not counts,** and the adapter's known-gaps
  declaration says so in the words a reader needs. The same caveat reaches the
  provenance page through the manifest, next to the one AirToxScreen carries.
- A tract PLACES does not cover is `Measurement.absent()`, never `0.0`.
- Tests run against recorded fixtures through a mock transport, never the live API.
- The `etl/README.md` walkthrough is checked against this adapter, since it is the
  first new source since the contract was written.

## CP-11 · Indicators S3 to S5 and the Sensitive Populations group · high · M

**Files:** `docs/methodology.md` §8 and §11, `scoring/burden/indicators.py`,
`scripts/run_scoring.py`, a migration if the indicator enum is constrained.

Acceptance:
- S3, S4 and S5 defined in §8's indicator table with their source, their
  direction and their units.
- §8's group design is **re-argued**, not patched. A five-indicator Sensitive
  Populations group is a different object from the two-indicator one and the
  paper has to say why the new one is right on its own terms.
- §11 rule 2's minimum for the group is revisited in the same argument. A
  minimum of 1 over five indicators is a weaker claim than a minimum of 1 over
  two, and that is the property the leave-one-out check measures.
- `GET /indicators` publishes the new set, and the hex panel's grouped indicator
  list renders them with their source and vintage.
- The score's arithmetic is unchanged: percentile ranks, group means, the
  multiplicative structure. Only the group's membership moves.

## CP-12 · Settle the two open methodology decisions · medium · M

**Covers** M5 and M8, the two audit findings marked "a methodology decision".
**Files:** `docs/methodology.md` §11, §12 and the P5 definition.

§13.7 forces a full re-run for any revision, so these are batched into the same
one rather than paying that cost a second time.

Acceptance:
- **M5:** how the §11 fallback penalty enters C(h) is decided and written into
  §12, with the reasoning.
- **M8:** P5's threshold is settled at 50% or 30%, argued from what the indicator
  is for rather than from what it does to the result.
- Both are argued without reference to run 11 or run 12. A decision that cites
  the failing gate as its reason is not admissible under §13.7.

## CP-13 · Methodology v0.3.0, then run 13 and the whole protocol again · critical · M

**Files:** `docs/methodology.md` §18, every validation document.

Acceptance:
- The paper is at v0.3.0, with a §18 changelog entry naming every change from
  CP-11 and CP-12 and the rationale for each.
- The PLACES source is ingested, the crosswalk is unchanged, and `make score`
  produces run 13.
- **Every check runs from the beginning:** §13.2 to §13.4, all three §13.5
  checks, and §13.6. §13.7 does not allow re-running only the checks that failed.
- Results committed as they came out. If run 13 clears, it is promoted and Phase 2
  exits.

## CP-14 · If the controls still fail: the criteria question · high · M

**Files:** `docs/methodology.md` §13, and a written argument.

Open this only if run 13 clears §13.2 and §13.5 and still fails §13.4. PLACES
plausibly answers the robustness failure and the health-outcome gap. It is much
less obvious that it answers Old Metairie and Bocage, where affluent
neighbourhoods rank high: if the pollution side is genuinely high there, a
richer vulnerability side may not pull them down below the 50th.

Acceptance:
- The remaining option is stated plainly: §13.7 permits revising the paper,
  including the criteria themselves, with an independent rationale. That
  argument is materially harder to make honestly than the PLACES one and must
  not be made quietly.
- Whatever is decided is argued in §13 of the paper, in the open, over the Lead's
  name, with the failing result it would resolve named in the same paragraph so
  no reader has to reconstruct the motive.
- Leaving the gate failing and shipping the result as it stands is on the list of
  options considered, and is rejected explicitly if it is rejected.

---

## Stage D — re-prove Phase 3 on real scores

## CP-15 · Re-run the fifty-draft audit against a promoted run · high · M

**Closes** CS-308 as a statement about production rather than about fixtures.
**Files:** `docs/validation/citation-audit.md`, `citation-audit-review.md`,
`docs/validation/audit-drafts/`.

The gate was met on invented hexagons. Phase 2 had not loaded a populated
database, so the scores and demographics in those 49 drafts are synthetic. The
statutes and facilities were real and every verification ran against them, which
is what makes the citation result meaningful — but it is not yet a statement
about production behaviour, and CP-22 must not cite it as one.

Depends on a promoted run with real scores: CP-09 if run 12 cleared, CP-13 if it
did not.

Acceptance:
- `make audit-seed`, then `make audit`, against the promoted run.
- 50 drafts across all four document types and a spread of hexes, down to the low
  confidence band, including hexes with two or fewer contributing facilities. The
  insufficient band cannot be drafted from at all and its absence is stated.
- **Gate: zero unverifiable citations in a shown draft.** Every citation
  re-checked independently of the pipeline that produced it.
- The prohibited-language scan runs: no intent or culpability vocabulary except
  in the required negation, no legal advice, and nothing implying a Title VI
  disparate-impact claim can be filed as a lawsuit.
- Harness output, manual review and all drafts committed, as the fixture run did.
- **Budget for a second iteration.** The fixture run found two real defects and a
  design gap on its first pass. A real-data run will find more, and that is the
  gate working rather than the gate failing.

---

## Stage E — the missing frontend

Independent of Stages A to D and the largest block of unwritten code in the
project. Run it alongside rather than after.

## CP-16 · Routing and site chrome · high · M

**Files:** `web/src/App.tsx`, a router, `web/src/components/Nav.tsx`.

`App.tsx` is a single screen: header, banner, map, panel. There is nowhere to put
a second page, which is why four Phase 4 tickets are blocked behind this one.

Acceptance:
- A router, with the map at `/` and the panel's behaviour unchanged. The abort
  handling AUD-10 added to hex selection survives the move.
- Navigation reachable from every view, and a footer carrying the standing
  disclaimer: not legal advice, drafts require human review.
- The chrome works at mobile width, where the panel is a sheet below the map
  rather than a rail beside it.
- Existing tests pass unchanged; the map and panel are not rewritten by this
  ticket.

## CP-17 · Provenance page · medium · M

**Closes** CS-406. **Files:** `web/src/pages/Provenance.tsx`, `web/src/lib/api.ts`.

`GET /provenance` is built, schema'd and tested, and nothing consumes it. This
ticket is mostly rendering.

Acceptance:
- Rendered from the live endpoint, so it cannot go stale. `docs/provenance.md`
  stays the repository-side view of the same data.
- Each source with its vintage, last pull, status, records loaded, records
  rejected and documented gaps. Most recent pull, not most recent successful one:
  a green row from three nights ago would read as current.
- Shows when a source was served from a snapshot rather than fetched, since a
  `stale` run is exactly what a reader deserves to be told.
- Explains the sparse-sensor problem in plain language, and why a missing value
  is never shown as a zero.
- Reachable from the main navigation.

## CP-18 · Methodology, model card and about pages · medium · M

**Files:** `web/src/pages/`.

Acceptance:
- A methodology page, linking the paper and carrying the parts a reader needs
  without opening it: what the score means, what it does not, that percentiles
  are Louisiana percentiles, and that race is recorded but never scored.
- A model card page, rendering CP-22's content. It is a route now and content
  later; CS-405 requires it be linked from the app and not only from the repo.
- An about page carrying the disclaimer, the licence and the data statement.
- Every page reachable from the navigation CP-16 adds.

## CP-19 · Accessibility pass · high · M

**Closes** CS-401. **Files:** `web/`, `.github/workflows/ci.yml`.

Acceptance:
- Keyboard navigation across map, panel and draft viewer. The panel work AUD-10
  did — focus moves to the panel on selection, Escape closes, visible focus
  rings — is the standard the rest meets.
- **A non-map path to the same hex data.** A `/hex/:h3` route reusing `HexPanel`,
  reachable from the search box. The API already returns exactly the payload the
  panel renders, so this is routing rather than new data work.
- Screen-reader labelling for map interactions, plus a manual pass with a real
  screen reader, recorded.
- Colour contrast meets WCAG AA. The ramp stays readable under common colour
  vision deficiencies, and the hatched low-confidence treatment stays
  distinguishable from the ramp itself — hatched rather than faded, because a
  faded fill reads as a lower score and conflates confidence with burden.
- `axe` runs in the `web` CI job and fails the build on a violation.

## CP-20 · Disclaimer and safe-language review · medium · S

**Closes** CS-407. **Files:** everything user-facing.

Acceptance:
- The disclaimer appears on the app and on every generated draft: not legal
  advice, requires human review.
- Every piece of site copy is read for anything asserting intent or wrongdoing
  rather than reporting documented facts.
- The "what this means and doesn't mean" explainers are checked against the
  methodology, including that a low score can mean low burden or can mean the
  indicators that would have caught it are missing.
- Confirmed in writing that there is no send, submit or publish path anywhere in
  the product.

---

## Stage F — the rest of Phase 4

## CP-21 · Rate limiting on the read endpoints · medium · S

**Closes** CS-402. **Files:** `api/app/rate_limit.py`, `api/app/routers/`.

`SlidingWindow` exists and guards `/draft` only. The read endpoints have nothing.

Acceptance:
- Read endpoints limited more loosely than `/draft`, per client, from the same
  window.
- Limits configurable without a redeploy.
- A 429 says what the limit is and how long until a retry will work. The sliding
  window can answer that exactly, which is why it was chosen over a token bucket.
- The honest caveat already written in `rate_limit.py` stays and is repeated
  wherever the limit is documented: this is a courtesy, not a control. Two
  replicas allow twice the limit and a restart forgets everything. The limit that
  cannot be got round is the provider's spend cap.

## CP-22 · Model card · high · M

**Closes** CS-405. **Depends on** CP-15 and CP-18.

Acceptance:
- Intended use, out-of-scope use, the four document types, and the human-review
  requirement.
- The guardrails, each named and located: the sealed corpus, citation
  verification including the proposition check, the facts-only language rules, no
  intent claims, and the refusal to draft from an insufficient-confidence hexagon.
- **The audit it reports is CP-15's, on real scores.** The fixture run is
  described as what it was and is not presented as production behaviour.
- The model and prompt versions actually used, read from the run rather than from
  a constant — the fixture audit found `str()` on a Pydantic AI model returning
  its class name, and every provenance record said `OpenAIChatModel()`.
- Rendered at the route CP-18 added, not only in the repo.

## CP-23 · Performance and payload review · medium · M

**Closes** CS-408.

Acceptance:
- Initial map load measured and improved where it is cheap to do so.
- What a first view actually pulls from the PMTiles archive by Range request,
  measured — not the archive size, which is not the number that matters.
- `GET /hex/{h3}` response time under a realistic click rate, since the panel
  makes one request per hexagon opened.
- Database size measured against the Neon plan with headroom recorded. The scored
  grid, the facility tables and the pgvector corpus are the three that grow.

## CP-24 · Architecture write-up · medium · M

**Closes** CS-409. Last, because it needs the final validation result whichever
way it goes.

Acceptance:
- The architecture and the design decisions, including the rejected ones and why.
- The interesting problems honestly: dasymetric interpolation, sparse sensor
  coverage, citation verification, and recording race without scoring it.
- The §13.6 disparity result with its independence argument intact.
- **The validation history as it happened.** Run 11's failure, what it was
  diagnosed as, what changed, and what the final run showed. A write-up that
  presents only the passing run misrepresents the method that produced it, and
  the method is the most interesting thing here.
- Screenshots, and links to the app, the repo, the paper and the model card.

## CP-25 · Score and build tiles nightly; promotion stays manual · medium · M

**Files:** `.github/workflows/etl.yml`.

The nightly job ingests, gates and regenerates the provenance page. It does not
score, build tiles, upload them or promote a run — those are `make score`,
`make tiles`, `make deploy-tiles`. A good night does not update the map.

Acceptance:
- After a night clears the quality gate, the workflow scores it and builds the
  archive, as artifacts.
- **Promotion stays manual until Phase 2 exits.** Promoting a run that has not
  cleared §13 would put an unvalidated score on the map, which is the single
  failure this project's discipline exists to prevent. Automating promotion is
  part of CS-410 and is gated on the validation harness passing, not on the
  quality gate passing.
- A night that fails the gate promotes nothing and says so, as it already does.
