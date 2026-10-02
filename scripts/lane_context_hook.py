#!/usr/bin/env python3
"""Context-size backstop for lane sessions (#847).

Wired into `.claude/settings.json` for two hook events, and a no-op unless the
session's cwd is inside one of the four lane worktrees
(`.claude/worktrees/{ash,jay,sky,kit}`):

- `Stop`: reads the session's current context size from its own transcript
  (the latest assistant message's `usage`) and, once it passes
  `LANE_CONTEXT_WARN_TOKENS`, shows the user a `systemMessage` suggesting
  `/clear` + `/team-member <name>`. It warns once on crossing the threshold and
  again each `LANE_CONTEXT_WARN_STEP` tokens past it, not on every turn.
- `SessionStart` (`resume`/`fork`): warns before the first request when the
  resumed context is at least `LANE_RESUME_WARN_TOKENS` and the prompt cache
  has likely expired, using the cost estimate Claude Code passes in.

A hook can't run `/clear` itself or start a turn, so the message is the whole
job. Stdlib only and 3.9-compatible, so it runs under a bare `python3` (macOS's
`/usr/bin/python3` is 3.9). Any error exits 0 silently: a broken backstop must
never get in the way of the session it's watching. The settings.json command
also skips the call when this file is missing (a checkout of a branch cut
before #847).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

LANE_NAMES = ("ash", "jay", "sky", "kit")

DEFAULT_WARN_TOKENS = 250_000
DEFAULT_WARN_STEP = 50_000
DEFAULT_RESUME_WARN_TOKENS = 100_000

_STATE_DIR = Path(tempfile.gettempdir()) / "mcp-gee-sweet-lane-context"


def lane_name(cwd: str | None) -> str | None:
    """Return the lane name if `cwd` is inside `.claude/worktrees/<lane>`, else None."""
    if not cwd:
        return None
    parts = Path(cwd).parts
    for i in range(len(parts) - 2):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees" and parts[i + 2] in LANE_NAMES:
            return parts[i + 2]
    return None


def _usage_total(usage: dict) -> int:
    return sum(
        int(usage.get(key) or 0)
        for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )


def context_tokens_from_transcript(path: str | os.PathLike) -> int | None:
    """Context size as of the latest main-thread assistant message, or None.

    Sidechain (subagent) entries and zero-usage entries (synthetic messages,
    e.g. an interrupted turn) are skipped: neither reflects what this session's
    next request will re-send.
    """
    latest = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "assistant":
                continue
            if entry.get("isSidechain"):
                continue
            message = entry.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            total = _usage_total(usage)
            if total > 0:
                latest = total
    return latest


def _k(tokens: int) -> str:
    return f"{round(tokens / 1000)}k"


def _restart_hint(lane: str) -> str:
    return f"/clear, then /team-member {lane.capitalize()}"


def stop_warning(
    tokens: int, lane: str, threshold: int, step: int, last_band: int | None
) -> tuple[str | None, int | None]:
    """Decide whether this turn warns. Returns (message or None, band to remember).

    Band 0 is "past the threshold", band N is "past threshold + N*step". A
    warning fires only when the band rises, so a session hovering above the
    threshold isn't nagged every turn. Below the threshold the band resets to
    None, so a later climb (e.g. after `/compact`) warns again.
    """
    if tokens < threshold:
        return None, None
    band = (tokens - threshold) // step if step > 0 else 0
    if last_band is not None and band <= last_band:
        return None, last_band
    message = (
        f"Lane context is ~{_k(tokens)} tokens (warning threshold {_k(threshold)}). "
        f"Every turn re-sends all of it. At the next good stopping point in this "
        f"ticket, start fresh: {_restart_hint(lane)}."
    )
    return message, band


def resume_warning(payload: dict, lane: str, threshold: int) -> str | None:
    """Warning for a cold resume of a large lane session, or None."""
    tokens = payload.get("context_tokens")
    if not isinstance(tokens, int) or tokens < threshold:
        return None
    if not payload.get("prompt_cache_likely_expired"):
        return None
    cost = payload.get("estimated_cache_write_usd")
    # Not `isinstance(cost, int | float)`: that needs 3.10, and a bare `python3`
    # can be 3.9 (PR #866). `type() in` also keeps a stray bool out.
    cost_clause = f" (~${cost:.2f})" if type(cost) in (int, float) else ""
    return (
        f"Resuming a ~{_k(tokens)}-token lane session with an expired prompt cache: "
        f"the first request re-writes all of it{cost_clause}. If this session's "
        f"ticket is done or between rounds, {_restart_hint(lane)} is cheaper."
    )


def _env_int(environ: dict, name: str, default: int) -> int:
    try:
        return int(environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _read_band(state_file: Path) -> int | None:
    try:
        return int(state_file.read_text().strip())
    except (OSError, ValueError):
        return None


def _write_band(state_file: Path, band: int | None) -> None:
    if band is None:
        state_file.unlink(missing_ok=True)
        return
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(str(band))


def handle(payload: dict, environ: dict, state_dir: Path = _STATE_DIR) -> dict | None:
    """Return the hook's JSON output for `payload`, or None for no output."""
    lane = lane_name(payload.get("cwd"))
    if lane is None:
        return None
    event = payload.get("hook_event_name")

    if event == "SessionStart":
        if payload.get("source") not in ("resume", "fork"):
            return None
        threshold = _env_int(environ, "LANE_RESUME_WARN_TOKENS", DEFAULT_RESUME_WARN_TOKENS)
        message = resume_warning(payload, lane, threshold)
        return {"systemMessage": message} if message else None

    if event == "Stop":
        transcript = payload.get("transcript_path")
        session_id = payload.get("session_id")
        if not transcript or not session_id:
            return None
        tokens = context_tokens_from_transcript(transcript)
        if tokens is None:
            return None
        threshold = _env_int(environ, "LANE_CONTEXT_WARN_TOKENS", DEFAULT_WARN_TOKENS)
        step = _env_int(environ, "LANE_CONTEXT_WARN_STEP", DEFAULT_WARN_STEP)
        # session_id is a UUID; keep only filename-safe characters regardless.
        state_file = state_dir / "".join(c for c in session_id if c.isalnum() or c == "-")
        message, band = stop_warning(tokens, lane, threshold, step, _read_band(state_file))
        _write_band(state_file, band)
        return {"systemMessage": message} if message else None

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        output = handle(payload, dict(os.environ)) if isinstance(payload, dict) else None
        if output:
            json.dump(output, sys.stdout)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
