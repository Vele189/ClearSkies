# Audit tickets — 2026-09-22

These tickets resolve the findings in [2026-09-22-codebase-audit.md](2026-09-22-codebase-audit.md).
Finding codes (M1, A3, …) refer to that report.

Each ticket is fixed on its own branch, `audit/aud-NN-<slug>`. Most branch from
`audit/2026-09-22-report`. A ticket that edits the same files as an earlier one
is **stacked**: it branches from that ticket's branch, and has to merge after
it. Three tickets add migrations, and their numbers are reserved here so that
branches merged in any order stay in sequence: AUD-02 is `0024`, AUD-07 is
`0025`, and AUD-12 is `0026`. Merge those three in that order.

| ID | Sev | Title | Findings | Branch base |
|---|---|---|---|---|
| AUD-01 | critical | Verify every citation a draft carries | A1 A2 A4 A11 | report |
| AUD-02 | high | Key the draft cache on the request and the scored run | A3 A5 | AUD-01 |
| AUD-03 | medium | Harden the API edges: h3 input, provider errors, pool, client, rate limit | A6 A7 A8 A9 | AUD-02 |
| AUD-04 | medium | API accounting and correctness: spend, facility count, embedding model, migration runner, router tests | A10 A12 A13 A14 A15 | AUD-03 |
| AUD-05 | high | Feed the scorer what the methodology specifies | M1 M2 M3 M4 M6 M7 M10(code) M11 | report |
| AUD-06 | medium | Bring the methodology changelog and indicator text up to date | M9 M10(text) | AUD-05 |
| AUD-07 | high | Dasymetric reconciliation, the areal counterpart, and rates | E1 E2 E3 | report |
| AUD-08 | medium | Pin the transaction's connection, and make ECHO paging fail loudly | E6 E7 | report |
| AUD-09 | medium | Make the nightly job and the snapshot fallback do what the docs say | E4 E5 E8 | AUD-08 |
| AUD-10 | high | Frontend state: stale draft, racing hex loads, search reopen, keyboard select | W1 W2 W5 W6 | report |
| AUD-11 | medium | Frontend content and rendering: legal basis, unscored band, hatch, opacity, ordinals | W3 W4 W7 | AUD-10 |
| AUD-12 | high | Statute corpus: eCFR depth, version label, atomic seal, TRUNCATE | C1 C3 C4 C5 C8 | report |
| AUD-13 | medium | Guards, audit scripts and CI coverage | C2 C6 C7 C9 | report |
| AUD-14 | high | Repository structure: Railway config, env example, unused Drizzle track, Makefile | R1 R5 R6 R7 R10 | report |
| AUD-15 | medium | Documentation: README status and layout, Neon-first setup docs, backlog, docs index | R3 R4 R9 | AUD-14 |

**For the owner, not fixable in a branch:**
- **R2:** push `neon-setup` and open a PR.
- **R8:** prune `origin/QA` and the stale `cs-214` ref, and decide whether bc889a5 on `cs-213-disparity-command` is superseded.
- **M5:** how the §11 fallback penalty enters C(h) is a methodology decision.
- **M8:** 50% versus 30% for P5 is a methodology decision.
- **Migration 0023** is pending on the Neon dev branch.

---

## AUD-01 · Verify every citation a draft carries · critical

**Covers** A1, A2, A4 and A11. **Files:** `api/app/assistant/documents.py`, `api/app/assistant/verifier.py`, tests.

Acceptance:
- `AgencyComplaintDraft.citations` includes every `legal_basis` citation. A fabricated statute in `legal_basis` fails verification (regression test).
- Verification judges every distinct (citation, proposition) pair. The deduped list is used for display only. A second, false proposition on an already-cited section fails (regression test).
- LIKE metacharacters in a section label are escaped. `4_ U.S.C. § 7410` and `%` do not match (unit test on the SQL builder, or on the escaping helper).
- A facility record citation verifies only if the facility is in the draft's hex context. The module docstring states exactly what a record citation proves and what it does not.

## AUD-02 · Key the draft cache on the request and the scored run · high

**Covers** A3 and A5. **Stacked on** AUD-01. **Migration** `0024`.

Acceptance:
- The cache key includes a SHA-256 of the normalised free-text `request` (empty string for none), and the `run_id` of the scored run.
- Drafts are stamped with the run's `methodology_version`, not the app constant.
- Migration 0024 adds the columns, replaces the unique constraint, and drops the duplicate `draft_lookup_idx`. Its down reverses all of this.
- Tests: two different `request` texts do not share a cache row, and a new `run_id` misses the cache.

