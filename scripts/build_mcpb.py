#!/usr/bin/env python3
"""
Build the MCP Bundle (`.mcpb`) from manifest.json (#1036).

Usage:
    uv run python scripts/build_mcpb.py [--out PATH] [--version X.Y.Z] [--smoke]

The bundle uses the manifest's `uv` server type: it ships pyproject.toml,
uv.lock and the source, and the host installs the dependencies with uv.

It never packs the repo root, or even the working tree. A working checkout
holds credentials.json, token.json, service_account.json and
src/mcp_gee_sweet/.env, and a deny-list that misses a new one would ship it;
an uncommitted edit to a tracked file could carry one too. So every file is
read from HEAD: an allowlist (`_ROOT_FILES`, everything under `_PACKAGE_DIR`,
and the icon) is written into a staging directory, and `mcpb pack` runs on
that. A local build of uncommitted changes needs a commit first.

manifest.json carries no version. The staged copy gets `version`, and the
UV_DYNAMIC_VERSIONING_BYPASS that stands in for the git tag inside the bundle,
from --version (the release workflow passes the tag) or else from server.json,
so no release step bumps manifest.json by hand.

--smoke extracts the built bundle and runs it the way the host does
(`uv run --frozen --no-dev`), checking that the package imports and reports
the stamped version.
"""

import argparse
import io
import json
import os
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

_REF = "HEAD"
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
_VERSION_ENV = "UV_DYNAMIC_VERSIONING_BYPASS"


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def read_committed(rel: str) -> bytes:
    return _git("show", f"{_REF}:{rel}")


def bundle_files() -> list[str]:
    """The repo-relative paths that go into the bundle, besides the icon: the
    allowlist, as committed at HEAD. An untracked or uncommitted file never
    reaches the staging directory."""
    listed = _git("ls-tree", "-r", "-z", "--name-only", _REF, "--", _PACKAGE_DIR, *_ROOT_FILES)
    files = sorted(p for p in listed.decode().split("\0") if p)
    missing = [p for p in _ROOT_FILES if p not in files]
    if missing:
        sys.exit(f"build_mcpb: not committed at {_REF}: {', '.join(missing)}")
    return files


def release_version(tag: str | None) -> str:
    """The bundle's version: the release tag if given, else server.json's."""
    if tag:
        return tag.removeprefix("v")
    return json.loads(read_committed("server.json"))["version"]


def stamped_manifest(version: str) -> dict:
    manifest = json.loads(read_committed("manifest.json"))
    manifest["version"] = version
    # pyproject.toml's version comes from the git tag, and a bundle has no .git:
    # without this, the installed package reports uv-dynamic-versioning's 0.0.0.
    manifest["server"]["mcp_config"]["env"][_VERSION_ENV] = version
    return manifest


def stage(dest: Path, manifest: dict) -> None:
    for rel in bundle_files():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_committed(rel))
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    # The logo is 1254px and most of the bundle's size; Claude Desktop recommends 512px.
    with Image.open(io.BytesIO(read_committed(_ICON_SOURCE))) as icon:
        icon.thumbnail((_ICON_SIZE, _ICON_SIZE))
        icon.save(dest / manifest["icon"], optimize=True)


def _warn_uncommitted() -> None:
    dirty = _git("status", "--porcelain", "--", _PACKAGE_DIR, _ICON_SOURCE, *_ROOT_FILES)
    if dirty.strip():
        print(
            f"build_mcpb: building from {_REF}; these uncommitted changes aren't in the bundle:\n"
            + dirty.decode(),
            file=sys.stderr,
        )


def pack(stage_dir: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["npx", "--yes", MCPB_CLI, "pack", str(stage_dir), str(out)],
        check=True,
    )


def clean_env() -> dict[str, str]:
    """This process's environment minus the active project and virtualenv, so
    `uv run` in an extracted bundle builds its own environment, as a host would."""
    return {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT")}


def smoke(bundle: Path, manifest: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as z:
            z.extractall(tmp)
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
            env={**clean_env(), **manifest["server"]["mcp_config"]["env"]},
            check=True,
            capture_output=True,
            text=True,
        )
        reported = result.stdout.strip().splitlines()[-1]
        if reported != manifest["version"]:
            sys.exit(
                f"build_mcpb: the bundle installs as version {reported!r}, "
                f"but its manifest says {manifest['version']!r}"
            )
        print(f"smoke: bundle installs and imports as mcp-gee-sweet {reported}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    parser.add_argument(
        "--out", type=Path, help="output path (default: dist/<name>-<version>.mcpb)"
    )
    parser.add_argument(
        "--version", help="the bundle's version, e.g. a release tag (default: server.json's)"
    )
    parser.add_argument("--smoke", action="store_true", help="install and import the built bundle")
    args = parser.parse_args()

    _warn_uncommitted()
    manifest = stamped_manifest(release_version(args.version))
    out = (args.out or ROOT / "dist" / f"{manifest['name']}-{manifest['version']}.mcpb").resolve()

    with tempfile.TemporaryDirectory() as tmp:
        stage_dir = Path(tmp) / manifest["name"]
        stage_dir.mkdir()
        stage(stage_dir, manifest)
        pack(stage_dir, out)
    if args.smoke:
        smoke(out, manifest)
    print(out)


if __name__ == "__main__":
    main()
