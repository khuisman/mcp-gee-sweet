"""Consistency checks for manifest.json, the MCP Bundle manifest (#1036), and for
scripts/build_mcpb.py's staging allowlist.

The script lives outside the mcp_gee_sweet package, so it's loaded here via
importlib rather than a normal import (same pattern as test_gen_tool_docs.py).
"""

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_mcpb.py"
_spec = importlib.util.spec_from_file_location("build_mcpb", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
build_mcpb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_mcpb)

# Variables a host substitutes in mcp_config besides ${user_config.*}.
_HOST_VARIABLES = {"__dirname", "HOME"}


def _manifest():
    return build_mcpb.load_manifest()


def _pyproject():
    with open(_REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def _mcp_config_strings(manifest):
    config = manifest["server"]["mcp_config"]
    return [config["command"], *config["args"], *config["env"].values()]


class TestVersion:
    def test_matches_server_json(self):
        with open(_REPO_ROOT / "server.json") as f:
            server_json = json.load(f)
        assert _manifest()["version"] == server_json["version"]

    def test_bypass_matches_version(self):
        # Inside the bundle there's no git tag for uv-dynamic-versioning to read,
        # so without this the installed package reports the 0.0.0 fallback.
        manifest = _manifest()
        env = manifest["server"]["mcp_config"]["env"]
        assert env["UV_DYNAMIC_VERSIONING_BYPASS"] == manifest["version"]

    def test_expect_version_accepts_the_tag(self):
        manifest = _manifest()
        build_mcpb.check_version(manifest, "v" + manifest["version"])

    def test_expect_version_rejects_a_stale_manifest(self):
        with pytest.raises(SystemExit, match=re.escape("expected '99.0.0'")):
            build_mcpb.check_version(_manifest(), "v99.0.0")

    def test_expect_version_rejects_a_stale_bypass(self):
        manifest = _manifest()
        manifest["server"]["mcp_config"]["env"]["UV_DYNAMIC_VERSIONING_BYPASS"] = "0.0.1"
        with pytest.raises(SystemExit, match=re.escape("UV_DYNAMIC_VERSIONING_BYPASS '0.0.1'")):
            build_mcpb.check_version(manifest, manifest["version"])


class TestIdentity:
    def test_matches_pyproject(self):
        manifest = _manifest()
        project = _pyproject()["project"]
        assert manifest["name"] == project["name"]
        assert manifest["description"] == project["description"]
        assert manifest["license"] == project["license"]
        assert manifest["author"] == project["authors"][0]
        assert manifest["homepage"] == project["urls"]["Homepage"]
        assert manifest["support"] == project["urls"]["Bug Tracker"]
        assert manifest["repository"]["url"] + ".git" == project["urls"]["Repository"]

    def test_python_floor_matches_pyproject(self):
        runtimes = _manifest()["compatibility"]["runtimes"]
        assert runtimes["python"] == _pyproject()["project"]["requires-python"]

    def test_uv_server_type(self):
        server = _manifest()["server"]
        assert _manifest()["manifest_version"] == "0.4"
        assert server["type"] == "uv"
        # The v0.4 validator requires mcp_config even for the uv type.
        assert server["mcp_config"]["command"] == "uv"

    def test_entry_point_is_the_launched_module(self):
        server = _manifest()["server"]
        assert server["entry_point"] == "src/mcp_gee_sweet/__main__.py"
        assert (_REPO_ROOT / server["entry_point"]).is_file()
        args = server["mcp_config"]["args"]
        assert args[-3:] == ["python", "-m", "mcp_gee_sweet"]

    def test_runs_frozen_without_dev_dependencies(self):
        args = _manifest()["server"]["mcp_config"]["args"]
        assert args[:3] == ["run", "--directory", "${__dirname}"]
        assert "--frozen" in args
        assert "--no-dev" in args


class TestUserConfig:
    def test_every_reference_resolves(self):
        # A host leaves `${user_config.KEY}` in place, verbatim, when KEY has no
        # value: an optional key without a default would reach the server as
        # that literal text (ENABLED_TOOLS="${user_config.enabled_tools}" would
        # register no tools).
        manifest = _manifest()
        user_config = manifest["user_config"]
        for s in _mcp_config_strings(manifest):
            for var in re.findall(r"\$\{([^}]+)\}", s):
                if var.startswith("user_config."):
                    key = var.removeprefix("user_config.")
                    assert key in user_config, var
                    opt = user_config[key]
                    assert opt.get("required") or "default" in opt, key
                else:
                    assert var in _HOST_VARIABLES, var

    def test_every_key_is_used(self):
        manifest = _manifest()
        used = " ".join(_mcp_config_strings(manifest))
        for key in manifest["user_config"]:
            assert f"${{user_config.{key}}}" in used, key

    def test_defaults_have_no_variables(self):
        # The reference implementation substitutes a default into mcp_config
        # without expanding the variables inside it.
        for key, opt in _manifest()["user_config"].items():
            assert "${" not in str(opt.get("default", "")), key

    def test_oauth_only(self):
        env = _manifest()["server"]["mcp_config"]["env"]
        assert env["AUTH_METHOD"] == "oauth"
        assert env["CREDENTIALS_PATH"] == "${user_config.credentials_path}"
        assert _manifest()["user_config"]["credentials_path"]["type"] == "file"
        # Outside the extension directory, which an update replaces.
        assert env["TOKEN_PATH"].startswith("${HOME}/")


class TestBundleFiles:
    def test_holds_the_project_and_the_package(self):
        files = build_mcpb.bundle_files()
        for rel in build_mcpb._ROOT_FILES:
            assert rel in files
        assert "src/mcp_gee_sweet/__main__.py" in files
        assert "src/mcp_gee_sweet/server.py" in files

    def test_nothing_outside_the_allowlist(self):
        for rel in build_mcpb.bundle_files():
            assert rel in build_mcpb._ROOT_FILES or rel.startswith(build_mcpb._PACKAGE_DIR + "/")

    def test_no_local_credentials(self):
        names = {Path(rel).name for rel in build_mcpb.bundle_files()}
        for secret in ("credentials.json", "token.json", "service_account.json", ".env"):
            assert secret not in names

    def test_stage_resizes_the_icon(self, tmp_path):
        from PIL import Image

        build_mcpb.stage(tmp_path)
        with Image.open(tmp_path / _manifest()["icon"]) as icon:
            assert max(icon.size) == build_mcpb._ICON_SIZE
        assert (tmp_path / "manifest.json").is_file()
        assert not (tmp_path / "src" / "mcp_gee_sweet" / ".env").exists()
