#!/usr/bin/env python3
"""
Flag any `<service>.files()`/`<service>.permissions()` call whose method
accepts `supportsAllDrives` but omits it — the recurring foot-gun from issue
#696 (a Drive API call silently fails with "File not found" against a
Shared Drive item when this is missing; see issue #687 for the first time
this shipped uncaught).

Usage:
    uv run python scripts/check_supports_all_drives.py

Wired into .pre-commit-config.yaml as a local hook, mirroring gen_tool_docs.py.
Checks via AST rather than a string/regex match, so formatting (the
multi-line chained-call style used throughout this codebase) can't hide a
call from it.

The method sets below were confirmed live against the Drive v3 discovery
document (https://www.googleapis.com/discovery/v1/apis/drive/v3/rest,
checked 2026-09-22) rather than assumed from the schema alone — see
CLAUDE.md's "Verify a ticket's API premise live before implementing, not
after." Only files/permissions/changes methods accept supportsAllDrives at
all; comments/replies/revisions/drives/about do not and are never flagged.
This codebase doesn't call the changes() resource, so it's left out of the
checked set — nothing to catch there yet. files.get_media (a client-generated
alias for files.get, not a separate REST method — see CHECKED_METHODS below)
is included since it shares files.get's parameters.

A call passing `supportsAllDrives=False` explicitly is flagged the same as
a call omitting it entirely, not just presence-checked — an earlier version
of this script only checked for the keyword's presence.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "mcp_gee_sweet"

CHECKED_METHODS: dict[str, set[str]] = {
    # get_media isn't a literal REST method — it's googleapiclient's generated
    # alias for files.get when supportsMediaDownload is set (confirmed live
    # against the discovery doc), so it takes the exact same parameters as
    # get, including supportsAllDrives.
    "files": {"get", "get_media", "list", "create", "update", "delete", "copy", "watch"},
    "permissions": {"get", "list", "create", "update", "delete"},
}


def _is_resource_builder_call(node: ast.expr, resource: str) -> bool:
    """True if node is exactly `<anything>.<resource>()` with no arguments.

    Known limitation: only matches the resource builder inlined directly on
    the checked call's receiver (`drive_service.files().get(...)`). A call
    built from an intermediate variable (`f = drive_service.files();
    f.get(...)`) isn't recognized — no call site in this codebase currently
    uses that shape.
    """
    return (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == resource
    )


def find_violations_in_source(source: str) -> list[tuple[int, str, str]]:
    """Return (lineno, resource, method) for every call missing supportsAllDrives,
    or passing it as the literal `False` constant."""
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        receiver = node.func.value
        for resource, methods in CHECKED_METHODS.items():
            if method not in methods or not _is_resource_builder_call(receiver, resource):
                continue
            # A **kwargs spread can't be statically verified either way — skip
            # rather than risk a false positive on a shape this codebase
            # doesn't currently use for these two resources (see module docstring).
            if any(kw.arg is None for kw in node.keywords):
                break
            kwarg = next((kw for kw in node.keywords if kw.arg == "supportsAllDrives"), None)
            is_literal_false = (
                kwarg is not None
                and isinstance(kwarg.value, ast.Constant)
                and kwarg.value.value is False
            )
            if kwarg is None or is_literal_false:
                violations.append((node.lineno, resource, method))
            break
    return violations


def find_violations(path: Path) -> list[tuple[int, str, str]]:
    return find_violations_in_source(path.read_text())


def main() -> int:
    all_violations: list[tuple[Path, int, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        for lineno, resource, method in find_violations(path):
            all_violations.append((path, lineno, resource, method))

    if all_violations:
        print("check_supports_all_drives: missing supportsAllDrives=True on Drive API calls:")
        for path, lineno, resource, method in all_violations:
            rel = path.relative_to(ROOT)
            print(f"  {rel}:{lineno}: .{resource}().{method}(...) has no supportsAllDrives=True")
        print(
            "\nA Drive API call operating on a specific file/permission needs "
            "supportsAllDrives=True or it silently fails with 'File not found' "
            "against any Shared Drive item — see issue #687/#696."
        )
        return 1

    print("check_supports_all_drives: all Drive API calls have supportsAllDrives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
