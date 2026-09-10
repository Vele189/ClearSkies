.DEFAULT_GOAL := help
SHELL := /bin/bash

API := api
ETL := etl
WEB := web
VENV := $(API)/.venv
ETL_VENV := $(ETL)/.venv
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

.PHONY: install
install: $(VENV) $(ETL_VENV) ## Install Python and frontend dependencies
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
check: lint test etl-check ## Everything CI runs, plus the validation-set guards
	./scripts/check_preregistration.sh
	$(PY) scripts/check_validation_set.py
	$(PY) scripts/check_requirements_sync.py

# ---- Pipeline (Phase 1 and 2) -----------------------------------------

.PHONY: ingest score tiles
ingest score tiles:
	@echo "'$@' arrives in Phase $(if $(filter ingest,$@),1,2). See docs/methodology.md."
	@exit 1
