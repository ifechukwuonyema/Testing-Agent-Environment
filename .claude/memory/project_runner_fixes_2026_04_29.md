---
name: Kardit All-Runner Fix Session 2026-04-29
description: Ship-ready fixes applied to all 8 Kardit test runners to match swagger contract + live backend corrections 2026-04-30
type: project
originSessionId: 0411d92a-9f5c-409d-9909-039a9cddde3b
---
All 8 runners fixed in session 2026-04-29. Auth is `type: none` across all runners.
Affiliate runner additionally corrected 2026-04-30 after live backend testing revealed path/payload mismatches.

**What was fixed and why:**

Affiliate runner:
- Added `_AFF_PATH_MAP` + `normalize_aff_path()`: maps old SRS paths (`/api/v1/onboarding/...`) to swagger-correct paths (`/api/v1/affiliates/onboarding/...`)
- `POST /api/v1/admin/onboarding/cases` → overridden to GET; body fields converted to query params
- `POST /api/v1/affiliates`: `onboardingCaseId` popped from body and sent as `caseId` query param
- Added null data check in `classify()`

Bank runner:
- Removed "dashboard", "kpi", "metrics" from manual_terms (was blocking all dashboard tests)
- Added `_BANK_PATH_MAP`: suspend/block now include `{bankId}` in path per swagger
- Added `_BANK_METHOD_OVERRIDES`: audit-logs and reports are POST (not GET) per swagger
- Added POST payloads for `/api/v1/banks/{bankId}/audit-logs` and `.../reports` in payload_overrides
- Added null data check in `classify()`

Customer runner:
- Added `normalize_cust_path_and_method()`: search→POST, /drafts→/draft (singular per swagger)
- Search criteria restructured: `{requestContext, criteria:{name,phone,customerRefId,idNumber}, pagination}` — removed email/idType/kycStatus/kycLevel (not in swagger)
- Draft field paths fixed: `contact.phone`→`customer.identity.phone`, `contact.email`→`customer.identity.email`, `address.addressLine`→`customer.identity.address.line1`
- Added `query` param to `request()` and wired up in `run_tc()`
- Added POST /api/v1/customers/search payload to payload_overrides
- Added null data check in `classify()`

Transactions runner:
- Removed "download", "file", "export lifecycle" from manual_terms (was blocking all export/download tests)
- Added `normalize_trx_path()`: fixes `/transactions/exports/` → `/transactions/export/` (singular) and `/{query}` → `/query`
- Fixed pagination: `page` → `pageNumber` in mutate_payload and payload_overrides
- Removed `filters.cardId` from payload_overrides (not in swagger Filters schema)
- Added null data check in `classify()`

Batch runner:
- Fixed `json_base64_upload_payload()`: now uses swagger-correct `{requestContext, productId, file:{fileName,contentType,fileBase64}}` from payload_overrides, injecting real file bytes
- Fixed `make_payload()`: replaced overbroad `payload = {}` (triggered by any "missing" in scenario name) with targeted field removal per scenario keyword
- Config: `upload.mode: multipart` → `upload.mode: json`
- Added null data check in `classify()`

Admin runner:
- Fixed `config.yaml`: `base_url: http://localhost:8080` → `http://167.172.49.177:8080`

Notifications runner:
- Removed "notification" from manual_terms in `classify()` (was blocking nearly all notification tests)
- Added null data check in `classify()`

**How to apply:** All runners are now ship-ready. Run each runner's `api_test_runner.py` directly. Evidence files land in `evidence/`, reports in `reports/`.
