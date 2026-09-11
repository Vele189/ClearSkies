.DEFAULT_GOAL := help
SHELL := /bin/bash

API := api
ETL := etl
WEB := web
SCORING := scoring
VENV := $(API)/.venv
ETL_VENV := $(ETL)/.venv
SCORING_VENV := $(SCORING)/.venv
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

.PHONY: install
install: $(VENV) $(ETL_VENV) $(SCORING_VENV) ## Install Python and frontend dependencies
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
	  .venv/bin/python -m pytest tests/test_facility_hex_sql.py -q

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
check: lint test etl-check scoring-check ## Everything CI runs, plus the validation-set guards
	./scripts/check_preregistration.sh
	$(PY) scripts/check_validation_set.py
	$(PY) scripts/check_requirements_sync.py
	$(PY) scripts/verify_anchors.py
	$(MAKE) validate-harness

# ---- Pipeline (Phase 1 and 2) -----------------------------------------

# `tiles` left this list in CS-207 and is a real target above. `score` is still
# a placeholder: the scoring package is built and tested, but running it end to
# end needs a populated database, which is CS-204's remaining dependency.
.PHONY: ingest score
ingest score:
	@echo "'$@' arrives in Phase $(if $(filter ingest,$@),1,2). See docs/methodology.md."
	@exit 1
