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

from .cache import DriveFolderCache, SheetDataCache, SheetStructureCache

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

CREDENTIALS_CONFIG = os.environ.get("CREDENTIALS_CONFIG")
TOKEN_PATH = os.environ.get("TOKEN_PATH", "token.json")
CREDENTIALS_PATH = os.environ.get("CREDENTIALS_PATH", "credentials.json")
SERVICE_ACCOUNT_PATH = os.environ.get("SERVICE_ACCOUNT_PATH", "service_account.json")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")


@dataclass
class SpreadsheetContext:
    sheets_service: Any
    drive_service: Any
    docs_service: Any
    folder_id: str | None = None
    cache: SheetStructureCache = field(default_factory=SheetStructureCache)
    sheet_data_cache: SheetDataCache = field(default_factory=SheetDataCache)
    drive_folder_cache: DriveFolderCache = field(default_factory=DriveFolderCache)


@asynccontextmanager
async def spreadsheet_lifespan(server: FastMCP) -> AsyncIterator[SpreadsheetContext]:
    from googleapiclient.discovery import build

    creds = None

    if CREDENTIALS_CONFIG:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(base64.b64decode(CREDENTIALS_CONFIG)), scopes=SCOPES
        )

    if not creds and SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
        try:
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_PATH, scopes=SCOPES
            )
            logger.debug("Using service account authentication")
            logger.debug(
                "Working with Google Drive folder ID: %s", DRIVE_FOLDER_ID or "Not specified"
            )
        except Exception as e:
            logger.error("Error using service account authentication: %s", e)
            creds = None

    if not creds:
        logger.debug("Trying OAuth authentication flow")
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH) as token:
                creds = Credentials.from_authorized_user_info(json.load(token), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.debug("Attempting to refresh expired token...")
                    creds.refresh(Request())
                    logger.debug("Token refreshed successfully")
                    with open(TOKEN_PATH, "w") as token:
                        token.write(creds.to_json())
                except Exception as refresh_error:
                    logger.warning("Token refresh failed: %s", refresh_error)
                    logger.debug("Triggering reauthentication flow...")
                    creds = None

            if not creds:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                    creds = flow.run_local_server(port=0)
                    with open(TOKEN_PATH, "w") as token:
                        token.write(creds.to_json())
                    logger.debug("Successfully authenticated using OAuth flow")
                except Exception as e:
                    logger.error("Error with OAuth flow: %s", e)
                    creds = None

    if not creds:
        try:
            logger.debug("Attempting to use Application Default Credentials (ADC)")
            logger.debug(
                "ADC will check: GOOGLE_APPLICATION_CREDENTIALS, gcloud auth, and metadata service"
            )
            creds, project = google.auth.default(scopes=SCOPES)
            logger.debug("Successfully authenticated using ADC for project: %s", project)
        except Exception as e:
            logger.error("Error using Application Default Credentials: %s", e)
            raise Exception(
                "All authentication methods failed. Please configure credentials."
            ) from e

    # cache_discovery=False: file cache requires oauth2client<4.0; all auth paths here use google-auth
    sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)

    try:
        yield SpreadsheetContext(
            sheets_service=sheets_service,
            drive_service=drive_service,
            docs_service=docs_service,
            folder_id=DRIVE_FOLDER_ID if DRIVE_FOLDER_ID else None,
            cache=SheetStructureCache(),
        )
    finally:
        pass
