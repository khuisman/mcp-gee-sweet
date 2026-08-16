"""Consistency checks for server.json, the MCP registry manifest at the repo root.

Guards against the manifest's identity fields drifting from pyproject.toml /
README.md silently — not the version number, which is expected to move on
every release and is updated as part of the release process instead.
"""

import json
import re
from pathlib import Path

import tomllib

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_server_json():
    with open(_REPO_ROOT / "server.json") as f:
        return json.load(f)


def _load_pyproject():
    with open(_REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


class TestServerJson:
    def test_is_valid_json_with_required_fields(self):
        manifest = _load_server_json()
        assert manifest["name"] == "io.github.khuisman/mcp-gee-sweet"
        assert manifest["description"]
        assert manifest["version"]

    def test_pypi_package_identifier_matches_pyproject(self):
        manifest = _load_server_json()
        pyproject = _load_pyproject()
        packages = manifest["packages"]
        pypi_packages = [p for p in packages if p["registryType"] == "pypi"]
        assert len(pypi_packages) == 1
        assert pypi_packages[0]["identifier"] == pyproject["project"]["name"]

    def test_pypi_package_version_matches_top_level_version(self):
        manifest = _load_server_json()
        pypi_package = next(p for p in manifest["packages"] if p["registryType"] == "pypi")
        assert pypi_package["version"] == manifest["version"]

    def test_readme_mcp_name_marker_matches_server_name(self):
        manifest = _load_server_json()
        readme = (_REPO_ROOT / "README.md").read_text()
        match = re.search(r"mcp-name:\s*(\S+?)(?=\s|-->|$)", readme)
        assert match is not None, "README.md is missing the mcp-name ownership marker"
        assert match.group(1) == manifest["name"]
