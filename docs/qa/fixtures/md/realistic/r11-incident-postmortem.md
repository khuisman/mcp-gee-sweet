# Postmortem: Checkout Outage on October 9

**Severity:** SEV-1
**Duration:** 47 minutes (14:12–14:59 UTC)
**Impact:** ~18% of checkout attempts failed; estimated $42k in delayed orders

## Summary

A configuration change raised the payment service's connection pool from 50 to
500. The database hit its connection limit within minutes, and checkout requests
started timing out.

## Timeline (UTC)

| Time | Event |
|------|-------|
| 14:05 | Config change merged and deployed |
| 14:12 | Error rate alert fires for `payments-api` |
| 14:18 | On-call acknowledges, starts investigating |
| 14:31 | Database connection saturation identified |
| 14:44 | Config change reverted |
| 14:59 | Error rate back to baseline |

## Root cause

The pool size is set **per pod**, not per service. With 10 pods, the change
meant 5,000 potential connections against a database limit of 1,000.

```yaml
# payments-api/config.yaml (the bad change)
db:
  pool_size: 500   # was 50
```

## What went well

- Alerting fired within 7 minutes
- The revert path was fast and well understood

## What went poorly

- The change had no review from the database team
- The config file has no comment explaining that `pool_size` is per pod
- It took 13 minutes to connect the errors to the database

## Action items

| # | Action | Owner | Due |
|---|--------|-------|-----|
| 1 | Add a CI check that caps `pool_size × replicas` | Platform | Oct 23 |
| 2 | Comment `pool_size` semantics in the config | Payments | Oct 16 |
| 3 | Add a DB-connections panel to the payments dashboard | SRE | Oct 20 |
| 4 | Require DB-team review for pool changes | Eng leads | Oct 30 |

## Lessons

1. Per-instance settings need the multiplier spelled out next to them.
2. A dashboard panel for the shared resource would have cut diagnosis time:
   - connections in use
   - connections waiting
   - rejected connections
