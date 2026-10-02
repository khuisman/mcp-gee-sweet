"""Tests for scripts/lane_context_hook.py (#847).

The script lives outside the mcp_gee_sweet package, so it's loaded here via
importlib rather than a normal import (same pattern as test_gen_tool_docs.py).
The transcript fixtures mirror a live Claude Code transcript's line shape.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO / "scripts" / "lane_context_hook.py"
_spec = importlib.util.spec_from_file_location("lane_context_hook", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

_LANE_CWD = "/Users/someone/Projects/repo/.claude/worktrees/jay"


def _assistant(input_tokens=0, cache_read=0, cache_creation=0, *, sidechain=False, model="m"):
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
                "output_tokens": 999_999,
            },
        },
    }


def _write_transcript(path: Path, entries) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


class TestLaneName:
    @pytest.mark.parametrize("lane", ["ash", "jay", "sky", "kit"])
    def test_lane_worktree_root(self, lane):
        assert hook.lane_name(f"/x/repo/.claude/worktrees/{lane}") == lane

    def test_subdirectory_of_lane_worktree(self):
        assert hook.lane_name("/x/repo/.claude/worktrees/kit/src/mcp_gee_sweet") == "kit"

    @pytest.mark.parametrize("role", ["aziz", "amy", "joy", "bob"])
    def test_non_lane_worktree(self, role):
        assert hook.lane_name(f"/x/repo/.claude/worktrees/{role}") is None

    def test_main_checkout(self):
        assert hook.lane_name("/x/repo") is None

    def test_lane_name_outside_worktrees_dir(self):
        assert hook.lane_name("/home/jay/repo") is None

    @pytest.mark.parametrize("cwd", [None, ""])
    def test_missing_cwd(self, cwd):
        assert hook.lane_name(cwd) is None


class TestContextTokensFromTranscript:
    def test_sums_input_and_cache_fields_of_latest_assistant(self, tmp_path):
        t = _write_transcript(
            tmp_path / "t.jsonl",
            [
                {"type": "user", "message": {"content": "hi"}},
                _assistant(1, 1000, 10),
                {"type": "user", "message": {"content": "more"}},
                _assistant(2, 90_024, 2384),
                {"type": "attachment"},
            ],
        )
        # output_tokens is excluded: it isn't re-sent as input.
        assert hook.context_tokens_from_transcript(t) == 2 + 90_024 + 2384

    def test_skips_sidechain_entries(self, tmp_path):
        t = _write_transcript(
            tmp_path / "t.jsonl",
            [_assistant(1, 50_000, 0), _assistant(1, 400_000, 0, sidechain=True)],
        )
        assert hook.context_tokens_from_transcript(t) == 50_001

    def test_skips_zero_usage_synthetic_entries(self, tmp_path):
        t = _write_transcript(
            tmp_path / "t.jsonl",
            [_assistant(1, 70_000, 0), _assistant(model="<synthetic>")],
        )
        assert hook.context_tokens_from_transcript(t) == 70_001

    def test_tolerates_malformed_and_partial_lines(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text(
            json.dumps(_assistant(5, 10, 0))
            + '\nnot json with "usage"\n'
            + '[1, "usage"]\n'
            + '{"type": "assistant", "message": {"usage": null}}\n'
            # A line still being written when the hook runs.
            + '{"type": "assistant", "message": {"usage": {"input_tok'
        )
        assert hook.context_tokens_from_transcript(t) == 15

    def test_missing_usage_keys_count_as_zero(self, tmp_path):
        t = _write_transcript(
            tmp_path / "t.jsonl",
            [{"type": "assistant", "message": {"usage": {"cache_read_input_tokens": 42}}}],
        )
        assert hook.context_tokens_from_transcript(t) == 42

    def test_no_assistant_messages(self, tmp_path):
        t = _write_transcript(tmp_path / "t.jsonl", [{"type": "user"}])
        assert hook.context_tokens_from_transcript(t) is None


class TestStopWarning:
    def test_below_threshold_is_silent_and_resets_band(self):
        assert hook.stop_warning(249_999, "jay", 250_000, 50_000, 3) == (None, None)

    def test_crossing_threshold_warns(self):
        message, band = hook.stop_warning(262_000, "jay", 250_000, 50_000, None)
        assert band == 0
        assert "~262k" in message
        assert "/clear, then /team-member Jay" in message

    def test_same_band_does_not_rewarn(self):
        assert hook.stop_warning(290_000, "jay", 250_000, 50_000, 0) == (None, 0)

    def test_next_band_rewarns(self):
        message, band = hook.stop_warning(301_000, "kit", 250_000, 50_000, 0)
        assert band == 1
        assert "/team-member Kit" in message

    def test_zero_step_warns_once(self):
        assert hook.stop_warning(900_000, "jay", 250_000, 0, 0) == (None, 0)


class TestResumeWarning:
    def _payload(self, **overrides):
        payload = {
            "context_tokens": 182_340,
            "prompt_cache_likely_expired": True,
            "estimated_cache_write_usd": 1.1396,
        }
        payload.update(overrides)
        return payload

    def test_cold_large_resume_warns_with_cost(self):
        message = hook.resume_warning(self._payload(), "sky", 100_000)
        assert "~182k" in message
        assert "~$1.14" in message
        assert "/clear, then /team-member Sky" in message

    def test_warm_cache_is_silent(self):
        payload = self._payload(prompt_cache_likely_expired=False)
        assert hook.resume_warning(payload, "sky", 100_000) is None

    def test_small_context_is_silent(self):
        assert hook.resume_warning(self._payload(context_tokens=99_999), "sky", 100_000) is None

    def test_missing_fields_are_silent(self):
        # Older Claude Code versions, or a transcript with no response yet.
        assert hook.resume_warning({}, "sky", 100_000) is None

    def test_missing_cost_omits_clause(self):
        message = hook.resume_warning(self._payload(estimated_cache_write_usd=None), "sky", 100_000)
        assert "$" not in message


class TestHandle:
    def test_stop_warns_once_per_band_across_turns(self, tmp_path):
        state = tmp_path / "state"
        t = tmp_path / "t.jsonl"
        payload = {
            "hook_event_name": "Stop",
            "cwd": _LANE_CWD,
            "session_id": "abc-123",
            "transcript_path": str(t),
        }

        _write_transcript(t, [_assistant(0, 260_000, 0)])
        first = hook.handle(payload, {}, state)
        assert "~260k" in first["systemMessage"]

        _write_transcript(t, [_assistant(0, 270_000, 0)])
        assert hook.handle(payload, {}, state) is None

        _write_transcript(t, [_assistant(0, 305_000, 0)])
        assert "~305k" in hook.handle(payload, {}, state)["systemMessage"]

        # Dropping below the threshold (e.g. /compact) resets, so the next climb warns.
        _write_transcript(t, [_assistant(0, 40_000, 0)])
        assert hook.handle(payload, {}, state) is None
        assert not (state / "abc-123").exists()
        _write_transcript(t, [_assistant(0, 255_000, 0)])
        assert hook.handle(payload, {}, state) is not None

    def test_stop_threshold_from_env(self, tmp_path):
        t = _write_transcript(tmp_path / "t.jsonl", [_assistant(0, 120_000, 0)])
        payload = {
            "hook_event_name": "Stop",
            "cwd": _LANE_CWD,
            "session_id": "s",
            "transcript_path": str(t),
        }
        env = {"LANE_CONTEXT_WARN_TOKENS": "100000"}
        assert hook.handle(payload, env, tmp_path / "state") is not None
        assert hook.handle(payload, {"LANE_CONTEXT_WARN_TOKENS": "junk"}, tmp_path / "s2") is None

    def test_non_lane_cwd_is_noop(self, tmp_path):
        t = _write_transcript(tmp_path / "t.jsonl", [_assistant(0, 900_000, 0)])
        payload = {
            "hook_event_name": "Stop",
            "cwd": "/x/repo/.claude/worktrees/bob",
            "session_id": "s",
            "transcript_path": str(t),
        }
        assert hook.handle(payload, {}, tmp_path / "state") is None

    @pytest.mark.parametrize("source", ["resume", "fork"])
    def test_session_start_resume(self, tmp_path, source):
        payload = {
            "hook_event_name": "SessionStart",
            "source": source,
            "cwd": _LANE_CWD,
            "context_tokens": 300_000,
            "prompt_cache_likely_expired": True,
        }
        assert "~300k" in hook.handle(payload, {}, tmp_path)["systemMessage"]

    @pytest.mark.parametrize("source", ["startup", "clear", "compact"])
    def test_session_start_other_sources_are_noop(self, tmp_path, source):
        payload = {
            "hook_event_name": "SessionStart",
            "source": source,
            "cwd": _LANE_CWD,
            "context_tokens": 300_000,
            "prompt_cache_likely_expired": True,
        }
        assert hook.handle(payload, {}, tmp_path) is None


class TestScriptEntryPoint:
    def _run(self, stdin: str, tmp_path: Path):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)],
            input=stdin,
            capture_output=True,
            text=True,
            env={"TMPDIR": str(tmp_path)},
            check=False,
        )

    def test_emits_system_message_json(self, tmp_path):
        payload = {
            "hook_event_name": "SessionStart",
            "source": "resume",
            "cwd": _LANE_CWD,
            "context_tokens": 300_000,
            "prompt_cache_likely_expired": True,
        }
        result = self._run(json.dumps(payload), tmp_path)
        assert result.returncode == 0
        assert "systemMessage" in json.loads(result.stdout)

    @pytest.mark.parametrize(
        "stdin",
        [
            "",
            "not json",
            "[]",
            json.dumps(
                {
                    "hook_event_name": "Stop",
                    "cwd": _LANE_CWD,
                    "session_id": "s",
                    "transcript_path": "/nonexistent/t.jsonl",
                }
            ),
        ],
    )
    def test_bad_input_exits_zero_silently(self, stdin, tmp_path):
        result = self._run(stdin, tmp_path)
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""


_RESUME_PAYLOAD = {
    "hook_event_name": "SessionStart",
    "source": "resume",
    "cwd": _LANE_CWD,
    "context_tokens": 300_000,
    "prompt_cache_likely_expired": True,
    "estimated_cache_write_usd": 1.5,
}


def _system_python_39():
    """macOS's /usr/bin/python3 (3.9), which the hook's bare `python3` can resolve to."""
    exe = shutil.which("python3", path="/usr/bin")
    if exe is None:
        return None
    version = subprocess.run(
        [exe, "-c", "import sys; print(sys.version_info[:2] < (3, 10))"],
        capture_output=True,
        text=True,
        check=False,
    )
    return exe if version.stdout.strip() == "True" else None


class TestRunsUnderPython39:
    """PR #866 round 1: `isinstance(x, int | float)` raised TypeError on 3.9, and
    main() swallowed it, so the resume warning silently never fired."""

    def test_resume_warning_with_cost_under_python_39(self, tmp_path):
        exe = _system_python_39()
        if exe is None:
            pytest.skip("no Python < 3.10 at /usr/bin/python3")
        result = subprocess.run(
            [exe, str(_SCRIPT_PATH)],
            input=json.dumps(_RESUME_PAYLOAD),
            capture_output=True,
            text=True,
            env={"TMPDIR": str(tmp_path)},
            check=False,
        )
        assert result.returncode == 0
        assert "(~$1.50)" in json.loads(result.stdout)["systemMessage"]


class TestSettingsCommand:
    """The settings.json command itself, run through bash as Claude Code does."""

    def _commands(self):
        settings = json.loads((_REPO / ".claude" / "settings.json").read_text())
        return [
            h["command"]
            for groups in settings["hooks"].values()
            for group in groups
            for h in group["hooks"]
            if "lane_context_hook.py" in h["command"]
        ]

    def _run(self, command: str, project_dir: Path, tmp_path: Path):
        return subprocess.run(
            ["bash", "-c", command],
            input=json.dumps(_RESUME_PAYLOAD),
            capture_output=True,
            text=True,
            env={
                "CLAUDE_PROJECT_DIR": str(project_dir),
                "TMPDIR": str(tmp_path),
                "PATH": os.environ["PATH"],
            },
            check=False,
        )

    def test_both_events_wired(self):
        assert len(self._commands()) == 2

    def test_runs_the_script(self, tmp_path):
        for command in self._commands():
            result = self._run(command, _REPO, tmp_path)
            assert result.returncode == 0
            assert "systemMessage" in json.loads(result.stdout)

    def test_missing_script_is_silent_success(self, tmp_path):
        # PR #866 round 1: a checkout of a branch cut before #847 has no script;
        # an unguarded `python3 <missing>` exits 2 and errors every turn.
        for command in self._commands():
            result = self._run(command, tmp_path, tmp_path)
            assert result.returncode == 0
            assert result.stdout == ""
            assert result.stderr == ""
