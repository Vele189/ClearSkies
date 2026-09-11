.DEFAULT_GOAL := help
SHELL := /bin/bash

API := api
ETL := etl
WEB := web
SCORING := scoring
ASSISTANT := assistant
VENV := $(API)/.venv
ETL_VENV := $(ETL)/.venv
SCORING_VENV := $(SCORING)/.venv
ASSISTANT_VENV := $(ASSISTANT)/.venv
PY := $(VENV)/bin/python

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---- Database ----------------------------------------------------------

.PHONY: up
up: ## Start Postgres with PostGIS, h3 and pgvector
	docker compose up -d --build db
	@echo "waiting for the database to finish initializing..."
	@until docker compose exec -T db psql -h 127.0.0.1 -U clearskies -d clearskies \
	  -tAc "SELECT 1 FROM clearskies_extensions LIMIT 1" >/dev/null 2>&1; \
	  do sleep 1; done
	@echo "ready"

.PHONY: down
down: ## Stop the database, keeping its volume
	docker compose down

.PHONY: extensions
extensions: ## Prove the custom image loaded all three extensions
	docker compose exec -T db psql -U clearskies -d clearskies \
	  -c "SELECT * FROM clearskies_extensions"

.PHONY: psql
psql: ## Open a psql shell on the local database
	docker compose exec db psql -U clearskies -d clearskies

# ---- Migrations --------------------------------------------------------
#
# Every schema change lands here. Nothing creates, alters or drops a table
# outside api/migrations; see docs/database.md.

.PHONY: migrate
migrate: $(VENV) ## Apply pending migrations
	cd $(API) && .venv/bin/python -m app.migrate up

.PHONY: migrate-status
migrate-status: $(VENV) ## List applied and pending migrations
	cd $(API) && .venv/bin/python -m app.migrate status

.PHONY: migrate-verify
migrate-verify: $(VENV) ## Fail unless every migration is applied and unedited
	cd $(API) && .venv/bin/python -m app.migrate verify

.PHONY: migrate-down
migrate-down: $(VENV) ## Revert the last migration
	cd $(API) && .venv/bin/python -m app.migrate down

.PHONY: migrate-new
migrate-new: $(VENV) ## Scaffold one: make migrate-new name=add_facility_naics
	@test -n "$(name)" || { echo "usage: make migrate-new name=add_facility_naics"; exit 1; }
	cd $(API) && .venv/bin/python -m app.migrate new $(name)

# ---- API ---------------------------------------------------------------

$(VENV): $(API)/pyproject.toml
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e "$(API)[dev]"
	@touch $(VENV)

# ---- ETL ---------------------------------------------------------------
# Its own environment: the ingestion job needs GeoPandas and h3 and the API
# does not, and the API service should not carry them into its container.

$(ETL_VENV): $(ETL)/pyproject.toml
	python3 -m venv $(ETL_VENV)
	$(ETL_VENV)/bin/pip install -q -e "$(ETL)[dev]"
	@touch $(ETL_VENV)

.PHONY: sources
sources: $(ETL_VENV) ## List the registered data sources
	cd $(ETL) && .venv/bin/python -m pipeline sources

.PHONY: ingest-fake
ingest-fake: $(ETL_VENV) ## Run the reference adapter end to end, no network needed
	cd $(ETL) && .venv/bin/python -m pipeline run fake

.PHONY: etl-check
etl-check: $(ETL_VENV) ## Lint, typecheck and test the ingestion package
	cd $(ETL) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(ETL) && .venv/bin/mypy pipeline tests
	cd $(ETL) && .venv/bin/python -m pytest -q
	cd $(ETL) && .venv/bin/python -m pipeline --log-level warning run fake
	cd $(ETL) && .venv/bin/python -m pipeline --log-level warning check fake --no-store

# ---- Scoring -----------------------------------------------------------
# Its own environment, and a deliberately empty dependency list. Section 13
# wants a run reproducible from its inputs, so the arithmetic stays on stdlib
# floats over an explicitly sorted list.

$(SCORING_VENV): $(SCORING)/pyproject.toml
	python3 -m venv $(SCORING_VENV)
	$(SCORING_VENV)/bin/pip install -q -e "$(SCORING)[dev]"
	@touch $(SCORING_VENV)

