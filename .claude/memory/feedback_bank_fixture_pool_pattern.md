---
name: feedback_bank_fixture_pool_pattern
description: Bank runner fixture pool pattern — 7-key JSON + Phase 0d early-return guard + duplicate-decision routing
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d56186cf-7247-46f8-8575-5d294e46703f
---

Bank runner must use 7 separate fixture pool keys in bank_fixtures_v2.json: suspend_pool, block_pool, approve_pool, reject_pool, part01_pool, already_approved_pool, already_rejected_pool. Phase 0d must early-return if SUSPEND_POOL and BLOCK_POOL are pre-loaded (skip live-probe override). Duplicate-decision / duplicate_request_id scenarios must route to ALREADY_APPROVED_POOL (approve) or ALREADY_REJECTED_POOL (reject), NOT the fresh PENDING pool.

**Why:** Prior runs had Phase 0d overwriting fixture-designated SUS/BLK pools with 50/50-split live probes, destroying the non-overlapping designation. Duplicate-decision TCs need already-settled IDs; fresh PENDING IDs → backend processes them and returns 200 where 409 is expected, causing wrong-classification FAILs.

**How to apply:** Any bank harness edit touching _load_fixture_pools or Phase 0d must preserve these invariants. When backend delivers new IDs, load them into the 7-key JSON structure. If Test Ids.txt format is reused, parse by section header exactly. The already_approved/already_rejected pools are 1-entry each — rotate(-1) is safe (loops on itself).
