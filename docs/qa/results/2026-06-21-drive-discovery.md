# QA Run — Drive Discovery Tools
**Date:** 2026-06-21
**Branch:** feat/drive-discovery
**Tools under test:** `list_shared_with_me`, `list_recent_files`, `get_storage_quota`
**Auth:** Service account

---

## Results

| TC | Tool | Description | Result | Notes |
|----|------|-------------|--------|-------|
| TC-D152 | `list_shared_with_me` | List all files shared with me | ✅ pass | OAuth: 50 files; SA: 5 files explicitly shared with SA |
| TC-D153 | `list_shared_with_me` | Filter by MIME type | ✅ pass | OAuth: 8 spreadsheets, all correct MIME type |
| TC-D154 | `list_shared_with_me` | max_results=3 | ✅ pass | OAuth: exactly 3 items returned |
| TC-D155 | `list_shared_with_me` | Quote escaping in MIME type | ✅ pass | Unit test |
| TC-D156 | `list_recent_files` | List recently modified files | ✅ pass | 10 files ordered by modifiedTime desc |
| TC-D157 | `list_recent_files` | Filter by days | ✅ pass | All files within 7-day window |
| TC-D158 | `list_recent_files` | Filter by MIME type | ✅ pass | 14 spreadsheets, all within 14 days |
| TC-D159 | `list_recent_files` | max_results capped at 100 | ✅ pass | Unit test |
| TC-D160 | `get_storage_quota` | Get storage quota | ✅ pass | OAuth: 15 GB limit, real usage. SA: limit_bytes=0 (API returns "0", not None — docstring corrected) |
| TC-D161 | `get_storage_quota` | Fields include storageQuota+user | ✅ pass | Unit test |
| TC-D162 | `get_storage_quota` | Byte values are integers | ✅ pass | Unit test |

**Unit tests:** 351 passed (24 drive, 327 other)

**Live tests:** 11/11 passed. One finding: SA `get_storage_quota` returns `limit_bytes=0` (not `None`) — Google API sends `"0"` for service accounts. Docstring and TC-D160 updated accordingly.
