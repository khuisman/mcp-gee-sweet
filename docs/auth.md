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

All of steps 1–4 happen in the [Google Cloud console](https://console.cloud.google.com/), signed in with the Google account the server should act as.

1. **Create a project.** Go to **Menu → IAM & Admin → Create a Project**, enter a project name, and click **Create**. Make sure the new project is the one selected in the project picker at the top of the console before you go on.
2. **Turn on the APIs.** Go to **Menu → APIs & Services → Library**. Search for each API in [Required Google APIs](#required-google-apis) below, open it, and click **Enable**.
3. **Set up the consent screen.** Go to **Menu → Google Auth Platform → Branding** and click **Get started**.
   - **App Information:** enter an app name (it's shown on the consent page) and choose your email as the user support email. Click **Next**.
   - **Audience:** choose **External**. (If your account belongs to a Google Workspace organization and only people in it will use the server, **Internal** also works and skips the test-user step below.) Click **Next**.
   - **Contact Information:** enter your email. Click **Next**.
   - **Finish:** agree to the Google API Services User Data Policy, click **Continue**, then **Create**.
   - **Test users (External only):** go to **Audience**, click **Add users** under **Test users**, enter your own Google account's address, and click **Save**. While the app is in testing, only test users can sign in.
4. **Create the OAuth client.** Go to **Google Auth Platform → Clients** and click **Create Client**. Choose **Application type → Desktop app**, give it a name, and click **Create**. Click **Download JSON** in the dialog that confirms it was created, before you close it: Google shows the full client secret only then, and a file downloaded from the **Clients** list later doesn't work with the `auth` command. That file is your OAuth client file. If you closed the dialog without downloading it, open the client and add a new secret, or create a new client.
5. Set environment variables:
   - `CREDENTIALS_PATH` — path to the downloaded OAuth JSON (default: `credentials.json`)
   - `TOKEN_PATH` — where the refresh token is stored after login (default: `token.json`). Its folder must already exist. Use an absolute path: the default is relative to the working directory, and an MCP client may start the server somewhere other than your shell's directory.
6. Log in once from a terminal, with the same `CREDENTIALS_PATH`, `TOKEN_PATH` and `ENABLED_TOOLS` the server will use. Pick the command that matches how you run the server:

   ```bash
   uvx mcp-gee-sweet auth                      # PyPI install, stable
   uvx --prerelease=allow mcp-gee-sweet auth   # PyPI install, develop builds
   uv run mcp-gee-sweet auth                   # cloned repo, run from its folder
   ```

   Add `--no-browser` to any of them to print the consent URL instead of opening a browser. (`uvx` doesn't put an `mcp-gee-sweet` command on your `PATH`, so a bare `mcp-gee-sweet auth` works only after an install that does, such as `uv tool install mcp-gee-sweet`.)

   This opens the Google consent page, waits for you to finish, and writes the token to `TOKEN_PATH`, replacing any token already there. It requests the scopes the registered tools need, so `--include-tools` / `ENABLED_TOOLS` narrow it the same way they narrow the server.

   On the way, Google shows a "Google hasn't verified this app" warning, because the app is yours and in testing. Click **Advanced**, then **Go to** your app's name, to continue. If the consent page lists the access as checkboxes, tick all of them: `auth` fails if one the tools need is left unticked.

**A token from a testing app lasts 7 days.** Google expires the refresh token of an **External** app in testing after 7 days. After that, the next tool call offers the consent link again (see **Re-authorizing from the client** below), or you rerun the step 6 command. An **Internal** app's token doesn't expire this way.

**Without a usable token, a stdio server doesn't open a browser itself.** Under stdio, stdout is the protocol channel and the client gives up on a slow start, so the server can't show a consent prompt. It starts without Google access instead, and `server://auth-status` reports `auth_method: "none"` with an `oauth_not_authorized` limitation. In the waterfall, the server first tries a service account and ADC, and only starts without access if neither is available. If a service account or ADC was configured on purpose (`SERVICE_ACCOUNT_PATH` or `GOOGLE_APPLICATION_CREDENTIALS` set) but wasn't usable, the error says why. An expired token whose refresh Google rejects at startup (for example, a revoked refresh token) is handled the same way. If Google simply can't be reached at startup (say, the network isn't up yet), the server keeps the token and refreshes it on the first tool call.

**Re-authorizing from the client.** When a tool call finds no usable token, or Google rejects a token refresh mid-session, the call offers the Google consent page itself, without a restart:

- A client that supports MCP URL elicitation (Claude Code does) gets a prompt with the consent link. The server never opens a browser on its own: you choose to open the link.
- Any other client gets an error whose text carries the link.

Open the link, approve access, and retry the call. The server saves the token to `TOKEN_PATH` (mode `0600`) and the retried call uses it, on every connection. The link works for `OAUTH_CONSENT_TIMEOUT_SECONDS` (default 5 minutes). Calls that fail while it's open get the same link, along with how long it still works, and a call after it expires gets a new one. A call whose token is rejected partway through isn't re-run, since it may have already done part of its work: its error includes what the tool itself reported. This works over stdio and SSE alike. It applies to OAuth only: a service account or ADC connection reports a rejected refresh as an ordinary error.

`mcp-gee-sweet auth` still works as the alternative, for example when the client can't show the link. Run it with the same settings as the server, then retry the call. The server re-reads `TOKEN_PATH` on the next call, so no restart is needed.

Over SSE, the server still runs the browser consent itself when there's no usable token. The prompt goes to stderr, and the server waits at most `OAUTH_CONSENT_TIMEOUT_SECONDS` (default 5 minutes). The rest of the server keeps working during the wait. Connections that open during it wait for the same consent instead of starting another one, and stopping the server (SIGTERM, Ctrl+C) ends the wait. If consent is denied, fails, or isn't finished by then, the connections waiting on it start without Google access as described above. The server doesn't start that browser consent again for later connections, so an unattended server doesn't make each new connection wait out the timeout. Those connections still offer the consent link from their first tool call, as described above.

`mcp-gee-sweet auth` checks that the `TOKEN_PATH` directory exists and is writable before it opens the consent page, and saves the token readable by your user only (mode `0600`). The server rewrites it the same way when it refreshes.

**Re-authenticating after a scope change:** at startup the server checks that the saved token was authorized for every scope the registered tools need. It never opens a browser to fix a shortfall on its own. What happens depends on which scope is missing:

- **Only the Gmail scope is missing** (for example, a token from before the Gmail tools existed): the server starts normally and Sheets, Drive, Docs, Calendar and activity tools keep working. Every Gmail tool returns an error naming the missing scope and how to re-authorize, and `server://auth-status` lists the Gmail tools under a `gmail_not_authorized` limitation.
- **Any other scope is missing:** under stdio, startup stops with an error naming the missing scopes. Most tools can't work without them. (Under a stdio client this error goes to stderr, which the client usually doesn't show; the client just reports that the connection closed. Set `DEBUG_LEVEL` and `LOG_FILE` to capture it in a file.) Over SSE, the server keeps running and the connection starts without Google access: every tool returns that error, with the instructions to re-authorize. The same applies to any other authentication failure over SSE.

Either way, run the `auth` command (see step 6 above) and restart the server to re-authorize. A tool call doesn't offer the consent link for a missing scope.

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
