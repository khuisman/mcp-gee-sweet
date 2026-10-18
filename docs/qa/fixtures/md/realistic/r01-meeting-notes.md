# Weekly Sync — Platform Team

**Date:** October 14, 2026
**Attendees:** Priya, Marcus, Dana, Leo
**Facilitator:** Dana

## Agenda

1. Review last week's action items
   - Migration script (Marcus) — done
   - Load test results (Leo) — still running
2. Q4 roadmap check-in
   - Confirm scope for the search rewrite
   - Decide whether the billing export slips to January
3. On-call rotation changes
4. Open floor

## Discussion

### Q4 roadmap

The team agreed the search rewrite stays in scope. Priya raised a concern that the
indexing service has **no owner** after the reorg, and that this is the biggest risk
to the date.

> "If nobody owns indexing by November 1st, we should cut the faceted filters."
> — Priya

Marcus pointed out that the billing export is *mostly* done and only blocked on the
finance team's sign-off.

### On-call

- Move to a **one-week** rotation starting November 3
- Secondary on-call becomes optional for weekends
- Leo will update the [rotation calendar](https://example.com/oncall)

## Decisions

| Topic | Decision | Owner |
|---|---|---|
| Search rewrite | Stays in Q4 scope | Priya |
| Billing export | Ship in December if finance signs off by Nov 15 | Marcus |
| On-call | One-week rotation from Nov 3 | Leo |

## Action items

- [ ] Find an owner for the indexing service — **Dana**
- [ ] Send finance the export spec — **Marcus**
- [x] Book the Q4 planning room — **Leo**
- [ ] Update the on-call runbook — **Leo**

*Next meeting: October 21, same time.*
