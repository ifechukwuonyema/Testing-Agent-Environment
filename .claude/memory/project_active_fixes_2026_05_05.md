---
name: Active Platform Fixes — REVIEW BEFORE NEXT TEST
description: Open fixes (NPML, runner, backend) tracked across the 2026-05-05 Transactions+Customer session. Surface this to the user at the start of any future Kardit test session before re-running.
type: project
originSessionId: afef7924-86e9-409e-adcd-5a4ee530f398
---
# ACTIVE FIXES — REVIEW BEFORE NEXT KARDIT TEST RUN

When the user starts ANY new Kardit test session (chain run, single-service hybrid run, or asks "let's test X"), surface this checklist BEFORE running. Confirm with them which items are still pending vs landed.

## Already shipped 2026-05-05 (locally — no re-deploy needed, just re-run picks up)

1. **NPML/canonical Postman path-templates restored** — 7 endpoints rewritten from concrete IDs back to `:param` form so runners' `PACK_TO_POSTMAN` lookups still hit. Backup at `Downloads\Kardit.Api.postman.collection.json.bak-2026-05-05`.

2. **NPML/canonical Postman pagination patch** — `POST /api/v1/customers/search` body changed from `pagination: {page:0, pageSize:0}` (invalid) to `{page:1, pageSize:20}`. Was causing pre-flight 400 + cascading 20 `A_unexpected_4xx` test failures.

3. **Customer runner extractor patch** — `extract_first_customer_ref_id_from_search` in `~\Kardit\harnesses\postman_hybrid_customer_runner.py` line 222: added `"result"` (singular) to sub-key tuple alongside existing `"items"`/`"results"`/`"customers"`. Live response shape is `data.result[]`, not `data.results[]`.

3a. **Admin / Notifications / Transactions runner extractor sweep** (2026-05-05 12:35) — same class as #3 but additive: added BOTH `"result"` and `"data"` to the sub_key tuple in `extract_first_case_id_from_list` (admin), `extract_first_notification_id_from_list` (notifications), `extract_first_transaction_id_from_query` (transactions). Validated by re-runs: Admin pre-flight FAIL→OK (real caseId derived), Transactions DEGRADED→OK (`TXN-2026-00001` derived live, no more seed fallback), Notifications stayed FAIL because the discovery call itself returns non-2xx (backend list endpoint broken — same suspected shared-dictionary bug; patch is correctly dormant until backend lands P0).

## Pending — file before/during next test session

4. **Backend recommendation for Transactions** — `Downloads\transactions_backend_recommendation_2026-05-05.md` is paste-ready for backend team.

5. **Backend recommendation for Customer** — to be drafted in same session as DOCX.

6. **Cross-service shared-bug hypothesis** — H_5xx pattern on identical exception text (`"An error occurred: The given key was not present in the dictionary."`) hits Transactions (156) AND Customer (24+).

9. **NPMC merged into canonical (2026-05-05 13:30)** — second merge cycle in same day. Source: `Downloads\NPMC.json`.

10. **Admin case-pool re-enabled with backend IDs (2026-05-05 13:30)** — `BACKEND_SUBMITTED_POOL` (4 IDs from `Downloads\BACKEND for admin.txt`) added.

11. **Customer affiliate pool + customer-detail rotation (2026-05-05 16:20)** — Phase 0e queries POST /affiliates/query → rotate_customer_uniqueness per attempt → retry on conflict.
