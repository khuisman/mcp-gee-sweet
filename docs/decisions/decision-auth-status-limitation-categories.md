# Decision: Per-Category Limitations in `server://auth-status` (issue #447)

**Date:** 2026-08-02
**Snapshot commit:** branch `fix/joy/issue-447` — see `src/mcp_gee_sweet/server.py`

## Background

`transfer_ownership` (#140, PR #445) ships with a docstring note pointing callers at `server://auth-status` to check whether their auth method supports it — but PR #445's own review found the tool was never added to `_SA_LIMITED_TOOLS`, the list `_auth_status_json` uses to populate that resource. A caller checking the resource before calling the tool wouldn't see the restriction and would only discover it when the live call failed (TC-D234, `docs/qa/tests/drive.md`).

This wasn't a one-line list addition. `_auth_status_json`'s existing schema attaches one shared `reason`/`alternatives` string to every tool in the list, written specifically for the *storage-quota* failure class shared by `create_spreadsheet`/`create_doc`/`copy_file`/the upload tools/`sync_folder`: "Service accounts have no Drive storage quota...". `transfer_ownership` fails for an unrelated reason — a service account has no personal Drive *identity* to transfer files to/from, not a quota problem — so its `reason` and `alternatives` needed to say something different. Attaching the quota reason to it would have been factually wrong; the ticket asked for a design call on how to generalize the schema (or handle the tool some other way) rather than shipping that.

## Decision: split into per-category limitation entries

`_SA_LIMITED_TOOLS` (a flat `list[str]`) became `_SA_LIMITATIONS` (a `list[dict]`), one entry per failure class:

```python
{
    "category": "no_drive_storage_quota",
    "tools": [...the original 7 tools...],
    "reason": "Service accounts have no Drive storage quota...",
    "alternatives": "Switch to OAuth (CREDENTIALS_PATH) or ADC for full tool coverage.",
}
```
```python
{
    "category": "no_personal_drive_identity",
    "tools": ["transfer_ownership"],
    "reason": "Service accounts have no personal Drive identity to transfer file ownership to/from...",
    "alternatives": "Switch to OAuth (CREDENTIALS_PATH) for full tool coverage.",
}
```

`_auth_status_json`'s output gained a `limitations` array (the categorized detail) alongside a `limited_tools` array that's still a flat, flattened-across-categories list — kept for callers that only want a quick "is this tool restricted" membership check without caring why. The old top-level `reason`/`alternatives` strings were removed rather than kept as a deprecated/backward-compatible pair: this is a pre-1.0 MCP resource with no external contract to preserve, and a stale flat `reason` sitting alongside the new categorized `limitations` would just invite a caller to read the wrong one.

**Alternatives considered and rejected:**
- **Bolt `transfer_ownership` onto the existing flat list, write a reason string broad enough to cover both classes.** Rejected — the issue itself flagged this as the thing to avoid; a caller reading "no Drive storage quota" as the reason `transfer_ownership` failed would misdiagnose the actual problem (identity, not quota) if they ever needed to reason about it beyond "this tool is restricted."
- **Per-tool map (`{tool_name: {reason, alternatives}}`) instead of per-category.** Rejected as unnecessary granularity for now — every restricted tool today maps to exactly one of two categories, and a per-tool map would just repeat the same reason/alternatives string across the 7 quota-limited tools for no benefit. Revisit if a third tool-specific failure class shows up that doesn't fit either existing category.

## Scoped out: ADC's own identity ambiguity

The `no_personal_drive_identity` category's `alternatives` deliberately does **not** suggest ADC as a fix, only OAuth — unlike the quota category, which still lists both. `google.auth.default()` (what `AUTH_METHOD=adc` resolves through) can return either a real user's credentials or a service-account-backed credential (GCE/Cloud Run/GKE attached metadata service account, or `GOOGLE_APPLICATION_CREDENTIALS` pointed at a key file), and `auth_method` alone can't currently distinguish the two — so telling a caller "switch to ADC" for this specific class would be an unverifiable claim.

This same ambiguity technically also undermines the pre-existing quota category's ADC suggestion (an ADC session backed by a service account has the same quota problem `AUTH_METHOD=service_account` does), but that's a *pre-existing* inaccuracy, not something #447 introduced or was scoped to fix. Filed separately as **#506** rather than folded into this change — fixing it means teaching `spreadsheet_lifespan` (`auth.py`) to inspect the resolved credential's actual type and report a more specific `auth_method`/identity flag, a bigger change than this ticket's per-tool schema fix.

## Consumers updated

- `tests/test_server.py::TestAuthStatusResource` — split the old single reason/alternatives test into one assertion per category (`test_service_account_storage_quota_limitation`, `test_service_account_transfer_ownership_limitation`), added `transfer_ownership` to the `limited_tools` membership check, updated the full-access (`oauth`/`adc`) tests to expect `limitations: []` instead of `reason: None`.
- `docs/qa/tests/infra.md` — TC-I27 added (new schema, service-account auth); TC-I25 (the original `#363` resource-resolution test, whose recorded `Result` shows the old flat shape) got a note pointing at TC-I27 rather than a rewritten `Result`, since TC-I25's own checks (no `AttributeError`, correct `auth_method`) are unaffected by the schema change and its historical result shouldn't be edited to claim something that wasn't actually re-run.
- `docs/auth.md` — the service-account "Limitation" bullet now also names `transfer_ownership` and notes it has no Shared Drive workaround (unlike the quota-limited tools).