.PHONY: scoring-check
scoring-check: $(SCORING_VENV) ## Lint, typecheck and test the scoring package
	cd $(SCORING) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(SCORING) && .venv/bin/mypy burden tests
	cd $(SCORING) && .venv/bin/python -m pytest -q

# ---- Statute corpus (CS-301) -------------------------------------------
#
# Its own environment, like the others. The corpus is built from public
# publishers over the network and written to the database as a versioned,
# sealed artifact; docs/corpus.md is the operator guide and
# docs/methodology.md Appendix B is the manifest of record.

$(ASSISTANT_VENV): $(ASSISTANT)/pyproject.toml
	python3 -m venv $(ASSISTANT_VENV)
	$(ASSISTANT_VENV)/bin/pip install -q -e "$(ASSISTANT)[dev]"
	@touch $(ASSISTANT_VENV)

.PHONY: corpus-manifest
corpus-manifest: $(ASSISTANT_VENV) ## Print the Appendix B manifest and its sources
	cd $(ASSISTANT) && .venv/bin/python -m corpus manifest

# Appendix B.4 rule 4: an authority exists in the corpus only if the paper says
# it does. Both directions, so the paper cannot promise one that nothing pulls.
.PHONY: corpus-check
corpus-check: $(ASSISTANT_VENV) ## Compare the manifest with docs/methodology.md
	cd $(ASSISTANT) && .venv/bin/python -m corpus check

.PHONY: corpus-build
corpus-build: $(ASSISTANT_VENV) ## Fetch, parse and chunk without writing anything
	cd $(ASSISTANT) && .venv/bin/python -m corpus build

.PHONY: corpus-ingest
corpus-ingest: $(ASSISTANT_VENV) ## Build and write a corpus version, unsealed
	cd $(ASSISTANT) && .venv/bin/python -m corpus ingest

# Exits non-zero unless the build covers every authority in Appendix B. An
# incomplete corpus stays open, and an open version is invisible to retrieval.
.PHONY: corpus-seal
corpus-seal: $(ASSISTANT_VENV) ## Build, write and seal a corpus version
	cd $(ASSISTANT) && .venv/bin/python -m corpus ingest --seal

# Embedding calls a paid API. It is implied by corpus-seal, because a sealed
# version refuses writes and one sealed without vectors has gaps that can never
# be filled.
.PHONY: corpus-embed
corpus-embed: $(ASSISTANT_VENV) ## Generate embeddings for the open corpus version
	cd $(ASSISTANT) && .venv/bin/python -m corpus ingest --embed

# Retrieval against the hand-written question set in corpus/questions.py.
# Not a benchmark: twenty pairs cannot say retrieval is good, only that it has
# stopped returning things it used to.
.PHONY: corpus-spotcheck
corpus-spotcheck: $(ASSISTANT_VENV) ## Measure retrieval against the question set
	cd $(ASSISTANT) && .venv/bin/python -m corpus spotcheck \
	  $(if $(REQUIRE_RECALL),--require-recall $(REQUIRE_RECALL),)

.PHONY: corpus-versions
corpus-versions: $(ASSISTANT_VENV) ## What corpus versions the database holds
	cd $(ASSISTANT) && .venv/bin/python -m corpus versions

.PHONY: assistant-check
assistant-check: $(ASSISTANT_VENV) ## Lint, typecheck and test the assistant package
	cd $(ASSISTANT) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(ASSISTANT) && .venv/bin/mypy corpus tests
	cd $(ASSISTANT) && .venv/bin/python -m pytest -q
	cd $(ASSISTANT) && .venv/bin/python -m corpus check

# ---- Tiles (CS-207) ----------------------------------------------------
#
# The map reads one PMTiles archive from R2 and there is no tile server. The
# build is a pipeline step rather than an export somebody performs, because the
# map is only ever as current as this file and one that depends on being
# remembered is one that silently goes stale. infra/r2/README.md has the bucket
# setup and why it is not on the Railway frontend service.

ARCHIVE ?= tiles/clearskies-la.pmtiles

