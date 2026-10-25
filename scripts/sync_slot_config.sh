#!/usr/bin/env bash
# Copy the main checkout's local config files into each dev-team worktree slot.
# Called by setup_team.sh as: sync_slot_config.sh <repo-root> <role>...
# (the roles are setup_team.sh's WORKTREE_ROLES, kept in that one place).
#
# Credential files are re-synced whenever the slot's copy no longer matches,
# so a credential change in the main checkout reaches every slot on the next
# setup_team.sh run (#1223). Before, a file was copied only when missing, and a
# slot provisioned before the 2026-09-01 identity migration kept authenticating
# as the old identity. Each slot keeps its own copy rather than a symlink: every
# slot's server refreshes and rewrites its own token.json.
#
# - credentials.json, service_account.json: replaced when the bytes differ.
# - token.json: replaced when it's for a different identity, i.e. a different
#   refresh_token or client_id. Not on a byte difference: a server rewrites its
#   slot's copy with a fresh access token on every refresh, so the bytes always
#   drift from the main checkout's while the identity stays the same.
# - .env, .claude/settings.local.json: copied only when missing. A slot may
#   hold deliberate local edits to these; .env propagation is #679.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <repo-root> <role>..." >&2
  exit 2
fi
REPO_ROOT="$1"
shift

RESYNCED_FILES=(credentials.json service_account.json token.json)
SEED_ONLY_FILES=(.env .claude/settings.local.json)

# Prints "<refresh_token>\n<client_id>" for a token file, or nothing if it
# can't be parsed (which then counts as a different identity).
token_identity() {
  python3 -c 'import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get("refresh_token", ""))
    print(d.get("client_id", ""))
except Exception:
    pass' "$1"
}

same_content() {
  local src="$1" dst="$2"
  if [ "$(basename "$src")" = token.json ]; then
    local a b
    a="$(token_identity "$src")"
    b="$(token_identity "$dst")"
    [ -n "$a" ] && [ "$a" = "$b" ]
  else
    cmp -s "$src" "$dst"
  fi
}

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
    if [ ! -f "$dst" ]; then
      install_copy "$src" "$dst"
      echo "$name: copied $f"
      continue
    fi
    case " ${RESYNCED_FILES[*]} " in
      *" $f "*) ;;
      *) continue ;;
    esac
    if ! same_content "$src" "$dst"; then
      install_copy "$src" "$dst"
      echo "$name: updated $f (differed from the main checkout's)"
    fi
  done
done
