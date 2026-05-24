# Backend Ask — Affiliate Onboarding Flow Defects Blocking Admin Case-Pool Test Coverage

**Filed:** 2026-05-05
**Filed by:** API testing harness team
**Severity:** HIGH — blocks ~13 of 47 admin FAILs from being recovered into PASS
**Status:** Open

## Summary

Two endpoints in the affiliate onboarding 5-step flow are non-functional on the live backend (`http://167.172.49.177:8080`). The flow is the only known path for an external test harness to mint a fresh `caseId` for the admin onboarding service. Without it, every admin decision/provision happy-path test must reuse a single seeded `caseId`, which the first happy-path TC consumes (state-machine transition), causing all subsequent same-pack happy-paths to fail with state-conflict 4xx.

The admin runner has the case-pool patch implemented (`postman_hybrid_admin_runner.py` Phase 0c/0d, currently disabled at `N_SUBMITTED_POOL = 0`), but cannot be activated until both endpoints below are fixed.

## Defect 1 — `POST /api/v1/affiliates/onboarding/drafts/{draftId}/documents` returns 500

**Reproduce:**
```
1. POST /api/v1/affiliates/onboarding/sessions
   { "channel": "web", "email": "<unique>", "phone": "<unique>", "consentAccepted": true }
   -> 200, returns { onboardingSessionId, draftId, expiresAt }

2. PUT /api/v1/affiliates/onboarding/drafts/{draftId}/organization
   <Postman literal body with rotated registrationNumber/legalName/tradingName>
   -> 200

3. POST /api/v1/affiliates/onboarding/drafts/{draftId}/documents
   { "onboardingSessionId": "<from step 1>", "docType": "CERTIFICATE_OF_INCORPORATION",
     "fileName": "test.pdf", "contentType": "application/pdf",
     "fileBase64": "<minimal valid PDF, ~200 bytes>" }
   -> 500 "Internal server error"
```

**Tested with:**
- Postman literal body (large base64 PDF from existing collection): **500**
- Minimal valid PDF (`%PDF-1.4` header + xref + EOF, ~200 bytes): **500**

**Expected:** 200/201 with documentId persisted to draft so subsequent submit can find it.

**Impact:** Step 5 (`/submit`) returns `422 "Missing required fields: No Required documents found"`.

## Defect 2 — `PUT /api/v1/affiliates/onboarding/drafts/{draftId}/issuing-banks` rejects every known bankId form

**Reproduce:** After steps 1–2 above, attempt step 4 with each form of `bankId`:
```
PUT /api/v1/affiliates/onboarding/drafts/{draftId}/issuing-banks
{ "onboardingSessionId": "<sess>", "selectedBanks": [{ "bankId": "<X>" }] }
```

| `bankId` value | Source | Response |
|---|---|---|
| `"TBK-001"` | Postman literal in current collection | **404** "Bank TBK-001 not found or not eligible." |
| `"724a1100-b10a-4e21-b106-1feac4a75616"` | Real UUID from `POST /api/v1/banks/query` (status=ACTIVE) | **404** "Bank 724a1100... not found or not eligible." |
| `"012233"` | `bankCode` from same `/banks/query` response | **500** "Internal server error" |

**Issue:** No documented contract for what the `selectedBanks[].bankId` field expects. There is no `GET /api/v1/affiliates/onboarding/banks` (or similar) endpoint in the Postman collection or via probe to discover eligibility-qualified banks.

**Expected:** Either
- (a) Document the eligibility contract (which IDs from `/banks/query` are "issuing-eligible" + the canonical ID format for this field), OR
- (b) Add `GET /api/v1/affiliates/onboarding/eligible-banks` (or similar) returning the listing of banks valid for this field.

**Impact:** Step 4 fails, step 5 (`/submit`) returns `422 "Missing required fields: No Selected banks found"`.

## Combined Impact on Test Coverage

| Metric | Today | After fix (case-pool re-enabled at N=4 + N=9) |
|---|---|---|
| Admin pass rate | 55.3% (68/123) | ~70.7% (87/123) |
| Admin G_4xx_where_2xx_expected cluster | 15 FAILs | ~2 FAILs (only true backend conflicts) |
| Decision pack happy-paths usable | 1 (TC-001 only) | 5 (TC-001 + 4 from pool) |
| Provision pack happy-paths usable | 1 (TC-001 only) | 10 (TC-001 + 9 from pool) |

## Acceptance Criteria

A successful end-to-end run of:
1. `POST /api/v1/affiliates/onboarding/sessions` → 200 with sessionId+draftId
2. `PUT /drafts/{draftId}/organization` → 200
3. `POST /drafts/{draftId}/documents` (with minimal valid PDF) → **200/201** ← currently 500
4. `PUT /drafts/{draftId}/issuing-banks` (with documented bankId source) → **200** ← currently 404/500
5. `POST /drafts/{draftId}/submit` → 200/201 with `caseId` in response body

unblocks the case-pool patch and recovers ~13 admin FAILs.

## See Also

- `postman_hybrid_admin_runner.py` — case-pool scaffolding (constants `N_SUBMITTED_POOL`, `N_APPROVED_POOL`, helpers `mint_submitted_case_via_onboarding`, `approve_case_for_pool`)
- `BACKEND_VERIFICATION_ENDPOINTS_REQUEST.md` (2026-05-03) — separate ask for read-only verification endpoints
