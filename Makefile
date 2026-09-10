.DEFAULT_GOAL := help
SHELL := /bin/bash

API := api
WEB := web
VENV := $(API)/.venv
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

# ---- API ---------------------------------------------------------------

$(VENV): $(API)/pyproject.toml
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e "$(API)[dev]"
	@touch $(VENV)

.PHONY: install
install: $(VENV) ## Install API dependencies
	cd $(WEB) && npm ci

.PHONY: api
api: $(VENV) ## Run the API on :8000, docs at /docs
	cd $(API) && .venv/bin/uvicorn app.main:app --reload --port 8000

.PHONY: web
web: ## Run the Vite dev server on :5173
	cd $(WEB) && npm run dev

# ---- Checks ------------------------------------------------------------

.PHONY: test
test: $(VENV) ## Run both test suites
	cd $(API) && .venv/bin/python -m pytest -q
	cd $(WEB) && npm run test

.PHONY: lint
lint: $(VENV) ## Lint and typecheck both services
	cd $(API) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(API) && .venv/bin/mypy app tests
	cd $(WEB) && npm run lint
	cd $(WEB) && npm run typecheck

.PHONY: build
build: ## Production build of the frontend
	cd $(WEB) && npm run build

.PHONY: check
check: lint test ## Everything CI runs, plus the validation-set guards
	./scripts/check_preregistration.sh
	$(PY) scripts/check_validation_set.py

# ---- Pipeline (Phase 1 and 2) -----------------------------------------

.PHONY: migrate ingest score tiles
migrate ingest score tiles:
	@echo "'$@' arrives in Phase $(if $(filter migrate ingest,$@),1,2). See docs/methodology.md."
	@exit 1
