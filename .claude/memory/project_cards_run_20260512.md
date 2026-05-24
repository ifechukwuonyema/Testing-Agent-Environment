---
name: Cards Hybrid Run 2026-05-12
description: Full run results + 3 harness fixes shipped; 779 TCs at 57.8%; schema drift catalogue; FUL-03 data gap documented
type: project
service: cards
run_date: 2026-05-12
tcs: 779
passes: 450
fails: 140
blocked: 189
pass_rate: 57.8
originSessionId: f1d2538a-d992-4d2c-b706-84c5fe821fa8
---
Previous baseline: 837 TCs, 464P (55.4%) — 2026-05-08

## Three harness fixes shipped this session

**Fix 1 — State-machine evaluator (4xx = PASS):** `evaluate()` now recognises enforcement scenarios as correctly expecting 4xx. Converted **12 FAILs → PASS**.

**Fix 2 — FUL-03 reinitiate sentinel:** When `cardIdFailedFulfillmentPool` is empty, returns sentinel `__NO_FAILED_FULFILLMENT_CARD__` → BLOCKED. **19 happy-path FAILs → BLOCKED**.

**Fix 3 — fulfillmentStatus is a sub-status, not top-level:** Removed `FAILED` from `STATUS_TO_POOL`. Added Phase 0f3b probe.

## Schema drift catalogue

| TC | Endpoint | Expects | Backend sends | Type |
|---|---|---|---|---|
| FRZ-01-030 | POST /freeze | `timestamp` | `frozenAt` | Z2 rename |
| UNF-01-030 | POST /unfreeze | `timestamp` | `unFrozenAt` | Z2 rename |
| FUL-02-030 | POST /fulfillment/refresh | `timestamp` | `updatedAt` | Z2 rename |
| CARD-13-022 | POST /cards/query | `cardType` | `productType` | Z2 rename |
| ISS-04-017 | GET /funding-details | `virtualAccountStatus` (flat) | `virtualAccount.status` (nested) | Z2 nesting |

## FUL-03 data gap

`cardIdFailedFulfillmentPool = 0`. Probe checked all 81 ACTIVE cards — none have `fulfillmentStatus: failed`. Backend must provision ACTIVE PHYSICAL cards with `fulfillmentStatus: failed`.

## Remaining 140 FAIL root causes
- ~50-60: auth pipeline (D-CARDS-1)
- ~30: terminate pool exhaustion (state cascade)
- ~10: pin-reset state issues
- 6: schema drift Z2 renames
