#!/usr/bin/env bash
# Idempotently provision the dev-team worktree slots (ash/sky/jay/kit/aziz/amy/joy)
# and write the combined MCP config used by `make claude-team`.
#
# Each slot rests on its own `team/<name>` branch (never `develop` itself —
# that branch is always checked out in the main checkout). Dev slots branch
# off `team/<name>` into `feat/<name>/issue-<n>` per ticket; QA slots stay on
# `team/<name>` forever and get reset to whatever PR branch they're
# verifying (see `/team-member`). Aziz, Amy, and Joy are also persistent
# `team/<name>` slots but don't get a dedicated MCP server process — Aziz
# borrows Sky's/Kit's at release-QA time, Amy just needs a worktree to write
# docs PRs from, and Joy just needs one for ad-hoc architecture work
# (see `.claude/team-roles/joy.md`).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORKTREE_ROLES=(ash sky jay kit aziz amy joy)
CONFIG_FILES=(.env credentials.json service_account.json token.json .claude/settings.local.json)

git fetch origin develop --quiet

for name in "${WORKTREE_ROLES[@]}"; do
  worktree_path="$REPO_ROOT/.claude/worktrees/$name"

  if [ ! -d "$worktree_path" ]; then
    echo "Creating worktree slot: $name"
    git worktree add "$worktree_path" -b "team/$name" origin/develop
  fi

  for f in "${CONFIG_FILES[@]}"; do
    src="$REPO_ROOT/$f"
    dst="$worktree_path/$f"
    if [ -f "$src" ] && [ ! -f "$dst" ]; then
      mkdir -p "$(dirname "$dst")"
      cp "$src" "$dst"
    fi
  done

  echo "Syncing dependencies: $name"
  (cd "$worktree_path" && uv sync --quiet)
done

echo "Writing .claude/mcp-configs/team.mcp.json"
mkdir -p "$REPO_ROOT/.claude/mcp-configs"

role_server() {
  local key="$1" dir="$2"
  cat <<JSON
    "$key": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "$dir", "mcp-gee-sweet"],
      "env": {
        "AUTH_METHOD": "oauth",
        "CREDENTIALS_PATH": "$dir/credentials.json",
        "TOKEN_PATH": "$dir/token.json"
      }
    }
JSON
}

# No entries for aziz/amy/joy here — they get no dedicated server process,
# just the shared .mcp.json copy for tool visibility (see WORKTREE_ROLES loop below).
cat > "$REPO_ROOT/.claude/mcp-configs/team.mcp.json" <<JSON
{
  "mcpServers": {
$(role_server mcp-gee-sweet-ash "$REPO_ROOT/.claude/worktrees/ash"),
$(role_server mcp-gee-sweet-sky "$REPO_ROOT/.claude/worktrees/sky"),
$(role_server mcp-gee-sweet-jay "$REPO_ROOT/.claude/worktrees/jay"),
$(role_server mcp-gee-sweet-kit "$REPO_ROOT/.claude/worktrees/kit"),
    "mcp-gee-sweet-kai-oauth": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "$REPO_ROOT", "mcp-gee-sweet"],
      "env": {
        "AUTH_METHOD": "oauth",
        "CREDENTIALS_PATH": "$REPO_ROOT/credentials.json",
        "TOKEN_PATH": "$REPO_ROOT/token.json"
      }
    },
    "mcp-gee-sweet-kai-sa": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "$REPO_ROOT", "mcp-gee-sweet"],
      "env": {
        "AUTH_METHOD": "service_account",
        "SERVICE_ACCOUNT_PATH": "$REPO_ROOT/service_account.json"
      }
    },
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": {}
    }
  }
}
JSON

echo "Copying .mcp.json into repo root and each worktree (Agent-view sessions don't inherit --mcp-config, only per-directory auto-discovery)"
cp "$REPO_ROOT/.claude/mcp-configs/team.mcp.json" "$REPO_ROOT/.mcp.json"
for name in "${WORKTREE_ROLES[@]}"; do
  cp "$REPO_ROOT/.claude/mcp-configs/team.mcp.json" "$REPO_ROOT/.claude/worktrees/$name/.mcp.json"
done

echo "Ready. Launch with: make claude-team"
