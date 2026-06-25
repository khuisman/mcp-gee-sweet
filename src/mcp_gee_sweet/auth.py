import base64
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import google.auth
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from mcp.server.fastmcp import FastMCP

from .cache import (
    CalendarCache,
    DocContentCache,
    DriveFolderCache,
    SheetDataCache,
    SheetStructureCache,
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
    cache: SheetStructureCache = field(default_factory=SheetStructureCache)
    sheet_data_cache: SheetDataCache = field(default_factory=SheetDataCache)
    drive_folder_cache: DriveFolderCache = field(default_factory=DriveFolderCache)
    doc_cache: DocContentCache = field(default_factory=DocContentCache)
    calendar_cache: CalendarCache = field(default_factory=CalendarCache)


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


@asynccontextmanager
async def spreadsheet_lifespan(server: FastMCP) -> AsyncIterator[SpreadsheetContext]:
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

    # cache_discovery=False: file cache requires oauth2client<4.0; all auth paths here use google-auth
    sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    activity_service = build("driveactivity", "v2", credentials=creds, cache_discovery=False)

    try:
        yield SpreadsheetContext(
            sheets_service=sheets_service,
            drive_service=drive_service,
            docs_service=docs_service,
            calendar_service=calendar_service,
            activity_service=activity_service,
            folder_id=DRIVE_FOLDER_ID if DRIVE_FOLDER_ID else None,
            auth_method=resolved,
            cache=SheetStructureCache(),
        )
    finally:
        pass
