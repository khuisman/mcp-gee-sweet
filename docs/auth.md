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

**Limitation:** service accounts cannot create files in a user's personal Drive (no quota). Use OAuth or a Shared Drive when you need to create files. See `server://auth-status` to check your active auth method.

## Method B: OAuth 2.0 (personal use / local dev)

Authenticates as you — gives full access to your personal Drive. Requires a browser login on first run.

1. Configure an OAuth consent screen in GCP Console → APIs & Services → OAuth consent screen.
2. Create an OAuth Client ID credential (type: Desktop app) and download the JSON.
3. Set environment variables:
   - `CREDENTIALS_PATH` — path to the downloaded OAuth JSON (default: `credentials.json`)
   - `TOKEN_PATH` — where the refresh token is stored after login (default: `token.json`)

**Re-authenticating after a scope change:** if you've already authenticated and a new scope has been added (e.g. `drive.activity.readonly`), delete `token.json` and restart the server to trigger a fresh OAuth flow.

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
https://www.googleapis.com/auth/calendar

gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

On GCP, attach a service account to your compute resource — ADC picks it up automatically. The `GOOGLE_APPLICATION_CREDENTIALS` env var (Google's standard) also feeds into ADC.

## Required Google APIs

Enable these in GCP Console → APIs & Services → Library:

- Google Sheets API
- Google Drive API
- Google Drive Activity API (required for `list_file_activity`)
- Google Docs API
- Google Calendar API

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
