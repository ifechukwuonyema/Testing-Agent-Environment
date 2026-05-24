---
name: Kardit Transactions Hybrid Run 2026-05-01
description: Transactions run with classifier patches; 440 TCs (80P/349F/11B); 0 runner-side defects; service-internal split — export subsystem 65% pass rate, transaction-read subsystem 0.6%
type: project
service: Transactions
run_date: 2026-05-01
tcs: 440
passes: 80
fails: 349
blocked: 11
pass_rate: 18
worst_cluster: H 5xx on read subsystem
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
Final Transactions run, 2026-05-01 21:02 — canonical Transactions record.

## Source artifacts

- Harness: `Downloads\postman_hybrid_transactions_runner.py` (cloned from customer hybrid; pre-flight via query-first POST /transactions/{query})
- Pack: `Downloads\kardit_transactions_api_test_agent_v3_1\kardit_transactions_api_test_agent_v3_1\data\transactions_microservice_functional_test_pack_v1_40_each.json` (440 TCs)
- Swagger: `Downloads\kardit_transactions_api_test_agent_v3_1\kardit_transactions_api_test_agent_v3_1\data\swagger.json`
- Final YAML: `Downloads\transactions_postman_hybrid_report_20260501-210204.yaml`

## Counts: 440 TCs (80 PASS / 349 FAIL / 11 BLOCKED / 0 ERROR)

## Pack drifts handled (4 endpoints)

- TRX-01: pack `/cards/{cardId}` → Postman+swagger `/cards/{cardId}/transactions` (suffix)
- TRX-05: pack `/transactions/query` → Postman+swagger `/transactions/{query}` (curly braces — swagger gen quirk)
- TRX-08/09: pack `/transactions/exports/{exportId}*` → Postman+swagger `/transactions/export/{exportId}*` (singular)

## Pre-flight outcome

- POST `/transactions/{query}` returned no transactionId (DEGRADED)
- Postman literal "string" placeholder skipped
- Verify not attempted; tests proceeded without transactionId seed

## Critical finding: service-internal split

**Two halves of the same service have wildly different health** (the most informative finding of the day):

| Subsystem | Endpoints | TCs | PASS | Pass rate |
|---|---:|---:|---:|---:|
| Transaction-read | 8 | 320 | 2 | **0.6%** |
| Export | 3 | 120 | 78 | **65%** |

Export pipeline (POST export → GET status → GET download) is healthy. Transaction-read controllers/repositories are non-functional. Likely root cause: unconfigured DB connection on read path, missing service registration for read repositories, or shared middleware NRE that fires only on read pipeline.

## Top FAIL clusters

- **H — 5xx server errors: 311** (89%) — concentrated on transaction-read endpoints (273 of 311)
- **B — Backend accepts invalid: 35** — primarily on export endpoints (validation/auth gaps)
- **Z_other: 3**

## Per-endpoint highlights

- All 8 transaction-read endpoints: **0% pass rate** (every TC crashes)
- POST `/transactions/{query}`: 5% (2/40)
- POST `/transactions/export`: 55%
- GET `/transactions/export/{exportId}`: **83%** (highest pass rate observed all day)
- GET `/transactions/export/{exportId}/download`: 58%

## Engineering ownership

360/440 (82%) backend-owned. Runner residual: 0.

## Critical fix priority

1. **Read 311 stack traces** — likely 1-2 distinct stack traces shared across the 7 read endpoints (single root cause)
2. **Cluster B on export endpoints (35)** — validation/auth gaps on the working subsystem
3. **B1 DB-verifications (11)** — needs read-only verification surface
