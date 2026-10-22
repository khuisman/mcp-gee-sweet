import os
from pathlib import Path

from dotenv import load_dotenv

# A blank token counts as unset (http_auth), so let .env supply one: docker-compose
# passes MCP_SERVER_TOKEN through as "" when its own .env doesn't set it.
if not os.environ.get("MCP_SERVER_TOKEN", "").strip():
    os.environ.pop("MCP_SERVER_TOKEN", None)
load_dotenv(Path(__file__).parent / ".env")  # env var > src/mcp_gee_sweet/.env > default

from . import server  # noqa: E402


def main():
    """Main entry point for the package."""
    server.main()


# Optionally expose other important items at package level
__all__ = ["main", "server"]
