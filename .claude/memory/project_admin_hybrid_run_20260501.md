---
name: Kardit Admin Services Hybrid Run 2026-05-01
description: Admin run with classifier+B7 fixes; 123 TCs (53P/61F/9B); 0 runner-side defects; backend health: list endpoint silently accepts invalid input (Cluster B); /admin/banks 100% crash rate
type: project
service: Admin
run_date: 2026-05-01
tcs: 123
passes: 53
fails: 61
blocked: 9
pass_rate: 43
worst_cluster: H 5xx on /admin/banks
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
Final Admin run, 2026-05-01 18:55 — canonical Admin record.

## Source artifacts (live at time of run)

- Harness: `Downloads\postman_hybrid_admin_runner.py` (cloned from Bank hybrid; pre-flight via list-first GET /admin/onboarding/cases)
- Findings DOCX generator: `Downloads\generate_admin_findings_docx.py`
- Postman: `Downloads\Kardit.Api.postman.collection.json` (all 4 admin endpoints present)
- Pack: `Downloads\admin_services_api_test_agent_v1\admin_services_api_test_agent\data\admin_services_functional_test_pack_v1_30_plus.json` (123 TCs)
- Master swagger: `Downloads\kardit_api_test_agent\kardit_api_test_agent\data\swagger.json` (covers admin endpoints)
- Final YAML: `Downloads\admin_postman_hybrid_report_20260501-185548.yaml`
- Findings DOCX: `Downloads\admin_findings_with_fixes_2026-05-01.docx`

Base URL: `http://167.172.49.177:8080`. Auth: none. Run mode: `postman_hybrid_admin`.

## Counts: 123 TCs (53 PASS / 61 FAIL / 9 BLOCKED / 0 ERROR)

Cluster-C reclassified: 0 (test env has zero onboarding cases — list-first discovery returned 200 but `cases:[]`; fallback to Postman literal failed verify; but no FAIL was 404, so reclassification didn't fire).

## In-scope runner defects: 0

Only 9 BLOCKED remain — all backend-owned B1 DB-verifications.

## Top FAIL clusters

- **H — 5xx server errors: 22** — ALL on `POST /api/v1/admin/banks`. Every mutation crashes the bank-provisioning endpoint.
- **G — Happy-path 4xx: 16** — provision (10) + decision (5) + banks (1). Likely state-machine guards rejecting valid bodies (case not in required state).
- **Z_other (auth-pipeline-order): 12** — auth tests expecting 401/403 got 400 instead. Backend validates body before checking auth, returns 400 first.
- **B — Backend accepts invalid: 11** — ALL on `GET /api/v1/admin/onboarding/cases`. List endpoint silently returns 200 for `page=0`, `negative_page`, missing auth, etc. No validation, no auth gate.

## Per-endpoint (P / F / B)

| Endpoint | P | F | B | Notes |
|---|---:|---:|---:|---|
| GET `/admin/onboarding/cases` | 16 | 12 | 2 | Cluster B dominant — list endpoint takes any input, no auth |
| POST `/admin/onboarding/cases/{caseId}/decision` | 15 | 11 | 4 | Auth-pipeline-order + state-dependent |
| POST `/admin/onboarding/cases/{caseId}/provision` | 15 | 15 | 1 | State-dependent (case not APPROVED) |
| POST `/admin/banks` | 7 | 23 | 2 | **22 × 5xx — endpoint crashes on every mutation** |

## Engineering ownership

114/123 (93%) backend-owned: 61 FAIL + 9 B1 BLOCKED, with only ~0 runner-side residual.

## Recommended fix order

1. **POST `/admin/banks` exception handling** — single try/catch refactor closes 21+ × 5xx FAILs
2. **GET `/admin/onboarding/cases` validation + auth gate** — closes 11 × Cluster B
3. **Auth pipeline ordering** — auth before body validation (12 × Z_other)
4. **Test env hygiene** — populate cases in each lifecycle state to enable decision/provision testing
