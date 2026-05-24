---
name: Kardit Customer Hybrid Run 2026-05-01
description: Customer run with classifier+B3 fixes; 120 TCs (14P/103F/3B); 0 runner-side defects; backend health CATASTROPHIC — 100% of FAILs are 500 server errors; only required-field validator works
type: project
service: Customer
run_date: 2026-05-01
tcs: 120
passes: 14
fails: 103
blocked: 3
pass_rate: 12
worst_cluster: H 5xx (100% of FAILs)
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
Final Customer run, 2026-05-01 19:30 — canonical Customer record.

## Source artifacts

- Harness: `Downloads\postman_hybrid_customer_runner.py` (cloned from admin hybrid; pre-flight via search-first POST /customers/search)
- Postman: 3 of 3 endpoints present, but 2 path drifts vs pack remapped via PACK_TO_POSTMAN
- Pack: `Downloads\kardit_customer_api_test_agent_v3_1\kardit_customer_api_test_agent_v3_1\data\customer_microservice_functional_test_pack_v1_40_each.json` (120 TCs)
- Final YAML: `Downloads\customer_postman_hybrid_report_20260501-193001.yaml`

Base URL: `http://167.172.49.177:8080`. Auth: none.

## Counts: 120 TCs (14 PASS / 103 FAIL / 3 BLOCKED / 0 ERROR)

## Pack drifts handled

- Pack `POST /api/v1/customers/drafts` → Postman+swagger `POST /api/v1/customers/draft` (singular)
- Pack `GET /api/v1/customers/{customerId}` → Postman+swagger `GET /api/v1/customers/{customerRefId}` (different param name)

Pack is wrong on both; PACK_TO_POSTMAN remaps directly. SEEDED_PATH_VAR_KEYS aliases `customerId` and `customerRefId`.

## Pre-flight outcome

- POST `/customers/search` with empty criteria: 200 OK but `cases:[]` (DEGRADED — no customer in DB)
- Postman literal customerRefId is `"string"` (placeholder, rejected)
- Verify not attempted; tests proceeded with `customerRefId="string"` literal

## Critical finding: 100% of FAILs are 5xx

**ALL 103 FAILs are 500 server errors** — single cluster H total dominance. Customer service is in catastrophic state.

| Endpoint | P | F | B | Pass rate |
|---|---:|---:|---:|---:|
| POST `/customers/draft` | 13 | 26 | 1 | 33% |
| POST `/customers/search` | 0 | 39 | 1 | **0%** (every input crashes) |
| GET `/customers/{customerRefId}` | 1 | 38 | 1 | 2.5% |

## The 14 PASSes

All are `missing_*_rejected` / `blank_*_rejected` validation TCs on POST `/customers/draft` — required-field validator (tenantId/affiliateId/firstName) works and returns clean 400. Validation runs first, then crashes after — same pattern observed across the catastrophic-tier services.

## Engineering ownership

106/120 (88%) backend-owned. Runner residual: 0.

## Critical fix priority

1. **POST `/customers/search` is unconditionally broken** (0/40) — likely NRE/DI failure firing before request handling. Single highest-leverage fix.
2. **Read 103 stack traces** in `Downloads\evidence_postman_customer_hybrid_20260501-193001\` — every triggering body present.
3. **Shared crash surface suspected** — DTO/middleware/request-context binding crashes pre-controller across all 3 endpoints.
4. **Test env needs at least one customer record** — pre-flight discovery returned empty list.
