#!/usr/bin/env bash
# The shared QA browser (#1410): one signed-in Chrome that parallel Playwright
# shards drive through the playwright-1..N MCP servers, each in its own tab.
#
#   qa_browser.sh start        launch it (no-op if already running)
#   qa_browser.sh stop         quit it
#   qa_browser.sh status       say whether it's running
#   qa_browser.sh endpoint     print the CDP endpoint the MCP servers attach to
#   qa_browser.sh mcp-package  print the pinned @playwright/mcp package spec
#   qa_browser.sh install      install that package into npx's cache once
#
# Why one browser and not N: Google ties the fixture account's session to the
# browser it was signed into (Device Bound Session Credentials), so a session
# exported with --storage-state and loaded into other browsers is revoked on
# first use (spike on #1410). Every shard shares this browser's one real
# sign-in instead, through Chrome's remote-debugging (CDP) endpoint.
#
# Why `install` exists: N `npx -y` processes starting together on a cold cache
# extract into the same directory at once and leave a broken install.
#
# The profile is outside the repo, in the user's cache directory, mode 0700.
# The debugging port listens on 127.0.0.1 only, but any local process can drive
# the signed-in browser through it: stop it when no QA pass needs it.
#
# Overrides: QA_BROWSER_PORT (default 9333), QA_BROWSER_PROFILE (profile dir),
# QA_BROWSER_CHROME (the Chrome binary). The playwright-<k> servers take their
# endpoint from QA_BROWSER_PORT when scripts/setup_team.sh writes the MCP
# configs, so a new port needs setup_team.sh re-run with it and the sessions
# relaunched; `start` and `status` warn when the two disagree.
set -euo pipefail

PLAYWRIGHT_MCP_PACKAGE="@playwright/mcp@0.0.84"
PORT="${QA_BROWSER_PORT:-9333}"
ENDPOINT="http://127.0.0.1:$PORT"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(uname)" = "Darwin" ]; then
  CACHE_ROOT="$HOME/Library/Caches"
else
  # The XDG spec says to ignore a relative value, as cache.default_db_path does.
  case "${XDG_CACHE_HOME:-}" in
    /*) CACHE_ROOT="$XDG_CACHE_HOME" ;;
    *) CACHE_ROOT="$HOME/.cache" ;;
  esac
fi
STATE_DIR="$CACHE_ROOT/mcp-gee-sweet"
PROFILE="${QA_BROWSER_PROFILE:-$STATE_DIR/qa-browser}"
# One pid file per port, so a second browser on another port can't overwrite
# the first one's record and leave it unstoppable.
PIDFILE="$STATE_DIR/qa-browser-$PORT.pid"
LOGFILE="$STATE_DIR/qa-browser-$PORT.log"

usage() {
  echo "usage: $0 start|stop|status|endpoint|mcp-package|install" >&2
  exit 2
}

find_chrome() {
  if [ -n "${QA_BROWSER_CHROME:-}" ]; then
    echo "$QA_BROWSER_CHROME"
    return
  fi
  local mac="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  if [ -x "$mac" ]; then
    echo "$mac"
    return
  fi
  local name
  for name in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$name" >/dev/null 2>&1; then
      command -v "$name"
      return
    fi
  done
  echo "Chrome not found; set QA_BROWSER_CHROME to its binary" >&2
  exit 1
}

endpoint_up() {
  curl -sf --max-time 2 "$ENDPOINT/json/version" >/dev/null 2>&1
}

# Prints the recorded pid when that process is this profile's Chrome on this
# port, and (where lsof can tell) the process listening on it.
our_pid() {
  [ -f "$PIDFILE" ] || return 1
  local pid command listeners
  pid="$(cat "$PIDFILE")"
  case "$pid" in '' | *[!0-9]*) return 1 ;; esac
  command="$(ps -ww -o command= -p "$pid" 2>/dev/null)" || return 1
  # The trailing space keeps /x/qa-browser from matching /x/qa-browser2.
  case "$command " in
    *" --user-data-dir=$PROFILE "*) ;;
    *) return 1 ;;
  esac
  case "$command " in
    *" --remote-debugging-port=$PORT "*) ;;
    *) return 1 ;;
  esac
  if command -v lsof >/dev/null 2>&1; then
    listeners="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
    printf '%s\n' "$listeners" | grep -qx -- "$pid" || return 1
  fi
  echo "$pid"
}

# The endpoint the repo's MCP config sends playwright-<k> to, if it names one.
configured_endpoint() {
  local config="$REPO_ROOT/.mcp.json"
  [ -f "$config" ] || return 0
  grep -o '"--cdp-endpoint", "[^"]*"' "$config" | head -n 1 | sed 's/.*, "\(.*\)"/\1/'
}

warn_if_config_differs() {
  local configured
  configured="$(configured_endpoint)"
  if [ -n "$configured" ] && [ "$configured" != "$ENDPOINT" ]; then
    echo "warning: the playwright-<k> servers attach to $configured, not $ENDPOINT." >&2
    echo "  Re-run scripts/setup_team.sh with the same QA_BROWSER_PORT, then relaunch the sessions." >&2
  fi
}

cmd_start() {
  if our_pid >/dev/null; then
    echo "QA browser already running at $ENDPOINT"
    warn_if_config_differs
    return
  fi
  if endpoint_up; then
    echo "Port $PORT is already serving CDP for another browser. Stop that browser, or set" >&2
    echo "  QA_BROWSER_PORT to a free port and re-run scripts/setup_team.sh with it, so the" >&2
    echo "  playwright-<k> servers attach to the new port; then relaunch the sessions." >&2
    exit 1
  fi
  local chrome
  chrome="$(find_chrome)"
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  if [ -L "$PROFILE" ]; then
    echo "Refusing a symlinked profile directory: $PROFILE" >&2
    exit 1
  fi
  mkdir -p "$PROFILE"
  chmod 700 "$PROFILE"
  nohup "$chrome" --user-data-dir="$PROFILE" --remote-debugging-port="$PORT" \
    --no-first-run --no-default-browser-check about:blank >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  local _
  for _ in $(seq 1 30); do
    if endpoint_up; then
      echo "QA browser running at $ENDPOINT (profile $PROFILE)"
      warn_if_config_differs
      return
    fi
    sleep 1
  done
  echo "QA browser didn't open $ENDPOINT within 30s; see $LOGFILE" >&2
  exit 1
}

cmd_stop() {
  local pid
  if ! pid="$(our_pid)"; then
    rm -f "$PIDFILE"
    echo "QA browser isn't running"
    return
  fi
  kill "$pid"
  rm -f "$PIDFILE"
  echo "QA browser stopped"
}

cmd_status() {
  if our_pid >/dev/null && endpoint_up; then
    echo "running at $ENDPOINT (profile $PROFILE)"
    warn_if_config_differs
  else
    echo "not running; start it with scripts/qa_browser.sh start"
    exit 1
  fi
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  endpoint) echo "$ENDPOINT" ;;
  mcp-package) echo "$PLAYWRIGHT_MCP_PACKAGE" ;;
  install) npx -y "$PLAYWRIGHT_MCP_PACKAGE" --version ;;
  *) usage ;;
esac
