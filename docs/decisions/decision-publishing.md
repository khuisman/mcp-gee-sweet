# Publishing Strategy — Proposal

**Date:** 2026-05-23
Status: **draft / under consideration**

## Goals

- Stable, semantically versioned releases on PyPI for production users
- A continuously-published pre-release track (`edge`) for community contributions and ongoing work that hasn't completed RC review
- All PRs (regardless of target branch) get CI coverage before merge
- Official stable release only happens after an RC is verified

## Proposed track structure

| Track | Source branch | PyPI version format | Who uses it |
|---|---|---|---|
| Stable | `main` | `1.2.3` | Production users |
| Edge | `edge` | `1.2.3.dev20260524` | Contributors, early adopters |

### Stable track
- Triggered by a GitHub release being published (current `release.yml` already handles this)
- Requires tests to pass before build (added in this PR)
- Semantic versioning: `MAJOR.MINOR.PATCH`
- Promotion path: `edge` → RC tag on edge → verify → merge to `main` → tag stable release

### Edge track
- Triggered on every push to the `edge` branch
- Version computed as `{last_stable_base}.dev{YYYYMMDD}` — e.g. if last stable is `1.2.3`, edge publishes as `1.2.3.dev20260524`
- Published to the same PyPI package (`mcp-gee-sweet`) as a pre-release
- Stable users are unaffected: `pip install mcp-gee-sweet` never pulls `.devN` versions by default

## Why same package over a separate `mcp-gee-sweet-edge` package

- One PyPI project, one trusted publisher config
- `pip` protects stable users automatically (pre-releases require `--pre` flag)
- MCP config can pin to either track by version: `mcp-gee-sweet==1.2.3` (stable) or `mcp-gee-sweet==1.2.3.dev20260524` (edge)
- Standard pattern used by Django, Flask, and most major Python projects

## Version injection (open question)

`uv-dynamic-versioning` with `strict = true` requires a clean git tag to compute a version; without one it falls back to `0.0.0`. For edge builds, options are:

1. **Tag edge branch before publish** — create a lightweight tag like `v1.3.0.dev0` before each edge build; dynamic versioning appends commit distance and hash automatically
2. **Inject version in CI** — workflow computes `{base}.dev{date}` and overrides via env var (exact mechanism TBD — `uv-dynamic-versioning` override support needs research)
3. **Relax `strict` for edge only** — set `strict = false` in the edge workflow so dynamic versioning produces `1.2.3.dev4+gabcdef` from git history automatically

Option 3 is likely the simplest. To be verified before implementation.

## Open questions

- What is the correct env var or mechanism to override the version in `uv-dynamic-versioning`?
- Should community PRs target `edge` directly, or go through a separate `contrib` branch first?
- Release cadence for stable: on demand vs. scheduled (e.g. monthly)?
- Who can trigger the RC → stable promotion?
