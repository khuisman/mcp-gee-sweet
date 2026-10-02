# Authentication

The server tries auth methods in a waterfall by default. Set `AUTH_METHOD` to pin a specific method with no fallback.

## Auth waterfall (default)

1. OAuth (`CREDENTIALS_PATH` / `TOKEN_PATH`)
2. Service account (`CREDENTIALS_CONFIG` or `SERVICE_ACCOUNT_PATH`)
3. Application Default Credentials (ADC)

OAuth is tried first because it authenticates as a user and has full personal Drive access. Service account is the headless fallback. ADC covers GCP-hosted deployments.

## Pinning a method

```bash
AUTH_METHOD=oauth            # OAuth only — fails fast if credentials are missing
AUTH_METHOD=service_account  # Service account only
AUTH_METHOD=adc              # ADC only
```

## Method A: Service account (recommended for servers)

Best for headless or automated environments. Credentials don't expire.

1. Create a service account in GCP Console → IAM & Admin → Service Accounts.
2. Download the JSON key file.
3. Share a Google Drive folder with the service account's `client_email` (Editor access).
4. Set environment variables:
   - `SERVICE_ACCOUNT_PATH` — path to the JSON key file
   - `DRIVE_FOLDER_ID` — ID of the shared Drive folder

**Limitation:** service accounts cannot create files in a user's personal Drive (no quota). Use OAuth or a Shared Drive when you need to create files. Service accounts also have no personal Drive identity, so `transfer_ownership` always fails — that one requires OAuth, with no Shared Drive workaround. **Gmail tools require OAuth** — service-account / domain-wide delegation is not wired yet. See `server://auth-status` to check your active auth method and affected tools (Gmail's are listed under the `no_user_mailbox` category).

## Method B: OAuth 2.0 (personal use / local dev)

Authenticates as you — gives full access to your personal Drive. Requires a one-time browser login.

1. Configure an OAuth consent screen in GCP Console → APIs & Services → OAuth consent screen.
2. Create an OAuth Client ID credential (type: Desktop app) and download the JSON.
3. Set environment variables:
   - `CREDENTIALS_PATH` — path to the downloaded OAuth JSON (default: `credentials.json`)
   - `TOKEN_PATH` — where the refresh token is stored after login (default: `token.json`). Use an absolute path: the default is relative to the working directory, and an MCP client may start the server somewhere other than your shell's directory.
4. Log in once from a terminal, with the same `CREDENTIALS_PATH`, `TOKEN_PATH` and `ENABLED_TOOLS` the server will use:

   ```bash
   mcp-gee-sweet auth              # cloned repo: uv run mcp-gee-sweet auth
   uvx mcp-gee-sweet auth          # PyPI install
   mcp-gee-sweet auth --no-browser # print the URL instead of opening a browser
   ```

   This opens the Google consent page, waits for you to finish, and writes the token to `TOKEN_PATH`, replacing any token already there. It requests the scopes the registered tools need, so `--include-tools` / `ENABLED_TOOLS` narrow it the same way they narrow the server.

**Without a usable token, a stdio server doesn't open a browser itself.** Under stdio, stdout is the protocol channel and the client gives up on a slow start, so the server can't show a consent prompt. It starts without Google access instead: every tool returns an error with the `mcp-gee-sweet auth` instructions, and `server://auth-status` reports `auth_method: "none"` with an `oauth_not_authorized` limitation. In the waterfall, the server first tries a service account and ADC, and only starts without access if neither is available. If a service account or ADC was configured on purpose (`SERVICE_ACCOUNT_PATH` or `GOOGLE_APPLICATION_CREDENTIALS` set) but wasn't usable, the error says why. Run `mcp-gee-sweet auth`, then restart the server. An expired token whose refresh Google rejects (for example, a revoked refresh token) is handled the same way. If Google simply can't be reached at startup (say, the network isn't up yet), the server keeps the token and refreshes it on the first tool call.

Over SSE, the server still runs the browser consent itself when there's no usable token. The prompt goes to stderr, and the server waits at most `OAUTH_CONSENT_TIMEOUT_SECONDS` (default 5 minutes). The rest of the server keeps working during the wait. Connections that open during it wait for the same consent instead of starting another one, and stopping the server (SIGTERM, Ctrl+C) ends the wait. If consent is denied, fails, or isn't finished by then, the connections waiting on it start without Google access as described above. The server doesn't try the browser consent again for later connections, so an unattended server doesn't make each new connection wait out the timeout. Each new connection re-reads `TOKEN_PATH` instead, so after `mcp-gee-sweet auth` a reconnect is enough.

`mcp-gee-sweet auth` checks that the `TOKEN_PATH` directory exists and is writable before it opens the consent page, and saves the token readable by your user only (mode `0600`). The server rewrites it the same way when it refreshes.

**Re-authenticating after a scope change:** at startup the server checks that the saved token was authorized for every scope the registered tools need. It never opens a browser to fix a shortfall on its own. What happens depends on which scope is missing:

- **Only the Gmail scope is missing** (for example, a token from before the Gmail tools existed): the server starts normally and Sheets, Drive, Docs, Calendar and activity tools keep working. Every Gmail tool returns an error naming the missing scope and how to re-authorize, and `server://auth-status` lists the Gmail tools under a `gmail_not_authorized` limitation.
- **Any other scope is missing:** under stdio, startup stops with an error naming the missing scopes. Most tools can't work without them. (Under a stdio client this error goes to stderr, which the client usually doesn't show; the client just reports that the connection closed. Set `DEBUG_LEVEL` and `LOG_FILE` to capture it in a file.) Over SSE, the server keeps running and the connection starts without Google access: every tool returns that error, with the instructions to re-authorize. The same applies to any other authentication failure over SSE.

