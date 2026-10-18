# Interview Guide: Senior Backend Engineer

Use this guide for the 60-minute system design interview. Score each area from
1 (no signal) to 4 (strong hire signal).

## Before the interview

- Read the candidate's résumé and the recruiter's notes
- Pick **one** prompt from the list below; don't change it mid-interview
- Have the scorecard open in another tab

## Prompts

1. **URL shortener at scale**
   1. Start with the API and data model
   2. Move to read/write ratios and caching
   3. Finish with analytics and abuse prevention
2. **Notification service**
   1. Fan-out on write vs. fan-out on read
   2. Delivery guarantees and retries
   3. User preferences and quiet hours
3. **Rate limiter**
   1. Algorithms: token bucket, sliding window
   2. Distributed coordination
   3. Failure modes when the store is down

## What good looks like

- Asks clarifying questions before drawing anything
- States assumptions out loud, e.g. *"I'll assume 100:1 reads to writes"*
- Discusses trade-offs, not just one design
  - Names at least one alternative
  - Explains when they'd switch to it
- Estimates rough numbers (QPS, storage) without being asked

## Red flags

- Jumps straight to a specific vendor's product
- Can't explain how their own design fails
- Dismisses operational concerns ("we'll just add monitoring")

## Scorecard

| Area | 1 | 2 | 3 | 4 |
|------|---|---|---|---|
| Requirements gathering | | | | |
| High-level design | | | | |
| Deep dive | | | | |
| Trade-offs | | | | |
| Communication | | | | |

## After the interview

1. Fill in the scorecard within **one hour**.
2. Write two or three sentences of evidence per area.
3. Don't discuss the candidate with other interviewers until everyone has submitted.
