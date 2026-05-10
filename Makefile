.DEFAULT_GOAL = help

.PHONY: build
build: ## Build container image.
	docker compose build

.PHONY: start
start: ## Spin up container.
	docker compose up -d

.PHONY: down
down: ## Stop and remove container.
	docker compose down

.PHONY: restart
restart: ## Restart container (requires Claude Code restart to reconnect SSE).
	docker compose restart mcp-gee-sweet

.PHONY: recreate
recreate: ## Recreate container from scratch (removes historical logs).
	docker compose up -d --force-recreate

.PHONY: logs
logs: ## Tail container logs.
	docker compose logs -f

.PHONY: sh
sh: ## Open a shell in the container.
	docker compose exec mcp-gee-sweet bash

.PHONY: install-hooks
install-hooks: ## Install pre-commit hooks into the local git repo.
	uv run pre-commit install

.PHONY: test
test: ## Run unit tests.
	uv run pytest

.PHONY: lint
lint: ## Run ruff linter and formatter, fixing issues in place.
	uv run ruff check --fix src/
	uv run ruff format src/

.PHONY: lint-extra
lint-extra: ## Run extended ruff rules (bugbear, pyupgrade, simplify) with fixes.
	uv run ruff check --fix --extend-select B,UP,SIM,RUF src/
	uv run ruff format src/

# Self-documenting help
# https://www.freecodecamp.org/news/self-documenting-makefile/
.PHONY: help
help: ## Show this help.
	@egrep -h '\s##\s' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
