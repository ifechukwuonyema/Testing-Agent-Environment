---
name: Backend Ask — Affiliate Onboarding Flow Defects
description: Document filed 2026-05-05 requesting fixes to documents (500) and issuing-banks (404/500) endpoints in the affiliate onboarding 5-step flow; blocks admin case-pool patch and ~13 G failures from converting to PASS
type: reference
originSessionId: f2faf347-b600-47a9-8402-697b467ab1b7
---
Document file: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\BACKEND_AFFILIATE_ONBOARDING_FLOW_REQUEST.md`

**Defects:**
1. `POST /drafts/{draftId}/documents` returns 500 with both Postman literal body AND a minimal valid PDF
2. `PUT /drafts/{draftId}/issuing-banks` rejects every known bankId form: Postman literal `"TBK-001"` (404), real UUID from `/banks/query` (404), bankCode (500). No documented eligibility contract; no listing endpoint exists.

**Blocks:** Admin case-pool patch (`postman_hybrid_admin_runner.py` Phase 0c/0d). Patch is implemented and self-reviewed but cannot mint cases until both backend defects are fixed.

**Numerical impact (admin run):** Today: 55.3% → After fix + pool re-enable: projected ~70.7%.

[[reference_backend_verification_endpoints_ask]] [[project_admin_hybrid_run_20260501]] [[feedback_codex_council_workflow]]
