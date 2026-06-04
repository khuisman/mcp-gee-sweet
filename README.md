<div align="center">
  <!-- Main Title Link -->
  <b>mcp-gee-sweet</b>

  <!-- Description Paragraph -->
  <p align="center">
    <i>Your AI Assistant's Gateway to Google Workspace!</i>
  </p>

![GitHub License](https://img.shields.io/github/license/khuisman/mcp-gee-sweet)
</div>

> **⚠️ Not published to PyPI — source install only.**
> Do not attempt `pip install mcp-gee-sweet` or `uvx mcp-gee-sweet` — the package is not on PyPI and those commands will fail. Use **Docker** or **clone the repo** (see Quick Start below).
>
> This project is under active development and has only been tested on personal use cases. A [manual QA checklist](docs/qa-checklist.md) must be completed before any PyPI release. For a stable, production-ready version, use [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) instead.

---

## 🤔 What is this?

`mcp-gee-sweet` is a Python-based MCP server that acts as a bridge between any MCP-compatible client (like Claude Desktop) and the Google Workspace APIs (Sheets, Drive, Docs). It allows you to interact with your spreadsheets, documents, and Drive files using a defined set of tools, enabling powerful automation and data manipulation workflows driven by AI.

Forked from [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) and extended with caching, Google Docs support, Drive file listing, and observability.

---

## 🚀 Quick Start

`mcp-gee-sweet` is not yet published to PyPI — run it from source using Docker (recommended) or `uv`.

_Refer to the [ID Reference Guide](#-id-reference-guide) for more information about the IDs used below._

### Prerequisites

1.  **☁️ Google Cloud Setup** — configure credentials and enable the APIs first.
    *   ➡️ See [**Detailed Google Cloud Platform Setup**](#-google-cloud-platform-setup-detailed).

2.  **🔑 Credentials** — place your service account key at `service_account.json` in the repo root and set `DRIVE_FOLDER_ID` in your environment.
    *   ➡️ See [**Authentication & Environment Variables**](#-authentication--environment-variables-detailed) for all options.

### Option A: Docker (Recommended)

Requires [Docker](https://docs.docker.com/get-docker/) and `make`.

```bash
git clone https://github.com/khuisman/mcp-gee-sweet.git
cd mcp-gee-sweet

make build   # build the container image
make start   # start the server (SSE on port 47000)
make logs    # tail logs
make restart # restart after code changes (then restart your MCP client too)
make down    # stop and remove the container
```

<details>
<summary>No <code>make</code>? Use <code>docker compose</code> directly.</summary>

```bash
docker compose build
docker compose up -d
docker compose logs -f
docker compose restart mcp-gee-sweet
docker compose down
```
</details>

The server listens on `http://localhost:47000`. Point your MCP client at `http://localhost:47000/sse` using SSE transport.

### Option B: Run locally with `uv`

```bash
git clone https://github.com/khuisman/mcp-gee-sweet.git
cd mcp-gee-sweet

# Install uv if needed: https://docs.astral.sh/uv/getting-started/installation/
uv sync
make install-hooks   # wire up pre-commit (one-time, per clone)

export SERVICE_ACCOUNT_PATH="/path/to/service-account-key.json"
export DRIVE_FOLDER_ID="YOUR_DRIVE_FOLDER_ID"

uv run mcp-gee-sweet                    # stdio transport
uv run mcp-gee-sweet --transport sse    # SSE on port 8000

make test        # run unit tests
make lint        # run ruff linter and formatter
```

### Connect your MCP Client

*   ➡️ See [**Usage with Claude Desktop**](#-usage-with-claude-desktop) for config examples.

### Optional: Tool Filtering

*   By default, all 25 tools are enabled. To reduce context usage, enable only the tools you need.
*   ➡️ See [**Tool Filtering**](#-tool-filtering-reduce-context-usage) for details.

You're ready! Start issuing commands via your MCP client.

---

## ✨ Key Features

*   **Seamless Integration:** Connects directly to Google Drive, Google Sheets, and Google Docs APIs.
*   **Comprehensive Tools:** Offers a wide range of operations (CRUD, listing, batching, sharing, formatting, Docs read/write, etc.).
*   **Flexible Authentication:** Supports **Service Accounts (recommended)**, OAuth 2.0, and direct credential injection via environment variables.
*   **Easy Deployment:** Run via Docker (recommended) or clone for development using `uv`. Not yet on PyPI.
*   **AI-Ready:** Designed for use with MCP-compatible clients, enabling natural language spreadsheet and document interaction.
*   **Tool Filtering:** Reduce context window usage by enabling only the tools you need with `--include-tools` or `ENABLED_TOOLS` environment variable.
*   **Caching:** Sheet structure, sheet data, Drive folder listings, and Doc content are cached in a local SQLite database to reduce API calls and latency. Cache location and TTL are configurable via environment variables.

---

## 🎯 Tool Filtering (Reduce Context Usage)

**Problem:** By default, this MCP server exposes all 25 tools. If you only need a few tools, this wastes valuable context window space.

**Solution:** Use tool filtering to enable only the tools you actually use.

### How to Enable Tool Filtering

You can filter tools using either:

1. **Command-line argument** `--include-tools`:
   ```json
   {
     "mcpServers": {
       "mcp-gee-sweet-local": {
         "command": "uv",
         "args": [
           "run",
           "--directory",
           "/path/to/your/mcp-gee-sweet",
           "mcp-gee-sweet",
           "--include-tools",
           "get_sheet_data,update_cells,list_spreadsheets,list_sheets"
         ],
         "env": {
           "SERVICE_ACCOUNT_PATH": "/path/to/service-account-key.json"
         }
       }
     }
   }
   ```

2. **Environment variable** `ENABLED_TOOLS`:
   ```json
   {
     "mcpServers": {
       "mcp-gee-sweet-local": {
         "command": "uv",
         "args": [
           "run",
           "--directory",
           "/path/to/your/mcp-gee-sweet",
           "mcp-gee-sweet"
         ],
         "env": {
           "SERVICE_ACCOUNT_PATH": "/path/to/service-account-key.json",
           "ENABLED_TOOLS": "get_sheet_data,update_cells,list_spreadsheets,list_sheets"
         }
       }
     }
   }
   ```

### Available Tool Names

When filtering, use these exact tool names (comma-separated, no spaces):

**Most Common Tools (recommended subset):**
- `get_sheet_data` - Read from spreadsheets
- `update_cells` - Write to spreadsheets
- `list_spreadsheets` - Find spreadsheets
- `list_sheets` - Navigate tabs

**All Available Tools:**
- `add_chart`
- `add_columns`
- `add_rows`
- `batch_update`
- `batch_update_cells`
- `copy_sheet`
- `create_doc`
- `create_sheet`
- `create_spreadsheet`
- `find_in_spreadsheet`
- `get_doc_content`
- `get_multiple_sheet_data`
- `get_multiple_spreadsheet_summary`
- `get_sheet_data`
- `get_sheet_formulas`
- `list_files`
- `list_folders`
- `list_sheets`
- `list_spreadsheets`
- `refresh_cache`
- `rename_sheet`
- `search_spreadsheets`
- `share_spreadsheet`
- `update_cells`
- `write_doc_content`

**Note:** If neither `--include-tools` nor `ENABLED_TOOLS` is specified, all tools are enabled (default behavior).

---

## 🛠️ Available Tools & Resources

This server exposes the following tools for interacting with Google Workspace:

_Refer to the [ID Reference Guide](#-id-reference-guide) for more information about the IDs used below._

*(Input parameters are typically strings unless otherwise specified)*

*   **`list_spreadsheets`**: Lists spreadsheets in the configured Drive folder (Service Account) or accessible by the user (OAuth).
    *   `folder_id` (optional string): Google Drive folder ID to search in. Get from its URL. If omitted, uses the configured default folder or searches 'My Drive'.
    *   _Returns:_ List of objects `[{id: string, title: string}]`
*   **`create_spreadsheet`**: Creates a new spreadsheet.
    *   `title` (string): The desired title for the spreadsheet. Example: "Quarterly Report Q4".
    *   `folder_id` (optional string): Google Drive folder ID where the spreadsheet should be created. Get from its URL. If omitted, uses configured default or root.
    *   _Returns:_ Object with spreadsheet info, including `spreadsheetId`, `title`, and `folder`.
    *   **⚠️ Service account limitation:** Cannot create files in personal Drive (no storage quota). Use OAuth/ADC auth or a Shared Drive destination. Check the `server://auth-status` resource for your current auth method.
*   **`get_sheet_data`**: Reads data from a range in a sheet/tab.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Name of the sheet/tab (e.g., "Sheet1").
    *   `range` (optional string): A1 notation (e.g., `'A1:C10'`, `'Sheet1!B2:D'`). If omitted, reads the whole sheet/tab specified by `sheet`.
    *   `include_grid_data` (optional boolean, default `False`): If `True`, returns full grid data including formatting and metadata (much larger). If `False`, returns values only (more efficient).
    *   _Returns:_ If `include_grid_data=True`, full grid data with metadata ([`get` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get#response-body)). If `False`, a values result object from the Values API ([`values.get` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get#response-body)).
*   **`get_sheet_formulas`**: Reads formulas from a range in a sheet/tab.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Name of the sheet/tab (e.g., "Sheet1").
    *   `range` (optional string): A1 notation (e.g., `'A1:C10'`, `'Sheet1!B2:D'`). If omitted, reads all formulas in the sheet/tab specified by `sheet`.
    *   _Returns:_ 2D array of cell formulas (array of arrays) ([`values.get` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get#response-body)).
*   **`update_cells`**: Writes data to a specific range. Overwrites existing data.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Name of the sheet/tab (e.g., "Sheet1").
    *   `range` (string): A1 notation range to write to (e.g., 'A1:C3').
    *   `data` (array of arrays): 2D array of values to write. Example: `[[1, 2, 3], ["a", "b", "c"]]`.
    *   _Returns:_ Update result object ([`values.update` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update#response-body)).
*   **`batch_update_cells`**: Updates multiple ranges in one API call.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Name of the sheet/tab (e.g., "Sheet1").
    *   `ranges` (object): Dictionary mapping range strings (A1 notation) to 2D arrays of values. Example: `{ "A1:B2": [[1, 2], [3, 4]], "D5": [["Hello"]] }`.
    *   _Returns:_ Result of the operation ([`values.batchUpdate` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchUpdate#response-body)).
*   **`add_rows`**: Adds (inserts) empty rows to a sheet/tab at a specified index.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Name of the sheet/tab (e.g., "Sheet1").
    *   `count` (integer): Number of empty rows to insert.
    *   `start_row` (optional integer, default `0`): 0-based row index to start inserting rows. If omitted, defaults to `0` (inserts at the beginning).
    *   _Returns:_ Result of the operation ([`batchUpdate` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate#response-body)).
*   **`list_sheets`**: Lists all sheet/tab names within a spreadsheet.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   _Returns:_ List of sheet/tab name strings. Example: `["Sheet1", "Sheet2"]`.
*   **`create_sheet`**: Adds a new sheet/tab to a spreadsheet.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `title` (string): Name for the new sheet/tab.
    *   _Returns:_ New sheet properties object.
*   **`get_multiple_sheet_data`**: Fetches data from multiple ranges across potentially different spreadsheets in one call.
    *   `queries` (array of objects): Each object needs `spreadsheet_id`, `sheet`, and `range`. Example: `[{"spreadsheet_id": "abc", "sheet": "Sheet1", "range": "A1:B2"}, ...]`.
    *   _Returns:_ List of objects, each containing the query params and fetched `data` or an `error`. Each `data` is a [`values.get` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get#response-body).
*   **`get_multiple_spreadsheet_summary`**: Gets titles, sheet/tab names, headers, and first few rows for multiple spreadsheets.
    *   `spreadsheet_ids` (array of strings): IDs of the spreadsheets (from their URLs).
    *   `rows_to_fetch` (optional integer, default `5`): How many rows (including header) to preview. Example: `5`.
    *   _Returns:_ List of summary objects for each spreadsheet.
*   **`share_spreadsheet`**: Shares a spreadsheet with specified users/emails and roles.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `recipients` (array of objects): `[{"email_address": "user@example.com", "role": "writer"}, ...]`. Roles: `reader`, `commenter`, `writer`.
    *   `send_notification` (optional boolean, default `True`): Send email notifications to recipients.
    *   _Returns:_ Dictionary with `successes` and `failures` lists.
*   **`add_columns`**: Adds (inserts) empty columns to a sheet/tab at a specified index.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Name of the sheet/tab (e.g., "Sheet1").
    *   `count` (integer): Number of empty columns to insert.
    *   `start_column` (optional integer, default `0`): 0-based column index to start inserting. If omitted, defaults to `0` (inserts at the beginning).
    *   _Returns:_ Result of the operation ([`batchUpdate` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate#response-body)).
*   **`copy_sheet`**: Duplicates a sheet/tab from one spreadsheet to another and optionally renames it.
    *   `src_spreadsheet` (string): Source spreadsheet ID (from its URL).
    *   `src_sheet` (string): Source sheet/tab name (e.g., "Sheet1").
    *   `dst_spreadsheet` (string): Destination spreadsheet ID (from its URL).
    *   `dst_sheet` (string): Desired sheet/tab name in the destination spreadsheet.
    *   _Returns:_ Result of the copy and optional rename operations.
*   **`rename_sheet`**: Renames an existing sheet/tab.
    *   `spreadsheet` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Current sheet/tab name (e.g., "Sheet1").
    *   `new_name` (string): New sheet/tab name (e.g., "Transactions").
    *   _Returns:_ Result of the operation ([`batchUpdate` response](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate#response-body)).
*   **`find_in_spreadsheet`**: Searches for a value across all cells in a spreadsheet.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `query` (string): The value to search for.
    *   _Returns:_ List of matching cell locations and values.
*   **`search_spreadsheets`**: Searches for spreadsheets by name in Google Drive.
    *   `query` (string): Name or partial name to search for.
    *   `folder_id` (optional string): Limit search to this Drive folder.
    *   _Returns:_ List of matching spreadsheet objects `[{id: string, title: string}]`.
*   **`list_folders`**: Lists Google Drive folders accessible to the service account.
    *   `parent_id` (optional string): Parent folder ID to list subfolders of. If omitted, lists top-level folders.
    *   _Returns:_ List of folder objects `[{id: string, name: string}]`.
*   **`list_files`**: Lists files in a Google Drive folder.
    *   `folder_id` (optional string): Folder ID to list files in. If omitted, uses the configured default folder.
    *   _Returns:_ List of file objects with id, name, and mimeType.
*   **`create_doc`**: Creates a new Google Doc.
    *   `title` (string): Title for the new document.
    *   `content` (optional string): Initial HTML or plain text content.
    *   `folder_id` (optional string): Drive folder to create the document in.
    *   _Returns:_ Object with document info including `documentId` and `title`.
    *   **⚠️ Service account limitation:** Cannot create files in personal Drive (no storage quota). Use OAuth/ADC auth or a Shared Drive destination. Workaround: create the file manually in Drive, then use `write_doc_content` to populate it. Check the `server://auth-status` resource for your current auth method.
*   **`get_doc_content`**: Reads the content of a Google Doc.
    *   `file_id` (string): The document ID (from its URL).
    *   _Returns:_ Document content as structured text.
*   **`write_doc_content`**: Writes or replaces the content of a Google Doc.
    *   `file_id` (string): The document ID (from its URL).
    *   `content` (string): New HTML or plain text content to write.
    *   _Returns:_ Result of the operation.
*   **`add_chart`**: Creates a chart in a Google Spreadsheet from specified data.
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `sheet` (string): Name of the sheet/tab containing the data (e.g., "Sheet1").
    *   `chart_type` (string): Type of chart to create. Options: `COLUMN` (vertical bars), `BAR` (horizontal bars), `LINE`, `AREA`, `PIE`, `SCATTER`, `COMBO`, `HISTOGRAM`.
    *   `data_range` (string): A1 notation range for the chart data (e.g., "A1:C10"). First row is treated as headers.
    *   `title` (optional string): Chart title.
    *   `x_axis_label` (optional string): Label for the X axis (bottom axis). Not applicable for pie charts.
    *   `y_axis_label` (optional string): Label for the Y axis (left axis). Not applicable for pie charts.
    *   `position_x` (optional integer, default `0`): Horizontal position offset in pixels from the top-left corner.
    *   `position_y` (optional integer, default `0`): Vertical position offset in pixels from the top-left corner.
    *   `width` (optional integer, default `600`): Width of the chart in pixels.
    *   `height` (optional integer, default `400`): Height of the chart in pixels.
    *   _Returns:_ Result object with success status, chart ID, and operation details.
*   **`batch_update`**: Passthrough to the Sheets `spreadsheets().batchUpdate()` endpoint. Accepts raw request objects for operations not covered by named tools (formatting, conditional formatting, dimension properties, etc.).
    *   `spreadsheet_id` (string): The spreadsheet ID (from its URL).
    *   `requests` (array of objects): Raw batchUpdate request objects per the [Sheets API spec](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate).
    *   _Returns:_ Raw batchUpdate response.
*   **`refresh_cache`**: Invalidates cached data, forcing fresh API calls on next use.
    *   `spreadsheet_id` (optional string): Invalidate cache for a specific spreadsheet only. If omitted, flushes all caches.
    *   `doc_id` (optional string): Invalidate doc content cache for a specific document only.
    *   _Returns:_ Confirmation of what was cleared.

**MCP Resources:**

*   **`spreadsheet://{spreadsheet_id}/info`**: Get basic metadata about a Google Spreadsheet.
    *   _Returns:_ JSON string with spreadsheet information.

---

## ☁️ Google Cloud Platform Setup (Detailed)

This setup is **required** before running the server.

1.  **Create/Select a GCP Project:** Go to the [Google Cloud Console](https://console.cloud.google.com/).
2.  **Enable APIs:** Navigate to "APIs & Services" -> "Library". Search for and enable:
    *   `Google Sheets API`
    *   `Google Drive API`
    *   `Google Docs API`
    *   `Google Calendar API` _(required for calendar tools)_
3.  **Configure Credentials:** You need to choose *one* authentication method below (Service Account is recommended).

---

## 🔑 Authentication & Environment Variables (Detailed)

The server needs credentials to access Google APIs. Choose one method:

_Refer to the [ID Reference Guide](#-id-reference-guide) for more information about the IDs used below._

### Method A: Service Account (Recommended for Servers/Automation) ✅

*   **Why?** Headless (no browser needed), secure, ideal for server environments. Doesn't expire easily.
*   **Steps:**
    1.  **Create Service Account:** In GCP Console -> "IAM & Admin" -> "Service Accounts".
        *   Click "+ CREATE SERVICE ACCOUNT". Name it (e.g., `mcp-sheets-service`).
        *   Grant Roles: Add `Editor` role for broad access, or more granular roles (like `roles/drive.file` and specific Sheets roles) for stricter permissions.
        *   Click "Done". Find the account, click Actions (⋮) -> "Manage keys".
        *   Click "ADD KEY" -> "Create new key" -> **JSON** -> "CREATE".
        *   **Download and securely store** the JSON key file.
    2.  **Create & Share Google Drive Folder:**
        *   In [Google Drive](https://drive.google.com/), create a folder (e.g., "AI Managed Sheets").
        *   Note the **Folder ID** from the URL: `https://drive.google.com/drive/folders/THIS_IS_THE_FOLDER_ID`.
        *   Right-click the folder -> "Share" -> "Share".
        *   Enter the Service Account's email (from the JSON file `client_email`).
        *   Grant **Editor** access. Uncheck "Notify people". Click "Share".
    3.  **Set Environment Variables:**
        *   `SERVICE_ACCOUNT_PATH`: Full path to the downloaded JSON key file.
        *   `DRIVE_FOLDER_ID`: The ID of the shared Google Drive folder.
        *(See [Quick Start](#-quick-start) for OS-specific examples)*

### Method B: OAuth 2.0 (Interactive / Personal Use) 🧑‍💻

*   **Why?** For personal use or local development where interactive browser login is okay.
*   **Steps:**
    1.  **Configure OAuth Consent Screen:** In GCP Console -> "APIs & Services" -> "OAuth consent screen". Select "External", fill required info, add scopes (`.../auth/spreadsheets`, `.../auth/drive`, `.../auth/documents`, `.../auth/calendar`), add test users if needed.
    2.  **Create OAuth Client ID:** In GCP Console -> "APIs & Services" -> "Credentials". "+ CREATE CREDENTIALS" -> "OAuth client ID" -> Type: **Desktop app**. Name it. "CREATE". **Download JSON**.
    3.  **Set Environment Variables:**
        *   `CREDENTIALS_PATH`: Path to the downloaded OAuth credentials JSON file (default: `credentials.json`).
        *   `TOKEN_PATH`: Path to store the user's refresh token after first login (default: `token.json`). Must be writable.

### Method C: Direct Credential Injection (Advanced) 🔒

*   **Why?** Useful in environments like Docker, Kubernetes, or CI/CD where managing files is hard, but environment variables are easy/secure. Avoids file system access.
*   **How?** Instead of providing a *path* to the credentials file, you provide the *content* of the file, encoded in Base64, directly in an environment variable.
*   **Steps:**
    1.  **Get your credentials JSON file** (either Service Account key or OAuth Client ID file). Let's call it `your_credentials.json`.
    2.  **Generate the Base64 string:**
        *   **(Linux/macOS):** `base64 -w 0 your_credentials.json`
        *   **(Windows PowerShell):**
            ```powershell
            $filePath = "C:\path\to\your_credentials.json"; # Use actual path
            $bytes = [System.IO.File]::ReadAllBytes($filePath);
            $base64 = [System.Convert]::ToBase64String($bytes);
            $base64 # Copy this output
            ```
        *   **(Caution):** Avoid pasting sensitive credentials into untrusted online encoders.
    3.  **Set the Environment Variable:**
        *   `CREDENTIALS_CONFIG`: Set this variable to the **full Base64 string** you just generated.
            ```bash
            # Example (Linux/macOS) - Use the actual string generated
            export CREDENTIALS_CONFIG="ewogICJ0eXBlIjogInNlcnZpY2VfYWNjb..."
            ```

### Method D: Application Default Credentials (ADC) 🌐

*   **Why?** Ideal for Google Cloud environments (GKE, Compute Engine, Cloud Run) and local development with `gcloud auth application-default login`. No explicit credential files needed.
*   **How?** Uses Google's Application Default Credentials chain to automatically discover credentials from multiple sources.
*   **ADC Search Order:**
    1.  `GOOGLE_APPLICATION_CREDENTIALS` environment variable (path to service account key) - **Google's standard variable**
    2.  `gcloud auth application-default login` credentials (local development)
    3.  Attached service account from metadata server (GKE, Compute Engine, etc.)
*   **Setup:**
    *   **Local Development:** 
        1. Run `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/calendar` once
        2. Set a quota project: `gcloud auth application-default set-quota-project <project_id>` (replace `<project_id>` with your Google Cloud project ID)
    *   **Google Cloud:** Attach a service account to your compute resource
    *   **Environment Variable:** Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json` (Google's standard)
*   **No additional environment variables needed** - ADC is used automatically as a fallback when other methods fail.

**Note:** `GOOGLE_APPLICATION_CREDENTIALS` is Google's official standard environment variable, while `SERVICE_ACCOUNT_PATH` is specific to this MCP server. If you set `GOOGLE_APPLICATION_CREDENTIALS`, ADC will find it automatically.

### Authentication Priority & Summary

The server checks for credentials in this order:

1.  `CREDENTIALS_CONFIG` (Base64 content)
2.  `SERVICE_ACCOUNT_PATH` (Path to Service Account JSON)
3.  `CREDENTIALS_PATH` (Path to OAuth JSON) - triggers interactive flow if token is missing/expired
4.  **Application Default Credentials (ADC)** - automatic fallback

**Environment Variable Summary:**

| Variable                         | Method(s)                   | Description                                                      | Default            |
|:---------------------------------|:----------------------------|:-----------------------------------------------------------------|:-------------------|
| `SERVICE_ACCOUNT_PATH`           | Service Account             | Path to the Service Account JSON key file (MCP server specific). | -                  |
| `GOOGLE_APPLICATION_CREDENTIALS` | ADC                         | Path to service account key (Google's standard variable).        | -                  |
| `DRIVE_FOLDER_ID`                | Service Account             | ID of the Google Drive folder shared with the Service Account.   | -                  |
| `CREDENTIALS_PATH`               | OAuth 2.0                   | Path to the OAuth 2.0 Client ID JSON file.                       | `credentials.json` |
| `TOKEN_PATH`                     | OAuth 2.0                   | Path to store the generated OAuth token.                         | `token.json`       |
| `CREDENTIALS_CONFIG`             | Service Account / OAuth 2.0 | Base64 encoded JSON string of credentials content.               | -                  |
| `CACHE_DB_PATH`                  | Cache                       | Path to the SQLite cache database.                               | `/tmp/mcp_gee_sweet.db` |
| `CACHE_TTL`                      | Cache                       | Cache time-to-live in seconds.                                   | `1800` (30 min)    |

---

## ⚙️ Running the Server (Detailed)

_Refer to the [ID Reference Guide](#-id-reference-guide) for more information about the IDs used below._

### Method 1: For Development (Cloning the Repo)

If you want to modify the code:

1.  **Clone:** `git clone https://github.com/khuisman/mcp-gee-sweet.git && cd mcp-gee-sweet`
2.  **Set Environment Variables:** As described above.
3.  **Run using `uv`:** (Uses the local code)
    ```bash
    uv run mcp-gee-sweet
    # Or with SSE transport:
    uv run mcp-gee-sweet --transport sse
    ```

### Method 2: Docker (SSE transport)

Run the server in a container using the included `Dockerfile`:

```bash
# Build the image
docker build -t mcp-gee-sweet .

# Run (SSE on port 8000)
# NOTE: Prefer CREDENTIALS_CONFIG (Base64 credentials content) in containers.
docker run --rm -p 8000:8000 \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -e CREDENTIALS_CONFIG=YOUR_BASE64_CREDENTIALS \
  -e DRIVE_FOLDER_ID=YOUR_DRIVE_FOLDER_ID \
  mcp-gee-sweet
```

- Use `CREDENTIALS_CONFIG` instead of `SERVICE_ACCOUNT_PATH` inside Docker to avoid mounting secrets as files.
- The container starts with `--transport sse` and listens on `HOST`/`PORT`. Point your MCP client to `http://localhost:8000` using SSE transport.

---

## 🔌 Usage with Claude Desktop

Add the server config to `claude_desktop_config.json` under `mcpServers`. Choose the block matching your setup:

_Refer to the [ID Reference Guide](#-id-reference-guide) for more information about the IDs used below._

**Note:** `mcp-gee-sweet` is not published to PyPI. The only supported install methods are cloning the repo (stdio transport) or running Docker (SSE transport).

<details>
<summary>🟡 Config: stdio — cloned repo + Service Account</summary>

```json
{
  "mcpServers": {
    "mcp-gee-sweet-local": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/your/mcp-gee-sweet",
        "mcp-gee-sweet"
      ],
      "env": {
        "SERVICE_ACCOUNT_PATH": "/path/to/your/mcp-gee-sweet/service_account.json",
        "DRIVE_FOLDER_ID": "your_drive_folder_id_here"
      }
    }
  }
}
```
*Adjust `/path/to/your/mcp-gee-sweet` and credential paths to match your actual workspace location. Other auth methods (OAuth, `CREDENTIALS_CONFIG`, ADC) work by swapping the env vars — see [Authentication & Environment Variables](#-authentication--environment-variables-detailed).*
</details>

<details>
<summary>🔵 Config: SSE — Docker container</summary>

Start the server first with `make start` (see Quick Start), then point Claude Desktop at the SSE endpoint:

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "transport": "sse",
      "url": "http://localhost:47000/sse"
    }
  }
}
```
*The Docker container must be running before starting Claude Desktop.*
</details>

---

## 💬 Example Prompts for Claude

Once connected, try prompts like:

*   "List all spreadsheets I have access to." (or "in my AI Managed Sheets folder")
*   "Create a new spreadsheet titled 'Quarterly Sales Report Q3 2024'."
*   "In the 'Quarterly Sales Report' spreadsheet, get the data from Sheet1 range A1 to E10."
*   "Add a new sheet named 'Summary' to the spreadsheet with ID `1aBcDeFgHiJkLmNoPqRsTuVwXyZ`."
*   "In my 'Project Tasks' spreadsheet, Sheet 'Tasks', update cell B2 to 'In Progress'."
*   "Append these rows to the 'Log' sheet in spreadsheet `XYZ`: `[['2024-07-31', 'Task A Completed'], ['2024-08-01', 'Task B Started']]`"
*   "Get a summary of the spreadsheets 'Sales Data' and 'Inventory Count'."
*   "Share the 'Team Vacation Schedule' spreadsheet with `team@example.com` as a reader and `manager@example.com` as a writer. Don't send notifications."
*   "Create a column chart in my 'Sales Report' spreadsheet showing monthly revenue from data in range A1:B13."
*   "Add a pie chart to the 'Market Analysis' sheet with data from A1:B5 titled 'Market Share by Product'."
*   "In spreadsheet `abc123`, create a line chart on Sheet1 from range A1:C10 with title 'Growth Trends' and labels 'Month' and 'Revenue'."
*   "Read the contents of the doc with ID `xyz789`."
*   "List all files in my Drive folder."
*   "Search for spreadsheets with 'Budget' in the name."

---

## 🆔 ID Reference Guide

Use the following reference guide to find the various IDs referenced throughout the docs:

```
Google Cloud Project ID:
  https://console.cloud.google.com/apis/dashboard?project=sheets-mcp-server-123456
                                                          └───── Project ID ─────┘

Google Drive Folder ID:
  https://drive.google.com/drive/u/0/folders/1xcRQCU9xrNVBPTeNzHqx4hrG7yR91WIa
                                             └────────── Folder ID ──────────┘

Google Sheets Spreadsheet ID:
  https://docs.google.com/spreadsheets/d/25_-_raTaKjaVxu9nJzA7-FCrNhnkd3cXC54BPAOXemI/edit
                                         └───────────── Spreadsheet ID ─────────────┘

Google Docs Document ID:
  https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
                                     └─────────────── Document ID ──────────────┘
```

---

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for first-time setup, QA workflows, and PR guidelines.

Before this project is published to PyPI, all items in [`docs/qa-checklist.md`](docs/qa-checklist.md) must be manually verified against a live Google account. If you're contributing new tools or fixing bugs, please add corresponding test cases and mark the relevant checklist items.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Credits

*   Forked from [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets).
*   Built with [FastMCP](https://github.com/cognitiveapis/fastmcp).
*   Inspired by [kazz187/mcp-google-spreadsheet](https://github.com/kazz187/mcp-google-spreadsheet).
*   Uses Google API Python Client libraries.