## AUD-03 · Harden the API edges · medium

**Covers** A6, A7, A8 and A9. **Stacked on** AUD-02.

Acceptance:
- One shared h3 validator: valid cell, resolution 8, canonical lower-case 15 hex digits. Anything else is a 422. It is used by `/hex/{h3}` and by `DraftRequest`.
- A verification failure from the judge (schema, retries exhausted, timeout) maps to 422 "unverifiable" or 503, never 500. Provider connection, timeout, auth and 5xx errors map to 503.
- `db.pool()` retries creating the pool after a failed first connect.
- A single app-scoped OpenAI client is closed in the lifespan.
- `/draft` has a per-client rate limit, configurable and on by default. Over the limit returns 429 with `Retry-After`.
- Tests for each of these.

## AUD-04 · API accounting and correctness · medium

**Covers** A10, A12, A13, A14 and A15. **Stacked on** AUD-03.

Acceptance:
- **Spend:** usage is recorded for the embedding and verification calls with real token counts, and the purpose values match migration 0021.
- **Facility count:** the model context and panel receive the true facility count alongside the capped list.
- **Embedding model:** retrieval refuses with 503 when the corpus `embedding_model` differs from the configured one.
- **Migration runner:** `--to` must be a four-digit existing version. `down` runs the drift check.
- **Router tests** cover `/draft`'s 409, 422 and 503 mappings. The `client` fixture really runs without a database.

## AUD-05 · Feed the scorer what the methodology specifies · high

**Covers** M1, M2, M3, M4, M6, M7, M10 (code) and M11. **Files:** `scripts/run_scoring.py`, and any testable helpers extracted from it.

Acceptance:
- **F1–F4 and E3:** 0.0 for every eligible hex with no qualifying facility, `None` only when the source itself did not load (§9, §11).
- **F2:** counts only `violation` and `high_priority_violation`, over distinct quarters in the 12 quarters ending at `as_of`.
- **c_spatial:** takes the population share of the hex drawn from tracts whose contributing ACS estimates exceed CV 0.30 (§12).
- **Mean block area:** `mean_block_area_m2` is the population-weighted mean over the hex's tracts.
- **Recency:** dates each indicator from the snapshot the run actually read. A missing contributing source makes the vintage unknown, not absent.
- **Unobserved rows:** `hex_indicator` rows with `observed=false` are written for unobserved indicators.
- **`--acs-vintage`:** used, or removed.
- **Tests:** the SQL-free logic is extracted into functions and covered by tests (zero versus missing, F2 status filtering, the vintage choice, the block-area mean, the CV share).

## AUD-06 · Methodology changelog and indicator text · medium

**Covers** M9 and M10 (text). **Stacked on** AUD-05. **Files:** `docs/methodology.md` §18, `api/app/indicators.py` text.

Acceptance:
- §18 records runs 6, 7 and 11 and the fixes in f0ad181, f2005b7, 8623959 and AUD-05, as §13.7 requires.
- The stale v0.2.0 claim is corrected.
- The F3 description and the E3 unit match the code.
- M5 and M8 are listed in §18 as open questions awaiting a revision. They are not decided.
- The weights and the validation set are unchanged.

## AUD-07 · Dasymetric reconciliation, the areal counterpart, and rates · high

**Covers** E1, E2 and E3. **Migration** `0025`.

Acceptance:
- **Reconciliation:** fails on an empty crosswalk, on a county whose tracts have no block overlap, and when unreached tracts hold more than a small, documented share of population.
- **Areal counterpart:** `areal_counterpart` works on a crosswalk with zero-population cells, by keeping those rows (migration relaxes `pop_weight > 0` to `>= 0`) or by an equivalent stored area share. The `export_run.py` note is corrected.
- **Rates:** `derive_rate` divides only over tracts that report both parts.
- A regression test for each.

## AUD-08 · Transaction connection and ECHO paging · medium

**Covers** E6 and E7.

Acceptance:
- **Transactions:** while a transaction is open, `_LazyConnection` routes every call to the pinned connection, and raises rather than reconnecting if the connection is lost.
- **ECHO paging:** `responseset` is sent at registration. Paging continues until `expected` is reached. A shortfall marks the source failed or partial, not `ok`, for both the facility and RCRA queries.
- Tests for both.

## AUD-09 · Nightly job and snapshot fallback · medium

**Covers** E4, E5 and E8. **Stacked on** AUD-08.

