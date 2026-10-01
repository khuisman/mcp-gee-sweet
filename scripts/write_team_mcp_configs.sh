#!/usr/bin/env bash
# Write the dev-team MCP configs under <repo-root>/.claude/mcp-configs/ and copy
# the combined one to .mcp.json in the repo root and each worktree slot.
# Called by setup_team.sh as: write_team_mcp_configs.sh <repo-root> <role>...
# (the roles are setup_team.sh's WORKTREE_ROLES, kept in that one place).
#
# - team.mcp.json: every server. Used by `make claude-team` (Kai + Agent View)
#   and copied to every .mcp.json.
# - <name>.mcp.json: just what that role may call, loaded by `make team-<name>`
#   with --strict-mcp-config (#850). Aziz gets none: `make team-aziz` stays
#   unflagged like `team-kai`, since a release QA pass uses every team server
#   plus the user-global mcp-gee-sweet (Gmail cases read the sender mailbox
#   through it), which --strict-mcp-config would drop. A launch flag, not a per-worktree
#   .mcp.json, because a session keeps the MCP servers of the directory it
#   launched in (EnterWorktree doesn't reload them), and one launched inside a
#   worktree still picks up the repo root's .mcp.json too.
# macOS ships bash 3.2, so no associative arrays here.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <repo-root> <role>..." >&2
  exit 2
fi
REPO_ROOT="$1"
shift
WORKTREE_ROLES=("$@")
CONFIG_DIR="$REPO_ROOT/.claude/mcp-configs"
ALL_SERVERS=(mcp-gee-sweet-ash mcp-gee-sweet-sky mcp-gee-sweet-jay mcp-gee-sweet-kit
  mcp-gee-sweet-kai-oauth mcp-gee-sweet-kai-sa mcp-gee-sweet-oauth mcp-gee-sweet-sa playwright)

oauth_server() {
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

sa_server() {
  local key="$1" dir="$2"
  cat <<JSON
    "$key": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "$dir", "mcp-gee-sweet"],
      "env": {
        "AUTH_METHOD": "service_account",
        "SERVICE_ACCOUNT_PATH": "$dir/service_account.json"
      }
    }
JSON
}

server_entry() {
  case "$1" in
    mcp-gee-sweet-ash | mcp-gee-sweet-sky | mcp-gee-sweet-jay | mcp-gee-sweet-kit)
      oauth_server "$1" "$REPO_ROOT/.claude/worktrees/${1#mcp-gee-sweet-}" ;;
    mcp-gee-sweet-kai-oauth | mcp-gee-sweet-oauth) oauth_server "$1" "$REPO_ROOT" ;;
    mcp-gee-sweet-kai-sa | mcp-gee-sweet-sa) sa_server "$1" "$REPO_ROOT" ;;
    playwright)
      cat <<JSON
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": {}
    }
JSON
      ;;
    *) echo "unknown MCP server: $1" >&2; exit 1 ;;
  esac
}

# write_config <file> [server...]: an empty server list writes an empty
# mcpServers, which under --strict-mcp-config means no MCP servers at all.
write_config() {
  local file="$1"; shift
  local sep=""
  {
    printf '{\n  "mcpServers": {\n'
    for key in "$@"; do
      printf '%s' "$sep"
      server_entry "$key"
      sep=$',\n'
    done
    printf '\n  }\n}\n'
  } > "$file"
}

# The servers each role may call (team-member.md §2). "unscoped" means no role
# config: the role launches without --strict-mcp-config (Aziz; Kai isn't a slot).
role_servers() {
  case "$1" in
    ash | jay) echo "mcp-gee-sweet-$1" ;;
    sky | kit) echo "mcp-gee-sweet-$1 playwright" ;;
    aziz) echo "unscoped" ;;
    amy | joy | bob) echo "" ;;
    *) echo "unknown role: $1" >&2; return 1 ;;
  esac
}

# Resolve every role before writing anything, so an unknown role leaves the
# existing configs untouched instead of half-rewritten.
ROLE_SERVERS=()
for name in "${WORKTREE_ROLES[@]}"; do
  ROLE_SERVERS+=("$(role_servers "$name")")
done

mkdir -p "$CONFIG_DIR"
echo "Writing .claude/mcp-configs/team.mcp.json and per-role configs"
write_config "$CONFIG_DIR/team.mcp.json" "${ALL_SERVERS[@]}"
for i in "${!WORKTREE_ROLES[@]}"; do
  name="${WORKTREE_ROLES[$i]}"
  servers="${ROLE_SERVERS[$i]}"
  if [ "$servers" = "unscoped" ]; then
    rm -f "$CONFIG_DIR/$name.mcp.json"
    continue
  fi
  # Word splitting of the server list is intended.
  # shellcheck disable=SC2086
  write_config "$CONFIG_DIR/$name.mcp.json" $servers
done

echo "Copying .mcp.json into repo root and each worktree (Agent-view sessions don't inherit --mcp-config, only per-directory auto-discovery)"
cp "$CONFIG_DIR/team.mcp.json" "$REPO_ROOT/.mcp.json"
for name in "${WORKTREE_ROLES[@]}"; do
  cp "$CONFIG_DIR/team.mcp.json" "$REPO_ROOT/.claude/worktrees/$name/.mcp.json"
done
