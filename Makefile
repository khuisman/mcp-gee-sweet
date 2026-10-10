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

# Each role's model and effort, explicit rather than the client's default, which
# changed under us once (Claude Code 2.1.280 moved some plans from Sonnet to Opus;
# #947). Override per launch, e.g. `make team-ash ASH_MODEL=sonnet ASH_EFFORT=medium`.
# An empty *_EFFORT omits --effort, leaving the client's default for that model.
TEAM_MODEL ?= opus
TEAM_EFFORT ?=
ASH_MODEL ?= $(TEAM_MODEL)
ASH_EFFORT ?= $(TEAM_EFFORT)
SKY_MODEL ?= $(TEAM_MODEL)
SKY_EFFORT ?= $(TEAM_EFFORT)
JAY_MODEL ?= $(TEAM_MODEL)
JAY_EFFORT ?= $(TEAM_EFFORT)
KIT_MODEL ?= $(TEAM_MODEL)
KIT_EFFORT ?= $(TEAM_EFFORT)
KAI_MODEL ?= $(TEAM_MODEL)
KAI_EFFORT ?= $(TEAM_EFFORT)
AZIZ_MODEL ?= $(TEAM_MODEL)
AZIZ_EFFORT ?= $(TEAM_EFFORT)
AMY_MODEL ?= $(TEAM_MODEL)
AMY_EFFORT ?= $(TEAM_EFFORT)
JOY_MODEL ?= $(TEAM_MODEL)
JOY_EFFORT ?= $(TEAM_EFFORT)
BOB_MODEL ?= $(TEAM_MODEL)
BOB_EFFORT ?= $(TEAM_EFFORT)

team_model = --model $($(1)_MODEL)$(if $($(1)_EFFORT), --effort $($(1)_EFFORT))

.PHONY: claude-team
claude-team: setup-team ## Launch Claude Code with all dev-team MCP servers connected (Kai/Ash/Sky/Jay/Kit/Aziz/Amy/Joy/Bob) for Agent View.
	claude $(call team_model,KAI) --mcp-config .claude/mcp-configs/team.mcp.json --strict-mcp-config --name "Kai"

# Each role session loads only its own servers (.claude/mcp-configs/<name>.mcp.json,
# written by setup_team.sh), not all of team.mcp.json: other roles' tool names cost
# ~26k tokens per session (#850). The flags go after the prompt because
# --mcp-config takes a variadic list and would swallow it. team-kai and team-aziz
# stay unflagged: they use every team server from the root .mcp.json plus the
# user-global ones, which --strict-mcp-config would drop.
team_mcp = --mcp-config "$(CURDIR)/.claude/mcp-configs/$(1).mcp.json" --strict-mcp-config

.PHONY: team-ash
team-ash: setup-team ## Launch Claude Code backgrounded directly into the Ash persona (Dev, lane A); shows up in `claude agents`.
	claude --bg --name "Ash" $(call team_model,ASH) "/team-member Ash" $(call team_mcp,ash)

.PHONY: team-sky
team-sky: setup-team ## Launch Claude Code backgrounded directly into the Sky persona (QA, lane A); shows up in `claude agents`.
	claude --bg --name "Sky" $(call team_model,SKY) "/team-member Sky" $(call team_mcp,sky)

.PHONY: team-jay
team-jay: setup-team ## Launch Claude Code backgrounded directly into the Jay persona (Dev, lane B); shows up in `claude agents`.
	claude --bg --name "Jay" $(call team_model,JAY) "/team-member Jay" $(call team_mcp,jay)

.PHONY: team-kit
team-kit: setup-team ## Launch Claude Code backgrounded directly into the Kit persona (QA, lane B); shows up in `claude agents`.
	claude --bg --name "Kit" $(call team_model,KIT) "/team-member Kit" $(call team_mcp,kit)

.PHONY: team-aziz
team-aziz: setup-team ## Launch Claude Code backgrounded directly into the Aziz persona (Release QA lead); shows up in `claude agents`.
	claude --bg --name "Aziz" $(call team_model,AZIZ) "/team-member Aziz"

.PHONY: team-amy
team-amy: setup-team ## Launch Claude Code backgrounded directly into the Amy persona (Tech writer); shows up in `claude agents`.
	claude --bg --name "Amy" $(call team_model,AMY) "/team-member Amy" $(call team_mcp,amy)

.PHONY: team-joy
team-joy: setup-team ## Launch Claude Code backgrounded directly into the Joy persona (Lead architect); shows up in `claude agents`.
	claude --bg --name "Joy" $(call team_model,JOY) "/team-member Joy" $(call team_mcp,joy)

.PHONY: team-bob
team-bob: setup-team ## Launch Claude Code backgrounded directly into the Bob persona (Senior prompt engineer); shows up in `claude agents`.
	claude --bg --name "Bob" $(call team_model,BOB) "/team-member Bob" $(call team_mcp,bob)

.PHONY: team-kai
team-kai: setup-team ## Launch Claude Code backgrounded directly into the Kai persona (Orchestrator); shows up in `claude agents`.
	claude --bg --name "Kai" $(call team_model,KAI) "/team-member Kai"

.PHONY: lane-a
lane-a: team-ash team-sky ## Launch both Ash (Dev) and Sky (QA) for lane A in the background.

.PHONY: lane-b
lane-b: team-jay team-kit ## Launch both Jay (Dev) and Kit (QA) for lane B in the background.

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
