"""Tests for scripts/sync_slot_config.sh (#1223).

Runs the real script against a temp repo root with fake config files, so no
worktrees are provisioned and no real credential is read.
"""

import json
import stat
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sync_slot_config.sh"


def _token(refresh: str, access: str = "a1", client: str = "c1") -> str:
    return json.dumps({"token": access, "refresh_token": refresh, "client_id": client})


def _root(tmp_path: Path, *roles: str) -> Path:
    for role in roles:
        (tmp_path / ".claude" / "worktrees" / role).mkdir(parents=True)
    (tmp_path / "credentials.json").write_text('{"installed": "new-client"}')
    (tmp_path / "service_account.json").write_text('{"client_email": "new-sa"}')
    (tmp_path / "token.json").write_text(_token("r-new"))
    (tmp_path / "token.json").chmod(0o600)
    (tmp_path / ".env").write_text("TEST_SPREADSHEET_ID=new\n")
    return tmp_path


def _slot(root: Path, role: str) -> Path:
    return root / ".claude" / "worktrees" / role


def _run(root: Path, *roles: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_SCRIPT), str(root), *roles], capture_output=True, text=True, check=True
    )


def test_seeds_missing_files(tmp_path):
    root = _root(tmp_path, "ash")
    out = _run(root, "ash").stdout
    slot = _slot(root, "ash")
    for f in ("credentials.json", "service_account.json", "token.json", ".env"):
        assert (slot / f).read_text() == (root / f).read_text()
        assert f"ash: copied {f}" in out
    assert stat.S_IMODE((slot / "token.json").stat().st_mode) == 0o600


def test_replaces_stale_credentials(tmp_path):
    root = _root(tmp_path, "aziz")
    slot = _slot(root, "aziz")
    (slot / "credentials.json").write_text('{"installed": "old-client"}')
    (slot / "service_account.json").write_text('{"client_email": "old-sa"}')
    (slot / "token.json").write_text(_token("r-old"))
    out = _run(root, "aziz").stdout
    for f in ("credentials.json", "service_account.json", "token.json"):
        assert (slot / f).read_text() == (root / f).read_text()
        assert f"aziz: updated {f}" in out


def test_token_for_a_different_client_is_replaced(tmp_path):
    root = _root(tmp_path, "aziz")
    (_slot(root, "aziz") / "token.json").write_text(_token("r-new", client="c-old"))
    assert "aziz: updated token.json" in _run(root, "aziz").stdout
    assert (_slot(root, "aziz") / "token.json").read_text() == (root / "token.json").read_text()


def test_refreshed_token_for_same_identity_is_kept(tmp_path):
    # A slot's server rewrites its token.json with a new access token on every
    # refresh; that's the same identity, and must not be clobbered.
    root = _root(tmp_path, "sky")
    slot_token = _slot(root, "sky") / "token.json"
    slot_token.write_text(_token("r-new", access="a-refreshed"))
    _run(root, "sky")  # seeds the other files
    out = _run(root, "sky").stdout
    assert out == ""
    assert json.loads(slot_token.read_text())["token"] == "a-refreshed"


def test_unparsable_slot_token_is_replaced(tmp_path):
    root = _root(tmp_path, "bob")
    (_slot(root, "bob") / "token.json").write_text("not json")
    assert "bob: updated token.json" in _run(root, "bob").stdout


def test_seed_only_files_keep_local_edits(tmp_path):
    root = _root(tmp_path, "joy")
    slot = _slot(root, "joy")
    (slot / ".env").write_text("TEST_SPREADSHEET_ID=local-edit\n")
    (slot / ".claude").mkdir()
    (slot / ".claude" / "settings.local.json").write_text('{"local": true}')
    (root / ".claude" / "settings.local.json").write_text('{"local": false}')
    out = _run(root, "joy").stdout
    assert (slot / ".env").read_text() == "TEST_SPREADSHEET_ID=local-edit\n"
    assert (slot / ".claude" / "settings.local.json").read_text() == '{"local": true}'
    assert ".env" not in out and "settings.local.json" not in out


def test_second_run_is_silent(tmp_path):
    root = _root(tmp_path, "ash", "kit")
    _run(root, "ash", "kit")
    assert _run(root, "ash", "kit").stdout == ""


def test_missing_slot_and_missing_source_are_skipped(tmp_path):
    root = _root(tmp_path, "amy")
    (root / "service_account.json").unlink()
    out = _run(root, "amy", "nonexistent").stdout
    assert not (_slot(root, "amy") / "service_account.json").exists()
    assert "nonexistent" not in out
    assert not list(_slot(root, "amy").glob(".*.sync.*"))
