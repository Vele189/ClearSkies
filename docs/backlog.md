# ClearSkies — Ticket Backlog

Tickets grouped by build phase. No dates; each phase closes when its exit
condition is met.

**Conventions**

- IDs: `CS-0xx` Phase 0, `CS-1xx` Phase 1, and so on.
- Size: S (under a day), M (a few days), L (a week or more).
- Dependencies reference ticket IDs. Anything with no dependency can start immediately.
- Owner: **Lead** (technical lead) or **Terrence** (junior). Every ticket has exactly one owner.
- Status: **Done**, **Partly done**, or **Not started**, judged only against what is
  in the repository. Anything that lives in a GitHub or Railway setting rather
  than in a file is marked unverified.

---

## What changed in this revision

This backlog was written before the repository existed. It has been reconciled
against the code as it now stands. The substantive changes:

**Hosting is Railway, not Supabase plus Render plus Vercel.** Three services in
one repo (`web`, `api`, `db`), each pointing at a different root directory, with
service definitions in `.railway/railway.ts`. The database is a custom image
built from `infra/postgres`, not a managed free-tier project, so the 500 MB
ceiling that shaped several tickets is gone and replaced by a Railway volume.
Cloudflare R2 hosts PMTiles only, because tiles are read with HTTP Range
requests and Railway bills egress.

**Railway does not idle a service.** Every acceptance criterion about free-tier
cold starts has been removed or replaced. This mainly rewrites CS-408 and part
of CS-403.

**The pilot state is Louisiana and the methodology is written.** Tickets that
described work in the abstract now name the indicators, weights, component
names, group minimums and confidence terms that `docs/methodology.md` and
`api/app/indicators.py` actually specify.

**The adapter interface shipped.** CS-101 through CS-105 are no longer "write an
adapter"; they are "implement `SourceAdapter` in `etl/pipeline/adapters/`" with
the retry, rate limit, partial-failure, snapshot and provenance behaviour
inherited rather than rewritten. Several acceptance criteria in CS-108 and
CS-110 were already satisfied by that interface and have been narrowed to what
is genuinely left.

**The validation set is larger than the ticket described.** Thirty registered
sites, not ten: ten active Louisiana sites, ten inactive out-of-state sites,
four negative controls and six stress cases. The gate is unchanged at 8 of 10,
but the negative-control and stress criteria were missing from CS-206 entirely.

**The statute corpus includes bounded case law.** CS-301 previously said case
law was deliberately excluded. Appendix B includes two cases, and *Sandoval* is
in the corpus for a specific reason that the ticket now records.

**Four tickets added** for work the codebase requires and the backlog did not
cover: CS-009 (verify the Railway service definitions), CS-111 (verify the
validation anchors, which are all committed as `verified: false`), CS-212
(robustness checks, methodology section 13.5) and CS-213 (disparity analysis,
section 13.6).

**One dependency corrected.** CS-303 depended on CS-005, the data source adapter
interface, which has nothing to do with document schemas. It now depends on
CS-004.

---

## Ownership

52 tickets: 27 Lead, 25 Terrence.

**What lands with the Lead**

- Anything that defines the methodology or the weights. Once these are wrong,
  everything downstream is wrong and the error is invisible.
- The two phase gates (CS-206, CS-308) and the validation set (CS-003, CS-111).
  The person who wrote the scoring shouldn't be the only one checking it, but
  the sign-off has to sit with the lead.
- Every safety-critical piece of the drafting assistant: corpus curation, prompt
  rules, citation verifier, disclaimer review. A hallucinated citation or an
  intent claim in a public draft is the project's one genuinely serious failure
  mode.
- Interfaces and contracts others build against: the adapter interface, the API
  response schema, the base database schema.
- The first instance of a repeated pattern (CS-101, CS-202), so Terrence has a
  worked example to follow instead of a spec to interpret.

**What lands with Terrence**

- Implementation against a written spec with a checkable answer: the remaining
  adapters, percentile utilities, spatial joins, tile builds.
- Infrastructure plumbing where failure is loud and recoverable: scheduled jobs,
  deploy config, monitoring, rate limiting.
- Most of the frontend. It's high-visibility, mistakes are obvious, and it's the
  best place for a junior to build real ownership of something.
- Documentation that benefits from fresh eyes (CS-404) — he'll hit the setup
  problems the lead has already unconsciously worked around.

**Tickets with a split inside them**

These stay assigned to one owner, but need a specific handoff:

| Ticket | Owner | Handoff |
|---|---|---|
| CS-001 Pilot state | Lead | Done. Terrence compiled the coverage and sizing comparison; Lead made the call. |
| CS-108 Data quality checks | Lead | Lead sets the thresholds on top of the interface's generic ones; Terrence adds per-source checks in the same PR as each adapter he owns. |
| CS-111 Anchor verification | Lead | Terrence checks each anchor against its cited documentation; Lead decides whether a correction is a methodology revision under section 17. |
| CS-203 Population characteristics | Terrence | Weights come from the methodology paper, not from judgment at the keyboard. Lead reviews before it feeds CS-204. |
| CS-210 Map shell | Terrence | Colour ramp, legend and the confidence-band treatment need Lead sign-off — how uncertainty is drawn is a communication decision, not a styling one. |
| CS-211 Detail panel | Terrence | Lead writes the "what this means and doesn't mean" copy. Terrence builds everything around it. |
| CS-306 Generation endpoint | Terrence | Lead sets the hard spend cap on the API key directly with the provider; Terrence owns caching and usage logging. |
| CS-307 Draft viewer | Terrence | Lead reviews all disclaimer copy and confirms there's no send or publish path, as part of CS-407. |
| CS-308 50-draft audit | Lead | Terrence generates the drafts and does the first pass on record ID verification. Lead does the language review for intent claims and legal advice, and signs off the gate. |
| CS-404 README and docs | Terrence | Terrence verifies clean-machine setup and writes the walkthrough; Lead writes the architecture overview and diagram. |

**Sequencing notes**

- Phase 0 is effectively closed. Six of nine tickets are done, CS-006 and CS-008
  have a defined remainder, and CS-007 is the only one not started.
- CS-005 is done, which was the blocker on Terrence's Phase 1 queue. CS-102,
  CS-104 and CS-105 can all start now against the worked example in
  `etl/pipeline/adapters/fake.py`.
- CS-006's remaining half is now the critical path for everyone: no adapter can
  load anything until the Postgres sink and the base tables exist. Do it before
  CS-101.
- CS-106 is code-complete and its arithmetic is tested, but it cannot run until
  CS-112 loads the 2020 block layer it reads. The transformation and its
  ancillary data were split across a ticket that existed and one that did not,
  so the gap only showed up when the interpolation went looking for blocks.
  CS-112 is the thing to schedule before any tract-sourced indicator is
  expected to produce a number.
- Terrence's Phase 2 work (CS-207, CS-208, CS-210) can run in parallel with the
  lead's scoring work, since tiles and the API skeleton only need the score's
  shape, not its final values. The shape is already fixed in `api/app/schemas.py`,
  so both sides can move.
- Phase 3 is the reverse of Phase 4: lead-heavy on safety, then Terrence carries
  most of the polish and launch prep while the lead writes the model card and
  the write-up.

---

## Phase 0 — Foundations

**Exit condition:** methodology paper written, repo builds green in CI.

---

### CS-001 — Select the pilot state and record the rationale

**Size:** S · **Labels:** decision, docs · **Depends on:** — · **Owner:** Lead · **Status:** Done

Pick one US state for the first release and write down why, so the choice is
defensible and scope is locked.

**Acceptance criteria**

- Candidate states compared on: data coverage in ECHO, TRI and AirToxScreen,
  OpenAQ sensor density, number of known EJ sites available for validation, and
  dataset size against the Railway volume.
- Chosen state and rationale committed to the repo.
- A note in the README stating that national coverage is out of scope.

**What landed:** Louisiana, argued in `docs/methodology.md` section 4 and locked.
The README carries the out-of-scope note and states that percentiles are
Louisiana percentiles, so a Louisiana 90th percentile is not a national one.

---

### CS-002 — Write methodology paper v0

**Size:** L · **Labels:** docs, methodology · **Depends on:** CS-001 · **Owner:** Lead · **Status:** Done

The scoring methodology is written before any scoring code exists, so the score
can't be quietly tuned to fit the results.

**Acceptance criteria**

- Documents: indicator list, source per indicator, weights, normalization
  approach (statewide percentile rank), the pollution × vulnerability structure,
  missing-data handling, and how the confidence value is derived.
- States explicitly what the score does **not** mean.
- Lives in the repo as Markdown, versioned, with a changelog section for later
  weight changes.
- Reviewed against the published CalEnviroScreen and EJScreen methodologies,
  with any deliberate divergences called out.

**What landed:** `docs/methodology.md` at v0.1.1, nineteen sections plus Appendix
A (the validation set) and Appendix B (the statute corpus manifest). Section 3
covers prior art and divergences, section 15 covers what the score is not,
section 17 is the revision policy and section 18 is the changelog. Section 14
argues at length for recording race but not scoring it, which is the project's
most consequential design decision and was not in the original ticket.

---

### CS-003 — Fix the validation set before scoring exists

**Size:** M · **Labels:** methodology, validation · **Depends on:** CS-001 · **Owner:** Lead · **Status:** Done

Lock in the environmental justice sites used to validate the score, so the
target is set before the code that hits it.

**Acceptance criteria**

- Ten active Louisiana sites selected, each with a citation to public
  documentation of the burden.
