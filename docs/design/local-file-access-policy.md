# Local-File Access Policy

**Date:** 2026-10-10 · **Issue:** [#796](https://github.com/khuisman/mcp-gee-sweet/issues/796) · **Modules:** new `src/mcp_gee_sweet/local_files.py`; `server.py`; the local-I/O sites under `tools/`

This doc is the implementation design for the policy approved on #796 (2026-10-04). It doesn't revisit the decision. Where carrying the decision out raised a question it doesn't answer, the question is listed under [Open questions](#open-questions) for the maintainer, not settled here.

## The decision, restated

- One setting, `LOCAL_FILE_ACCESS=full|roots|off`.
  - `full`: any local path (today's behavior).
  - `roots`: a path must resolve, symlinks included, under a directory listed in `LOCAL_FILE_ROOTS`.
  - `off`: no local file access.
- Default: `full` under stdio, `off` under SSE or streamable HTTP.
- Every local read and write goes through one shared check.
- Always blocked, in every mode: the server's own `CREDENTIALS_PATH`, `TOKEN_PATH`, `SERVICE_ACCOUNT_PATH`, and `.env`.
- In `off` mode, local-only tools aren't registered. Tools whose only local I/O is an optional `local_path` stay registered and return a clear error when it's used.
- Gmail's attachment read moves off the event loop.
- Out of scope: remote-safe replacements (binary upload, image bytes, large-result destinations, downloads) and input size limits.

## What changed since the ticket was filed

Checked against `develop` at `f899708`:

- **Gmail's attachment read is already off the loop.** PR #928 (#896) moved `_read_attachment_bytes` inside `_compose_raw`, which runs `_build_raw_message` via `asyncio.to_thread`. The last synchronous local read under `tools/` is `docs/content.py`'s `_read_doc_source_file` (Sky's comment on #796). That one is now this ticket's off-loop item.
- **Streamable HTTP is a third transport** (#917). The default rule reads "anything but stdio", not "SSE".
- **Markdown/HTML image sources are a local read the ticket didn't list.** `create_doc`, `write_doc_content`, `create_doc_from_file` and `update_doc_from_file` resolve `![](path)` / `<img src>` through `_resolve_image_source`, which uploads any local path. The shared check has to cover it.
- **`export_file` and `export_revision` don't touch disk.** They return bytes in-memory. "Downloads and exports" in the decision means `download_file`, `download_folder` and `sync_folder`.

## Design

### 1. One module: `src/mcp_gee_sweet/local_files.py`

It's a top-level module beside `http_transport.py`, not under `tools/`, because `server.py` needs it at import time for registration and every tool domain needs it at call time. It owns:

- `LocalFileAccess`: a `str, Enum` with `FULL`, `ROOTS`, `OFF` (not `StrEnum`, which needs Python 3.11; the package supports 3.10).
- `POLICY`: the process's resolved policy (mode, roots, deny-list), computed once at import.
- `check_read(path) -> Path` and `check_write(path) -> Path`: the one shared check. Each returns the resolved `Path` to use for the I/O, or raises `LocalFileAccessError`.
- `LocalFileAccessError(ValueError)`: a `ValueError` subclass, so `_timed`'s error-visibility allowlist (`decision-tool-error-visibility.md`) passes its message to the client unchanged. Sites that report errors as `{"error": ...}` or as per-item `failed` entries catch it and use `str(e)`.
- `registers_local_only_tools() -> bool`: `False` in `off` mode.

It imports the credential paths from `auth.py`. `auth.py` imports nothing from `tools/` or from this module, so there's no cycle.

### 2. Resolving the mode at import, and the fail-safe

Tool registration runs at import (`register_all(tool)` in `server.py`), before `main()` parses `--transport`. `off` mode decides which tools register, so the mode must be known at import too. `ENABLED_TOOLS` already solves this by reading `sys.argv` at import (`_parse_enabled_tools`). The policy does the same:

1. Extract `_cli_transport(argv) -> str` from `main()` (default `"stdio"`). `main()` and the policy resolver both call it, so the two can't disagree.
2. `LOCAL_FILE_ACCESS` set: use it. Not set: `full` if the CLI transport is `stdio`, else `off`.
3. Record whether the mode was explicit or defaulted (`POLICY.explicit`).

`--reload` is covered. uvicorn's reload worker is a `multiprocessing` spawn child, and a spawn child inherits the parent's `sys.argv`. Confirmed with a scratch script: the child saw `--transport sse`. So `docker-compose.yml`'s `--transport sse --reload` resolves to `off` in the worker that actually serves.

**The gap argv can't close.** `mcp_gee_sweet.server:app` is a module-level ASGI object. An operator who points uvicorn at it directly (`uvicorn mcp_gee_sweet.server:app`) never passes `--transport`, so argv resolution says stdio and the default would be `full` on a network-facing server. That launch isn't documented, but nothing stops it, and the decision's default exists precisely for network-facing servers. So, a runtime tripwire:

- `_timed` already reads `ctx.request_context.request` for the access log. It's a Starlette `Request` under SSE and streamable HTTP, and `None` under stdio.
- `_timed` sets a `ContextVar`, `local_files.request_over_http`, for the duration of the call.
- `check_read` / `check_write` refuse every path when `POLICY.mode is FULL and not POLICY.explicit and request_over_http.get()`, with an error naming `LOCAL_FILE_ACCESS`. The first such refusal logs one `WARNING`.

An explicit `LOCAL_FILE_ACCESS=full` over HTTP is honored, because the operator chose it. The tripwire catches only a stdio default leaking onto an HTTP request. In that misconfigured launch the local-only tools are still registered, but every call they make is refused, so the failure is closed.

### 3. The check

```
check_read(path) / check_write(path):
  1. tripwire (§2)
  2. mode OFF   -> refuse
  3. p = Path(os.path.realpath(path))        # relative paths resolve against cwd, as open() does
  4. mode ROOTS -> refuse unless p.is_relative_to(r) for some resolved root r
  5. deny-list  -> refuse if p is a credential file (below)
  6. return p
```

**Check before any `stat`.** Several sites currently call `Path(x).is_file()` / `.exists()` first and return `"No file found at ..."`. In `roots` and `off` mode, that ordering is an existence oracle for paths outside the roots. The check must run first, and its refusal message must be the same whether or not the path exists. `realpath` needs no existing target: it resolves the existing prefix, so writes to new files work.

**Use the returned path.** A site does its I/O on the `Path` the check returned, not on the caller's string. This narrows the window between check and use, though it doesn't close it (see Known limitations).

**Containment is a string test on resolved paths, and it fails closed.** On a case-insensitive filesystem (macOS APFS default), `realpath` keeps the caller's spelling of components that exist. Confirmed: `realpath("dir/TOKEN.json") != realpath("dir/token.json")` for one file. So a differently-cased path can fail the `is_relative_to` test for a file that really is inside a root (a false refusal), but it can never pass the test for a file outside one.

**The deny-list compares file identity, not strings.** For the same reason, a string compare would let `TOKEN.json` through on macOS. A hardlink to the token would also slip past it, inside a root or not. At import, resolve each deny-listed path (`CREDENTIALS_PATH`, `TOKEN_PATH`, `SERVICE_ACCOUNT_PATH`, `Path(mcp_gee_sweet.__file__).parent / ".env"`) with `realpath`. Relative defaults like `token.json` resolve against the startup cwd, which is what `auth.py` reads. Then a target is refused if:

- it exists and `os.path.samefile(p, entry)` holds for an entry that exists (this catches case variants, hardlinks and bind mounts), or
- it doesn't exist and its `realpath` equals an entry's `realpath` under `os.path.normcase` and `casefold()`. This is the write case. A download to a `TOKEN_PATH` that hasn't been written yet would otherwise plant a token the server then loads.

The deny-list applies in `full` mode too. There it guards a local user against an LLM-composed `send_message(attachments=[{local_path: "token.json"}])` or a `sync_folder` run over the config directory, not against a hostile caller.

**Refusal messages** name the setting, never the configured values:

- `off`: `"local file access is disabled on this server (LOCAL_FILE_ACCESS=off)"`
- `roots`: `"<path> is outside this server's LOCAL_FILE_ROOTS"`
- deny-list: `"<path> is one of this server's credential files and can't be read or written by a tool"`
- tripwire: `"local file access is disabled for HTTP requests unless LOCAL_FILE_ACCESS is set explicitly"`

Don't interpolate `TOKEN_PATH`'s value or other secret-named values into log lines (CodeQL `py/clear-text-logging-sensitive-data`; see root `CLAUDE.md`). Echoing the caller's own `path` back is fine.

### 4. Configuration validation

Done at import, alongside `ENABLED_TOOLS`. An invalid value raises `SystemExit` with a one-line message, so a misconfigured server never starts serving:

- `LOCAL_FILE_ACCESS` not in `full|roots|off` (case-insensitive).
- `roots` with `LOCAL_FILE_ROOTS` empty or unset.
- A `LOCAL_FILE_ROOTS` entry that doesn't exist or isn't a directory.
- `LOCAL_FILE_ROOTS` set while the mode isn't `roots`: log a `WARNING` that it's ignored, but don't exit.

`LOCAL_FILE_ROOTS` is split on `os.pathsep` (`:` on POSIX, `;` on Windows), like `PATH`/`PYTHONPATH`, rather than on the comma `ENABLED_TOOLS` uses: tool names can't contain commas, but paths can. Each root is resolved with `realpath` once, at import.

### 5. Site inventory and choke points

Each local read or write gets exactly one check, placed at the narrowest shared function. Function names are given rather than line numbers, since line numbers move.

| Tool(s) | Local I/O | Check site | Op |
|---|---|---|---|
| `upload_local_file`, `upload_local_folder` (per file), `insert_local_images` and Markdown/HTML local images (via `upload_and_share_local_image`) | open + `MediaFileUpload` | `transfer._upload_local_file`, at the top | read |
| `insert_local_images`, Markdown/HTML local images | `stat`, image header read, resize read (`check_image_file`, `prepare_local_image`) *before* the upload | `images.upload_and_share_local_image`, at the top, before `prepare_local_image`. Also replace `insert_local_images`'s own `Path(local_path).is_file()` pre-check and `content._resolve_image_source`'s with the check (ordering rule, §3) | read |
| `upload_local_folder` | `iterdir` of the folder | the folder itself, in the tool, before `is_dir()` | read |
| `create_doc_from_file`, `update_doc_from_file` | `read_text` | `content._read_doc_source_file`, at the top, before `exists()` | read |
| `import_csv_to_sheet` | `open` | the tool, before `path.open` | read |
| `send_message`, `create_draft` (attachments) | `read_bytes` | `gmail._read_attachment_bytes` (already in a worker thread; the `ValueError` propagates out of `_compose_raw` as today's missing-field error does) | read |
| `download_file` | `_write_atomically`, `mkdir` | the tool, before `_validate_local_destination` (that helper `stat`s parents) | write |
| `download_folder`, `sync_folder` (downloads) | `mkdir`, `_write_atomically` per file | the destination root in the tool, before `mkdir`, plus each file (§6) | write |
| `sync_folder` (uploads, `use_checksum` hashing, `stat`) | `MediaFileUpload`, `_local_md5`, `stat` | each local entry where `_sync_level` builds `local_map` / `local_folder_map` (§6) | read |
| `sync_folder`, `upload_local_folder`, `download_folder`: the `local_path` root | `mkdir` / `iterdir` | the tool, at entry | read for upload-only, write for any direction that can download |
| 9 tools with the response-cap bypass (`get_sheet_data`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `find_in_spreadsheet`, `get_doc_content`, `find_in_doc`, `get_doc_as_markdown`, `get_message`, `get_thread`) and `sync_folder(result_local_path=)` | `mkdir`, `write_text` | `response_limits.write_capped_result_to_disk`, at the top, before `is_dir()`. Check the final `dest` after the directory join too, since `default_filename` changes the target | write |

`sync_folder`'s existing "`result_local_path` inside `local_path`" `ValueError` stays as it is and runs after the policy check. The two are independent.

### 6. Folder walks: check each entry, not just the root

`iterdir()` followed by `is_file()` / `is_dir()` follows symlinks. A symlink inside an allowed root that points at `/etc` or at the token file is uploaded today, and a pre-existing symlink in a download destination is written through (`_write_atomically` deliberately writes through a symlinked `dest`). Checking only the root would miss both, so:

- **Local reads during a walk.** `_sync_level` runs `check_read` on each `p` as it builds `local_map`. A refused file follows the `unsafe_names` precedent beside it: it doesn't enter `local_map`, and it surfaces as one `local_read_fail` step carrying the refusal reason, so `dry_run` previews it and a real run reports it in `failed`. That needs no new plan-action kind. `local_folder_map` gets the same treatment for symlinked subdirectories, so recursion never descends outside a root. `upload_local_folder`'s per-file `_upload_local_file` call already gets its check from §5; a refusal lands in `failed` like any other per-file error.
- **Local writes during a walk.** Every `_write_atomically` call site in `download_folder` and `_sync_level`'s download branch runs `check_write(dest_file)` before streaming. A refusal goes to `failed`. Don't put the check inside `_write_atomically`: its callers already handle per-file errors differently, and the error should be reported before the Drive download starts, not after.
- **Drive-supplied names** can't escape the destination root on their own (`_safe_local_dest` / `_unsafe_name_reason`). The per-file check is for symlinks and the deny-list, not for traversal.

A refused entry never aborts the whole walk. That matches how every other per-file failure in these tools is reported.

### 7. Registration in `off` mode

Add a `local_only: bool = False` keyword to `server.tool()`. Mark the tools at their own decorator (`@tool(local_only=True)`), not in a central list of names, because a renamed tool silently drops out of a central list. That's the failure `gen_tool_docs.py`'s `SUBSETS` check exists to catch.

`tool()` skips registration when `local_only and not local_files.registers_local_only_tools()`, the same way it skips a tool missing from `ENABLED_TOOLS`. If `ENABLED_TOOLS` names a tool that `off` mode drops, log one `WARNING` at startup listing the dropped names, so an operator who asked for `sync_folder` learns why it's missing.

The decision lists seven local-only tools: `sync_folder`, `upload_local_file`, `upload_local_folder`, `download_folder`, `insert_local_images`, `create_doc_from_file`, `update_doc_from_file`. Two more tools also take a **required** `local_path`: `download_file` and `import_csv_to_sheet`. They see the same treatment as the seven under the decision's own rule, but they aren't on its list. See [Open questions](#open-questions).

Every other tool with local I/O stays registered and reaches the check at call time:

- the nine response-cap `local_path` tools
- `send_message` / `create_draft` (`attachments[].local_path`; `content_base64` still works in `off` mode)
- `create_doc` / `write_doc_content` (local image sources fail per image through the existing image-outcome path, and the doc is still written)

Each local-only tool's docstring gains one sentence, "Not available when the server runs with `LOCAL_FILE_ACCESS=off`.", so `docs/tools.md` (generated) says so too.

### 8. Off-loop read

`_read_doc_source_file` keeps its signature. Both callers wrap it as `await asyncio.to_thread(_read_doc_source_file, ...)`. The policy check runs inside it, at the top, so it runs on the worker thread with the read. Nothing else under `tools/` reads file contents on the loop (`grep -rn "read_text\|read_bytes" src/mcp_gee_sweet/tools`). The cheap `stat` calls that remain on the loop (the check's `realpath`/`samefile`, `is_dir()`) are in the same cost class as the `is_file()` pre-checks that already run there, so they don't move.

### 9. Docs and release notes

- `docs/configuration.md`: `LOCAL_FILE_ACCESS` and `LOCAL_FILE_ROOTS` in the environment-variable table, plus a short section with the transport defaults, the always-blocked list, and a Docker bind-mount example (`LOCAL_FILE_ACCESS=roots`, `LOCAL_FILE_ROOTS=/data`).
- `src/mcp_gee_sweet/.env.template`: both settings, commented out.
- `CHANGELOG.md`: a **Breaking** entry. An SSE or streamable-HTTP server that relied on local-path tools must now set `LOCAL_FILE_ACCESS`.
- `docs/known-limitations.md`: the limitations below.
- Root `CLAUDE.md`: a one-paragraph invariant entry ("every local read/write goes through `local_files.check_read`/`check_write`; local-only tools take `@tool(local_only=True)`"), since a future tool that forgets the check is the regression this design is most exposed to.
- `docker-compose.yml` needs no change. It mounts no data directory, so `off` is the right default for it, and its service-account key is deny-listed anyway.

### 10. Tests

Unit tests only for the policy itself; it has no Google API surface.

- `tests/test_local_files.py`:
  - The mode matrix: `LOCAL_FILE_ACCESS` unset/each value × `--transport` absent/`stdio`/`sse`/`streamable-http`.
  - Validation exits (§4).
  - `roots` containment with `tmp_path`: inside, outside, `..` traversal, a symlink inside a root pointing outside, a symlink outside pointing inside.
  - The deny-list: a case variant (skip unless the filesystem is case-insensitive), a hardlink, a non-existent `TOKEN_PATH` as a write target, `.env`.
  - The tripwire: defaulted `full` + HTTP request refuses; explicit `full` + HTTP request allows; stdio allows.
  - Identical refusal text for existing vs. missing paths outside a root.
- `tests/test_server.py`: in `off` mode the seven (or nine) tools aren't registered and the rest are; the `ENABLED_TOOLS` warning. Follow the existing `ENABLED_TOOLS` tests' `monkeypatch` of `sys.argv` and the module attribute rather than re-importing `server`.
- One test per §5 choke point: in `off` mode the tool returns the refusal and the filesystem is untouched (no file created, no `mkdir`, no Drive call made).
- `sync_folder` / `upload_local_folder` / `download_folder`: a walked directory with one symlink escaping the root. The other files transfer, and the escaping one is a `failed` / `local_read_fail` entry, under `dry_run` as well.
- A guard test: every `@tool` function with a parameter named `local_path` or `result_local_path`, or `attachments`/`images`, appears in an explicit allowlist of tools whose checks are covered above. A new local-path tool then fails CI until someone decides where its check goes.

Live QA: the policy makes no Google API calls of its own, so live QA is limited to confirming the real launch paths. One stdio and one SSE subprocess run through `tests/integration/` (`decision-local-fs-test-harness.md`): under SSE with no setting, `sync_folder` is absent from `tools/list`; with `LOCAL_FILE_ACCESS=roots`, `upload_local_file` works inside the root and is refused outside it.

## Known limitations

- **Check-then-use race.** A symlink swapped between the check and the `open` defeats `roots`. A remote caller can't create symlinks through any tool (downloads write regular files and `sync_folder` never creates links), so exploiting it needs a local actor with write access inside a root. Closing it fully would mean `openat`-style descriptor-relative I/O through every site, which is out of proportion here.
- **`roots` false refusals on case-insensitive filesystems** when the caller's spelling of a directory differs from the root's (§3). This fails closed. Callers should use the root's spelling.
- **Deny-list scope.** Only the server's own credential files are protected. Another secret inside an allowed root, or anywhere in `full` mode, is readable by design. `roots` is the tool for limiting that.

## Open questions

These come out of carrying the decision through, and each is the maintainer's call. They're listed here, not decided.

1. **`download_file` and `import_csv_to_sheet` in `off` mode.** Each takes a required `local_path`, so each is unusable in `off` mode exactly like the seven listed tools, but neither is on the approved list. Registered, each would only ever return the refusal. Should they be unregistered too?
2. **More deny-list candidates.** The approved list has four entries. Other process-level files a tool could read or overwrite:
   - `GOOGLE_APPLICATION_CREDENTIALS` (an ADC key file, the same class of secret as `SERVICE_ACCOUNT_PATH`)
   - gcloud's default ADC file (`~/.config/gcloud/application_default_credentials.json`)
   - `CACHE_DB_PATH` (overwriting it corrupts the cache; reading it exposes cached Drive/Sheets data)
   - `LOG_FILE` / `ACCESS_LOG_FILE` (overwrite or truncate)

   Should any of them join the list?
3. **Telling callers about the policy.** In `roots` mode, a caller has no way to learn the allowed roots: the refusal names the setting, not the directories. Should the mode (and, in `roots` mode, the roots) appear in `server://auth-status`, or would publishing the roots disclose more than an operator wants?
