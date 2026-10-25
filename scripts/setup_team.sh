#!/usr/bin/env bash
# Idempotently provision the dev-team worktree slots (ash/sky/jay/kit/aziz/amy/joy/bob)
# and write the MCP configs used by `make claude-team` and `make team-<name>`
# (see write_team_mcp_configs.sh).
#
# Each slot rests on its own `team/<name>` branch (never `develop` itself —
# that branch is always checked out in the main checkout). Dev slots branch
# off `team/<name>` into `feat/<name>/issue-<n>` per ticket; QA slots stay on
# `team/<name>` forever and get reset to whatever PR branch they're
# verifying (see `/team-member`). Aziz, Amy, Joy, and Bob are also persistent
# `team/<name>` slots but don't get a dedicated MCP server process — during a
# release QA pass Aziz uses every mcp-gee-sweet-* slot already provisioned
# here (all four lanes, kai-oauth/-sa, plus the standalone oauth/sa slots
# below), Amy just needs a worktree to write docs PRs from, Joy just needs
# one for ad-hoc architecture work (see `.claude/team-roles/joy.md`), and Bob
# just needs one to review other roles' self-edited process files (see
# `.claude/team-roles/bob.md`).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORKTREE_ROLES=(ash sky jay kit aziz amy joy bob)

git fetch origin develop --quiet

for name in "${WORKTREE_ROLES[@]}"; do
  worktree_path="$REPO_ROOT/.claude/worktrees/$name"

  if [ ! -d "$worktree_path" ]; then
    echo "Creating worktree slot: $name"
    git worktree add "$worktree_path" -b "team/$name" origin/develop
  fi

  echo "Syncing dependencies: $name"
  (cd "$worktree_path" && uv sync --quiet)
done

# Re-syncs credentials a slot already has when they've changed (#1223).
"$REPO_ROOT/scripts/sync_slot_config.sh" "$REPO_ROOT" "${WORKTREE_ROLES[@]}"
"$REPO_ROOT/scripts/write_team_mcp_configs.sh" "$REPO_ROOT" "${WORKTREE_ROLES[@]}"

echo "Ready. Launch with: make claude-team"