- Each site resolved to an explicit set of H3 resolution 8 cells, frozen in the
  fixture rather than derived at scoring time.
- Out-of-state sites registered now and marked inactive, scoreable only if
  coverage extends. Flipping `active` is a pre-declared transition, not a change
  to the set.
- Negative controls and stress cases registered alongside the high-burden sites.
- Committed as a fixture file, treated as read-only from this point, with CI
  enforcing both the commit ordering and the file's internal consistency.

**What landed:** `docs/validation/sites.yml`, schema version 2, status closed,
thirty registered sites: ten active Louisiana high-burden sites, ten inactive
out-of-state sites, four negative controls, three "not a poverty map" stress
cases and three "not an emissions map" stress cases. Every site's cells are
derived once from an anchor with `h3.grid_disk` and frozen.
`scripts/check_preregistration.sh` enforces that the fixture precedes any file
under `scoring/`; `scripts/check_validation_set.py` re-derives every cell list
from its anchor and fails CI if they disagree. Both run in CI.

**Note:** every anchor was committed with `verified: false`. CS-111 verified
them on 2026-09-11 and corrected three that named a community they did not sit
in; twenty-nine of thirty now carry `verified: true`.

---

### CS-004 — Repo scaffolding and CI

**Size:** M · **Labels:** infra · **Depends on:** — · **Owner:** Lead · **Status:** Done

Set up the monorepo, tooling, and a CI pipeline that runs on every push.

**Acceptance criteria**

- Python 3.12 backend and TypeScript frontend in one repo with clear directory
  boundaries.
- Lint, format, and type-check configured for both: ruff and mypy in strict mode,
  eslint with type-aware rules and `tsc --noEmit`.
- Pytest and a frontend test runner wired up with at least one real test each.
- GitHub Actions workflow runs lint, types, and tests on push and PR.
- MIT licence, contribution notes, and issue templates in place.

**What landed:** `api/` and `web/`, with `etl/` added by CS-005. Five CI jobs:
pre-registration, API, ingestion, frontend, and a database job that builds the
custom image and asserts all four extensions load. MIT licence, `CONTRIBUTING.md`
and four issue templates covering bugs, scoring problems, methodology changes
and data sources.

**Remaining, unverified from the repo:** branch protection requiring CI to pass
is a GitHub setting and cannot be confirmed from a checkout.

---

### CS-005 — Define the data source adapter interface

**Size:** M · **Labels:** architecture, backend · **Depends on:** CS-004 · **Owner:** Lead · **Status:** Done

One interface that every data source implements, so adding a sixth source later
is a contained change.

**Acceptance criteria**

- Abstract adapter defining: fetch, validate, normalize, and load stages.
- Standard metadata every adapter must emit: source name, version or vintage,
  pull timestamp, record count, known gaps.
- Retry, rate limit, and partial-failure behaviour specified once at the
  interface level rather than per adapter.
- A reference implementation against a trivial fake source, covered by tests.
- README section: "how to add a new data source."

**What landed:** `etl/pipeline/adapters/base.py` defines `SourceAdapter` with the
four stages; `load` has a working default so most adapters implement three
methods. `pipeline/policy.py` holds one `SourcePolicy` carrying the retry policy
with jittered backoff, a token-bucket rate limit and the partial-failure
tolerance. `pipeline/runner.py` sequences the stages, counts rejections against
that tolerance, opens and commits the sink transaction, and emits a
`PullMetadata` for every run including failed ones. Statuses are `ok`, `partial`,
`stale` and `failed`; a pull that exceeds its tolerance loads nothing and leaves
the previous data in place, and an unreachable source re-runs fetch against the
last good snapshot and reports `stale`. `Measurement` makes it structurally
impossible to store a missing value as a zero. `etl/README.md` carries the full
contract and the walkthrough. Sixty-seven tests, ruff and mypy strict clean.

---

### CS-006 — Provision the database and base schema

**Size:** M · **Labels:** infra, database · **Depends on:** CS-004 · **Owner:** Lead · **Status:** Partly done

Stand up Postgres with the extensions the project depends on and get migrations
under version control.

**Acceptance criteria**

- A Postgres image with PostGIS, h3, h3_postgis and pgvector, built from source
  in the repo rather than configured by a dashboard click. **Done:**
  `infra/postgres/Dockerfile` plus `initdb/01-extensions.sql`, with a
  `clearskies_extensions` view that `GET /health` reports so a deploy can prove
  which image is running.
- Local development path documented. **Done:** `docker-compose.yml` builds the
  same image, `make up` waits for the init scripts rather than the socket, and
  `make extensions` prints the versions.
- Migration tooling configured; schema changes only ever land via migration.
  **Not started.** Alembic or equivalent, wired into `make migrate`, which
  currently exits with a Phase 1 message.
- Base tables for facilities, releases, exposure, measurements, demographics,
  hexes and scores. **Not started.** The API already queries `hex_score` by name
  and degrades when it is absent, so that name is fixed.
- A Postgres implementation of the `Sink` protocol from CS-005, so adapters can
  load for real. **Not started.** It must preserve the two properties the
  in-memory reference has: upsert on the natural key, and all-or-nothing commit
  of the records together with their `PullMetadata`.

---

### CS-007 — Generate the H3 hex grid for the pilot state

**Size:** S · **Labels:** geospatial · **Depends on:** CS-001, CS-006 · **Owner:** Terrence · **Status:** Not started

Produce the fixed set of resolution 8 hexes that everything else joins against.

**Acceptance criteria**

- Full resolution 8 coverage of Louisiana's land area plus coastal water out to
  the state boundary.
- Hexes intersecting the state line are included if their centroid falls inside
  Louisiana, per methodology section 5. Percentile denominators later use
  included hexes only.
- Stored in PostGIS with the H3 index as primary key and geometry alongside.
- Cell indexes computed in Python with h3-py during the job, not by `h3-pg`. The
  extension is present for ad-hoc queries and the pipeline must not depend on it.
- Hex count and total area recorded and sanity-checked against Louisiana's
  published area. Expect roughly 150,000 populated cells at a mean cell area of
  0.737 km².
- Idempotent: re-running does not duplicate rows.

---

### CS-008 — Configuration and secrets handling

**Size:** S · **Labels:** infra, security · **Depends on:** CS-004 · **Owner:** Terrence · **Status:** Partly done

One config path for local, CI, and deployed environments; no credentials in the
repo.

**Acceptance criteria**

- Typed settings object covering database URL, LLM API key, CORS origins, log
  level and the pilot state. **Done:** `api/app/config.py` using
  pydantic-settings, with an `lru_cache`d accessor.
- Absent LLM key degrades rather than crashes. **Done:** the draft endpoint is
  specified to return 503 rather than failing at import.
- `.env.example` committed; real `.env` gitignored. **Done.**
- GitHub Actions secrets configured for the scheduled job. **Not started.**
  CS-104 made this real: the OpenAQ adapter reads `OPENAQ_API_KEY` through
  `ctx.credential`, so the nightly workflow needs that secret before E4 can be
  pulled. Without it the pull fails with a legible reason and the other sources
  are unaffected.
- Secret scanning enabled on the repo. **Unverified:** a GitHub setting, not a
  file.

---

### CS-009 — Verify the Railway services and regenerate the IaC file

**Size:** S · **Labels:** infra, deploy · **Depends on:** CS-004 · **Owner:** Terrence · **Status:** Not started

`.railway/railway.ts` is committed as a starting point that has never been run
against a live project. It says so at the top of the file.

**Acceptance criteria**

- Three services created with the correct root directories: `web` at `/web`,
  `api` at `/api`, `db` at `/infra/postgres` with a volume at
  `/var/lib/postgresql/data`.
- Watch paths scoped so a frontend commit does not redeploy the API.
- CDN enabled on `web` only. The draft endpoint is a POST returning per-hex
  generated documents, and an edge cache in front of it buys nothing and risks
  serving one request's output to another.
- `railway config pull` run after the services work, so the committed file
  reflects reality rather than a guess. Watch paths and Dockerfile path are not
  in the published IaC reference and may need to be set in the dashboard first.
- The repository placeholder in the file replaced with the real repository.
- Confirmed before the 2026-12-01 cutoff, after which `railway.json` is no longer
  supported. Note that a service cannot be managed by the dashboard and by
  infrastructure as code at the same time.

---

## Phase 1 — Data pipeline

**Exit condition:** full pilot state dataset loaded in PostGIS via the nightly
job.

Every adapter in this phase subclasses `SourceAdapter` and registers itself.
None of them writes a retry loop, a rate limiter, a partial-failure rule or a
provenance manifest; those come from the interface. The contract and a worked
example are in `etl/README.md`.

---

### CS-101 — EPA ECHO/ICIS adapter

**Size:** L · **Labels:** etl · **Depends on:** CS-005, CS-006 · **Owner:** Lead · **Status:** Not started

Facilities, permits, violations and enforcement actions for Louisiana. Feeds
indicators F1 through F4.

**Acceptance criteria**

- Implemented as `pipeline/adapters/echo.py`, registered, and listed by
  `python -m pipeline sources`.
- Facility records carry the EPA FRS registry identifier, which is what the
  detail panel's link back to the public record page is built from.
- Violation and enforcement history retained with dates, so the twelve quarters
  of non-compliance behind F2 and the five years of formal actions behind F3 can
  be computed later.
- Pagination handled inside `fetch`. Rate limits and transient failures are the
  interface's job; the adapter declares its rate limit on the class and does
  nothing else about it.
