#!/usr/bin/env python3
"""
Launch a built MCP Bundle the way a host does, and talk to it over stdio (TC-I68, #1036).

Usage:
    uv run python scripts/qa_launch_mcpb.py BUNDLE.mcpb --credentials PATH --home DIR
        [--tool NAME] [--wait-for-consent]

It extracts the bundle into DIR/ext and runs manifest.json's mcp_config with
the variables substituted as @anthropic-ai/mcpb's getMcpConfigForManifest does:
${__dirname} is the extraction directory, ${HOME} is DIR (so the token lands in
DIR, never in your real home), and each ${user_config.KEY} is its default, or
--credentials for credentials_path. It then initializes, lists the tools, and
calls --tool (default list_spreadsheets) with no arguments.

With --wait-for-consent, a call that returns the Google consent link is retried
once the token file appears: open the printed link and approve it within the
deadline the message gives. Run it again with the same --home to check that a
restart reuses the token.

This is a QA aid, not a test: it needs network access, and consent needs a
person at a browser.
"""

import argparse
import asyncio
import io
import json
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

# Run as a script, this directory is first on sys.path.
from build_mcpb import clean_env
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_CONSENT_POLL_SECONDS = 2
_CONSENT_DEADLINE_SECONDS = 300
# The token file exists (O_CREAT) before it's written, and the server adopts it
# after that, so the first call after it appears can still miss it.
_RETRIES_AFTER_CONSENT = 3
_CONSENT_LINK = re.compile(r"https://accounts\.google\.com/")


def host_params(bundle: Path, credentials: Path, home: Path) -> tuple[StdioServerParameters, Path]:
    ext = home / "ext"
    shutil.rmtree(ext, ignore_errors=True)
    ext.mkdir(parents=True)
    with zipfile.ZipFile(bundle) as z:
        z.extractall(ext)
    manifest = json.loads((ext / "manifest.json").read_text())

    variables = {"__dirname": str(ext), "HOME": str(home)}
    for key, opt in manifest.get("user_config", {}).items():
        if "default" in opt:
            variables[f"user_config.{key}"] = str(opt["default"])
    variables["user_config.credentials_path"] = str(credentials)

    def sub(s: str) -> str:
        return re.sub(r"\$\{([^}]+)\}", lambda m: variables.get(m.group(1), m.group(0)), s)

    config = manifest["server"]["mcp_config"]
    env = {k: sub(v) for k, v in config.get("env", {}).items()}
    print("env:", json.dumps(env, indent=2))
    params = StdioServerParameters(
        command=config["command"], args=[sub(a) for a in config["args"]], env={**clean_env(), **env}
    )
    return params, Path(env["TOKEN_PATH"])


def _token_written(path: Path) -> bool:
    try:
        return bool(json.loads(path.read_text()))
    except (OSError, ValueError):
        return False


async def _call(session: ClientSession, tool: str) -> tuple[bool, str]:
    result = await session.call_tool(tool, {})
    text = " ".join(getattr(c, "text", "") for c in result.content)
    return bool(result.is_error), text


async def run(args: argparse.Namespace) -> int:
    params, token_path = host_params(args.bundle, args.credentials.resolve(), args.home.resolve())
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        print("server:", init.server_info.name, init.server_info.version)
        tools = await session.list_tools()
        print("tools:", len(tools.tools))
        print("token file before the call:", token_path.exists())
        is_error, text = await _call(session, args.tool)
        print(f"{args.tool}: is_error={is_error}\n{text[:2000]}")
        if not (is_error and args.wait_for_consent and _CONSENT_LINK.search(text)):
            return 1 if is_error else 0
        print("\nOpen the link above and approve it. Waiting for the token file...")
        deadline = time.monotonic() + _CONSENT_DEADLINE_SECONDS
        while not _token_written(token_path):
            if time.monotonic() > deadline:
                print("no token file before the deadline")
                return 1
            await asyncio.sleep(_CONSENT_POLL_SECONDS)
        print("token file written, mode", oct(token_path.stat().st_mode & 0o777))
        for attempt in range(1, _RETRIES_AFTER_CONSENT + 1):
            is_error, text = await _call(session, args.tool)
            print(f"retry {attempt} of {args.tool}: is_error={is_error}\n{text[:2000]}")
            if not is_error:
                return 0
            await asyncio.sleep(_CONSENT_POLL_SECONDS)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--credentials", type=Path, required=True, help="OAuth client JSON")
    parser.add_argument("--home", type=Path, required=True, help="stands in for ${HOME}")
    parser.add_argument("--tool", default="list_spreadsheets")
    parser.add_argument("--wait-for-consent", action="store_true")
    args = parser.parse_args()
    # The consent link must show up even when stdout is redirected to a file.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    args.home.mkdir(parents=True, exist_ok=True)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
