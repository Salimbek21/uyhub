#  UyHub — developer entrypoints.
#
#  Run `make help` for the full list. Targets that a later phase will deliver are
#  present and fail with the phase number rather than being silently missing
#  (CLAUDE.md keeps this list accurate).

.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

BACKEND  := backend
COMPOSE  := docker compose --env-file .env -f infra/docker-compose.yml
# This network intercepts TLS; uv must trust the system certificate store.
UV       := UV_SYSTEM_CERTS=1 uv --directory $(BACKEND)
RUN      := $(UV) run

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUyHub targets:\n\n"} \
		/^[a-zA-Z0-9_.-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@echo

.PHONY: .require-env
.require-env:
	@test -f .env || { \
		echo "error: .env is missing. Run: cp .env.example .env"; \
		exit 1; \
	}

##@ Local stack

.PHONY: up
up: .require-env ## Start Postgres, Redis and SeaweedFS and wait until healthy
	$(COMPOSE) up -d --wait
	$(RUN) uyhub init-storage
	@echo "infrastructure ready"

.PHONY: down
down: .require-env ## Stop the stack, keeping all data
	$(COMPOSE) down

.PHONY: ps
ps: .require-env ## Show container status
	$(COMPOSE) ps -a

.PHONY: logs
logs: .require-env ## Follow container logs
	$(COMPOSE) logs -f --tail=100

.PHONY: clean
clean: ## Remove build and tool caches (no data is touched)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(BACKEND)/.mypy_cache
	@echo "caches removed"

.PHONY: clean-volumes
clean-volumes: .require-env ## DESTRUCTIVE: delete database, Redis and object storage data
	@echo "This deletes the local Postgres, Redis and SeaweedFS volumes. Data is unrecoverable."
	@read -r -p "Type 'yes' to continue: " answer && [ "$$answer" = "yes" ] || { echo "aborted"; exit 1; }
	$(COMPOSE) down -v

##@ Development

.PHONY: install
install: ## Install or update Python dependencies from uv.lock
	$(UV) sync

.PHONY: fmt
fmt: ## Format the code (ruff)
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

.PHONY: lint
lint: lint-backend lint-frontend ## Lint and type-check everything

.PHONY: lint-backend
lint-backend: ## ruff + mypy --strict on backend/src
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy

.PHONY: lint-frontend
lint-frontend: ## eslint + tsc on the Mini App (Phase 5)
	@if [ -d miniapp/node_modules ]; then \
		cd miniapp && npm run lint && npx tsc --noEmit; \
	elif [ -f miniapp/package.json ]; then \
		echo "miniapp: dependencies missing. Run: cd miniapp && npm ci"; exit 1; \
	else \
		echo "miniapp: not present yet (Phase 5) — skipping eslint and tsc"; \
	fi

.PHONY: typecheck
typecheck: ## mypy --strict only
	$(RUN) mypy

.PHONY: hooks
hooks: ## Install the git pre-commit hooks
	$(RUN) pre-commit install

.PHONY: pre-commit
pre-commit: ## Run every pre-commit hook against all files
	$(RUN) pre-commit run --all-files

##@ Tests

.PHONY: test
test: .require-env ## Run all tests (needs `make up`)
	$(RUN) pytest

.PHONY: test-unit
test-unit: ## Run only tests with no external dependencies
	$(RUN) pytest -m unit

.PHONY: test-integration
test-integration: .require-env ## Run only tests that need Postgres, Redis and object storage
	$(RUN) pytest -m integration

.PHONY: coverage
coverage: .require-env ## Run tests with a coverage report
	$(RUN) pytest --cov=uyhub --cov-report=term-missing

##@ Database

.PHONY: migrate
migrate: .require-env ## Apply all migrations
	$(RUN) alembic upgrade head

.PHONY: migration
migration: .require-env ## Create a revision: make migration m="add listings"
	@test -n "$(m)" || { echo 'error: provide a message, e.g. make migration m="add listings"'; exit 1; }
	$(RUN) alembic revision --autogenerate -m "$(m)"

.PHONY: downgrade
downgrade: .require-env ## Roll back one revision
	$(RUN) alembic downgrade -1

.PHONY: db-shell
db-shell: .require-env ## Open psql against the local database
	$(COMPOSE) exec postgres psql -U "$${POSTGRES_USER:-uyhub}" -d "$${POSTGRES_DB:-uyhub}"

##@ Services

.PHONY: api
api: .require-env ## Run the API with auto-reload
	$(RUN) uyhub api --reload

.PHONY: check
check: .require-env ## Probe Postgres, Redis and object storage from the application
	$(RUN) uyhub check

.PHONY: init-storage
init-storage: .require-env ## Create the object storage buckets if missing
	$(RUN) uyhub init-storage

.PHONY: collector
collector: .require-env ## Run the Telegram collector
	$(RUN) uyhub collector

##@ Operator commands

.PHONY: login-userbot
login-userbot: .require-env ## Interactive Telethon login — run this yourself, never in CI
	@echo "Interactive. The phone number, login code and 2FA password are typed"
	@echo "here and are never logged, stored or sent anywhere but Telegram."
	@echo
	$(RUN) python scripts/login_userbot.py

##@ Not implemented yet

.PHONY: eval-parser
eval-parser: ## Parser accuracy on the golden set
	$(RUN) python tests/eval/run_eval.py $(ARGS)

.PHONY: seed
seed: ## Seed 200k listings for the performance test (Phase 4)
	@echo "not implemented until Phase 4 (API)."
	@exit 1