- Positional accuracy handled per methodology section 6: facilities whose
  coordinates fall outside Louisiana's boundary buffer, or more than 2 km from
  their reported ZIP centroid, are rejected with a stated reason and counted.
  The exclusion count reaches the provenance page through the manifest.
- Known gaps declared on the adapter, including the 2025 withdrawals of EPA
  environmental justice datasets that make the stale fallback necessary.
- Tests run against recorded fixtures through a mock transport, never the live
  API.

---

### CS-102 — EPA TRI adapter

**Size:** M · **Labels:** etl · **Depends on:** CS-005, CS-006 · **Owner:** Terrence · **Status:** Not started

Annual toxic release volumes by facility. Feeds indicator E3.

**Acceptance criteria**

- Releases loaded per facility per year per chemical, with units normalized.
- Reporting year is the manifest's `vintage`, so the pipeline can never silently
  mix vintages and the recency term reflects the release rather than the
  download date.
- Joins to ECHO facilities on the FRS identifier. Unmatched facilities are
  counted and surfaced in the manifest rather than dropped quietly.
- A facility reporting zero releases is `Measurement.of(0.0)`, an observation. A
  facility that did not report is `Measurement.absent()`. The two are never
  merged.

---

### CS-103 — EPA NEI / AirToxScreen adapter

**Size:** L · **Labels:** etl · **Depends on:** CS-005, CS-007 · **Owner:** Lead · **Status:** Not started

Modeled air toxics exposure, the primary pollution input because it covers every
area evenly. Feeds indicators E1 and E2.

**Acceptance criteria**

- Modeled cancer risk and respiratory hazard index loaded at census tract level
  and mapped onto the resolution 8 grid.
- Mapping follows methodology section 7. These are intensive quantities, so they
  are combined as a population-weighted mean of the source values overlapping
  the hex, never area-averaged and never recomputed from separately interpolated
  numerators and denominators.
- Every hex in the pilot state receives a value or an explicit, counted absence.
- Model vintage recorded as the manifest's `vintage`. The release reflects an
  emissions inventory several years old and the recency term must see that.

---

### CS-104 — OpenAQ adapter with sparse-coverage flagging

**Size:** M · **Labels:** etl · **Depends on:** CS-005, CS-007 · **Owner:** Terrence · **Status:** Done

Measured daily air quality, plus honest signalling of where sensors don't exist.
Feeds indicator E4 and the `c_monitor` confidence term.

**Acceptance criteria**

- Daily PM2.5 measurements pulled for Louisiana and attached to the nearest hex.
- Beyond 25 km from a monitor the value is `Measurement.absent()`, never zero and
  never a neighbour's reading. An unmonitored area is uncertain, not clean.
- Distance to the nearest monitor stored per hex, because `c_monitor` is
  `min(1, 10 km / d_nearest)` and the detail panel displays the distance.
- Observation count and measurement recency stored per hex.
- Documented rule for outlier and obviously faulty sensor readings, applied in
  `validate` so rejections are counted like any other.

**What landed:** `etl/pipeline/adapters/openaq.py`. Daily PM2.5 for the pilot
envelope from OpenAQ v3, each location placed on its resolution 8 cell, each
daily mean stored with the hourly observations behind it. Migration `0012` adds
`hex_air_quality`, one row per hex per pollutant: the inverse-distance weighted
annual mean where a monitor is within 25 km, `Measurement.absent()` where none
is, and the distance to the nearest reporting monitor either way. Two check
constraints hold the missing-data rule at the schema level: an unobserved hex
cannot carry a value, and an observed one cannot claim a measurement with no
monitor-days behind it.

Two radii, doing different jobs. Twenty-five kilometres is section 8.1's
interpolation cutoff. Two hundred is where `min(1, 10 / d)` reaches the 0.05
floor section 12 puts on every confidence term, so past it a stored distance
cannot change a score; hexes beyond it get no row and the pull counts them as a
known gap, which checks the assumption that Louisiana has none rather than
believing it.

Screening is one predicate per grain, shared by `fetch` and `validate` so the
two can never disagree: negative concentrations, the `-999` family of sentinels,
daily means above the 500 µg/m³ AQI ceiling, days flagged by the provider, days
built from under 75% of expected hours, and a fortnight of the identical value,
which is a stuck instrument. Each rejection is counted and sampled like any
other. A high wildfire-smoke day is exactly the observation E4 exists to capture
and survives all of it. A monitor reporting fewer than 274 usable days still
anchors `c_monitor` — it exists and is being read — but its mean does not enter
E4, and a monitor that has gone silent anchors nothing.

OpenAQ is the first source that authenticates, so `RunContext` grew
`credential()` and `pipeline/__main__.py` grew `CREDENTIAL_ENV`, the one place
in the package that reads the environment. A missing key is a `PermanentSourceError`:
a failed pull with a legible reason, not a crash that takes the nightly job
down. Forty tests against a synthetic network, `0012` applied and reverted
against the project image, ruff and mypy strict clean.

**Not yet verified against the live service.** No OpenAQ key was available, so
the request and response shapes come from the service's published OpenAPI
document rather than from a recorded extract. Two details it settles are worth
re-checking on the first authenticated run: the PM2.5 `parameters_id` of 2, and
that `/v3/sensors/{id}/days` takes `date_from` and `date_to` where its hourly
siblings take `datetime_from` and `datetime_to`.

---

### CS-105 — US Census ACS adapter

**Size:** M · **Labels:** etl · **Depends on:** CS-005, CS-006 · **Owner:** Terrence · **Status:** Not started

Tract-level demographics. Feeds indicators S1, S2 and P1 through P5, plus the
race and ethnicity fields that are recorded and displayed but never scored.

**Acceptance criteria**

- All required ACS variables pulled at tract level, with the ACS 5-year release
  as the manifest's `vintage`.
- Margins of error retained alongside estimates. The coefficient of variation
  travels with the value into the `c_spatial` confidence term, and estimates
  above 0.30 degrade confidence rather than being dropped, because dropping them
  preferentially removes small and rural populations.
- Race and ethnicity loaded into their own fields, clearly separated from the
  scored indicators. Methodology section 14 is the reason: keeping them out of
  the arithmetic is what makes the later disparity finding an independent result.
- Tract geometries loaded and validated against the state boundary.

---

### CS-106 — Dasymetric areal interpolation from tracts to hexes

**Size:** L · **Labels:** geospatial, methodology · **Depends on:** CS-105, CS-007, CS-112 · **Owner:** Lead · **Status:** Done

Move census data from tracts onto hexes without smearing population across empty
land. The method is already specified in methodology section 7; this ticket
implements it.

**Acceptance criteria**

- 2020 Decennial Census block population counts (PL 94-171) used as the ancillary
  layer, per section 7.
- Extensive quantities (counts) apportioned by block population share and block
  area share. Intensive quantities (rates and modeled risks) combined as a
  population-weighted mean. The two are never confused, which is the most common
  source of error in this step.
- Where a rate has a published numerator and denominator, both are interpolated
  as extensive quantities and the rate derived once at the end.
- Margins of error combined in quadrature under the Census Bureau's approximation
  for derived sums, with the resulting coefficient of variation carried through.
- Statewide population totals after interpolation match tract totals within a
  documented tolerance.
- Unit tests covering a hand-checkable synthetic case.
- The known error, that population is assumed uniform within a block, is already
  recorded in section 7; confirm the implementation matches what is written
  rather than writing a new description.

---

### CS-107 — Facility-to-hex spatial assignment

**Size:** M · **Labels:** geospatial · **Depends on:** CS-101, CS-007 · **Owner:** Terrence · **Status:** Done

Attach facilities to hexes, both for the drill-down list and for the
distance-decayed proximity indicators.

**Shipped.** The assignment rules are `etl/pipeline/geo`, shared by every source
that publishes a point rather than living in the ECHO adapter. The neighbour
query is migration `0014`: `hex_facility_links` for one hexagon,
`hex_facility_links_all` for the grid, `facilities_near_hex` for the panel, all
over one geography index and one decay kernel, so the panel and the score cannot
disagree about what is near a hexagon. `api/app/facilities.py` is the read path
`GET /hex/{h3}` calls once CS-205 has a score to attach it to.

One thing the query is ready for and the pipeline is not. Nothing filters on
state, so an out-of-state facility within the interaction radius contributes as
section 5 requires — but the ECHO adapter queries one state at a time, so there
are no Texas facilities in the table yet to contribute. Until a neighbouring-
state pull lands, hexes along the state lines understate F1 through F4, and the
adapter declares that as a known gap rather than leaving it to be discovered.

**Acceptance criteria**

- Each facility assigned to its containing hex, for the panel's contributing
  facilities list.
- A neighbour query supporting the decay calculations: inverse-square with a
  10 km cutoff for E3, distance-decayed counts for F1 through F4. Out-of-state
  facilities within the interaction radius are included, so a hex on the Texas
  line near a Beaumont-area facility is not artificially clean.
- Facilities with missing, zeroed or clearly wrong coordinates are quarantined
  and counted, not dropped silently. This is the same rejection path CS-101
  uses, so the counts appear in the manifest.
- Geocoding quality flag stored per facility.
- The hex-to-facilities query path is indexed and fast enough for `GET /hex/{h3}`.

---

### CS-108 — Data quality checks and pipeline gate

**Size:** M · **Labels:** etl, testing · **Depends on:** CS-101, CS-102, CS-103, CS-104, CS-105 · **Owner:** Lead · **Status:** Done

A bad load should fail loudly, not quietly poison the score.

