#!/usr/bin/env python3
"""
Build the MCP Bundle (`.mcpb`) from manifest.json (#1036).

Usage:
    uv run python scripts/build_mcpb.py [--out PATH] [--expect-version X.Y.Z] [--smoke]

The bundle uses the manifest's `uv` server type: it ships pyproject.toml,
uv.lock and the source, and the host installs the dependencies with uv.

It never packs the repo root. A working checkout holds credentials.json,
token.json, service_account.json and src/mcp_gee_sweet/.env, and a deny-list
that misses a new one would ship it. So the bundle is staged from an allowlist
of git-tracked files (`_ROOT_FILES` plus everything tracked under
`_PACKAGE_DIR`), and `mcpb pack` runs on that staging directory.

--expect-version fails the build when manifest.json's version, or the
UV_DYNAMIC_VERSIONING_BYPASS that stands in for the git tag inside the bundle,
isn't that version: the release workflow passes the tag, so a release cut
without bumping manifest.json attaches no stale bundle.

--smoke extracts the built bundle and runs it the way the host does
(`uv run --frozen --no-dev`), checking that the package imports and reports
the manifest's version.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

# The npm CLI that validates and packs a bundle. Pinned: `pack` validates
# against the schema it ships with.
MCPB_CLI = "@anthropic-ai/mcpb@2.1.2"

_ROOT_FILES = [
    "manifest.json",
    ".mcpbignore",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "LICENSE",
]
_PACKAGE_DIR = "src/mcp_gee_sweet"
_ICON_SOURCE = "docs/assets/logo.png"
_ICON_SIZE = 512


def load_manifest() -> dict:
    with open(ROOT / "manifest.json") as f:
        return json.load(f)


def bundle_files() -> list[str]:
    """The repo-relative paths that go into the bundle, besides the icon.

    Only tracked files: an untracked file under the package directory (a
    local .env, a stray token) never reaches the staging directory.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", _PACKAGE_DIR, *_ROOT_FILES],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    files = sorted(p for p in tracked if p)
    missing = [p for p in _ROOT_FILES if p not in files]
    if missing:
        sys.exit(f"build_mcpb: not tracked by git: {', '.join(missing)}")
    return files


def stage(dest: Path) -> None:
    for rel in bundle_files():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    # The logo is 1254px and most of the bundle's size; Claude Desktop recommends 512px.
    with Image.open(ROOT / _ICON_SOURCE) as icon:
        icon.thumbnail((_ICON_SIZE, _ICON_SIZE))
        icon.save(dest / load_manifest()["icon"], optimize=True)


def check_version(manifest: dict, expected: str) -> None:
    expected = expected.removeprefix("v")
    bypass = manifest["server"]["mcp_config"]["env"]["UV_DYNAMIC_VERSIONING_BYPASS"]
    if manifest["version"] != expected or bypass != expected:
        sys.exit(
            f"build_mcpb: manifest.json has version {manifest['version']!r} and "
            f"UV_DYNAMIC_VERSIONING_BYPASS {bypass!r}, expected {expected!r}. "
            "Bump both alongside server.json."
        )


def pack(stage_dir: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["npx", "--yes", MCPB_CLI, "pack", str(stage_dir), str(out)],
        check=True,
    )


def smoke(bundle: Path, manifest: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as z:
            z.extractall(tmp)
        env_bypass = manifest["server"]["mcp_config"]["env"]["UV_DYNAMIC_VERSIONING_BYPASS"]
        result = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                tmp,
                "--frozen",
                "--no-dev",
                "python",
                "-c",
                "import importlib.metadata, mcp_gee_sweet.__main__; "
                "print(importlib.metadata.version('mcp-gee-sweet'))",
            ],
            env={**_clean_env(), "UV_DYNAMIC_VERSIONING_BYPASS": env_bypass},
            check=True,
            capture_output=True,
            text=True,
        )
        reported = result.stdout.strip().splitlines()[-1]
        if reported != manifest["version"]:
            sys.exit(
                f"build_mcpb: the bundle installs as version {reported!r}, "
                f"but manifest.json says {manifest['version']!r}"
            )
        print(f"smoke: bundle installs and imports as mcp-gee-sweet {reported}")


def _clean_env() -> dict[str, str]:
    """This process's environment minus the active virtualenv, so `uv run`
    in the extracted bundle builds its own environment, as a host would."""
    return {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    parser.add_argument(
        "--out", type=Path, help="output path (default: dist/<name>-<version>.mcpb)"
    )
    parser.add_argument("--expect-version", help="fail unless manifest.json has this version")
    parser.add_argument("--smoke", action="store_true", help="install and import the built bundle")
    args = parser.parse_args()

    manifest = load_manifest()
    if args.expect_version:
        check_version(manifest, args.expect_version)
    out = (args.out or ROOT / "dist" / f"{manifest['name']}-{manifest['version']}.mcpb").resolve()

    with tempfile.TemporaryDirectory() as tmp:
        stage_dir = Path(tmp) / manifest["name"]
        stage_dir.mkdir()
        stage(stage_dir)
        pack(stage_dir, out)
    if args.smoke:
        smoke(out, manifest)
    print(out)


if __name__ == "__main__":
    main()
