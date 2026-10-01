"""Tests for scripts/write_team_mcp_configs.sh (#850).

Runs the real script against a temp repo root, so no worktrees are provisioned.
The role list is read from setup_team.sh and the Makefile, so a role added
to one without the others fails here instead of at the next `make team-<name>`.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_WRITER = _SCRIPTS / "write_team_mcp_configs.sh"
_MAKEFILE = _SCRIPTS.parent / "Makefile"

_ALL_SERVERS = [
    "mcp-gee-sweet-ash",
    "mcp-gee-sweet-sky",
    "mcp-gee-sweet-jay",
    "mcp-gee-sweet-kit",
    "mcp-gee-sweet-kai-oauth",
    "mcp-gee-sweet-kai-sa",
    "mcp-gee-sweet-oauth",
    "mcp-gee-sweet-sa",
    "playwright",
]

# None: no role config; `make team-<name>` launches without --strict-mcp-config.
_EXPECTED_ROLE_SERVERS = {
    "ash": ["mcp-gee-sweet-ash"],
    "jay": ["mcp-gee-sweet-jay"],
    "sky": ["mcp-gee-sweet-sky", "playwright"],
    "kit": ["mcp-gee-sweet-kit", "playwright"],
    "aziz": None,
    "amy": [],
    "joy": [],
    "bob": [],
}


def _setup_team_roles() -> list[str]:
    text = (_SCRIPTS / "setup_team.sh").read_text()
    match = re.search(r"^WORKTREE_ROLES=\(([^)]*)\)", text, re.MULTILINE)
    assert match, "WORKTREE_ROLES not found in setup_team.sh"
    return match.group(1).split()


def _makefile_scoped_roles() -> list[str]:
    return re.findall(r"\$\(call team_mcp,(\w+)\)", _MAKEFILE.read_text())


def _run(root: Path, roles: list[str], *args: str) -> subprocess.CompletedProcess:
    for role in roles:
        (root / ".claude" / "worktrees" / role).mkdir(parents=True, exist_ok=True)
    argv = list(args) if args else [str(root), *roles]
    return subprocess.run(["bash", str(_WRITER), *argv], capture_output=True, text=True)


def _load(path: Path) -> dict:
    return json.loads(path.read_text())["mcpServers"]


@pytest.fixture
def written(tmp_path):
    roles = _setup_team_roles()
    result = _run(tmp_path, roles)
    assert result.returncode == 0, result.stderr
    return tmp_path, roles


def test_every_setup_team_role_has_an_expected_config():
    assert sorted(_setup_team_roles()) == sorted(_EXPECTED_ROLE_SERVERS)


def test_team_config_lists_every_server(written):
    root, _ = written
    assert list(_load(root / ".claude/mcp-configs/team.mcp.json")) == _ALL_SERVERS


@pytest.mark.parametrize(
    "role", sorted(r for r, s in _EXPECTED_ROLE_SERVERS.items() if s is not None)
)
def test_role_config_lists_only_that_roles_servers(written, role):
    root, _ = written
    team = _load(root / ".claude/mcp-configs/team.mcp.json")
    servers = _load(root / f".claude/mcp-configs/{role}.mcp.json")
    assert list(servers) == _EXPECTED_ROLE_SERVERS[role]
    # Same entry as the combined config, so a role session starts the same process.
    for key, entry in servers.items():
        assert entry == team[key]


def test_unscoped_role_gets_no_config(written):
    root, _ = written
    assert not (root / ".claude/mcp-configs/aziz.mcp.json").exists()


def test_makefile_launches_exactly_the_scoped_roles(written):
    # Every `$(call team_mcp,<x>)` must point at a config the script writes, and
    # every scoped role must actually be launched with it.
    root, _ = written
    called = _makefile_scoped_roles()
    assert sorted(called) == sorted(r for r, s in _EXPECTED_ROLE_SERVERS.items() if s is not None)
    for role in called:
        assert (root / f".claude/mcp-configs/{role}.mcp.json").exists()


def test_lane_server_points_at_its_own_worktree(written):
    root, _ = written
    entry = _load(root / ".claude/mcp-configs/jay.mcp.json")["mcp-gee-sweet-jay"]
    worktree = str(root / ".claude/worktrees/jay")
    assert entry["args"] == ["run", "--directory", worktree, "mcp-gee-sweet"]
    assert entry["env"]["TOKEN_PATH"] == f"{worktree}/token.json"


def test_root_and_worktree_mcp_json_are_the_combined_config(written):
    root, roles = written
    team = (root / ".claude/mcp-configs/team.mcp.json").read_text()
    assert (root / ".mcp.json").read_text() == team
    for role in roles:
        assert (root / ".claude/worktrees" / role / ".mcp.json").read_text() == team


def test_rerun_is_idempotent(written):
    root, roles = written
    config_dir = root / ".claude/mcp-configs"
    before = {p.name: p.read_text() for p in config_dir.iterdir()}
    result = _run(root, roles)
    assert result.returncode == 0, result.stderr
    assert {p.name: p.read_text() for p in config_dir.iterdir()} == before


def test_unknown_role_fails_before_writing_anything(written):
    root, _ = written
    snapshot = {p: p.read_text() for p in root.rglob("*.json")}
    (root / ".claude/mcp-configs/team.mcp.json").write_text("{}")
    snapshot[root / ".claude/mcp-configs/team.mcp.json"] = "{}"
    result = _run(root, ["ash", "zed"])
    assert result.returncode != 0
    assert "unknown role: zed" in result.stderr
    assert {p: p.read_text() for p in root.rglob("*.json")} == snapshot


@pytest.mark.parametrize("argc", [0, 1])
def test_missing_arguments_print_usage_and_write_nothing(tmp_path, argc):
    result = _run(tmp_path, [], *[str(tmp_path)][:argc])
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert not (tmp_path / ".claude").exists()


def test_system_bash_3_2_runs_it(tmp_path):
    # macOS's /bin/bash is 3.2, which has no associative arrays and treats an
    # empty array as unbound under set -u.
    roles = _setup_team_roles()
    for role in roles:
        (tmp_path / ".claude" / "worktrees" / role).mkdir(parents=True)
    if not Path("/bin/bash").exists():
        pytest.skip("no /bin/bash")
    result = subprocess.run(
        ["/bin/bash", str(_WRITER), str(tmp_path), *roles], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