Either way, run `mcp-gee-sweet auth` (see step 4 above) and restart the server to re-authorize.

**Gmail scope is only requested when a Gmail tool is registered.** With no `ENABLED_TOOLS` filter every tool is registered, so the server asks for `gmail.modify` (read, compose, send, label, trash). If you don't want to grant mailbox access, leave the Gmail tools out of `ENABLED_TOOLS` / `--include-tools`. The server then neither requests nor requires the Gmail scope, and an existing pre-Gmail token keeps working.

## Method C: Base64 credential injection

Useful in Docker/Kubernetes where file mounts are inconvenient. Encode your service account or OAuth JSON as Base64 and pass it via environment variable.

```bash
# macOS / Linux
base64 -i service_account.json | tr -d '\n'
```

Set the output as `CREDENTIALS_CONFIG`. The server detects the credential type automatically.

## Method D: Application Default Credentials

For GCP-hosted environments (GKE, Cloud Run, Compute Engine) or local dev with `gcloud`.

```bash
# Local development
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/spreadsheets,\
https://www.googleapis.com/auth/drive,\
https://www.googleapis.com/auth/drive.activity.readonly,\
https://www.googleapis.com/auth/documents,\
https://www.googleapis.com/auth/calendar,\
https://www.googleapis.com/auth/gmail.modify

gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

On GCP, attach a service account to your compute resource — ADC picks it up automatically. The `GOOGLE_APPLICATION_CREDENTIALS` env var (Google's standard) also feeds into ADC.

**ADC can resolve to either a real user or a service identity**, and the two have different limitations: a real user credential (`gcloud auth application-default login`, or Workforce Identity Federation) has full personal Drive access, while a service identity — a GCE/Cloud Run/GKE attached metadata identity, `GOOGLE_APPLICATION_CREDENTIALS` pointed at a service account key, Workload Identity Federation, an impersonated service account, or a GDCH service account — has the same restrictions as Method A above. `server://auth-status` reports which one is actually active — `auth_method` stays `"adc"` either way, but `is_service_account_identity` distinguishes them.

## Required Google APIs

Enable these in GCP Console → APIs & Services → Library:

- Google Sheets API
- Google Drive API
- Google Drive Activity API (required for `list_file_activity`)
- Google Docs API
- Google Calendar API
- Gmail API

## Environment variable summary

Auth-specific variables only — see [Configuration](configuration.md#environment-variables) for the full list including cache, tool filtering, and transport settings.

| Variable | Auth method | Description | Default |
|---|---|---|---|
| `AUTH_METHOD` | all | Pin to one method: `oauth`, `service_account`, `adc` | waterfall |
| `SERVICE_ACCOUNT_PATH` | service account | Path to service account JSON key | — |
| `GOOGLE_APPLICATION_CREDENTIALS` | ADC | Path to service account key (Google standard) | — |
| `DRIVE_FOLDER_ID` | service account | Drive folder shared with the service account | — |
| `CREDENTIALS_PATH` | OAuth | Path to OAuth client ID JSON | `credentials.json` |
| `TOKEN_PATH` | OAuth | Path to store the OAuth refresh token | `token.json` |
| `CREDENTIALS_CONFIG` | service account / OAuth | Base64-encoded credentials JSON | — |