The adapter interface already provides the generic half of this: per-record
rejection counting, a tolerance rule that refuses to load a pull that lost too
much, duplicate natural key detection, and a manifest for every run including
failures. What remains is source-specific and cross-source.

**Acceptance criteria**

- Per-source thresholds tuned beyond the interface default: expected row count
  range, required-field null rates, geometry validity, plausible value bounds.
  **Done:** `etl/pipeline/quality/expectations.py`, all five sources, every
  number carrying the reason it holds that value.
- Cross-source checks the interface cannot see: TRI facilities matching ECHO
  facilities above a threshold, tract coverage complete after interpolation,
  every scored hex having at least the group minimums from section 11.
  **Done:** `etl/pipeline/quality/cross.py`.
- Check results persisted per run alongside the manifests, so trends over time
  are visible. **Done:** a directory per run plus an append-only history file,
  and the `quality_run` and `quality_check_result` tables in migration `0015`.
- Failure surfaces somewhere visible rather than only in a log. **Done:** the
  Actions step summary, a workflow annotation per failure, a non-zero exit
  status, the persisted tables, and a thirty-day run artifact.

**What landed:** `etl/pipeline/quality/`, `python -m pipeline check` and
`python -m pipeline history`, migration `0015`, `docs/quality.md`, and 68 tests.
The gate runs in CI on every pull request and in the nightly job.

**Four statuses, not two.** `skip` is a first-class result. A check that could
not run is not a check that passed, and a gate reporting green because half its
checks found no data is the failure this ticket exists to close. `--require`
names the sources a run must produce, and turns a skip on one of them into a
failure.

**Two things are deliberately not finished here, and the gate says so every
run rather than hiding it.**

*Most thresholds are envelopes, not tuned ranges.* Four of the five adapters are
on unmerged branches and have never run against live upstream, so the numbers are
set to catch catastrophe rather than drift. That is why every run persists the
value it observed: `python -m pipeline history` is the evidence for narrowing
them, and doing so is a follow-up once a fortnight of nightly runs exists.

*The section 11 group minimums are checked only where a hex-level table exists.*
E1, E2 and E4 have one. E3 and F1 through F4 need CS-107 and CS-202; S1, S2 and
P1 through P5 need CS-106. Those groups report `skip` naming the indicators they
could not look for, because evaluating a group on the indicators that happen to
exist invents failures. Each becomes live by adding one line to
`HEX_INDICATORS`.

*The nightly job gates the reference adapter only.* Running the five real
sources in dependency order is CS-109, and pointing the nightly job at live EPA
endpoints belongs in the ticket that owns that decision.

---

### CS-109 — Nightly ETL workflow on GitHub Actions

**Size:** M · **Labels:** infra, etl · **Depends on:** CS-108 · **Owner:** Terrence · **Status:** Done

Scheduled orchestration of every adapter, with no server to manage.

The orchestration lives in `python -m pipeline nightly`, not in workflow steps,
because it has rules worth testing and a rule written in YAML is a rule no test
can reach. The job installs the package and calls it. See `docs/nightly.md`.

**Acceptance criteria**

- Scheduled workflow exists with a manual trigger. **Done:**
  `.github/workflows/etl.yml` runs at 07:00 UTC, roughly 01:00 in the pilot
  state, and supports `workflow_dispatch` with a `force` input for the morning a
  new release lands.
- All adapters run in dependency order. **Done:** `pipeline/schedule.py`
  topologically sorts the declared graph and orders cheapest first within a
  level, so a night cut off by the timeout has spent its minutes on the sources
  most likely to have finished. Today's edge set is empty and that is designed
  rather than missing: the adapter interface gives a source no way to read
  another, and TRI joins ECHO's registry ids from ECHO's own endpoint. A test
  asserts the emptiness so a future edge has to be argued for. The mechanism is
  here because CS-106, CS-107 and CS-204 consume what the adapters write, and
  each should land as one entry rather than as a rewrite of the job.
- Refresh cadence is per-source and documented. **Done:** one interval per
  source, each carrying its reason, in `pipeline/schedule.py` and tabulated in
  `docs/nightly.md`. OpenAQ and the reference adapter pull nightly, ECHO every
  seven days to match its upstream refresh, and the three annual sources every
  thirty. The interval counts from the last success, so a failing source stays
  due nightly instead of resting out its cadence. A source that is not due is
  *carried*, which the ledger records as a distinct outcome from a failed pull.
- Run stays inside GitHub Actions free-tier limits. **Done:** about 275 minutes
  a month against the 2,000-minute private-repo floor, and unmetered on a public
  one. The cadence policy is what buys that: pulling all six nightly would be
  roughly 900 minutes for identical numbers. The job carries a 45-minute timeout
  and a concurrency group, so a scheduled run and a hand-triggered one cannot
  load at once.
- Failures notify, and a failed run leaves the previous dataset intact as a
  whole. **Done:** the run is recorded and then not promoted. Nothing is rolled
  back, because every source's transaction closed before the gate ran; the map
  keeps serving the run that last passed. `pipeline/ledger.py` mirrors
  `pipeline_run` from migration 0002, including the rule that only a succeeded
  run may be current. A night on which every source was carried is also not
  promoted, since its gate passed by having nothing to check. Failure surfaces
  as a non-zero exit, the step summary, annotations, a 30-day artifact, and an
  issue labelled `nightly-etl` that is commented on rather than reopened nightly.

**Interim, and named as such.** The ledger is files carried between runs by the
Actions cache. Its durable home is `pipeline_run`, and it moves there with the
Postgres sink; `row_for_sql` already emits the table's shape. A cache miss costs
one redundant full pull and nothing else, which is the right failure direction.

---

### CS-110 — Provenance capture

**Size:** S · **Labels:** etl, docs · **Depends on:** CS-109 · **Owner:** Terrence · **Status:** Done

Record where every number came from and when, feeding the public provenance page
later.

**Acceptance criteria**

- Per source: last successful pull, dataset vintage, record count and known gaps.
  **Done at the source:** `PullMetadata` carries all of it plus checksummed
  artifacts, a rejection histogram and the run status.
- The page exists and explains itself. **Done:** `docs/provenance.md`, with a
  generated block and the column definitions.
- Manifests persisted so history is queryable, not just the latest run.
  **Done:** migration 0016 adds `source_pull` with `source_pull_gap` and
  `source_pull_artifact`, and `pipeline/provenance.py` records every pull to an
  append-only history whose `rows_for_sql` emits those exact shapes. The history
  matters because the page's question is "where did this number come from", and
  a reader checking a claim from last month needs last month's manifest rather
  than tonight's.
- The generated block regenerated by the nightly job. **Done:** a `provenance`
  step rewrites the block between the markers from the recorded manifests and
  commits the page only when it changed, so a quiet night produces no commit.
  The generator raises rather than guessing if the markers are missing: one that
  invents a place to write is one that duplicates the table the first time
  somebody reformats the page.
- Exposed through an endpoint for CS-406. **Done:** `GET /provenance` returns the
  latest pull of each source, and `GET /provenance?source=epa_echo` that source's
  history. It reports 503 with a reason when nothing has been ingested, because
  an empty list would read as "no source has ever been pulled".
- Values are written by the pipeline itself, never maintained by hand. **Done.**

**One rule runs through it.** A failed pull is published as a failed pull. The
page and the endpoint both show the most recent pull rather than the most recent
successful one, since a green row from three nights ago tells a reader the data
is current when it is not.

**Interim, and named as such.** The history is a file carried between runs by the
Actions cache, on the same terms as the CS-109 ledger. It moves into the 0016
tables with the Postgres sink.

---

### CS-111 — Verify the validation set anchors

**Size:** M · **Labels:** validation, methodology · **Depends on:** CS-003, CS-007 · **Owner:** Lead · **Status:** Done

Every one of the thirty registered sites carries `verified: false`. The anchors
were chosen from documentation without being checked against the grid, and the
gate in CS-206 is meaningless until they are.

**Acceptance criteria**

- Each anchor checked against the documentation cited for that site, confirming
  it names the right community and falls where the citation says.
- Each anchor's frozen cell list confirmed to cover the site's physical extent at
  the chosen `k`.
- `verified: true` set only where the check passes.
- A correction that moves an anchor is a methodology revision under section 17:
  recorded in the changelog with a rationale, and it triggers a re-run of the
  full protocol. An anchor is never moved because it would improve a result, and
  the distinction is recorded explicitly for any anchor that changes.
- Completed before CS-206 runs.

**What landed:** 29 of 30 anchors verified. `docs/validation/anchor-references.yml`
records an externally sourced coordinate for every site's community and for the
facilities its citations name, each carrying its authority: USGS GNIS for place
names, US Census TIGERweb for parish and place boundaries, EPA ECHO and FRS for
facilities. `scripts/verify_anchors.py` re-checks every anchor against them and
fails CI if any `verified` flag disagrees with the evidence; it runs in CI and in
`make check` alongside `check_validation_set.py`. Method and full results are in
`docs/validation/anchor-verification.md`, changelog entry in methodology §18
v0.1.2.

Three anchors named a community they shared no cell with and were corrected under
§17.4, each moved mechanically to that community's published GNIS coordinate with
`k` untouched: site 2 Welcome (was 4.21 km east, at the historical Uncle Sam
site), N-WARREN Afton (was in Franklin County, 19.16 km away) and N3 Bocage (was
1.91 km away, outside its own k=1 disk). SB3's parish label was corrected from
West Feliciana to East Baton Rouge without moving its anchor, recorded separately
as metadata rather than a re-anchoring.

