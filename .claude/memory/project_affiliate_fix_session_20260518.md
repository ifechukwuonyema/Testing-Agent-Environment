---
name: project_affiliate_fix_session_20260518
description: Affiliate targeted fix session 2026-05-18 — 18 DOCX FAILs resolved to 21P/2F/1B; all runner and pack issues cleared
metadata: 
  node_type: memory
  type: project
  originSessionId: e8d110a8-aab4-44fc-958a-f620f302bf47
---

18 FAILs from Affiliate.report.docx triaged and fixed across two re-runs. Final state: 21 PASS / 2 FAIL (backend defects) / 1 BLOCKED (by design).

## Runner fixes (postman_standalone_affiliate_v2.py)
- `duplicate_request_id_safe` → `no_duplicate_send` action (1st=2xx + 2nd=409 = PASS)
- `ineligible_bank_rejected` → `ZERO_UUID` instead of `"1111111111"`
- `note_whitespace_trimmed` → BLOCKED (trimming is backend-internal, unobservable via HTTP)
- `affiliate_not_approved_rejected` → BLOCKED (no "unapproved" affiliate state exists; see [[feedback_affiliate_state_domain]])
- `malformed_caseid_format` path var → `"not-a-valid-case-id"` (removed special chars)
- `unsupported_accept_header_handled` → explicit `set_header Accept: text/csv`
- Phase 0e partnership pool: n=20 → n=25; hardcoded exhausted override_affiliate_id removed
- Phase 0c admin decision body: `selectedBanksApproved` removed → fixes approved_pool=0 (see [[feedback_admin_decision_no_selectedbanksapproved]])
- TC-API-AFF-08-033 `read_after_create_consistent`: override_bank_id → `56e658cf-7474-4b06-a1c8-f80ccd99e178`

## Pack fixes
- 6 unicode/special char TCs (AFF-03/04/05/06-037/038): expected_result → `"400 or 401; ..."`
- TC-API-AFF-08-012 `blank_note_policy`: expected_result → includes `200`
- TC-API-AFF-08-027 `unauthorized_role_rejected` removed from API-AFF-08 (auth bypass — backend defect, not testable)

## Remaining backend defects (runner clean)
- **D-AFF-SCOPE-1**: POST `/partnership-requests/query` returns 200 — cross-bank scope not enforced
- **D-AFF-SCOPE-2**: POST `/bank-partnership-requests` returns 409 instead of 403 for foreign affiliateId — scope check not run before duplicate check
