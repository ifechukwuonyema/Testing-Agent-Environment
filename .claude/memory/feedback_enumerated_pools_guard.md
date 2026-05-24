---
name: ENUMERATED_POOLS Guard — Live Pools Must Not Be Contaminated by ACTIVE.txt
description: When Phase 0f1 live enumeration fills a status pool, ACTIVE.txt merge must be skipped for that pool
type: feedback
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
When Phase 0f1 live enumeration (`GET /api/v1/cards?status=S`) fills `cardIdActivePool` (and other status pools), the ACTIVE.txt loader merge loop must skip those pools entirely.

**Why:** ACTIVE.txt is a static legacy file that is never reset between runs. Cards listed there get TERMINATED over time. Merging ACTIVE.txt into a live-enumerated pool injects stale TERMINATED cardIds, causing endpoints like freeze/unfreeze/load to fail with "Only ACTIVE cards can be frozen. Current status is TERMINATED."

**How to apply:** The guard is implemented as a set `ENUMERATED_POOLS = {"cardIdActivePool", "cardIdFrozenPool", ...}` checked inside the ACTIVE.txt merge loop. Any time a new status pool is added to Phase 0f1 enumeration, add it to `ENUMERATED_POOLS`. Never bypass this guard as a workaround for a "low pool size" problem — probe live instead.
