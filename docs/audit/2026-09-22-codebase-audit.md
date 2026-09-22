# Codebase audit — 2026-09-22

Scope: the whole repository at `neon-setup` @ `bcb0c70`: `api/`, `etl/`,
`scoring/`, `assistant/`, `web/`, `scripts/`, CI, the root JavaScript, and every
document under `docs/`. The audit was read-only. Each finding below was
confirmed by reading the code, and most were also reproduced with a throwaway
snippet or query. The tickets that resolve them are in
[tickets.md](tickets.md).

## Summary

| | |
|---|---|
| Baseline `make check` | **Green.** ruff, mypy (strict) and tests pass in every package: api 258 passed / 39 skipped (DB-only), etl 737, scoring 238, assistant 79, web 120 (vitest) |
| Working tree | Clean. No secrets are tracked, and none are in history |
| Findings | 1 critical, 13 high, 35 medium, and a long tail of low |
| Where the risk is | The citation verifier and the draft cache (the assistant's guarantees), and how the scoring script treats zero versus missing (model accuracy) |

A green suite does not mean the code is correct. Every finding below passes CI
today. Most of them live in code no test exercises, or in the space between two
modules that are each tested on their own: `scripts/run_scoring.py`, the
router-level draft path, `MapView`/`App`, and the seal and store code.

Severity: **critical** means a stated safety guarantee does not hold.
**High** means a wrong score, a wrong document, or silent data loss.
**Medium** means wrong under conditions that will occur. **Low** means
cosmetic, drift, or hardening.

---

## 1. Model accuracy (scoring)

The primitives in `scoring/burden` are correct against the methodology. The
problems are in how `scripts/run_scoring.py` feeds them.

**Checked and correct:**
- Hazen mid-rank percentiles with averaged ties (§9).
- The 25-person eligibility rule (§5).
- Subgroup weights, minimums, the fallback and the 10·raw/max rescale (§10).
- Confidence weights, floor, τ = 4 y and band edges (§12).
- The F3 fix (8623959), the E1/E2 intensive interpolation (f2005b7), and the
  recency re-keying (f0ad181).
- Robustness Spearman, and the validation pass/fail rules.
- No race variable reaches any score (§14).

| # | Sev | Finding | Where |
|---|---|---|---|
| M1 | high | **Proximity indicators are missing where the spec says zero.** §9 says F1–F4 and E3 are zero for a hex with no qualifying facility within 10 km. The query only returns rows for hexes that have a facility, and E3 inner-joins TRI toxicity. So those hexes get no values: they drop out of the zero block and the denominators, Environmental Effects becomes non-computable, and c_coverage is penalised. robustness.md §7.2 shows this as 8,247 of 17,263 hexes losing a group | `run_scoring.py:308-384,467-472`, `0014…up.sql:228` |
| M2 | high | **F2 counts `unknown` quarters as violations.** The filter is `status <> 'in_compliance'`, and ECHO writes `unknown` for unmonitored quarters. A facility nobody inspected therefore scores the maximum 12/12. The window is also "last 12 rows" rather than "12 quarters before as_of", which goes wrong once more than one program is loaded. The panel query counts violations only, so score and drill-down disagree | `run_scoring.py:323` |
| M3 | high | **c_spatial is given a CV where it expects a population share.** It receives `min(cv_B01003, 1)`. §12 specifies the share of population from estimates with CV > 0.30, and the formula itself was never ratified in §18 | `run_scoring.py:676`, `confidence.py:51` |
| M4 | medium | **`mean_block_area_m2` comes from one tract per hex.** A dict comprehension keeps the last tract for each hex | `run_scoring.py:659-662` |
| M5 | medium | **The §11 fallback penalty is never applied.** `HexComponent.confidence_penalty` is computed and tested, but nothing reads it. The name is also inverted: lower means heavier | `component.py:195` |
| M6 | medium | **Recency dates the newest snapshot, not the one scored.** `max(vintage_end)` over all snapshots, while the run pins 2019/2024/ACS. A missing contributing source is dropped rather than treated as unknown | `run_scoring.py:544` |
| M7 | medium | **Unobserved indicators are never persisted, so `observed=false` cannot occur.** The robustness export then ranks against a different denominator from the published run | `run_scoring.py:826`, `export_run.py` |
| M8 | medium | **P5 uses a 30% housing-cost cut; §8.4 and the registry say 50%.** There is no §18 entry | `census_acs.py:348`, `indicators.py` |
| M9 | medium | **§18 is stale.** v0.2.0 still says Exposures are absent. Runs 6, 7 and 11 are not recorded, and §13.7 requires them to be | `docs/methodology.md` §18 |
| M10 | low | `--acs-vintage` is parsed and ignored. The F3 description still says "log-scaled penalties". The E3 unit reads lb/km², but the kernel divides by m². The F3 window has no upper bound | `run_scoring.py:588`, `indicators.py` |
| M11 | test-gap | Nothing imports `run_scoring.py`, and none of the three recent scoring fixes added a test | — |

## 2. Drafting assistant and API

**Checked and correct:**
- bcb0c70.
- The migration checksum and ordering checks, and the advisory lock.
- Every up migration is reversed by its down.
- All SQL is parameterised.
- Only verified drafts are cached, and `unclear` counts as a failure.
- The insufficient band is refused before any spend.
- CORS is restricted.

| # | Sev | Finding | Where |
|---|---|---|---|
| A1 | **critical** | **The complaint's `legal_basis` citations are never verified.** `AgencyComplaintDraft` does not add them to `citations`, so a fabricated statute there verifies and is cached (reproduced) | `assistant/documents.py:196-218,280` |
| A2 | high | **Citation dedupe drops repeat propositions.** The key is (kind, section, doc), so a second, false claim on an already-cited section is never judged (reproduced) | `documents.py:209,387` |
| A3 | high | **One requester's free text is cached and served to everyone else.** `request` shapes retrieval and generation but is not in the cache key | `routers/draft.py:48`, `service.py:81` |
| A4 | medium | **LIKE wildcards in a model-supplied section label get past the existence check** (reproduced on Neon: `4_ U.S.C.`, `%`) | `verifier.py:116-128` |
| A5 | medium | **The cache key and stamps use the app constant, not the scored run.** A re-run under the same version serves drafts with old scores | `draft.py:149`, `service.py:200,305` |
| A6 | medium | **A non-canonical h3 value returns 500.** Upper case, `0x` and whitespace pass `h3.is_valid_cell` and then fail the `h3_cell` domain. `/draft` does not validate at all | `routers/hex.py`, `draft.py:46` |
| A7 | medium | **Verifier and provider failures return 500.** Verification is not wrapped, and connection, timeout and 5xx errors are not mapped to 503 | `service.py:155-172,283` |
| A8 | medium | **The DB pool never retries after a failed first connect**, so a Neon cold start leaves the process degraded forever | `db.py:19-37` |
| A9 | medium | **`/draft` has no rate limit, and a new `AsyncOpenAI` client is built and never closed on every request** | `draft.py:134` |
| A10 | medium | **Spend omits embedding and judge tokens.** Verification is recorded as 0 tokens | `service.py:288` |
| A11 | medium | **Record citations never check the claim they carry**, although the verifier's docstring promises they do | `verifier.py:289-342` |
| A12 | low | **The capped facility count (50) is presented to the model as the total** | `context.py:235`, `facilities.py:260` |
| A13 | low | **The corpus `embedding_model` is never compared with the configured model.** Retrieval can come back short across several corpus versions (HNSW post-filter) | `retrieval.py:96-117` |
| A14 | low | **Migration runner edge cases:** `--to` is compared as a string (`up --to 7` applies everything), the "one statement" no-transaction rule is not enforced, `down` skips the drift check, and `status` writes | `migrate.py:247,263` |
| A15 | test-gap | **No router-level test of the 422/409/503 mapping.** `test_hex` accepts 200 *or* 503 | `api/tests` |

## 3. ETL

**Checked and correct:**
- Crosswalk normalisation.
- Extensive/intensive enforcement.
- ACS margins of error.
- EPSG:5070 areas.
- The grid fringe.
- The AirToxScreen 2010→2020 crossing.
- TRI unit conversion.
- The sink's single transaction.
- The quality gate's skip-to-fail on required sources.
- The disparity statistics.
- Deterministic tiles.

| # | Sev | Finding | Where |
|---|---|---|---|
| E1 | high | **Reconciliation passes an empty crosswalk.** Every unreached tract counts as "explained" (reproduced: 12,000 people, residual 0) | `dasymetric/reconcile.py:131-171` |
| E2 | high | **c5c9ac0 broke `areal_counterpart`.** Dropped zero-population rows mean `area_weight` no longer sums to 1, so `PartialCrosswalk` is raised and the §13.5 areal comparison cannot run | `dasymetric/weights.py:310`, `areal.py:95` |
| E3 | medium | **`derive_rate` divides a partial numerator by a full denominator.** A missing numerator acts as zero (reproduced: 0.25 vs 0.5) | `dasymetric/interpolate.py:227-260` |
| E4 | high | **The stale-snapshot fallback cannot work from the CLI.** Each process gets a new `InMemorySnapshotStore`, yet the README and the published gaps promise "continues on the last good snapshot" | `__main__.py:125`, `http.py:223` |
| E5 | medium | **Nightly loads into `InMemorySink`, requires only `fake`, and pulls `census_block` (about 30 min) every night** with no schedule entry. The budget comments are stale | `__main__.py:430`, `etl.yml:113`, `schedule.py` |
| E6 | medium | **`_LazyConnection` reconnects mid-transaction,** so the remaining statements autocommit on a fresh connection | `__main__.py:176-184` |
| E7 | medium | **ECHO paging:** `responseset` is not sent at registration, and a shortfall against `expected` is only a note, so the status stays `ok` | `adapters/echo.py:583-701` |
| E8 | low | **Stale AirToxScreen gap and docstrings after d9ffb26**, plus minor counting and default-vintage issues | `airtoxscreen.py:671`, `schedule.py:224`, `tract_vintage.py:152` |

## 4. Statute corpus, scripts and CI

**Checked and correct:**
- The manifest matches Appendix B.
- No chunk crosses a section boundary.
- The fetch-cache hash.
- Embedding checks.
- Every guard script exits non-zero on error.
- There is no `continue-on-error` or `|| true` in CI.

| # | Sev | Finding | Where |
|---|---|---|---|
| C1 | high | **eCFR clause `(i)` after `(h)` is parsed as a sibling subsection,** producing citable labels that do not exist (`§ 7.35(i)`, `§ 7.35(ii)(i)`) | `assistant/corpus/parse.py:187,231` |
| C2 | medium | **The preregistration guard misses edits to `sites.yml` made after scoring exists** | `scripts/check_preregistration.sh` |
| C3 | medium | **The version label hashes only the manifest,** so a parser fix cannot be rebuilt under its default name | `corpus/ingest.py:381` |
| C4 | medium | **The seal records the in-memory hash** without locking the row or comparing it with the stored chunks | `corpus/store.py:172` |
| C5 | medium | **`TRUNCATE` bypasses the seal triggers,** and no test writes to a sealed version | `0018…up.sql` |
| C6 | medium | **`test_retrieval_sql` never runs in CI,** and `make test-spatial` and CI run different sets | `ci.yml`, `Makefile:356` |
| C7 | medium | **The citation audit and red-team hardcode methodology `0.1.4` and read the draft cache.** The audit also exits 0 when 49 of 50 drafts error | `run_citation_audit.py:103,181,519`, `run_redteam.py:65` |
| C8 | low | **Spot-check prefix match counts `2000d-1` as a hit for `2000d`.** The `sections` range filter hides partial coverage. The seal test only asserts a subclass | `spotcheck.py:267`, `ingest.py:291`, `test_ingest.py:144` |
| C9 | low | **CI push trigger lists a nonexistent `project-setup` branch.** `scripts/` is never linted. `pip install` is unpinned | `ci.yml:5` |

## 5. Frontend

**Checked and correct:**
- Band cut points.
- Ramp breaks.
- `types.ts` matches `schemas.py` field for field.
- No `innerHTML` anywhere.
- Map and search effects clean up.
- The insufficient-band toggle.

| # | Sev | Finding | Where |
|---|---|---|---|
| W1 | high | **The previous hex's draft stays on screen under a newly selected hex,** and an in-flight POST lands under the wrong one (reproduced) | `App.tsx:76`, `DraftPanel.tsx:335` |
| W2 | medium | **Out-of-order `getHex` responses can show the wrong hex.** There is no abort and no loading state | `App.tsx:43-53` |
| W3 | medium | **The complaint's `legal_basis` is never rendered or exported,** and key-figure citations are missing from the list | `DraftPanel.tsx`, `lib/draft.ts` |
| W4 | medium | **Unscored hexes render hatched, but the legend shows them solid grey,** and the API calls them `insufficient` | `lib/ramp.ts:62-89` |
| W5 | medium | **The search dropdown reopens after a pick** | `SearchBox.tsx:31-57` |
| W6 | medium | **Keyboard users cannot open a hex panel.** Search only flies to the location | `MapView.tsx:157,199` |
| W7 | low | **Rendering mismatches:** the legend hatch leans the other way from the map; `fill-opacity: 0.75` makes map colours differ from the swatches; ordinals come out as "1th"/"22th"; the clipboard rejection is unhandled; the blob URL is revoked too early | various |

## 6. Repository hygiene, structure and documentation

**Checked and fine:**
- No tracked caches, venvs or builds.
- No secrets tracked.
- Every relative Markdown link and anchor resolves.
- The four Python packages share one ruff/mypy configuration.

| # | Sev | Finding | Where |
|---|---|---|---|
| R1 | high | **`.railway/railway.ts` still deploys a Railway `db` service and volume** and composes `DATABASE_URL` from it. The README says the database is Neon | `.railway/railway.ts` |
| R2 | high | **`neon-setup` has no upstream,** and 19 commits exist only on this machine | git |
| R3 | high | **README status says "Phase 0 … nothing is scored yet"**, while run 11 results are committed | `README.md:7,227` |
| R4 | medium | **`docs/database.md`, `CONTRIBUTING.md` and the `infra/postgres` header describe the container as the default path.** `backlog.md` describes a Railway DB, and the CS-206/212/213 statuses are stale | docs |
| R5 | medium | **`.env.example` is missing `LOG_FORMAT`, `DB_CONNECT_TIMEOUT`, `DATABASE_URL_UNPOOLED`, `TILES_ORIGIN` and `CLEARSKIES_TEST_DATABASE_URL`,** and its comments are stale | `.env.example` |
| R6 | medium | **An unused second schema:** `src/db`, `drizzle/`, `drizzle.config.ts` and the root `package.json`. Nothing imports it | root |
| R7 | medium | **`make score` and `make ingest` are Phase 0 placeholders,** though `run_scoring.py`, `export_run.py` and `pipeline run` exist | `Makefile:380` |
| R8 | medium | **Stale branches:** `origin/QA` and the local `cs-214` ref are merged; `origin/cs-213-disparity-command` has one unmerged commit (bc889a5) | git |
| R9 | low | **README layout** omits most docs and `api/app/assistant`, says 22 migrations (there are 23), and lists the untracked `.neon`. There is no docs index, and `site-validation.md` and `disparity.md` are linked from nowhere. "`make check` = CI" is inaccurate | `README.md`, `docs/` |
| R10 | low | **Housekeeping:** `*.local` in `.gitignore` is broad; the vendored `.claude/skills` are undocumented; the `extensions` help text says three extensions; there is no drafting issue template | root |

Operational note: on the Neon dev branch, migration **0023 is pending**, no
`pipeline_run` is current, and no corpus version is sealed. The audit did not
change any of this.