Acceptance:
- **Snapshots:** a persistent filesystem `SnapshotStore` is used by the CLI, and the nightly workflow keeps its directory in the Actions cache. A test shows a second process serving offline from the first process's snapshots.
- **Nightly:** `census_block` has a schedule entry and is not due nightly. The workflow `--require`s the real sources. The docs and workflow comments say truthfully whether nightly loads into Postgres. The budget comments match `pipeline plan`.
- **AirToxScreen text:** the gap text and docstrings reflect the 2010→2020 crossing.

## AUD-10 · Frontend state · high

**Covers** W1, W2, W5 and W6.

Acceptance:
- **Stale draft:** changing hex resets the draft panel and aborts any in-flight draft POST.
- **Racing loads:** hex loads abort the previous request, stale responses are ignored, and a loading state is shown.
- **Search:** picking a result or pressing Escape does not reopen the dropdown.
- **Keyboard:** choosing a search result selects the hex at that point, so keyboard users can open the panel. The map container has a region role.
- Tests for each.

## AUD-11 · Frontend content and rendering · medium

**Covers** W3, W4 and W7. **Stacked on** AUD-10.

Acceptance:
- **Legal basis:** `legal_basis` is rendered and exported, and key-figure citations appear in the citations list.
- **Unscored band:** unscored hexes render the same way as the legend's "Not scored" swatch, and the doc says which.
- **Hatch and opacity:** the legend hatch angle matches the map, and map fill opacity matches the swatches (or the swatches account for it).
- **Small fixes:** ordinals are correct (1st, 2nd, 3rd, 11th, 22nd), null percentile and reason text are handled, the clipboard failure is handled, and the blob URL is revoked after the download starts.
- Tests.

## AUD-12 · Statute corpus · high

**Covers** C1, C3, C4, C5 and C8. **Migration** `0026`.

Acceptance:
- **eCFR depth:** `(h)(1)(i)` nests correctly (regression test). An ambiguous marker is never made citable at the wrong depth.
- **Version label:** includes the build's content hash.
- **Atomic seal:** the seal locks the version row, recomputes the hash and counts from `statute_chunk`, and refuses a mismatch or an already-sealed row, all in one transaction.
- **TRUNCATE:** migration 0026 adds a statement-level `BEFORE TRUNCATE` guard.
- **Spot-check:** matches `label == expect` or `label` starting with `expect + "("`.
- **Sections filter:** fails on any listed section that is missing.
- **Tests:** real tests of `seal` and `write` with a fake connection.

## AUD-13 · Guards, audit scripts and CI coverage · medium

**Covers** C2, C6, C7 and C9.

Acceptance:
- **Preregistration guard:** fails on any commit touching `docs/validation/sites.yml` after the first scoring commit, unless the commit carries a `Methodology-Revision:` trailer.
- **Audit scripts:** the citation audit and red-team import `METHODOLOGY_VERSION` and bypass or report the cache. The audit fails when any draft errors.
- **Spatial tests:** CI and `make test-spatial` run the same three spatial test files.
- **CI hygiene:** the stale push branch is removed, `scripts/` is linted in CI, and the preregistration job's pip installs are pinned.

## AUD-14 · Repository structure · high

**Covers** R1, R5, R6, R7 and R10.

Acceptance:
- **Railway:** `.railway/railway.ts` defines `web` and `api` only, and the api's `DATABASE_URL` is supplied by Neon.
- **Env example:** `.env.example` documents every variable the code reads, with Neon-accurate comments (pooled for the API, unpooled for migrations).
- **Drizzle:** the unused Drizzle track is removed. `neon.ts` is kept only if something documents a use for the bucket. The tables it created on Neon are listed for manual removal, not dropped.
- **Makefile:** `make score`, `make export-run` and `make ingest SOURCE=` run the real commands. The `extensions` help text is accurate.
- **Housekeeping:** `.gitignore` no longer ignores `*.local` wholesale.

## AUD-15 · Documentation · medium

**Covers** R3, R4 and R9. **Stacked on** AUD-14.

Acceptance:
- **README:** the status reflects the phase the repository is actually in, and the run 11 gate is recorded as failing. The layout tree matches the tree. The migration count is right. The "two schemas" section is resolved. The "`make check` = CI" claim is accurate.
- **Setup docs:** `docs/database.md` and `CONTRIBUTING.md` lead with Neon, with the container as the optional and CI path.
- **Backlog:** hosting is Neon, and the CS-206, CS-212 and CS-213 statuses are current.
- **Docs index:** `docs/README.md` indexes every document, including the validation results and this audit.
