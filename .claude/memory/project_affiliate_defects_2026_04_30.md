---
name: Kardit Affiliate API Backend Defects 2026-04-30
description: Confirmed backend defects + real test IDs discovered during live affiliate microservice testing session
type: project
originSessionId: 0411d92a-9f5c-409d-9909-039a9cddde3b
---
Affiliate microservice tested live against http://167.172.49.177:8080 on 2026-04-29/30.
920 test cases run. 217 passed, 679 failed, 24 blocked.

**Real backend IDs discovered:**
- Existing affiliates: `AFF-7B1950BA8BC146C5A6BC40FCED46B68D` (ACTIVE), `AFF-ACDC96EE11DC4924B54D7785366AD2E5` (ACTIVE), `ddfd5ceb-979d-45ab-9d36-92f58a77f6a0` (SUSPENDED, UUID)
- Real bank UUID: `352e426f-6fbe-46b6-affe-8f06c42ceff9`
- Only submitted onboarding case UUID: `d3e5e5b1-1a1d-4f47-9df9-7a4a70a78f01` (SUBMITTED, can't approve — persistent backend error)

**CRITICAL defects:**
1. `GET /api/v1/affiliates/{id}` → 404 for ALL IDs — get-by-ID not implemented
2. Affiliate ID format mismatch: creation returns `AFF-...`, suspend/block only accepts UUID format → lifecycle is impossible
3. `POST /api/v1/admin/onboarding/cases/{caseId}/decision` → persistent 400 "Failed to persist decision" — approval flow broken
4. Submit returns non-UUID caseId, admin decision path requires UUID — structurally incompatible steps
5. Partnership query/approve/reject endpoints 404 — not implemented
6. Bank-scope suspend/block 404 — not implemented
7. Audit logs endpoint 404 — not implemented

**HIGH defects:**
8. No auth enforcement on any onboarding draft endpoint (unauthenticated = 200)
9. No input validation on draft endpoints (empty arrays, null, malformed IDs all → 200)
10. No state-machine enforcement (updates accepted after draft submitted)
11. Wrong HTTP codes: creation endpoints return 200 instead of 201

**MEDIUM defects:**
12. Session creation is email-idempotent — same email always returns same draft
13. Bank partnership request → 403 "Internal server error" (unhandled exception)
14. KYB snapshot → 404 for affiliates without linked onboarding case
15. Admin cases list doesn't reflect newly submitted cases

**Confirmed working paths:**
- POST /api/v1/affiliates/onboarding/sessions → 200
- PUT /api/v1/affiliates/onboarding/drafts/{draftId}/organization → 200
- POST /api/v1/affiliates/onboarding/drafts/{draftId}/documents → 200
- PUT /api/v1/affiliates/onboarding/drafts/{draftId}/issuing-banks → 200
- POST /api/v1/affiliates/onboarding/drafts/{draftId}/submit → 200 (first time)
- GET /api/v1/admin/onboarding/cases → 200
- GET /api/v1/affiliates/{AFF-id}/profile → 200
- GET /api/v1/affiliates/{AFF-id}/bank-partnerships → 200
- POST /api/v1/affiliates/query → 200
- POST /api/v1/affiliates/{UUID}/suspend → 200 (UUID format only)

**Why:** Use these for future affiliate test runs and to brief developers on backend gaps.
**How to apply:** When setting up future affiliate runner runs, use real IDs above. When reviewing backend PRs, check these specific gaps.
