# Tool Philosophy

## What This Server Is

An MCP server for Google Workspace. Its job is to give an AI client reliable, direct access to Google APIs that the client cannot call itself. Every tool added to this server is a named entry in a flat list that the AI must reason about — more tools means more noise, not more capability.

## The Inclusion Test

A tool belongs here if it passes all three gates:

1. **Requires Google API access** — the operation calls a Google API (Sheets, Drive, Docs, Calendar). Tools that only manipulate local data or do pure computation don't belong here.

2. **Not already coverable** — the operation is not already expressible via an existing tool (including the `batch_update` passthrough, which is the intended escape hatch for raw Sheets API operations).

3. **Atomic or justified composite** — the operation is a single logical action, OR it is a multi-step chain that is fiddly enough in practice that Claude fails or requires retries without a server-side wrapper. See [decision-composite-tools.md](decision-composite-tools.md) for the failure modes that justify a composite.

## What Doesn't Belong

- **Simple sequential chains** the AI handles correctly — if a workflow is two predictable API calls in order, Claude will chain the primitives. A wrapper adds surface area and a duplicate tool name the AI has to disambiguate.
- **Convenience aliases** — renaming or re-exposing an existing tool with different defaults is not a new tool.
- **Speculative features** — tools added because they might be useful someday. The roadmap tracks candidates; they stay there until there is a real use case.
- **Non-Google operations** — format conversion, local file transforms, computation. These belong in the client or in a separate server.

## Tool Count as a Cost

The tool list is flat. The AI sees every registered tool on every call. Each additional tool:
- Increases the chance of the AI picking the wrong one
- Makes descriptions harder to keep distinct
- Adds a parameter schema the AI has to keep straight

Prefer depth over breadth. A well-parameterized `export_file` that handles PDF, DOCX, HTML, and XLSX is better than four separate export tools.

## The `batch_update` Rule

If an operation can be expressed as a raw Sheets `batchUpdate` request, it does not automatically need a named tool. The `batch_update` passthrough exists precisely so that uncommon or one-off operations don't require a new tool. A named tool is warranted when the operation is common enough that spelling out the raw request every time is unreasonable.

## Scope Boundaries

The server covers **Google Workspace productivity tools** — the suite a person uses to write, organize, communicate, and schedule. The line is drawn at Google Cloud infrastructure and analytics, which are a different category of product serving a different purpose.

| In scope | Out of scope |
|----------|-------------|
| Google Sheets | BigQuery / BigTable |
| Google Docs | Google Analytics |
| Google Drive | Google Cloud Storage (raw GCS) |
| Google Calendar | Compute Engine / GKE / GCE |
| Google Slides | Maps / Places |
| Google Forms | Pub/Sub / Dataflow |
| Gmail | Any non-Google service |
| Google Tasks / Keep | General local file system ops |
| Google Chat | |

Not all in-scope services need to be implemented — the list above is the ceiling, not a commitment. Priority follows actual use. Adding a new Workspace service requires a decision record in `docs/` explaining the use case and estimated tool count cost.