Site 4 Alsen / North Baton Rouge did **not** verify and was deliberately left
alone: it sits in North Baton Rouge, which its compound name covers, but is 2.62
km from Alsen, which two of its three citations are about. Under §17.4 that makes
it poorly chosen rather than misnamed, so it keeps its anchor, keeps
`verified: false`, and is still reported. CS-206 should read its result knowing
the cells cover North Baton Rouge and not Alsen.

**Note:** the three moved anchors make this a §17 revision, so §17.6 requires the
full §13 protocol to re-run before any score is published. No scoring code exists
yet, so this costs nothing — which is why CS-111 was scheduled ahead of CS-206.

---

### CS-112 — Load the 2020 Decennial block layer

**Size:** M · **Labels:** etl, geospatial · **Depends on:** CS-005, CS-006 · **Owner:** Terrence · **Status:** Not started

The ancillary layer of methodology section 7 has a table and a consumer but no
adapter. `census_block` is created by migration 0003 and read by CS-106, and
nothing fills it: CS-105 loads tracts, and no other ticket claims blocks. Until
this lands, the dasymetric step of section 7 has correct arithmetic and no data
to run it on.

This was missed because section 7 names the block layer as a property of the
method rather than as a source, and because `census_block` already existed in
the schema, which made it look owned.

**Acceptance criteria**

- 2020 Decennial PL 94-171 population counts loaded per block for the pilot
  state, as counts rather than estimates. The distinction is the whole reason
  section 7 trusts blocks to distribute tract values.
- Block geometries loaded from the TIGER vintage that nests inside the tract
  geometries CS-105 loaded. Two vintages that disagree strand blocks on tract
  boundaries and the crosswalk reports it as a grid defect.
- Every block's `tract_geoid` resolves to a loaded tract, since migration 0003
  makes it a foreign key and an unmatched block is a silent hole in a tract's
  weights.
- Statewide block population totalled and checked against the published 2020
  state population, recorded like any other pull.
- Written through the adapter interface, so the retry, rate limit,
  partial-failure and provenance behaviour is inherited rather than rewritten.

---

## Phase 2 — Score and map

**Exit condition:** live map, and 8 of the 10 active validation sites land in the
top decile.

Note that the first file committed under `scoring/` is what the pre-registration
guard checks against. The validation set is already committed and is an ancestor
of anything landing now, so the check passes, but it reads commit history and
will fail the build if that ordering is ever inverted.

---

### CS-201 — Percentile ranking utilities

**Size:** S · **Labels:** scoring · **Depends on:** CS-108 · **Owner:** Terrence · **Status:** Done

Shared normalization so every indicator is expressed the same way.

**Acceptance criteria**

- Statewide percentile rank with a documented tie-handling rule. **Done:**
  `scoring/burden/percentile.py`, the Hazen convention of section 9,
  `100 · (r − 0.5) / n`, with tied hexes taking the mean of the ranks they
  occupy. Both choices are argued in the module docstring against the
  alternatives they beat: `(r−1)/(n−1)` would put the state minimum at exactly
  0, and section 10 multiplies the components, so one indicator at its minimum
  would annihilate a hex's whole Pollution Burden.
- Nulls excluded from the ranking rather than treated as zero. **Done:** a hex
  with no value for an indicator is left out of `n_k` and comes back with
  `observed` false carrying neither value nor percentile, which is the shape
  `hex_indicator` already requires. Zero is an observation and stays one.
- Hexes that are not scored are excluded from every percentile denominator.
  Section 5 leaves cells under 25 people unscored, and including them would
  distort the distribution. **Done:** `rank` takes the scored universe as a
  required keyword argument rather than inferring it from the values it was
  handed. Hexes outside it get no row and reach no denominator, and the count of
  those dropped is reported on the result instead of vanishing.
- Unit tested against hand-computed cases including ties and heavy
  zero-inflation. **Done:** 34 tests, each asserting a constant derived from the
  formula in the comment above it rather than agreeing with a second
  implementation. The zero-inflation case is 70 hexes with no facility within
  10 km against 30 with one, which is the shape section 9 warns about for E3 and
  F1 through F4.

**The two exclusions are not the same exclusion, and the output says which.** An
unscored hex is a place the methodology declines to rank. A scored hex with no
value is a place one indicator could not see. The first gets no row, the second
gets a row marked unobserved, and neither is ever filled in with a zero or a
median. That is section 11's rule and the failure the project exists to avoid:
an unmonitored area is uncertain, not clean.

**The zero block is counted, not smoothed.** `Distribution.zero_block_percentile`
returns the single percentile every exactly-zero hex shares, `50 · n_zero / n`.
Section 9 requires that number to be published, because below it a facility
indicator carries no information at all and a reader cannot tell that from the
percentile alone.

**No dependencies, on purpose.** The package installs nothing. CS-204 needs a
scoring run reproducible from its inputs, and a sort plus a division over stdlib
floats has no reduction order to argue about later.

---

### CS-202 — Pollution Burden component

**Size:** M · **Labels:** scoring · **Depends on:** CS-201, CS-103, CS-107 · **Owner:** Lead · **Status:** Done

The pollution half of the score: the Exposures and Environmental Effects groups.

**Acceptance criteria**

- Indicators and weights match `api/app/indicators.py`, which is the single
  declaration of the fifteen indicators and is itself locked to methodology
  section 8. Exposures carries weight 1.0, Environmental Effects 0.5. **Done:**
  `scoring/burden/indicators.py` restates group membership, weights and minimums
  because `api` and `scoring` are separate distributions, and
  `test_indicators.py::test_the_registry_matches_the_api` loads the registry of
  record off disk and fails the moment the two disagree. The same arrangement
  the ingestion package already uses in `quality/cross.py`.
- Group minimums enforced: at least 2 of 4 Exposures, at least 2 of 4
  Environmental Effects. Subgroup means are averaged, not pooled. **Done:** below
  its minimum a group drops out of the combination entirely rather than
  reporting the one or two indicators it has, since a mean of one Exposures
  indicator is a different quantity wearing the same name.
- Missing indicators are dropped from their group mean, never imputed to zero or
  to the median. **Done:** and tested in both directions, because zero and the
  median fail differently and section 11 rules out each by name.
- If Exposures is not computable, the component falls back to Environmental
  Effects alone with a heavy confidence penalty. If neither is computable the hex
  is `no_score` with reason `insufficient_pollution_data`. **Done:** the weights
  re-normalize over the groups that survived, so the fallback is that group's
  mean outright rather than a third of it.
- AirToxScreen is the primary input. OpenAQ contributes without letting sensor
  absence read as cleanliness. **Done:** E1 and E2 stay primary by being two of
  the four Exposures slots and modeled statewide; the module deliberately does
  not raise the 2-of-4 minimum to "and one must be AirToxScreen", which would be
  a stricter rule than section 11 states and belongs in the methodology first.
  E4 absent is dropped, never zeroed, and the test states the direction of that
  failure: zero is the bottom of the scale, so an unmonitored hex imputed to it
  would be painted cleaner than one that was measured and found clean.
- Component rescaled to 0 to 10 per section 10. **Done:** against the statewide
  maximum, which is returned alongside the scores because the rescaling is only
  reproducible beside the number it divided by.
- Per-hex sub-scores persisted, not just the total. The explain panel needs them,
  and so does the `observed` flag on every indicator. **Done:** both group means,
  the raw component before rescaling, and the used and dropped indicator lists
  per hex, which map onto `exposures_mean` and `env_effects_mean` on `hex_score`
  and onto the `observed` flag on `hex_indicator`.

**The assembly is shared with CS-203.** `scoring/burden/component.py` holds
section 10 steps 1 to 3 once and the two components supply their groups, their
weights and the name of the reason a hex fails. The two halves of section 11's
fallback rules are the same rule with different weights, and writing it twice is
how they would drift.

**The confidence penalty is computed here and applied in CS-205.** Section 12
owns the confidence value, and rules 3 and 4 ask for a penalty without fixing a
number. What this reports is the share of the component's weight that survived,
so losing Exposures costs two thirds and losing Environmental Effects one third.
That is the asymmetry rule 3 asks for, derived from the weights already in
section 10 rather than picked to look severe.

**Percentiles from two denominators are refused.** Averaging a percentile ranked
against 150,000 hexes with one ranked against 900 produces a number that looks
like a component score and is not one, and the mistake is silent everywhere
downstream, so the component checks its rankings cover the universe it was asked
to score and raises otherwise.

---

### CS-203 — Population Characteristics component

**Size:** M · **Labels:** scoring · **Depends on:** CS-201, CS-106 · **Owner:** Terrence · **Status:** Done

The demographic half of the score: the Sensitive Populations and Socioeconomic
Factors groups. Named to match `Component.POPULATION_CHARACTERISTICS` in the
code rather than the looser "vulnerability" of the original ticket.

**Acceptance criteria**

- Indicators and weights match `api/app/indicators.py`. Both groups carry weight
  1.0. **Done:** through the same restated registry and drift guard CS-202 uses.
- Group minimums enforced: at least 1 of 2 Sensitive Populations, at least 4 of 5
  Socioeconomic Factors. **Done:** and the 4-of-5 boundary is tested from both
  sides, since it is the strictest of the four groups.
- If one subgroup is not computable the component uses the other alone with a
  confidence penalty. If neither is computable the hex is `no_score` with reason
  `insufficient_population_data`. **Done:** both groups weigh 1.0, so either loss
  costs half the component's weight. The symmetry is asserted against Pollution
  Burden's 1/3 and 2/3, so neither reads later as an oversight in the other.
