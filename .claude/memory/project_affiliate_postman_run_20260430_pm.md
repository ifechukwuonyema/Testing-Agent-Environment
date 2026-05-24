---
name: Kardit Affiliate Postman-Driven Standalone Run 2026-04-30 (PM)
description: Findings from Postman-driven standalone Affiliate API test pass — 920 TC slots, 98 PASS / 434 FAIL / 388 BLOCKED; surfaced contract drift, backend-accepts-invalid defects, and 5xx instability under negative inputs
type: project
service: Affiliate
run_date: 2026-04-30
tcs: 920
passes: 98
fails: 434
blocked: 388
pass_rate: 11
worst_cluster: Z1 envelope + state-endpoint-zero-pass
originSessionId: 506fc878-81d5-47e4-95a1-58c711c395e6
---
Source artifacts (live at time of run):
- Postman: `C:\Users\Onyema Ifechukwu\Downloads\Kardit.Api.postman.collection.json` (Kardit.Api collection, 81 endpoints across all services, 1 request each)
- Test pack: `kardit_affiliate_api_test_agent_v3_1\data\affiliate_microservice_functional_test_pack_v1_40_each_exact.json` (23 endpoints × 40 TCs = 920)
- Swagger: `kardit_affiliate_api_test_agent_v3_1\data\swagger.json`
- Harness: `Downloads\postman_standalone_runner.py`
- Report: `Downloads\affiliate_postman_standalone_report_20260430-154106.yaml` (~11MB)
- Evidence: `Downloads\evidence_postman_affiliate_20260430-154106\` (532 JSON files)

Base URL: `http://167.172.49.177:8080`. Auth: none (per user direction).

## Coverage decisions (locked in by user before run)
- **Path-prefix drift** (7 onboarding endpoints + partnership-requests/query): pack uses `/api/v1/onboarding/...`, Postman uses `/api/v1/affiliates/onboarding/...` — treat as match, flag in `contract_drift_findings`.
- **API-ONB-06 method mismatch**: pack `GET /api/v1/onboarding/cases/{caseId}`, Postman `POST /api/v1/affiliates/onboarding/cases/{caseId}` — run as POST per Postman.
- **API-AUD-01 path drift**: pack `POST /api/v1/audit-logs`, Postman `POST /api/v1/banks/{bankId}/audit-logs` — same endpoint per user.
- **API-AFF-03** (`GET /api/v1/affiliates/{affiliateId}`): no Postman entry → all 40 TCs BLOCKED.

## Real defect classes surfaced (from FAIL distribution)
- **Backend 5xx under invalid input (113 cases)**: backend returns 500/503 when test pack expects 4xx. Should be defensive validation, not crash.
- **Backend accepts invalid (33 cases)**: backend returns 200 when expecting 400/422 — contract violations not enforced (e.g. happy-path mutations like `missing_X` returned success).
- **No-auth backend open (10 cases)**: returns 200 where test pack expects 401 — confirms "no auth enforced" environment, but means auth-protected scenarios will need a separate auth-on run.
- **Happy path 404 (22 cases)**: real Postman IDs returning 404 → either Postman data is stale OR endpoint path is wrong. Spot-check evidence files for these to triage which.
- **Already-exists 409 (2 cases observed; likely more in OTHER bucket)**: Postman happy-path POSTs hitting "entity already created" because real DB data exists — this is *expected*, not a defect.

## Endpoint-level summary
Best (executed cases per endpoint):
- `PUT /api/v1/affiliates/onboarding/drafts/{draftId}/organization` (API-ONB-02): 17 PASS / 13 FAIL
- `GET /api/v1/admin/onboarding/cases` (API-ONB-07): 26 PASS / 7 FAIL
- `POST /api/v1/admin/onboarding/cases/{caseId}/decision` (API-ONB-08): 11 PASS / 13 FAIL

Worst (zero passes despite executing):
- `POST /api/v1/affiliates/{affiliateId}/suspend` (API-AFF-04): 0 PASS / 16 FAIL
- `POST /api/v1/affiliates/{affiliateId}/block` (API-AFF-06): 0 PASS / 16 FAIL
- `POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend` (API-AFF-14): 0 PASS / 16 FAIL
- `POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/block` (API-AFF-15): 0 PASS / 16 FAIL
- `POST /api/v1/partnership-requests/query` (API-AFF-09): 0 PASS / 29 FAIL
- `POST /api/v1/partnerships/{requestId}/approve` & `/reject` (API-AFF-10/11): 0 PASS / 16 FAIL each

The state-mutation endpoints (suspend/block/approve/reject) all returning zero passes is suspicious — likely state-precondition issues (the affiliates from Postman are not in the right starting state, or the state transitions return non-2xx codes the pack doesn't list).

## Methodology gotcha (worth remembering)
Mutation engine v1 (with ~10 patterns) only achieved 9 PASS / 185 FAIL / 726 BLOCKED. v2 (with ~30 patterns including `null_X`, `malformed_X`, `*_too_long`, `pagination_*`, `script_*`, `empty_body`, `wrong_content_type`, response-shape recognizer) achieved the final 98/434/388. The pack's scenario naming has 200+ distinct patterns; reach diminishing returns past ~30 patterns (~5% remain unrecognized in fallback).

## Postman collection scope note
Kardit.Api collection contains 81 endpoints spanning Affiliate, Cards, Transactions, Batches, Customers, Ops, Notifications. For Affiliate runs, only the affiliate-scoped subset is used. Same collection can drive runs for other services by swapping the test pack and match-map.

## Reusable for future Postman-driven runs
The harness at `Downloads\postman_standalone_runner.py` is generic for any Kardit service — change `TEST_PACK_PATH`, `SWAGGER_PATH`, and `PACK_TO_POSTMAN` map at top of file.
