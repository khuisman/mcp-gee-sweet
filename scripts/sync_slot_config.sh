#!/usr/bin/env bash
# Copy the main checkout's local config files into each dev-team worktree slot.
# Called by setup_team.sh as: sync_slot_config.sh <repo-root> <role>...
# (the roles are setup_team.sh's WORKTREE_ROLES, kept in that one place).
#
# Credential files are re-synced when the slot's copy is stale, so a credential
# change in the main checkout reaches every slot on the next setup_team.sh run
# (#1223). Before, a file was copied only when missing, and a slot provisioned
# before the 2026-09-01 identity migration kept authenticating as the old
# identity. Each slot keeps its own copy rather than a symlink: every slot's
# server refreshes and rewrites its own token.json.
#
# - credentials.json, service_account.json: replaced when the bytes differ.
# - token.json: replaced only when it was issued by a different OAuth client
#   (client_id), or doesn't parse. Not on a different refresh_token: each slot
#   may be authorized on its own (a per-slot `mcp-gee-sweet auth`, or a #873
#   re-auth from a tool call), and that token is current, not stale. Skipped
#   with a warning when the main checkout's own token.json doesn't parse, e.g.
#   read mid-rewrite, so a broken token never overwrites a working one.
# - .env, src/mcp_gee_sweet/.env, .claude/settings.local.json: copied only when
#   missing. A slot may hold deliberate local edits; .env propagation is #679.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <repo-root> <role>..." >&2
  exit 2
fi
REPO_ROOT="$1"
shift

RESYNCED_FILES=(credentials.json service_account.json token.json)
SEED_ONLY_FILES=(.env src/mcp_gee_sweet/.env .claude/settings.local.json)

# Prints a token file's client_id, or nothing if it doesn't parse or has none.
token_client_id() {
  python3 -c 'import json, sys
try:
    print(json.load(open(sys.argv[1])).get("client_id") or "")
except Exception:
    pass' "$1"
}

SOURCE_CLIENT_ID=""
if [ -f "$REPO_ROOT/token.json" ]; then
  SOURCE_CLIENT_ID="$(token_client_id "$REPO_ROOT/token.json")"
  if [ -z "$SOURCE_CLIENT_ID" ]; then
    echo "warning: the main checkout's token.json doesn't parse; leaving every slot's token.json as is" >&2
  fi
fi

# Replace through a temp file in the same directory, so a server reading the
# file never sees it half-written. cp -p keeps the source's mode (token.json is
# 0600 in the main checkout).
install_copy() {
  local src="$1" dst="$2" tmp
  mkdir -p "$(dirname "$dst")"
  tmp="$(dirname "$dst")/.$(basename "$dst").sync.$$"
  cp -p "$src" "$tmp"
  mv -f "$tmp" "$dst"
}

for name in "$@"; do
  slot="$REPO_ROOT/.claude/worktrees/$name"
  [ -d "$slot" ] || continue

  for f in "${RESYNCED_FILES[@]}" "${SEED_ONLY_FILES[@]}"; do
    src="$REPO_ROOT/$f"
    dst="$slot/$f"
    [ -f "$src" ] || continue
    if [ "$f" = token.json ] && [ -z "$SOURCE_CLIENT_ID" ]; then
      continue
    fi
    if [ ! -f "$dst" ]; then
      install_copy "$src" "$dst"
      echo "$name: copied $f"
      continue
    fi
    case "$f" in
      token.json)
        [ "$(token_client_id "$dst")" = "$SOURCE_CLIENT_ID" ] && continue
        ;;
      credentials.json | service_account.json)
        cmp -s "$src" "$dst" && continue
        ;;
      *)
        continue
        ;;
    esac
    install_copy "$src" "$dst"
    echo "$name: updated $f (differed from the main checkout's)"
  done
done
