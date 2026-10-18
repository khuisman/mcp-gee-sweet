# PRD: Saved Searches

**Status:** Draft
**Author:** Product team
**Last updated:** 2026-10-12

---

## 1. Problem

Users repeat the same searches every day. Today they retype the query and
re-apply filters each time, which takes about 40 seconds per search based on
session recordings.

## 2. Goals and non-goals

### Goals

- Let a user save a search (query + filters + sort) with a name
- Show saved searches in the sidebar
- Notify the user when new results match a saved search

### Non-goals

- Sharing saved searches with other users (v2)
- Saved searches on mobile (v2)

## 3. User stories

1. As an analyst, I want to save a search so that I can rerun it in one click.
2. As an analyst, I want to rename or delete a saved search.
3. As a manager, I want a daily email digest of new matches.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Priority |
|:---|:------------|:--------:|
| F1 | Save the current search with a name (max 80 chars) | P0 |
| F2 | List saved searches, most recent first | P0 |
| F3 | Rename and delete a saved search | P1 |
| F4 | Daily digest email for new matches | P2 |

### 4.2 Non-functional

- Saving a search must complete in under **200 ms** (p95)
- A user can have at most 50 saved searches

## 5. API

The client calls a new endpoint:

```http
POST /api/v1/saved-searches
Content-Type: application/json

{"name": "Open P1 bugs", "query": "priority:P1 status:open", "sort": "updated"}
```

The response includes the new search's `id` and `created_at`.

## 6. Open questions

- Should the digest respect the user's timezone or the account's?
- Do we cap digest frequency for searches with hundreds of new matches?

## 7. Appendix

See the [search architecture doc](https://example.com/search-arch) and the
[analytics dashboard](https://example.com/dash "Search analytics").
