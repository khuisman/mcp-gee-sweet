"""Tests for scripts/write_team_mcp_configs.sh (#850).

Runs the real script against a temp repo root, so no worktrees are provisioned.
The role list is read from setup_team.sh and the Makefile, so a role added
to one without the others fails here instead of at the next `make team-<name>`.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_WRITER = _SCRIPTS / "write_team_mcp_configs.sh"
_QA_BROWSER = _SCRIPTS / "qa_browser.sh"
_MAKEFILE = _SCRIPTS.parent / "Makefile"

_ALL_SERVERS = [
    "mcp-gee-sweet-ash",
    "mcp-gee-sweet-sky",
    "mcp-gee-sweet-jay",
    "mcp-gee-sweet-kit",
    "mcp-gee-sweet-rio",
    "mcp-gee-sweet-kai-oauth",
    "mcp-gee-sweet-kai-sa",
    "mcp-gee-sweet-oauth",
    "mcp-gee-sweet-sa",
    "playwright",
    "playwright-1",
    "playwright-2",
    "playwright-3",
    "playwright-4",
]

# None: no role config; `make team-<name>` launches without --strict-mcp-config.
_EXPECTED_ROLE_SERVERS = {
    "ash": ["mcp-gee-sweet-ash"],
    "jay": ["mcp-gee-sweet-jay"],
    "sky": ["mcp-gee-sweet-sky", "playwright"],
    "kit": ["mcp-gee-sweet-kit", "playwright"],
    "rio": ["mcp-gee-sweet-rio", "playwright"],
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


def _run(
    root: Path, roles: list[str], *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    for role in roles:
        (root / ".claude" / "worktrees" / role).mkdir(parents=True, exist_ok=True)
    argv = list(args) if args else [str(root), *roles]
    return subprocess.run(
        ["bash", str(_WRITER), *argv],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


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


def _qa_browser(*args: str, **env: str) -> str:
    result = subprocess.run(
        ["bash", str(_QA_BROWSER), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_every_playwright_server_uses_one_pinned_package(written):
    # A range or @latest lets each `npx` resolve on its own, and the shards' tab
    # protocol was verified against one specific version (#1410).
    root, _ = written
    package = _qa_browser("mcp-package")
    assert re.fullmatch(r"@playwright/mcp@\d+\.\d+\.\d+", package)
    team = _load(root / ".claude/mcp-configs/team.mcp.json")
    for key in [k for k in team if k.startswith("playwright")]:
        assert team[key]["command"] == "npx"
        assert team[key]["args"][:2] == ["-y", package]


def test_shard_playwright_servers_attach_to_the_shared_browser(written):
    root, _ = written
    endpoint = _qa_browser("endpoint")
    team = _load(root / ".claude/mcp-configs/team.mcp.json")
    for k in range(1, 5):
        assert team[f"playwright-{k}"]["args"][2:] == ["--cdp-endpoint", endpoint]
    # The default server keeps its own per-directory profile.
    assert team["playwright"]["args"][2:] == []


def test_shared_browser_endpoint_is_loopback_and_honors_the_port_override(tmp_path):
    assert _qa_browser("endpoint", QA_BROWSER_PORT="9333") == "http://127.0.0.1:9333"
    assert _qa_browser("endpoint", QA_BROWSER_PORT="9444") == "http://127.0.0.1:9444"
    result = _run(tmp_path, _setup_team_roles(), env={"QA_BROWSER_PORT": "9444"})
    assert result.returncode == 0, result.stderr
    team = _load(tmp_path / ".claude/mcp-configs/team.mcp.json")
    assert team["playwright-1"]["args"][-1] == "http://127.0.0.1:9444"


def test_qa_browser_rejects_an_unknown_command():
    result = subprocess.run(["bash", str(_QA_BROWSER), "bogus"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "usage:" in result.stderr


# A stand-in for Chrome: answers CDP's /json/version on --remote-debugging-port
# until killed, so start/status/stop run their real code without a browser.
_FAKE_CHROME = """\
import http.server, sys
port = int(next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--remote-debugging-port=")))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def browser_env(tmp_path):
    """A copy of qa_browser.sh under tmp_path/scripts (so its repo root, and the
    .mcp.json it reads, is tmp_path), a fake Chrome, and a private cache dir.
    Runs from tmp_path, so a relative cache path can't land in the checkout."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "qa_browser.sh"
    shutil.copy(_QA_BROWSER, script)
    fake = tmp_path / "fake-chrome"
    fake.write_text(f"#!{sys.executable}\n{_FAKE_CHROME}")
    fake.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "QA_BROWSER_CHROME": str(fake),
    }
    started: list[dict[str, str]] = []

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        full = {**os.environ, **env, **extra}
        if args[:1] == ("start",):
            started.append(full)
        return subprocess.run(
            ["bash", str(script), *args], capture_output=True, text=True, env=full, cwd=tmp_path
        )

    yield run, tmp_path
    for full in started:
        subprocess.run(["bash", str(script), "stop"], capture_output=True, env=full, cwd=tmp_path)
    # Backstop: a broken `stop` (the bug these tests catch) mustn't leak servers.
    subprocess.run(["pkill", "-f", str(fake)], capture_output=True)


def _profile(tmp_path: Path, name: str) -> str:
    return str(tmp_path / "profiles" / name)


def test_status_and_start_report_only_a_browser_on_their_own_port(browser_env):
    # Kit's round-1 repro: a browser on one port made `start`/`status` on the
    # default port report "running" there.
    # Kit's case had a different Chrome answering on the default port.
    run, tmp = browser_env
    a, other = _free_port(), _free_port()
    result = run("start", QA_BROWSER_PORT=str(a), QA_BROWSER_PROFILE=_profile(tmp, "a"))
    assert result.returncode == 0, result.stderr
    assert (
        run("status", QA_BROWSER_PORT=str(a), QA_BROWSER_PROFILE=_profile(tmp, "a")).returncode == 0
    )
    stray = subprocess.Popen(
        [str(tmp / "fake-chrome"), f"--remote-debugging-port={other}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", other)) == 0:
                    break
            time.sleep(0.1)
        env_other = {"QA_BROWSER_PORT": str(other), "QA_BROWSER_PROFILE": _profile(tmp, "a")}
        status = run("status", **env_other)
        assert status.returncode == 1
        assert "not running" in status.stdout
        start = run("start", **env_other)
        assert "already running" not in start.stdout
        assert start.returncode == 1
    finally:
        stray.kill()
        stray.wait()


def test_a_second_port_keeps_its_own_record_and_each_stops(browser_env):
    # Kit's round-1 repro: a second browser overwrote the one pid file, so
    # neither could be stopped.
    run, tmp = browser_env
    a, b = _free_port(), _free_port()
    env_a = {"QA_BROWSER_PORT": str(a), "QA_BROWSER_PROFILE": _profile(tmp, "a")}
    env_b = {"QA_BROWSER_PORT": str(b), "QA_BROWSER_PROFILE": _profile(tmp, "b")}
    assert run("start", **env_a).returncode == 0
    assert run("start", **env_b).returncode == 0
    stop_a = run("stop", **env_a)
    assert stop_a.stdout.strip() == "QA browser stopped"
    assert run("status", **env_a).returncode == 1
    assert run("status", **env_b).returncode == 0
    assert run("stop", **env_b).stdout.strip() == "QA browser stopped"


def test_a_profile_prefix_is_not_mistaken_for_its_own(browser_env):
    run, tmp = browser_env
    port = _free_port()
    assert (
        run("start", QA_BROWSER_PORT=str(port), QA_BROWSER_PROFILE=_profile(tmp, "qa2")).returncode
        == 0
    )
    status = run("status", QA_BROWSER_PORT=str(port), QA_BROWSER_PROFILE=_profile(tmp, "qa"))
    assert status.returncode == 1


def test_start_on_a_port_another_browser_holds_says_to_rerun_setup(browser_env):
    run, tmp = browser_env
    port = _free_port()
    assert (
        run("start", QA_BROWSER_PORT=str(port), QA_BROWSER_PROFILE=_profile(tmp, "a")).returncode
        == 0
    )
    clash = run("start", QA_BROWSER_PORT=str(port), QA_BROWSER_PROFILE=_profile(tmp, "b"))
    assert clash.returncode == 1
    assert "setup_team.sh" in clash.stderr


def test_start_warns_when_the_mcp_config_names_another_port(browser_env):
    run, tmp = browser_env
    port = _free_port()
    (tmp / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "playwright-1": {"args": ["-y", "x", "--cdp-endpoint", "http://127.0.0.1:1"]}
                }
            }
        )
    )
    started = run("start", QA_BROWSER_PORT=str(port), QA_BROWSER_PROFILE=_profile(tmp, "a"))
    assert started.returncode == 0
    assert "attach to http://127.0.0.1:1, not" in started.stderr
    (tmp / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "playwright-1": {
                        "args": ["-y", "x", "--cdp-endpoint", f"http://127.0.0.1:{port}"]
                    }
                }
            }
        )
    )
    status = run("status", QA_BROWSER_PORT=str(port), QA_BROWSER_PROFILE=_profile(tmp, "a"))
    assert status.returncode == 0
    assert "warning" not in status.stderr


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS uses ~/Library/Caches, not XDG")
def test_a_relative_xdg_cache_home_is_ignored(browser_env):
    run, tmp = browser_env
    port = _free_port()
    result = run("start", QA_BROWSER_PORT=str(port), XDG_CACHE_HOME="relative/cache")
    assert result.returncode == 0, result.stderr
    assert f"profile {tmp / 'home' / '.cache' / 'mcp-gee-sweet' / 'qa-browser'}" in result.stdout
    assert not (tmp / "relative").exists()


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
