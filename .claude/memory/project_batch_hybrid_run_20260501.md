---
name: Kardit Batch Hybrid Run 2026-05-01
description: Batch run with classifier+B7+B9+Z fixes; 177 TCs (102P/70F/5B); 0 runner-side defects; backend HEALTHIEST observed today — zero 5xx, real working batch lifecycle, single Cluster-B refactor closes most FAILs
type: project
service: Batch
run_date: 2026-05-01
tcs: 177
passes: 102
fails: 70
blocked: 5
pass_rate: 58
worst_cluster: B (zero 5xx)
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
Final Batch run, 2026-05-01 22:31 — canonical Batch record.

## Source artifacts

- Harness: `Downloads\postman_hybrid_batch_runner.py` (cloned from transactions hybrid; pre-flight mints fresh batchId via POST /Batches/card-creation/upload)
- Pack: `Downloads\kardit_batch_api_test_agent_v3_1\kardit_batch_api_test_agent_v3_1\data\batch_microservice_functional_test_pack_v3_30_each.json` (177 TCs)
- Swagger: `Downloads\kardit_batch_api_test_agent_v3_1\kardit_batch_api_test_agent_v3_1\data\swagger.json`
- Final YAML: `Downloads\batch_postman_hybrid_report_20260501-223110.yaml`

## Counts: 177 TCs (102 PASS / 70 FAIL / 5 BLOCKED / 0 ERROR)

**Best single service result of the day. 58% PASS rate, zero 5xx.**

## Pack drift handled (uniform)

- All 6 endpoints: pack `/api/v1/batches/*` → Postman+swagger `/api/v1/Batches/*` (capitalization)

## Pre-flight outcome — first SUCCESSFUL mint of the day

- POST `/Batches/card-creation/upload` minted fresh batchId `31a8b552-c866-4784-bd0b-51b81c73387b`
- Verify GET `/Batches/{batchId}` returned 200 on attempt 1 (`verified=True`)
- Persisted to SessionStore

## Z fix applied

GET `/Batches/{batchId}/rows` requires `Page` + `PageSize` query params; Postman base lacked them. Added pre-loop injection: when path contains `/rows` and method is GET, inject `Page=1&PageSize=10` if missing. Eliminated 5 × 400 FAILs from the rows endpoint, flipped /rows from 3P/5F/22B → 14P/16F/0B.

## Top FAIL clusters (70 total)

- **B — Backend accepts invalid: 54** (77%) — concentrated on POST /upload + GET /rows + GET /results/download. Validation/auth gaps on upload + read endpoints.
- **Z2 — Response-shape no parseable expected: 12** — paired with Cluster B; auto-resolves when B is fixed.
- **G — Happy-path 4xx: 2**
- **Z_other: 2**
- **H — 5xx server errors: 0** ⭐ — first service today with this property

## Per-endpoint (P / F / B)

| Endpoint | P | F | B | Pass rate |
|---|---:|---:|---:|---:|
| POST `/Batches/card-creation/upload` | 6 | 22 | 2 | 20% |
| POST `/Batches/{batchId}/validate` | 24 | 4 | 2 | **80%** ⭐ |
| POST `/Batches/{batchId}/submit` | 19 | 9 | 1 | 66% |
| GET `/Batches/{batchId}` | 22 | 6 | 0 | 79% |
| GET `/Batches/{batchId}/rows` | 14 | 16 | 0 | 47% |
| GET `/Batches/{batchId}/results/download` | 17 | 13 | 0 | 57% |

## The 5 BLOCKED — all backend-owned

- TC-API-BATCH-01-026 / 01-030 (upload-side audit/persistence verifications)
- TC-API-BATCH-02-029 / 02-030 (validate-side audit assertions)
- TC-API-BATCH-03-028 (submit-side persistence check)

All B1 DB-verifications. Runner residual: 0.

## Engineering ownership

75/177 (42%) backend-owned. Best ratio of the day — most non-PASS results concentrated in a single fixable defect class on a healthy service.

## Critical fix priority

1. **Auth gate on GET `/rows` and `/results/download`** — multiple 401/403-expected scenarios returning 200
2. **Upload validation** — required-field validation on POST /upload payload
3. **One server-side validation pass** closes 54 × Cluster B FAILs
4. **B1 DB-verifications (5)** — provide audit-log read endpoint or DB access

## Why batch is the gold standard

Pre-flight worked. Verify worked. Validate endpoint at 80% pass rate proves the validation logic IS in place when implemented. Zero crashes across all 6 endpoints. The Cluster-B issues are conventional "trust client input too much" defects that are well-understood and fixable.
