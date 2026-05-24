---
name: project_batch_run_20260521
description: Batch Hybrid Run 2026-05-21 — 252 TCs (203P/31F/18B, 80.6%); BATCH-08 wired; 3 harness fixes; all 31 FAILs confirmed backend auth bypass
metadata: 
  node_type: memory
  type: project
  originSessionId: c5e9fedc-d329-4c60-8f32-02637a0c5ac0
---

Final clean run: **203P/31F/18B (80.6%)** from `batch_postman_hybrid_report_20260521-144933.yaml`.

## What was done

1. **BATCH-08 wired** — `GET /api/v1/Batches` (list+filter+paginate) added: 30 TCs, PMC entry with 18 disabled query stubs, classifier block, `PACK_TO_POSTMAN` entry. Endpoint performing at 96.7%.

2. **PMC merged** — `Kardit.Api.postman_collection (9).json`:
   - `bankId` field added to upload body (now required by backend)
   - Customer seed ID swapped
   - Bodies updated for `/cards/issuance`, `/customers/search`, `/customers/draft`

3. **Harness fixes shipped:**
   - `BatchType` filter enum: `card-creation` → `CARD_CREATION`
   - `MakerUserId` filter: `"tester"` → `00000000-0000-0000-0000-000000000000`
   - Idempotency verdict: second call with 4xx accepted as PASS when `expected` mentions "rejected"

4. **Stale-pool regression found and fixed** — Pool hardcoded IDs reset on every Python restart. Fix: pool cleared between runs; user supplies fresh VALIDATED IDs per session. See [[feedback_validated_pool_single_use]].

## Per-endpoint final state

| Endpoint | Pass% | Remaining FAILs |
|---|---|---|
| BATCH-08 GET /Batches | 96.7% | 1 auth bypass |
| BATCH-05 /rows | 90.0% | 3 auth bypass |
| BATCH-04 /{batchId} | 88.2% | 4 auth bypass |
| BATCH-02 /validate | 86.7% | 2 auth bypass |
| BATCH-03 /submit | 79.4% | 5 auth bypass |
| BATCH-06 /results/download | 71.9% | 5 auth bypass |
| BATCH-01 /upload | 73.3% | 6 auth bypass |
| BATCH-07 /download/{token} | 59.4% | 5 auth bypass |

## Confirmed backend defects

- **D-BATCH-AUTH-1** (31 FAILs): Auth middleware missing on all 8 endpoints. Ceiling from 80.6% → ~92.1% when fixed.
- **18 BLOCKED are irreducible**: 7 DB/audit verify, 5 rate-limit untriggerable, 3 obsolete {batchId} path, 2 design-state, 1 event emission.

Runner: `Kardit\harnesses\postman_hybrid_batch_runner.py`
Pack: `Downloads\kardit_batch_api_test_agent_v3_1\...\batch_microservice_functional_test_pack_v3_30_each.json` (252 TCs, 8 endpoints)
