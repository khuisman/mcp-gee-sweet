#!/usr/bin/env python3
"""
OAuth token setup for QA automation.

Starts the OAuth consent flow without auto-opening a browser, prints the
authorization URL to stdout, and waits for the local callback. Use this
when token.json is missing or expired and you need to (re-)authorize.

Usage:
    uv run python scripts/oauth_setup.py

Then either:
  a) Copy the URL and paste it into any browser (manual)
  b) Let the QA conductor (Claude Code + Playwright MCP) navigate to it

The token is saved to TOKEN_PATH (default: token.json) on completion.

CI / headless alternative — see docs/qa/playwright_oauth.md for refresh-token
injection via GOOGLE_OAUTH_REFRESH_TOKEN, which skips this browser flow entirely.
"""

import json
import os
import sys
from pathlib import Path

# Bootstrap package env so CREDENTIALS_PATH / TOKEN_PATH are resolved from .env
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import dotenv

dotenv.load_dotenv(Path(__file__).parent.parent / "src" / "mcp_gee_sweet" / ".env")

from mcp_gee_sweet.auth import CREDENTIALS_PATH, SCOPES, TOKEN_PATH  # noqa: E402


def main() -> None:
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"ERROR: credentials file not found at {CREDENTIALS_PATH!r}", file=sys.stderr)
        print("Set CREDENTIALS_PATH in .env or provide credentials.json", file=sys.stderr)
        sys.exit(1)

    # Import here so the dotenv load above takes effect first
    from google_auth_oauthlib.flow import InstalledAppFlow

    print(f"Credentials : {CREDENTIALS_PATH}")
    print(f"Token target: {TOKEN_PATH}")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(
        port=0,
        open_browser=False,
        authorization_prompt_message=(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "OAUTH_URL: {url}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Navigate to the URL above (browser or Playwright).\n"
            "Waiting for callback…"
        ),
        success_message=("Authorization complete — you may close this tab."),
    )

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"\nToken saved to {TOKEN_PATH}")


def from_refresh_token() -> None:
    """
    Reconstruct token.json from GOOGLE_OAUTH_REFRESH_TOKEN env var.

    Use this in CI or repeated automated runs where the refresh token is
    stored as a secret rather than running the full browser flow each time.

    Required env vars:
        GOOGLE_OAUTH_REFRESH_TOKEN  — the refresh_token value from token.json
        GOOGLE_OAUTH_CLIENT_ID      — client_id from credentials.json
        GOOGLE_OAUTH_CLIENT_SECRET  — client_secret from credentials.json
    """
    refresh_token = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

    if not all([refresh_token, client_id, client_secret]):
        print(
            "ERROR: GOOGLE_OAUTH_REFRESH_TOKEN, GOOGLE_OAUTH_CLIENT_ID, and "
            "GOOGLE_OAUTH_CLIENT_SECRET must all be set.",
            file=sys.stderr,
        )
        sys.exit(1)

    token_data = {
        "token": None,
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": SCOPES,
        "universe_domain": "googleapis.com",
    }

    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"token.json written from refresh token → {TOKEN_PATH}")
    print("The server will exchange it for an access token on first use.")


if __name__ == "__main__":
    if "--from-refresh-token" in sys.argv:
        from_refresh_token()
    else:
        main()