.PHONY: tiles
tiles: $(ETL_VENV) ## Build the PMTiles archive: make tiles SCORES=run.json
	@test -n "$(SCORES)" || { echo "usage: make tiles SCORES=path/to/scores.json"; exit 1; }
	cd $(ETL) && .venv/bin/python -m pipeline tiles \
	  --scores $(abspath $(SCORES)) --out $(abspath $(ARCHIVE))

.PHONY: deploy-tiles
deploy-tiles: ## Upload the archive to R2: make deploy-tiles ARCHIVE=...
	@test -n "$$CLOUDFLARE_ACCOUNT_ID" || { echo "CLOUDFLARE_ACCOUNT_ID is not set"; exit 1; }
	@test -n "$$R2_BUCKET" || { echo "R2_BUCKET is not set"; exit 1; }
	aws s3 cp "$(ARCHIVE)" "s3://$$R2_BUCKET/$(notdir $(ARCHIVE))" \
	  --endpoint-url "https://$$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com" \
	  --content-type application/octet-stream

# Asks the published URL what a browser will ask. A host that ignores Range
# still renders a correct map while pulling the whole archive on every visit,
# which is invisible in a browser and visible only in a bill.
.PHONY: check-tiles
check-tiles: $(ETL_VENV) ## Confirm the published archive serves Range and CORS
	@test -n "$(URL)" || { echo "usage: make check-tiles URL=\$$VITE_TILES_URL"; exit 1; }
	cd $(ETL) && .venv/bin/python -m pipeline tiles-hosting --url "$(URL)" \
	  $(if $(ORIGIN),--origin "$(ORIGIN)",)

# The section 13 gate. One command, so a validation result is something anyone
# can reproduce rather than something someone reports. Exits non-zero unless the
# gate passed, because that is what a gate is for.
.PHONY: validate
validate: $(VENV) ## Run the validation protocol: make validate SCORES=run.json
	@test -n "$(SCORES)" || { echo "usage: make validate SCORES=path/to/scores.json"; exit 1; }
	$(PY) scripts/run_validation.py --scores $(SCORES) --require-pass $(if $(OUT),--out $(OUT),)

# Proves the command still parses the frozen fixture and applies the criteria
# without a database, on the same terms as `make ingest-fake`. The scores are
# invented and the fixture is built to fail, so this asserts that the gate runs,
# never that it passed.
.PHONY: validate-harness
validate-harness: $(VENV) ## Run the gate over the synthetic fixture, proving the command works
	$(PY) scripts/run_validation.py \
	  --scores $(SCORING)/tests/fixtures/synthetic_scores.json --out /dev/null

# The section 13.5 robustness checks. Also one command, and for the same reason:
# a result about whether the score is an artifact of its own construction is
# worth nothing if only one person can reproduce it. Unlike `validate` this does
# not gate by default, because two of the four things it reports are expressly
# reported rather than required; pass REQUIRE_PASS=1 to exit non-zero on a
# gating miss.
.PHONY: robustness
robustness: $(SCORING_VENV) ## Run the section 13.5 checks: make robustness VALUES=run.json
	@test -n "$(VALUES)" || { echo "usage: make robustness VALUES=path/to/values.json"; exit 1; }
	$(SCORING_VENV)/bin/python scripts/run_robustness.py --values $(VALUES) \
	  $(if $(REQUIRE_PASS),--require-pass,) $(if $(OUT),--out $(OUT),)

# Proves the command still scores a run four ways and applies the section 13.5
# criteria without a database, on the same terms as `validate-harness`. The
# values are invented and the fixture is built to fail, so this asserts that the
# checks run, never that they passed.
.PHONY: robustness-harness
robustness-harness: $(SCORING_VENV) ## Run the 13.5 checks over the synthetic fixture
	$(SCORING_VENV)/bin/python scripts/run_robustness.py \
	  --values $(SCORING)/tests/fixtures/synthetic_values.json --out /dev/null

# ---- Red team (CS-304) -------------------------------------------------
#
# Runs the adversarial set against the real model and writes the report. A
# script rather than a test because it costs money and needs a key, and a test
# suite that sometimes bills you is one people stop running. CI runs the offline
# half in api/tests/test_guardrails.py.

