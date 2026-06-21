# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| Latest stable on PyPI | Yes |
| Dev releases (`*.devN`) | No — dev track only, no security backports |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Use GitHub's private vulnerability reporting instead:
1. Go to the [Security tab](../../security) of this repository.
2. Click **"Report a vulnerability"**.
3. Describe the issue, including reproduction steps and potential impact.

You'll receive an acknowledgement within 72 hours. If the vulnerability is confirmed, a fix will be prioritized and a patched release published before public disclosure.

## Scope

In-scope:
- Credential or token leakage via the MCP server or its tooling
- Privilege escalation through tool parameters (e.g., accessing Drive files outside the configured folder)
- Secrets exposed through environment variable handling or log output
- Dependency vulnerabilities with a realistic exploitation path

Out-of-scope:
- Google API quota or rate-limit abuse (report directly to Google)
- Issues requiring physical access to the host machine
- Theoretical vulnerabilities with no realistic attack vector
