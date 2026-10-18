# Comparison: Hosted Postgres Providers

We evaluated three providers for the analytics database. Prices are list prices
for a 4 vCPU / 16 GB instance with 500 GB storage, as of October 2026.

## At a glance

| | Provider A | Provider B | Provider C |
|:--|:--:|:--:|:--:|
| Monthly cost | $410 | $365 | $520 |
| Point-in-time recovery | ✅ 30 days | ✅ 7 days | ✅ 35 days |
| Read replicas | Up to 5 | Up to 3 | Up to 10 |
| Private networking | ✅ | ❌ | ✅ |
| Postgres 17 | ✅ | Preview | ✅ |
| SOC 2 Type II | ✅ | ✅ | ✅ |

## Detailed notes

### Provider A

**Pros**

- Mature tooling and a good CLI
- Private networking included at no extra cost

**Cons**

- Read replicas cost the same as the primary
- Support response times are slow on the standard plan

### Provider B

**Pros**

- Cheapest option
- Very fast provisioning (under 2 minutes)

**Cons**

- *No private networking*, which our security policy requires
- Postgres 17 is still in preview

### Provider C

**Pros**

- Best replica story (up to 10, cross-region)
- Longest PITR window

**Cons**

- Most expensive, by about 27% over Provider A

## Scoring

| Criterion | Weight | A | B | C |
|---|--:|--:|--:|--:|
| Cost | 30% | 7 | 9 | 5 |
| Reliability | 30% | 8 | 6 | 9 |
| Security fit | 25% | 9 | 2 | 9 |
| Operability | 15% | 8 | 7 | 8 |
| **Weighted total** | | **7.95** | **6.05** | **7.65** |

## Recommendation

Go with **Provider A**. Provider B fails our private-networking requirement, and
Provider C's extra replica capacity doesn't justify the cost at our current scale.
Revisit if we need more than 5 replicas.
