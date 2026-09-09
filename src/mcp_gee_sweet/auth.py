import base64
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import google.auth
from google.auth import compute_engine, external_account, impersonated_credentials
from google.auth.transport.requests import Request
from google.oauth2 import gdch_credentials, service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from mcp.server.mcpserver import MCPServer

from .cache import (
    CalendarCache,
    DocContentCache,
    DriveFolderCache,
    SheetDataCache,
    SheetStructureCache,
)
from .http_transport import (  # noqa: F401 — re-exported for tool imports
    execute_in_thread,
    thread_http,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.activity.readonly",
]

CREDENTIALS_CONFIG = os.environ.get("CREDENTIALS_CONFIG")
TOKEN_PATH = os.environ.get("TOKEN_PATH", "token.json")
CREDENTIALS_PATH = os.environ.get("CREDENTIALS_PATH", "credentials.json")
SERVICE_ACCOUNT_PATH = os.environ.get("SERVICE_ACCOUNT_PATH", "service_account.json")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
# When unset, auth falls through: OAuth → service_account → ADC.
# Explicit values pin to one method with no fallback: "oauth" | "service_account" | "adc"
AUTH_METHOD = os.environ.get("AUTH_METHOD")


@dataclass
class SpreadsheetContext:
    sheets_service: Any
    drive_service: Any
    docs_service: Any
    calendar_service: Any
    activity_service: Any
    folder_id: str | None = None
    auth_method: str = "unknown"  # "service_account" | "oauth" | "adc"
    # True whenever the resolved credential has no personal Drive identity —
    # always true for auth_method == "service_account", but also true for
    # auth_method == "adc" when google.auth.default() itself resolved to a
    # service-account-backed credential (see _is_service_account_credential).
    is_service_account_identity: bool = False
    cache: SheetStructureCache = field(default_factory=SheetStructureCache)
    sheet_data_cache: SheetDataCache = field(default_factory=SheetDataCache)
    drive_folder_cache: DriveFolderCache = field(default_factory=DriveFolderCache)
    doc_cache: DocContentCache = field(default_factory=DocContentCache)
    calendar_cache: CalendarCache = field(default_factory=CalendarCache)


def _is_service_account_credential(creds: Any) -> bool:
    """Whether `creds` is backed by a service-account identity (no personal Drive
    storage quota, no personal Drive identity) rather than a real user's own.

    True for the credentials `_service_account_creds()` returns, and — the case
    issue #506 is about — also true for an ADC-resolved credential
    (`google.auth.default()`) when ADC itself resolved to one of the
    non-user-identity credential classes `google.auth._default.py`'s own dispatch
    table can produce (confirmed against the installed `google-auth` package,
    PR #613 QA round 1 — the original version of this check only covered the
    first two and silently misclassified the rest the same way plain `"adc"` did
    before this fix existed):

    - `service_account.Credentials` — `GOOGLE_APPLICATION_CREDENTIALS` pointed at
      a key file, the same class the explicit `service_account` path uses.
    - `compute_engine.Credentials` — a GCE/Cloud Run/GKE attached metadata identity.
    - `external_account.Credentials` — Workload Identity Federation (AWS, a
      pluggable external process, or a file/URL-sourced identity pool; `aws`,
      `pluggable`, and `identity_pool` credentials all subclass this one base).
    - `impersonated_credentials.Credentials` — an impersonated service account,
      common in CI.
    - `gdch_credentials.ServiceAccountCredentials` — a GDCH service account.

    Deliberately excludes `external_account_authorized_user.Credentials`
    (Workforce Identity Federation): per its own module docstring it "usually
    access[es] resources on behalf of a user (resource owner)" — a real human
    authenticated through an external IdP, not a service identity — so it's
    treated the same as `google.oauth2.credentials.Credentials`, the class an ADC
    session backed by a real user (`gcloud auth application-default login`) or
    `_oauth_creds()`'s own OAuth flow resolves to.
    """
    return isinstance(
        creds,
        service_account.Credentials
        | compute_engine.Credentials
        | external_account.Credentials
        | impersonated_credentials.Credentials
        | gdch_credentials.ServiceAccountCredentials,
    )


