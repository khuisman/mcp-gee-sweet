# MCP Bundle (`.mcpb`)

**Issue:** #1036. **Date:** 2026-10-25.

The server ships as an [MCP Bundle](https://github.com/modelcontextprotocol/mcpb) alongside the PyPI package: a zip holding `manifest.json`, which tells an MCPB-aware host (Claude Desktop) how to launch the server and what to ask the user for at install.

#1036 also meant the bundle for a Smithery listing, which takes a local stdio server only as a `.mcpb`. That part was dropped: on 2026-10-31 Smithery ends its connection services, deprecates its CLI, and keeps only a non-proxied registry of verified servers' direct MCP URLs ([smithery.ai/future](https://smithery.ai/future)), which says nothing about local bundles. The bundle is for one-click installs in an MCPB-aware host.

## Pieces

| File | Role |
|---|---|
| `manifest.json` | MCPB manifest v0.4, `server.type: "uv"`. The source of truth for the bundle's metadata and launch command, everything but the version. |
| `scripts/build_mcpb.py` | Stages an allowlist of files as committed at `HEAD`, stamps the version, and runs `mcpb pack` (`@anthropic-ai/mcpb`, pinned). `--smoke` is the CI check. |
| `.mcpbignore` | A backstop inside the staging directory, not the main guard (below). |
| `src/mcp_gee_sweet/__main__.py` | `python -m mcp_gee_sweet`, the launch command, and the manifest's `entry_point`. |
| `.github/workflows/mcpb.yml` | Builds and smoke-tests on a PR that touches the bundle's inputs; on a published release, attaches the bundle to it. |
| `scripts/qa_launch_mcpb.py` | QA aid for TC-I68: runs the bundle's `mcp_config` the way a host does. |
| `tests/test_mcpb_manifest.py` | Version stamping, identity, `user_config` wiring, the allowlist, and staging from `HEAD` (against a throwaway repo). |

## Decisions

**`uv` server type, not `python`.** The `python` type needs the dependencies vendored into the bundle, and the spec says compiled ones (pydantic, cryptography, Pillow) can't be bundled portably. The `uv` type ships `pyproject.toml` and `uv.lock`, and the host installs them.

**`mcp_config` is explicit.** The spec's prose calls it optional for `uv`, but the v0.4 validator that `mcpb pack` runs requires it (mcpb#263). It runs `uv run --directory ${__dirname} --frozen --no-dev python -m mcp_gee_sweet`. `--frozen` installs exactly what `uv.lock` pins, with no re-resolve on the user's machine; `--no-dev` leaves out the dev group (mkdocs, pytest, ruff). `-m` rather than a script path: running `src/mcp_gee_sweet/__main__.py` as a script puts the package directory first on `sys.path`, where `server.py`, `cache.py` and `auth.py` would shadow any top-level module of those names.

**Version stamped at build time.** `pyproject.toml`'s version is dynamic (`uv-dynamic-versioning`, from the git tag), and a bundle has no `.git`, so the installed package reported the `0.0.0` fallback (checked). The staged manifest gets `version`, and an `mcp_config.env` `UV_DYNAMIC_VERSIONING_BYPASS` that the plugin uses instead of a tag, from `--version` (the release workflow passes the tag) or else `server.json`. The committed `manifest.json` carries neither, so no release step bumps it and nothing can drift (PR #1255 QA round 1; an earlier version kept both by hand and checked them against the tag). `--smoke` checks that the installed package reports the stamped version.

**Staged from committed files on an allowlist, never the repo root.** A working checkout holds `credentials.json`, `token.json`, `service_account.json` and `src/mcp_gee_sweet/.env`. `mcpb pack` excludes `.env*` by default but not the JSON files, and a deny-list in `.mcpbignore` would miss the next new one. So `build_mcpb.py` writes six root files, everything under `src/mcp_gee_sweet/`, and the icon into a temporary directory, reading each one from `HEAD` (`git ls-tree`, `git show`), and packs that. An untracked file, or an uncommitted edit to a tracked one, can't reach the bundle; the build warns about uncommitted changes it left out. `mcpb pack .` from the repo root isn't a supported build.

**OAuth only.** The bundle sets `AUTH_METHOD=oauth`. Asking for an OAuth client file states the user's intent, and the default waterfall would fall through to Application Default Credentials on a machine with `gcloud` set up, instead of offering consent. Service-account and ADC setups keep the manual config in `docs/client-setup.md`.

**Token location.** `TOKEN_PATH` is fixed at `${HOME}/.mcp-gee-sweet-token.json` rather than asked for:
- A `file` picker doesn't promise to accept a path that doesn't exist yet, and the token doesn't exist before the first consent.
- The reference implementation (`getMcpConfigForManifest`) substitutes a `user_config` default into `mcp_config` without expanding the variables inside it, so a `${HOME}/...` default would reach the server verbatim. `${HOME}` written directly in `mcp_config` is expanded.
- `write_token_json` doesn't create a parent directory, so the path has to be one that exists. `${HOME}` does.
- It's outside the extension directory, which an update replaces.

**Optional settings need a default.** An unset `user_config` value with no default is left as the literal `${user_config.KEY}` text (`replaceVariables` keeps a variable it can't resolve). `ENABLED_TOOLS` therefore defaults to `""`, which the server reads as "every tool". `CACHE_TTL` isn't offered: MCPB has no integer type, `int()` of a decimal at import would stop the server, and `set_cache_ttl` changes it at runtime anyway.

**Platforms.** `darwin` and `linux`, what's tested. `win32` waits for a Windows test. No `compatibility.claude_desktop` floor: the first Claude Desktop version with `uv`-type support isn't published (mcpb#291 says env passing was fixed in Claude Desktop, without a version).

## Not covered by automation

Completing OAuth consent needs a person at a browser, and a Claude Desktop install needs macOS with Claude Desktop. Both are TC-I68 in `docs/qa/tests/infra.md`.
