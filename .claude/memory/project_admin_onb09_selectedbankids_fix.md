---
name: project_admin_onb09_selectedbankids_fix
description: ONB-09 provision fix — RESOLVED 2026-05-13; bank injection removed; 25/31 TCs now pass
metadata: 
  node_type: memory
  type: project
  originSessionId: ffbb37a1-b336-43b6-9f12-6ac506bcf721
---

**RESOLVED 2026-05-13.**

**Original problem:** `POST /api/v1/admin/onboarding/cases/{caseId}/provision` was failing with `"selectedBankIds cannot be empty."` because Postman base omits `selectedBankIds`. Additionally, the `mint_submitted_case_via_onboarding` issuing-banks step was injecting a hardcoded bank (`000045f9-d01b-479c-a84d-0fe82454d55a`) which exhausted the partnership capacity for that bank, causing all ONB-09 provision calls to return `"Active partnership already exists for bank(s): 000045f9-..."`.

**Resolution:** Removed bank injection from the issuing-banks step entirely. Runner now passes the Postman base as-is, which uses two different bank UUIDs (`e9686a3b-07c2-4ee3-a1f6-e0b67fafdd5d` and `96da6f8e-0b43-4f09-82e8-ffb6e52ba228`) that are not exhausted. `selectedBanksApproved` was also removed from `approve_case_for_pool` since the new Postman collection dropped that field from the ONB-08 spec.

**Result:** ONB-09 went from 0P to 25P/4F/2B. The 4 FAILs are all auth bypass (backend defect D-ADMIN-AUTH-1).

**Runner file:** `Kardit\harnesses\postman_hybrid_admin_runner.py`

[[project_admin_run_20260513]] [[feedback_admin_case_pool_one_time_use]]