.PHONY: redteam
redteam: $(VENV) ## Run the red-team set against the model: make redteam
	cd $(API) && .venv/bin/python ../scripts/run_redteam.py \
	  --out ../docs/validation/redteam.md \
	  $(if $(MODEL),--model $(MODEL),) \
	  $(if $(REQUIRE_CLEAN),--require-clean,)

# The other half of the same argument: does the judge catch a real section
# attached to a claim it does not support? Eight traps and four true
# propositions, against the real corpus.
.PHONY: check-verifier
check-verifier: $(VENV) ## Check the citation verifier against real sections
	cd $(API) && .venv/bin/python ../scripts/check_verifier.py \
	  --out ../docs/validation/verifier.md \
	  $(if $(MODEL),--model $(MODEL),) \
	  $(if $(REQUIRE_CLEAN),--require-clean,)

# ---- The Phase 3 gate (CS-308) -----------------------------------------
#
# Fifty drafts across four document types and a spread of hexagons, with every
# citation re-checked independently of the pipeline that produced it. Needs a
# sealed corpus and a facility table with rows in it; `audit-seed` loads real
# ECHO facilities for the second.

.PHONY: audit-seed
audit-seed: $(VENV) ## Load real ECHO facilities so record citations can verify
	$(PY) scripts/seed_audit_facilities.py \
	  --database-url "$${DATABASE_URL:-postgresql://clearskies:clearskies@localhost:5432/clearskies}" \
	  --limit $(or $(LIMIT),60)

.PHONY: audit
audit: $(VENV) ## Run the fifty-draft citation audit
	cd $(API) && .venv/bin/python ../scripts/run_citation_audit.py \
	  --count $(or $(COUNT),50) \
	  --out ../docs/validation/citation-audit.md \
	  --drafts-dir ../docs/validation/audit-drafts \
	  $(if $(MODEL),--model $(MODEL),)

.PHONY: install
install: $(VENV) $(ETL_VENV) $(SCORING_VENV) $(ASSISTANT_VENV) ## Install Python and frontend dependencies
	cd $(WEB) && npm ci

.PHONY: api
api: $(VENV) ## Run the API on :8000, docs at /docs
	cd $(API) && .venv/bin/uvicorn app.main:app --reload --port 8000

.PHONY: web
web: ## Run the Vite dev server on :5173
	cd $(WEB) && npm run dev

# ---- Checks ------------------------------------------------------------

.PHONY: test
test: $(VENV) ## Run the API and frontend test suites
	cd $(API) && .venv/bin/python -m pytest -q
	cd $(WEB) && npm run test

# The rest of the API suite runs without a database on purpose. These cannot:
# what they check is what PostGIS does with a geography index and a spheroid
# distance. They seed inside a transaction and roll it back, so running them
# against your development database leaves it as it was.
.PHONY: test-spatial
test-spatial: $(VENV) ## Run the neighbour-query tests against the local database
	cd $(API) && CLEARSKIES_TEST_DATABASE_URL="$${DATABASE_URL:-postgresql://clearskies:clearskies@localhost:$${POSTGRES_PORT:-5432}/clearskies}" \
	  .venv/bin/python -m pytest tests/test_facility_hex_sql.py tests/test_retrieval_sql.py -q

.PHONY: lint
lint: $(VENV) ## Lint and typecheck the API and frontend
	cd $(API) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(API) && .venv/bin/mypy app tests
	cd $(WEB) && npm run lint
	cd $(WEB) && npm run typecheck

.PHONY: build
build: ## Production build of the frontend
	cd $(WEB) && npm run build

.PHONY: check
check: lint test etl-check scoring-check assistant-check ## Everything CI runs, plus the validation-set guards
	./scripts/check_preregistration.sh
	$(PY) scripts/check_validation_set.py
	$(PY) scripts/check_requirements_sync.py
	$(PY) scripts/verify_anchors.py
	$(MAKE) validate-harness
	$(MAKE) robustness-harness

# ---- Pipeline (Phase 1 and 2) -----------------------------------------

# `tiles` left this list in CS-207 and is a real target above. `score` is still
# a placeholder: the scoring package is built and tested, but running it end to
# end needs a populated database, which is CS-204's remaining dependency.
.PHONY: ingest score
ingest score:
	@echo "'$@' arrives in Phase $(if $(filter ingest,$@),1,2). See docs/methodology.md."
	@exit 1