- Hexes below 25 population are `no_score` with reason `low_population`, per
  section 5, rather than producing unstable percentiles. **Done:**
  `scoring/burden/eligibility.py`, which runs before anything is ranked and
  returns the scored universe every percentile denominator is computed over. A
  hex with no population estimate at all is treated as unpopulated, following
  the reading `interpolate.py` already takes of CS-106's `no_population`. A
  population that is not a number is refused rather than filtered, because a NaN
  compares false against every threshold and would sail into a denominator.
- Race and ethnicity are not inputs. They are carried on the response for display
  and for CS-213, and nowhere else. **Done:** the seven indicators are age
  structure and economic circumstance. Two guards rather than a comment: one
  scans all fifteen registry entries for racial and ethnic terms and fails if any
  appears, and one hands the component a racial-composition ranking anyway and
  asserts the output is byte-identical, since the component reads its groups'
  indicator ids and nothing else.
- Sub-scores persisted per hex. **Done:** both group means and the raw component,
  mapping onto `sensitive_mean` and `socioeconomic_mean` on `hex_score`.

**Section 5 is where the denominator is decided.** It is the smallest module in
the package and the one with the widest blast radius: the set it returns is what
section 9 ranks against, so an off-by-one at the threshold does not produce a few
wrong hexes, it moves every percentile in Louisiana. The boundary is pinned in a
test of its own, because section 5 says "below 25" and "at most 25" differ by
exactly one hex.

**`low_population` and `insufficient_population_data` are kept apart.** One says
the methodology declines to score a place with almost nobody in it; the other
says a populated place had too little data to describe. Collapsing them would
tell a reader in a rural hex that the census failed them when the cell holds
eleven people.

**Why the section 14 guard is a test and not a comment.** If racial composition
were an input, the score would be high where the population is Black partly
because the formula put it there, the section 13.6 correlation would be a fact
about the arithmetic rather than a finding, and a Title VI argument resting on it
would be weaker than one resting on a metric that never reached for race. That is
worth a check that fails a well-intentioned pull request.

---

### CS-204 — Final burden score

**Size:** S · **Labels:** scoring · **Depends on:** CS-202, CS-203 · **Owner:** Lead · **Status:** Not started

Compose the two components into one score per hex.

**Acceptance criteria**

- Pollution Burden × Population Characteristics, per section 10.
- Score scaled to 0 to 100 and its statewide distribution recorded, alongside
  each hex's own percentile.
- All four `no_score` reasons handled and stored: `low_population`,
  `insufficient_pollution_data`, `insufficient_population_data`,
  `outside_pilot_state`. A hex without a score reports why rather than returning
  a bare null.
- Scoring run is reproducible: the same inputs and the same methodology version
  produce identical output.
- Methodology version stamped on every scored row, matching the version the API
  reports from `/indicators`.
- Written to `hex_score`, the table name the API already probes in `/health` and
  `GET /hex/{h3}`.

---

### CS-205 — Confidence value

**Size:** M · **Labels:** scoring · **Depends on:** CS-204, CS-104, CS-110 · **Owner:** Lead · **Status:** Not started

Every hex carries an honest statement of how much its score can be trusted.

**Acceptance criteria**

- Four terms implemented exactly as section 12 specifies: `c_coverage` at 0.35,
  `c_recency` at 0.20, `c_spatial` at 0.25, `c_monitor` at 0.20.
- `c_recency` is `exp(−Δt / τ)` with τ of 4 years, computed against the source
  vintages recorded by the adapters, not against pull timestamps.
- Combined as a weighted geometric mean, with each term floored at 0.05 so a
  single zero cannot annihilate the product. Geometric rather than arithmetic so
  one badly deficient term cannot be averaged away by three healthy ones.
- Bands assigned per section 12: high at 0.80 and above, moderate 0.60 to 0.79,
  low 0.40 to 0.59, insufficient below 0.40.
- Computed for every scored hex, including fully-covered ones.
- Low-confidence hexes identifiable in a single query for QA.
- Hexes in the insufficient band are excluded from validation statistics and are
  barred from the drafting assistant. Both exclusions are enforced in code, not
  left to the caller.

---

### CS-206 — Validation run against the fixed site set

**Size:** M · **Labels:** validation, gate · **Depends on:** CS-204, CS-003, CS-111 · **Owner:** Lead · **Status:** Not started

The phase gate. The score should flag known sites on its own, without being tuned
to them.

**Acceptance criteria**

- Scores computed for every active site in `docs/validation/sites.yml`, using the
  cells frozen in the fixture rather than a radius evaluated at scoring time.
- **Primary gate:** at least 8 of the 10 active Louisiana sites have at least one
  pre-registered cell in the statewide top decile.
- **Negative controls:** all 4 of 4 fall below the statewide median. Every scored
  cell of the site, not just one.
- **Stress case A, not a poverty map:** the three high-poverty low-industry Delta
  parishes are expected between roughly the 40th and 75th percentiles. Reported,
  not gating. A result outside the band triggers a documented investigation.
- **Stress case B, not an emissions map:** the three high-emission low-population
  industrial sites are expected below the top decile. Reported, not gating.
- A site with no scored cell is reported as `not_applicable` and never counted as
  a pass.
- Results written up: which sites pass, which don't, and the likely reason for
  each miss.
- Failure protocol from section 13.7 applies. Permitted responses are a code
  fix, a data-handling fix, or a methodology revision whose rationale stands
  independently of the validation outcome, followed by re-running every check
  from the beginning. Adjusting a weight because it makes a site pass is not one
  of them, and the validation set itself is never edited.
- Every run, passing or failing, recorded in methodology section 18 against the
  document version it ran under.
- Validation run reproducible via a single command in CI.

---

### CS-207 — Vector tile build and hosting

**Size:** M · **Labels:** frontend, infra · **Depends on:** CS-204 · **Owner:** Terrence · **Status:** Not started

Serve scored hexes as static tiles, with no tile server to run.

**Acceptance criteria**

- Scored hexes exported to PMTiles with score, percentile, confidence value,
  confidence band, H3 index and `no_score_reason` as attributes.
- Hosted on Cloudflare R2, not on the Railway frontend service. PMTiles are read
  with HTTP Range requests against one large archive, which is a poor fit for an
  edge cache keyed on whole URLs, and Railway bills egress at $0.05/GB while R2
  charges nothing.
- CORS configured on the bucket for the frontend origin, and Range requests
  confirmed working.
- The archive URL is read from `VITE_TILES_URL`, already present in
  `.env.example`.
- Tile generation is a repeatable step in the pipeline, not a manual export.
- Total archive size and initial load size recorded and kept reasonable.

---

### CS-208 — FastAPI service with published OpenAPI docs

**Size:** M · **Labels:** backend, api · **Depends on:** CS-204 · **Owner:** Terrence · **Status:** Partly done

The API skeleton, deployed and documented.

**Acceptance criteria**

- FastAPI app with health check and structured logging. **Done:** `GET /health`
  reports the extension list from `clearskies_extensions`, whether `hex_score`
  exists, how many hexes are scored, and degrades rather than failing when the
  database is unreachable. `GET /indicators` publishes the running indicator set
  and weights so a reader can check them against the methodology paper.
- OpenAPI docs auto-generated and publicly reachable. **Done** locally at `/docs`.
- CORS configured for the frontend origin. **Done:** driven by `CORS_ORIGINS`.
- Deployed on the Railway `api` service with CDN disabled and the healthcheck
  path wired up. **Not started**, and dependent on CS-009.
- Startup does not require the database: a deploy that comes up before Postgres
  is reachable reports the problem instead of crash-looping. **Done** in
  `app/db.py`, worth keeping as a regression check.

---

### CS-209 — `GET /hex/{h3}` drill-down endpoint

**Size:** M · **Labels:** backend, api · **Depends on:** CS-208, CS-205, CS-107 · **Owner:** Lead · **Status:** Partly done

One request returns everything the explain panel shows.

**Acceptance criteria**

- Response schema typed and reflected in the OpenAPI docs. **Done:** `HexDetail`
  in `api/app/schemas.py` carries the score, both components with their group
  scores, all fifteen indicators with percentile and an `observed` flag, the
  four-term confidence breakdown, the demographic profile, the contributing
  facilities and the `no_score_reason`.
- Validation semantics. **Done:** 422 for a malformed H3 index and 422 for a cell
  at the wrong resolution, with a message pointing at section 5. 503 while the
  pipeline has not run. 404 for a valid resolution 8 cell that is not in the
  scored set.
- The real query against `hex_score` and its joins. **Not started:** the handler
  currently raises 404 with a Phase 2 note.
- Per-indicator source and vintage returned, so the panel can cite what it
  displays. The `data_vintage` field exists on the schema and needs filling from
  the provenance data.
- Contributing facilities returned with their EPA record links.
- Response time acceptable under a realistic query load.

---

### CS-210 — Map shell

**Size:** L · **Labels:** frontend · **Depends on:** CS-207 · **Owner:** Terrence · **Status:** Partly done

React and MapLibre GL frontend rendering the scored hexes.

**Acceptance criteria**

- React 19, MapLibre GL 6, PMTiles and Tailwind 4 under Vite. **Done:** `web/`
  builds, with `MapView` and `HexPanel` components and a typed API client.
- PMTiles wired up. **Done:** the protocol is registered and torn down with the
  map, and the vector source is added from `VITE_TILES_URL` when one is set.
  There is no archive to point it at until CS-207.
- A documented, colourblind-safe choropleth ramp and a visible legend.
  **Not done.** Ramp and legend need Lead sign-off.
