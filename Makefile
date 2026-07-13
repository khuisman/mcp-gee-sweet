.DEFAULT_GOAL = help

.PHONY: run
run: ## Run MCP server locally via stdio.
	uv run mcp-gee-sweet

.PHONY: run-sse
run-sse: ## Run MCP server locally via SSE (http://localhost:8000).
	uv run mcp-gee-sweet --transport sse

.PHONY: package
package: ## Build distributable wheel and sdist into dist/.
	uv build

.PHONY: sync
sync: ## Sync dependencies from uv.lock.
	uv sync

.PHONY: oauth
oauth: ## Start OAuth consent flow — prints URL, waits for browser callback, writes token.json.
	uv run python scripts/oauth_setup.py

.PHONY: oauth-from-token
oauth-from-token: ## Reconstruct token.json from GOOGLE_OAUTH_REFRESH_TOKEN env var (CI / headless).
	uv run python scripts/oauth_setup.py --from-refresh-token

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

.PHONY: dev-logs
dev-logs: ## Tail MCP server log file (requires LOG_FILE set in src/mcp_gee_sweet/.env).
	tail -f $$(grep -E '^LOG_FILE=' src/mcp_gee_sweet/.env | cut -d= -f2)

.PHONY: access-logs
access-logs: ## Tail HTTP access log (requires ACCESS_LOG_FILE set in src/mcp_gee_sweet/.env).
	tail -f $$(grep -E '^ACCESS_LOG_FILE=' src/mcp_gee_sweet/.env | cut -d= -f2)

.PHONY: sh
sh: ## Open a shell in the container.
	docker compose exec mcp-gee-sweet bash

.PHONY: docs
docs: ## Serve docs locally at http://127.0.0.1:8000 (live reload).
	uv run mkdocs serve

.PHONY: install-hooks
install-hooks: ## Install pre-commit hooks into the local git repo.
	uv run pre-commit install

.PHONY: setup-team
setup-team: ## Idempotently provision/refresh dev-team worktree slots and MCP config, without launching Claude.
	scripts/setup_team.sh

.PHONY: claude-team
claude-team: setup-team ## Launch Claude Code with all dev-team MCP servers connected (Kai/Ash/Sky/Jay/Kit/Aziz/Amy) for Agent View.
	claude --mcp-config .claude/mcp-configs/team.mcp.json --strict-mcp-config

.PHONY: test
test: ## Run unit tests.
	uv run python -m pytest

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
