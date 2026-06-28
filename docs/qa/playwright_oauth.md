# Playwright OAuth Automation

How to acquire or refresh an OAuth token for QA runs without manually clicking through Google's consent screen.

---

## When you need this

- Fresh environment with no `token.json`
- `token.json` expired and cannot be refreshed (e.g. revoked, scopes changed)
- Running `⚠️ requires-oauth` test cases in an automated QA session

If `token.json` already exists and is valid, you don't need any of this — the server refreshes the access token automatically.

---

## Approach A — Playwright-assisted browser flow

Use `oauth_setup.py` to start the consent flow without auto-launching a browser, then let the Playwright MCP complete it.

### Prerequisites

Add to `src/mcp_gee_sweet/.env`:

```
GOOGLE_TEST_EMAIL=your-test-account@gmail.com
GOOGLE_TEST_PASSWORD=your-test-account-password
```

> **Security note:** these are used only by the Playwright step below and are never sent to the MCP server. Keep them in `.env` (gitignored).

### Step 1 — Start the OAuth server

In a terminal:

```bash
uv run python scripts/oauth_setup.py
```

The script prints an `OAUTH_URL: https://accounts.google.com/o/oauth2/auth?...` line and waits for the callback.

### Step 2 — Conductor prompt (Playwright MCP)

Paste this into a Claude Code session that has the Playwright MCP connected:

```
I need to complete a Google OAuth consent flow. Do the following:

1. Read GOOGLE_TEST_EMAIL and GOOGLE_TEST_PASSWORD from src/mcp_gee_sweet/.env
2. Navigate to the OAUTH_URL printed by the oauth_setup.py script (running in a terminal)
3. On the Google sign-in page, enter the email address and click Next
4. Enter the password and click Next
5. On the consent screen, click "Allow" (or "Continue") to grant all requested scopes
6. Wait for the "Authorization complete" message on the page

Report what you see at each step and flag immediately if Google shows a CAPTCHA or
"This browser or app may not be secure" warning — those require manual intervention.
```

### Step 3 — Verify

Once the script exits, confirm `token.json` was updated:

```bash
python3 -c "import json; d=json.load(open('token.json')); print('refresh_token present:', bool(d.get('refresh_token')))"
```

### Known limitations

**✅ Confirmed working (2026-06-27).** Full flow tested end-to-end:
- Google sign-in page renders in Playwright
- Manual login + MFA completed in the Playwright window
- Consent screen loaded and "Allow" granted
- `oauth_setup.py` received the callback and wrote `token.json` with a refresh token and all four scopes

**Note:** If the account uses MFA, the human must complete the login step in the Playwright window before handing control back to the automation. This is expected — use Approach A for the initial token, then Approach B for all subsequent runs.

Possible failure modes if the flow breaks in the future:

| Symptom | Cause | Resolution |
|---|---|---|
| "This browser or app may not be secure" | Google flagged the automated browser | Complete login manually in Chrome, save refresh token via Approach B |
| CAPTCHA or phone verification prompt | Account triggered fraud detection | Use a test-only Google account with a trusted browser profile |
| Redirect loop or 400 error | `redirect_uri` mismatch | Ensure `credentials.json` has `http://localhost` in authorized redirect URIs |

---

## Approach B — Refresh token injection (CI / headless)

Run the browser flow **once** (manually or via Playwright), then store the refresh token as an environment secret. All future runs reconstruct `token.json` without any browser.

### Step 1 — Extract the refresh token (one time)

After a successful OAuth flow:

```bash
python3 -c "import json; d=json.load(open('token.json')); print(d['refresh_token'])"
```

Store the output as:
- `GOOGLE_OAUTH_REFRESH_TOKEN` (secret)
- `GOOGLE_OAUTH_CLIENT_ID` (from `credentials.json → installed.client_id`)
- `GOOGLE_OAUTH_CLIENT_SECRET` (from `credentials.json → installed.client_secret`)

### Step 2 — Reconstruct token.json on each run

```bash
uv run python scripts/oauth_setup.py --from-refresh-token
```

This writes a minimal `token.json` with the refresh token. The MCP server exchanges it for a fresh access token on first use (same as a normal expired-token refresh — no browser needed).

### In CI (GitHub Actions example)

```yaml
- name: Restore OAuth token
  env:
    GOOGLE_OAUTH_REFRESH_TOKEN: ${{ secrets.GOOGLE_OAUTH_REFRESH_TOKEN }}
    GOOGLE_OAUTH_CLIENT_ID: ${{ secrets.GOOGLE_OAUTH_CLIENT_ID }}
    GOOGLE_OAUTH_CLIENT_SECRET: ${{ secrets.GOOGLE_OAUTH_CLIENT_SECRET }}
  run: uv run python scripts/oauth_setup.py --from-refresh-token
```

---

## Which approach to use

| Scenario | Approach |
|---|---|
| First-ever token acquisition on a new machine | A (Playwright or manual) |
| QA run after token expiry — Playwright available | A |
| QA run after token expiry — no browser possible | B (if refresh token stored) |
| CI pipeline | B |
| Playwright blocked by Google | Manual browser + B for future |