- Confidence is drawn, not just reported. Section 12 specifies the treatment:
  full opacity for high and moderate, hatched fill for low, and the insufficient
  band hidden by default behind a toggle.
- Free basemap configured from `VITE_BASEMAP_STYLE`, currently OpenFreeMap
  Positron.
- Pan, zoom and search-to-location work across desktop and mobile viewports.
- Deployed on the Railway `web` service with the CDN enabled, built by Vite and
  served by `serve -s dist`. Preview environments per pull request if Railway
  supports it on the plan; otherwise document that previews are not available.
- Loading and error states handled; a tile fetch failure does not leave a blank
  screen. The Phase 0 banner explaining that no hexagon is scored yet is the
  current example of this and should not be deleted until scores exist.

---

### CS-211 — Hex detail panel

**Size:** L · **Labels:** frontend · **Depends on:** CS-210, CS-209 · **Owner:** Terrence · **Status:** Partly done

Clicking a hex explains itself. Nothing on screen is a black box.

`web/src/components/HexPanel.tsx` already renders against the `HexDetail` schema
and covers more of this than the original ticket assumed. What is left is mostly
the parts that need data the API cannot yet return.

**Acceptance criteria**

- Score, statewide percentile, and the `no_score_reason` when there is no score.
  **Done.**
- Which of the fifteen indicators were used and which were dropped. **Done:**
  indicators are grouped, each row shows its percentile or reads "not observed",
  and the header counts how many were unavailable. Section 11 requires the user
  always sees this.
- Contributing facilities listed, each linking to its EPA record. **Done.**
- Demographics shown with an explicit note that they are recorded and displayed
  but never scored. **Done.**
- A short "what this means and doesn't mean" explainer, written by hand rather
  than generated. **Partly done:** the footer carries the wrongdoing and
  Louisiana-percentile caveats. Lead reviews and extends this copy rather than
  writing it from scratch.
- Waterfall breakdown showing how the total was reached. **Not done:** the
  components section prints each component's score out of 10 but not the four
  group scores, their weights, or how they compose. The `GroupScore` objects are
  already on the response.
- Confidence displayed with a plain-language reading. **Partly done:** the band
  label and value are shown. The four-term breakdown is not, and the low band
  does not yet lead with its caveat.
- Source and vintage shown for each indicator. **Not done:** waiting on
  `data_vintage` being populated in CS-209.
- Panel is keyboard-navigable and works at mobile width. **Not verified.** The
  close button is labelled; nothing else has been checked.

---

### CS-212 — Robustness checks

**Size:** M · **Labels:** validation, methodology · **Depends on:** CS-204, CS-206 · **Owner:** Lead · **Status:** Not started

Methodology section 13.5 specifies three checks that the original backlog did not
cover. They test whether the score is an artifact of its own construction.

**Acceptance criteria**

- **Alternative specifications.** Spearman rank correlation of at least 0.85
  between the score and each of: equal weighting of Exposures and Environmental
  Effects; Exposures only; additive rather than multiplicative combination. A low
  correlation against the additive variant is expected and informative rather
  than disqualifying, and is reported rather than required to pass.
- **Leave-one-indicator-out.** Removing any single indicator must not move more
  than 10% of hexes by more than one decile. An indicator that fails this is
  doing too much work alone and its inclusion is re-argued in the methodology
  paper.
- **Interpolation sensitivity.** Scores recomputed with simple areal weighting
  instead of dasymetric weighting, to quantify how much the section 7 machinery
  actually changes.
- Results committed and recorded in section 18.

---

### CS-213 — Disparity analysis

**Size:** M · **Labels:** validation, methodology, docs · **Depends on:** CS-204, CS-105 · **Owner:** Lead · **Status:** Not started

Methodology section 13.6. This is the project's headline finding and it needs to
be computed carefully and framed correctly.

**Acceptance criteria**

- Correlation between a hex's score percentile and its Black population share,
  and separately its overall people-of-colour share, computed population-weighted
  and published with confidence intervals.
- Framed as a reported result, not a validation target. Because race is not an
  input to the score, any correlation found is a property of the pollution and
  vulnerability data rather than an artifact of the construction. There is no
  threshold it must meet, and a weaker-than-expected correlation is a finding
  worth publishing rather than a bug to fix.
- The independence argument stated wherever the number is shown, so the result
  cannot be read as circular.
- Feeds the architecture write-up and the public site.

---

## Phase 3 — Drafting assistant

**Exit condition:** zero unverifiable citations across a 50-draft audit.

---

### CS-301 — Curate and version the statute corpus

**Size:** L · **Labels:** llm, data · **Depends on:** CS-006 · **Owner:** Lead · **Status:** Not started

A closed, curated corpus is what keeps retrieval honest: no open web, no model
recall.

**Acceptance criteria**

- Every authority in methodology Appendix B ingested from an authoritative
  source. Federal: the Clean Air Act including the hazardous air pollutants,
  state implementation plan, prevention of significant deterioration and
  operating permit provisions; the Clean Water Act; RCRA; EPCRA; Title VI; and
  EPA's Title VI implementing regulations at 40 C.F.R. Part 7. Louisiana: the
  constitutional public trust provision, the Environmental Quality Act, the Air
  Control Law and LAC 33:III.
- Bounded case law included: *Save Ourselves* and *Alexander v. Sandoval*. The
  assistant may cite these but may not reason from them to a legal conclusion.
  *Sandoval* is in the corpus specifically so the assistant gets the procedural
  posture right: a Title VI disparate-impact claim is an administrative complaint
  to EPA's external civil rights office, not a lawsuit a resident can file. A
  draft implying otherwise sends someone down a dead end, which is worse than a
  missing citation.
- Chunked by section, never across section boundaries, so a retrieved passage
  always carries a complete citable unit.
- Every document stored with its full text, an edition or amendment date, and the
  URL and date it was retrieved.
- Corpus versioned and immutable once versioned. It cannot grow at runtime, and
  adding an authority requires a manifest entry in Appendix B first.
- Ingestion repeatable from a script, not a one-off manual load.

---

### CS-302 — pgvector retrieval over the corpus

**Size:** M · **Labels:** llm, backend · **Depends on:** CS-301 · **Owner:** Terrence · **Status:** Not started

Retrieval that only ever returns real, in-corpus sections.

**Acceptance criteria**

- Embeddings generated and stored in pgvector with an appropriate index. The
  extension is already present in the database image.
- Retrieval returns section identifiers alongside text, so citations trace to
  something checkable.
- Retrieval quality spot-checked against a set of hand-written question and
  expected-section pairs.
- Retrieval cannot return anything outside the versioned corpus, by construction
  rather than by prompt instruction.

---

### CS-303 — Pydantic schemas for the four document types

**Size:** M · **Labels:** llm, backend · **Depends on:** CS-004 · **Owner:** Lead · **Status:** Not started

Public comment letter, agency complaint draft, community briefing sheet,
journalist fact sheet.

**Acceptance criteria**

- One schema per type, each with a required, non-empty citations field.
- Citation entries are structured, a record ID or statute section plus its
  source, never free text.
- Structured output enforced via Pydantic AI. A response that doesn't conform is
  rejected rather than repaired by hand.
- Schema validation covered by tests including deliberately malformed responses.

---

### CS-304 — Prompt design and content guardrails

**Size:** M · **Labels:** llm, safety · **Depends on:** CS-303, CS-302 · **Owner:** Lead · **Status:** Not started

Rules that keep drafts to documented facts and statistical patterns.

**Acceptance criteria**

- Prompts permit documented facts and statistical patterns only. Claims about
  corporate intent, motive or knowledge are prohibited.
- The model works from retrieved context and supplied hex data only.
- A hex in the insufficient confidence band cannot be drafted from. Producing a
  cited complaint from a score the system does not itself trust would be the most
  damaging thing this tool could do, and the refusal belongs in the prompt layer
  as well as in code.
- Prompts versioned in the repo and referenced by version in generation logs.
- A red-team set of prompts attempting to elicit intent claims, legal advice or
  invented facts, with expected refusals as tests.

---

### CS-305 — Citation verifier

**Size:** L · **Labels:** llm, safety, gate · **Depends on:** CS-303, CS-302, CS-101 · **Owner:** Lead · **Status:** Not started

Every citation is checked against the database before a draft is ever shown.

**Acceptance criteria**

- Every facility and record ID checked to exist in the loaded dataset.
- Every statute section checked to exist in the versioned corpus.
- **Existence alone is not sufficient.** Corpus rule 3 requires the verifier to
  check that the quoted or paraphrased proposition actually appears in the
  retrieved chunk. A real section number attached to a claim it does not support
  is exactly the failure this component exists to catch.
- A draft containing any unverifiable citation is rejected and never rendered to
  the user. Not shown with a warning.
- Rejections logged with the offending citation, for auditing.
- Tests cover fabricated IDs, near-miss IDs, sections that exist in the real
  world but not in the corpus, and a correct section paired with a proposition it
  does not support.

---

### CS-306 — Generation endpoint with caching and spend controls

**Size:** M · **Labels:** backend, llm, cost · **Depends on:** CS-305, CS-208 · **Owner:** Terrence · **Status:** Not started

Generation wired into the API without an open-ended bill.

**Acceptance criteria**

- Drafts cached per hex, document type, methodology version and prompt version. A
  repeat request serves the cache; a methodology or prompt revision invalidates
  it.
- Refuses hexes in the insufficient confidence band, matching CS-304.
- Hard monthly spend cap set on the LLM API key with the provider, independent of
  application logic.
