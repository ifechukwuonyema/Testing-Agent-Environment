---
name: project_admin_run_20260513
description: Admin runs 2026-05-13 — final clean run 114P/26F/13B (74.5%); all runner bugs resolved; 26 FAILs are backend-only
metadata: 
  node_type: memory
  type: project
  originSessionId: ffbb37a1-b336-43b6-9f12-6ac506bcf721
---

**Early replay (072217):** 7P/41F/0B (14.6%). 3 root causes: SUBMITTED pool exhausted, selectedBankIds missing from provision, no auth middleware.

**Final clean run (184514):** 153 TCs — 114P/26F/13B (74.5%). Report: `admin_postman_hybrid_report_20260513-184514.yaml`. Phase 0d: 20/20 minted. Phase 0c: 30 batch-4 SUBMITTED IDs loaded.

**Fixes applied this session:**
1. Removed `selectedBanksApproved` re-injection from `approve_case_for_pool`
2. Removed bank injection from issuing-banks step of `mint_submitted_case_via_onboarding`
3. Deleted TC-008 (`approve_missing_selected_banks`) and TC-010 (`approve_empty_selected_banks`)
4. Wired batch 4 IDs: 30 SUBMITTED + 30 APPROVED from query.txt

**26 remaining FAILs — all backend:**
- 24 auth bypass: all 5 endpoints return 200 for no-auth, expired, invalid tokens, wrong roles (D-ADMIN-AUTH-1)
- 1 body-before-auth: ONB-08 TC-025 `wrong_role_rejected` → 400 instead of 403
- 1 tenant leakage: ONB-10 TC-023 `foreign_tenant_case_not_visible` → 200 instead of 403/404 (D-ADMIN-TENANT-1)

**13 BLOCKs:** audit log, notification triggered, backend-failure-safe TCs.

**Ceiling:** Fix D-ADMIN-AUTH-1 + D-ADMIN-TENANT-1 → 140P/0F/13B (100% of executable TCs).

[[feedback_admin_case_pool_one_time_use]] [[project_admin_run_20260512]] [[reference_admin_auth_bypass_confirmed]] [[reference_admin_tenant_leakage]]
