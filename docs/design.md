# Design Principles

This document is the living reference for how mcp-gee-sweet is designed and how design decisions get made. It is updated as the project's thinking evolves. For the historical reasoning behind specific decisions, see the [Decision Log](decisions/index.md). For code-level convention — module size, test structure, linting — see the [Style Guide](style-guide.md).

---

## What This Server Is

An MCP server for Google Workspace. Its job is to give an AI client reliable, direct access to Google APIs that the client cannot call itself. Every tool added to this server is a named entry in a flat list that the AI must reason about — more tools means more noise, not more capability.

---

## Scope

The server covers **Google Workspace productivity tools** — the suite a person uses to write, organise, communicate, and schedule. The line is drawn at Google Cloud infrastructure and analytics, which are a different product category serving a different purpose.

| In scope | Out of scope |
|---|---|
| Google Sheets | BigQuery / BigTable |
| Google Docs | Google Analytics |
| Google Drive | Google Cloud Storage (raw GCS) |
| Google Calendar | Compute Engine / GKE / GCE |
| Google Slides | Maps / Places |
| Google Forms | Pub/Sub / Dataflow |
| Gmail | Any non-Google service |
| Google Tasks / Keep | General local file system ops |
| Google Chat | |

Not all in-scope services need to be implemented — the table above is the ceiling, not a commitment. Priority follows actual use. Adding a new Workspace service requires a decision record in `docs/decisions/` explaining the use case and estimated tool count cost.

---

## Adding a Tool — The Inclusion Test

A tool belongs here if it passes all three gates:

1. **Requires Google API access** — the operation calls a Google API (Sheets, Drive, Docs, Calendar). Tools that only manipulate local data or do pure computation don't belong here.

2. **Not already coverable** — the operation is not already expressible via an existing tool, including the `batch_update` passthrough, which is the intended escape hatch for raw Sheets API operations.

3. **Atomic or justified composite** — the operation is a single logical action, OR it is a multi-step chain where Claude fails or requires retries without a server-side wrapper. See [When to Build a Composite](#when-to-build-a-composite) below.

### What doesn't belong

- **Simple sequential chains** — if a workflow is two predictable API calls in order, Claude handles the primitives. A wrapper adds surface area and a duplicate name the AI has to disambiguate.
- **Convenience aliases** — re-exposing an existing tool with different defaults is not a new tool.
- **Speculative features** — tools added because they might be useful someday. The [roadmap](roadmap.md) tracks candidates; they stay there until there is a real use case.
- **Non-Google operations** — format conversion, local file transforms, computation. These belong in the client or a separate server.

### Tool count as a cost

The tool list is flat. The AI sees every registered tool on every call. Each additional tool increases the chance of the AI picking the wrong one, makes descriptions harder to keep distinct, and adds a parameter schema the AI has to reason about. Prefer depth over breadth — a well-parameterised `export_file` that handles PDF, DOCX, HTML, and XLSX is better than four separate export tools.

### The `batch_update` rule

If an operation can be expressed as a raw Sheets `batchUpdate` request, it does not automatically need a named tool. A named tool is warranted when the operation is common enough that spelling out the raw request every time is unreasonable.

---

## When to Build a Composite

The default position is that the AI client chains atomic tools. Server-side composite tools are built only when intermediate steps are fiddly enough that Claude will fail or require retries in normal use. The test: *would a developer write a helper script to avoid doing this by hand?*

Three failure modes justify a server-side wrapper, based on observed usage:

1. **Binary data handling** — tools that return base64-encoded content (XLSX exports, PDF exports, image downloads) require a decode step that Claude handles inconsistently. A server-side tool that handles decode and local write once is more reliable than Claude doing it on every call.

2. **Pagination loops** — bulk operations over a folder or large file list require correctly following `nextPageToken`. Claude can do this but will occasionally stop at the first page or loop incorrectly under load.

3. **Data encoding decisions in transformation chains** — operations like `sheet_to_doc` involve choices about how to encode tables, handle formatting, and structure output that benefit from a consistent server-side implementation.

For everything else, the right investment is clear tool docstrings that describe when and how to combine the primitives — not a new tool.

See [Decision: Composite Tool Policy](decisions/decision-composite-tools.md) for the full case analysis and the specific tools approved or ruled out at the time this policy was established.

---

## Testing

**Unit tests** (`tests/test_tools.py`) cover helpers, HTML conversion, tool filtering, A1 notation parsing, and cache TTL/invalidation logic. These run in CI on every push and PR.

**AI-directed manual verification** is the primary QA method for tool correctness. Test cases are natural language prompts paired with explicit check lists (`docs/qa/tests/`). A Claude session connected to the live server executes the prompts, evaluates results against the checks, and saves a results report. Tests run against the real Google APIs under real conditions — the same environment as production.

Automated integration tests against live Google APIs were evaluated and deferred. The setup cost (managed credentials, fixture maintenance, API quota, test flakiness) does not pay off at current scale. See [Decision: Testing Approach](decisions/decision-testing.md) for the full rationale and the conditions under which this should be revisited.