def _oauth_creds() -> Credentials:
    """Obtain OAuth credentials, refreshing or running the interactive flow as needed."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            creds = Credentials.from_authorized_user_info(json.load(f), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            logger.debug("Refreshing expired OAuth token...")
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            logger.debug("Token refreshed successfully")
            return creds
        except Exception as e:
            logger.warning("Token refresh failed: %s — re-running OAuth flow", e)
            creds = None

    if not creds or not creds.valid:
        if not os.path.exists(CREDENTIALS_PATH):
            raise RuntimeError(
                f"{CREDENTIALS_PATH!r} not found. Set CREDENTIALS_PATH or provide credentials.json."
            )
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        logger.debug("OAuth flow completed successfully")

    return creds


def _service_account_creds() -> service_account.Credentials:
    """Load service account credentials from env or file."""
    if CREDENTIALS_CONFIG:
        return service_account.Credentials.from_service_account_info(
            json.loads(base64.b64decode(CREDENTIALS_CONFIG)), scopes=SCOPES
        )
    if SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
        return service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_PATH, scopes=SCOPES
        )
    return None


# mcp v2's MCPServer dropped FastMCP's get_context() with no replacement for static
# (non-templated) resources — Context injection there raises ValueError outright, and
# there's no other way to reach the running server's per-process state (confirmed live
# against mcp==2.0.0, issue #175). SpreadsheetContext is created once per process by
# this lifespan (not per-request), so mirroring it here is the correct-shaped fix, not
# a workaround: server.py's get_auth_status() (a static resource) reads it via
# get_lifespan_context() instead of going through Context at all.
_lifespan_context: SpreadsheetContext | None = None


def get_lifespan_context() -> SpreadsheetContext:
    if _lifespan_context is None:
        raise RuntimeError("Server lifespan has not started yet")
    return _lifespan_context


@asynccontextmanager
async def spreadsheet_lifespan(server: MCPServer) -> AsyncIterator[SpreadsheetContext]:
    from googleapiclient.discovery import build

    logger.debug("AUTH_METHOD=%s", AUTH_METHOD or "auto (waterfall)")

    # --- Strict override modes (AUTH_METHOD set explicitly) ---

    if AUTH_METHOD == "oauth":
        creds = _oauth_creds()
        resolved = "oauth"

    elif AUTH_METHOD == "service_account":
        creds = _service_account_creds()
        if not creds:
            raise RuntimeError(
                "AUTH_METHOD=service_account but no credentials found. "
                "Set CREDENTIALS_CONFIG or SERVICE_ACCOUNT_PATH."
            )
        resolved = "service_account"

    elif AUTH_METHOD == "adc":
        try:
            creds, project = google.auth.default(scopes=SCOPES)
            logger.debug("ADC resolved project: %s", project)
            resolved = "adc"
        except Exception as e:
            raise RuntimeError("AUTH_METHOD=adc but ADC failed.") from e

    # --- Waterfall (AUTH_METHOD not set) ---

    else:
        creds = None
        resolved = "unknown"

        # 1. OAuth
        try:
            creds = _oauth_creds()
            resolved = "oauth"
            logger.debug("Waterfall: using OAuth")
        except Exception as e:
            logger.debug("Waterfall: OAuth unavailable (%s), trying service account", e)

        # 2. Service account
        if not creds:
            creds = _service_account_creds()
            if creds:
                resolved = "service_account"
                logger.debug("Waterfall: using service account")
                logger.debug("Drive folder ID: %s", DRIVE_FOLDER_ID or "not specified")

        # 3. ADC
        if not creds:
            try:
                creds, project = google.auth.default(scopes=SCOPES)
                resolved = "adc"
                logger.debug("Waterfall: using ADC for project: %s", project)
            except Exception as e:
                raise RuntimeError(
                    "All authentication methods failed. Please configure credentials."
                ) from e

    logger.debug("Auth resolved: %s", resolved)
    is_service_account_identity = _is_service_account_credential(creds)
    if resolved == "adc" and is_service_account_identity:
        logger.debug("ADC resolved to a service-account-backed credential")

    # cache_discovery=False: file cache requires oauth2client<4.0; all auth paths here use google-auth
    sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    activity_service = build("driveactivity", "v2", credentials=creds, cache_discovery=False)

    global _lifespan_context
    context = SpreadsheetContext(
        sheets_service=sheets_service,
        drive_service=drive_service,
        docs_service=docs_service,
        calendar_service=calendar_service,
        activity_service=activity_service,
        folder_id=DRIVE_FOLDER_ID if DRIVE_FOLDER_ID else None,
        auth_method=resolved,
        is_service_account_identity=is_service_account_identity,
        cache=SheetStructureCache(),
    )
    _lifespan_context = context
    try:
        yield context
    finally:
        _lifespan_context = None