- Per-request token usage and cost logged.
- Missing API key returns 503 rather than failing at startup, which
  `api/app/config.py` already anticipates.
- Graceful, explanatory failure when the cap or the provider's limits are hit.
- The endpoint is a POST and must never sit behind the CDN.

---

### CS-307 — Draft viewer UI

**Size:** M · **Labels:** frontend · **Depends on:** CS-306, CS-211 · **Owner:** Terrence · **Status:** Not started

"Draft a document" on any hex, with the draft framing impossible to miss.

**Acceptance criteria**

- Document type picker for the four types.
- Generation progress and failure states handled, including the refusal for
  insufficient-confidence hexes, explained in plain language rather than as an
  error code.
- Every output visibly labelled as a draft requiring human review.
- Citations rendered as links to the underlying EPA record or statute section.
- Copy and download only. No send, publish or share-to-agency functionality
  anywhere in the UI.

---

### CS-308 — 50-draft citation audit

**Size:** M · **Labels:** validation, gate · **Depends on:** CS-307 · **Owner:** Lead · **Status:** Not started

The phase gate.

**Acceptance criteria**

- 50 drafts generated across all four document types and a spread of hexes,
  including low-confidence hexes and hexes with few contributing facilities.
  Insufficient-band hexes cannot be drafted from, so the spread runs to the low
  band and stops there.
- Every citation in every draft manually verified.
- **Gate: zero unverifiable citations.**
- Drafts also reviewed for prohibited intent claims, for anything reading as
  legal advice, and specifically for anything implying a Title VI disparate-impact
  claim can be filed as a lawsuit.
- Audit results written up and committed, feeding the model card.

---

## Phase 4 — Polish and launch

**Exit condition:** public URL and public repo live.

---

### CS-401 — Accessibility pass

**Size:** M · **Labels:** frontend, a11y · **Depends on:** CS-211, CS-307 · **Owner:** Terrence · **Status:** Not started

A tool aimed at underserved communities has to be usable.

**Acceptance criteria**

- Keyboard navigation across map, panel and draft viewer.
- Screen-reader labelling for map interactions, with a non-map path to the same
  hex data. The API returns the same payload the panel renders, so a search or
  address lookup that lands directly on a hex detail view is the natural route.
- Colour contrast meets WCAG AA, and the choropleth is readable for common colour
  vision deficiencies. The hatched treatment for low-confidence hexes must remain
  distinguishable from the ramp itself.
- Automated axe checks in CI plus a manual pass with a screen reader.

---

### CS-402 — Rate limiting on public endpoints

**Size:** S · **Labels:** backend, cost · **Depends on:** CS-306 · **Owner:** Terrence · **Status:** Not started

Protect the budget and the database.

**Acceptance criteria**

- Generation endpoint limited to a small number of requests per IP per day.
- Read endpoints limited more loosely.
- Limits are enforced in the API, since the CDN is deliberately off for this
  service and cannot absorb the traffic.
- Limits return a clear message explaining the restriction and why it exists.
- Limits configurable without a redeploy.

---

### CS-403 — Monitoring and uptime checks

**Size:** S · **Labels:** infra · **Depends on:** CS-208 · **Owner:** Terrence · **Status:** Not started

Know when it's down or when the nightly job failed.

**Acceptance criteria**

- External uptime check on the API health endpoint and the frontend. Because
  `/health` degrades rather than failing when the database is unreachable, the
  check must look at the status field, not just the HTTP code.
- Alerting on ETL job failure, including the case where a run completes but
  reports `failed` or `stale` status for a source.
- Railway logs retained and searchable enough to debug an incident.
- Railway does not idle a service, so a slow first response is a real problem
  rather than an expected cold start. There is no cold-start caveat to document.

---

### CS-404 — README and developer documentation

**Size:** M · **Labels:** docs · **Depends on:** CS-109, CS-208 · **Owner:** Terrence · **Status:** Partly done

Someone should be able to clone it and run it.

**Acceptance criteria**

- "How to add a new data source" walkthrough against the real adapter interface.
  **Done:** `etl/README.md`, with the four-stage contract, the metadata table,
  the run statuses and a seven-step walkthrough, plus the worked example in
  `pipeline/adapters/fake.py`.
- Local setup verified from scratch on a clean machine. **Not started.** Note
  that `make up` compiles h3-pg from source and takes several minutes the first
  time, which is the kind of thing a first run discovers and the README should
  say plainly.
- Architecture overview with a diagram. **Not started.** Lead writes this.
- Deployment notes for each hosted piece: the three Railway services, the R2
  bucket, and the GitHub Actions nightly job.

---

### CS-405 — Model card for the AI component

**Size:** M · **Labels:** docs, safety · **Depends on:** CS-308 · **Owner:** Lead · **Status:** Not started

What it does, what it won't do, and where it fails.

**Acceptance criteria**

- Covers intended use, out-of-scope use, the four document types and the
  human-review requirement.
- Documents the guardrails: curated corpus, citation verification including the
  proposition check, facts-only language rules, no intent claims, and the refusal
  to draft from insufficient-confidence hexes.
- Reports the 50-draft audit results and known limitations.
- Names the model and prompt versions used.
- Linked from the app itself, not just the repo.

---

### CS-406 — Public data provenance page

**Size:** S · **Labels:** frontend, docs · **Depends on:** CS-110 · **Owner:** Terrence · **Status:** Not started

Every source, when it was last pulled, and its known gaps.

**Acceptance criteria**

- Rendered from live provenance data, so it cannot go stale. `docs/provenance.md`
  is the repository-side view of the same data; this is the user-facing one.
- Lists each source with vintage, last successful pull, record count, run status
  and documented gaps.
- Explains the sparse-sensor problem in plain language, and explains why a
  missing value is never shown as a zero.
- Shows when a source was served from a snapshot rather than fetched, since a
  `stale` run is exactly the situation a reader deserves to know about.
- Reachable from the map's main navigation.

---

### CS-407 — Disclaimer and safe-language review

**Size:** S · **Labels:** safety, docs · **Depends on:** CS-307 · **Owner:** Lead · **Status:** Not started

A pass over everything user-facing, checking the framing holds up.

**Acceptance criteria**

- Disclaimer on the app and on every generated draft: not legal advice, requires
  human review.
- Site copy reviewed for anything asserting intent or wrongdoing rather than
  reporting documented facts. A high burden score describes a pattern in public
  data and is not a finding of wrongdoing by any operator.
- "What this means and doesn't mean" explainers reviewed for accuracy against the
  methodology, including the point that a low score can mean low burden or can
  mean the indicators that would have caught the burden are missing.
- Confirmed there is no send, submit or publish path anywhere in the product.

---

### CS-408 — Performance and payload review

**Size:** M · **Labels:** frontend, backend · **Depends on:** CS-210, CS-208 · **Owner:** Terrence · **Status:** Not started

The demo should not look broken on first load. Rewritten from the original
cold-start ticket, which assumed a host that spins down.

**Acceptance criteria**

- Initial map load time measured and improved where cheap to do so.
- Tile archive and API payload sizes reviewed. The PMTiles archive is the largest
  asset in the project and is fetched by Range request, so measure what a first
  view actually pulls rather than the archive size alone.
- CDN cache behaviour confirmed on the `web` service: cache hits should cost no
  egress and should not wake the container.
- Database size measured against the Railway volume, with headroom recorded. The
  scored grid, the facility tables and the pgvector corpus are the three things
  that grow.
- `GET /hex/{h3}` response time measured under a realistic click rate, since the
  panel makes one request per hex opened.

---

### CS-409 — Architecture write-up

**Size:** M · **Labels:** docs, portfolio · **Depends on:** CS-404, CS-405 · **Owner:** Lead · **Status:** Not started

The blog post that makes this legible from a resume link.

**Acceptance criteria**

- Walks through the architecture and the design decisions, including the ones
  that were rejected and why.
- Covers the interesting problems honestly: dasymetric interpolation, sparse
  sensor coverage, citation verification, and the decision to record race but not
  score it.
- Reports the disparity analysis from CS-213 with its independence argument
  intact.
- Includes screenshots and links to the live app, repo, methodology paper and
  model card.
- Published somewhere linkable.

---

### CS-410 — Launch

**Size:** S · **Labels:** launch · **Depends on:** CS-401, CS-402, CS-403, CS-404, CS-405, CS-406, CS-407 · **Owner:** Lead · **Status:** Not started

Make it public.

**Acceptance criteria**

- Repo made public with a licence, a README that renders well, and no secrets in
  history.
- Live URL on the Railway domain, reachable and stable.
- End-to-end pass on the deployed site: load map, open a hex, read the
  breakdown, follow a citation, generate a draft.
- Nightly job confirmed running against production, and `GET /health` reporting
  a non-zero scored hex count.
- All eight deliverables from the proposal confirmed present and linked.

---

## Coverage against the proposal's deliverables

| Deliverable | Tickets |
|---|---|
| 1. Live public URL with interactive map | CS-207, CS-210, CS-211, CS-410 |
| 2. Public repo with CI, tests, README | CS-004, CS-404, CS-410 |
| 3. REST API with OpenAPI docs and hex drill-down | CS-208, CS-209 |
| 4. Methodology paper | CS-002, CS-106, CS-205, CS-206, CS-212, CS-213 |
| 5. Working drafting assistant with verified citations | CS-301 through CS-308 |
| 6. Model card | CS-405 |
| 7. Data provenance page | CS-110, CS-406 |
| 8. Architecture write-up | CS-409 |
