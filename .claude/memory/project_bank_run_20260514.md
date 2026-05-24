---
name: project_bank_run_20260514
description: Bank Hybrid Run 2026-05-14 — 4 harness fixes + new fixture IDs; 90P/48F/46B (48.9%); primary ceiling is auth bypass + D-BNK-PERSIST-1
metadata: 
  node_type: memory
  type: project
  originSessionId: d56186cf-7247-46f8-8575-5d294e46703f
---

Bank hybrid run 2026-05-14 (report: bank_postman_hybrid_report_20260514-185802.yaml). Scoped to 5 endpoints (CTRL-01/02, PART-01/02/03). 184 TCs: 90P/48F/46B (48.9%).

**Why:** Fresh test IDs delivered in Test Ids.txt (40 AFF-SUS-400..439 for suspend, 40 AFF-BLK-500..539 for block, 40 REQ-APP-600..639 for approve, 40 REQ-REJ-700..739 for reject).

**4 harness fixes shipped:**
1. `bank_fixtures_v2.json` rebuilt with 7 separate keys: suspend_pool/block_pool/approve_pool/reject_pool/part01_pool/already_approved_pool/already_rejected_pool
2. `_load_fixture_pools()` returns 7 deques including ALREADY_APPROVED_POOL / ALREADY_REJECTED_POOL
3. Phase 0d early-return guard: if SUSPEND_POOL and BLOCK_POOL already populated from fixture, skip live-probe override
4. Duplicate-decision pool routing: `duplicate_decision` / `duplicate_request_id` scenarios draw from ALREADY_APPROVED_POOL or ALREADY_REJECTED_POOL

**Results by endpoint:**
- CTRL-01 (suspend): 40TC 18P/5F/17B 45%
- CTRL-02 (block):   40TC 18P/5F/17B 45%
- PART-01 (get):     24TC 17P/7F/0B  71%
- PART-02 (approve): 40TC 17P/17F/6B 42%
- PART-03 (reject):  40TC 20P/14F/6B 50%

**D-BNK-PERSIST-1 confirmed with new IDs:** AFF-SUS-xxx/AFF-BLK-xxx IDs appear in GET /banks/{bankId}/affiliates but suspend/block returns 404. This is NOT a test-data problem — same defect on brand-new IDs.

**Ceiling:** Auth fix (D-BNK-AUTH-1) → +37 FAILs → 68.9%; PERSIST fix (D-BNK-PERSIST-1) → additional +12pp.

**Fixture pool status:** All IDs consumed. Next run needs fresh IDs — bank_test_data_request_20260514.txt filed.
