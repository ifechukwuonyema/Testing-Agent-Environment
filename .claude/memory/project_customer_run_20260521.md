---
name: project_customer_run_20260521
description: Customer 3-TC scoped replay 2026-05-21 — TC-02-011/TC-02-012 unblocked via 4-part fix; both confirmed backend defects (D-CUS-SEARCH-1); 3/3 PASS
metadata:
  node_type: memory
  type: project
  originSessionId: dcda5f54-9fac-460c-a328-13eff2763c0a
---

Scoped replay run: 3 TCs, final result **3/3 PASS**.
Report: `Downloads\customer_postman_hybrid_report_replay_20260520-091324.yaml`

**Root problem:** TC-02-011 and TC-02-012 were stuck BLOCKED/FAIL because:
1. `idType` and `idNumber` were absent from the active collection's POST /search criteria base body
2. Stale hardcoded `return {"action": "blocked", ...}` for TC-011 in `classify_scenario()`
3. `rewrite_customer_search_criteria()` wiped body to `{}` before any mutation fired

**4-part fix chain:**
1. Added `"idType": "NationalId"` and `"idNumber": "NIN000044"` to POST /search criteria base body in PMC
2. Removed stale hardcoded BLOCKED return for `missing_id_number_when_id_type_supplied_rejected`
3. Added explicit `drop_field: idNumber` (TC-011) and `drop_field: idType` (TC-012) handlers BEFORE the generic regex; added both to `FORCE_V1_PLAN_SCENARIOS`
4. Added `_idtype_idnumber_cross_field` bypass flag around `rewrite_customer_search_criteria()`

**Backend defect confirmed:** Backend silently accepts idType-only or idNumber-only search criteria — returns 200 instead of 400/422. D-CUS-SEARCH-1 cross-field co-validation not enforced.

[[feedback_customer_search_rewrite_bypass]]
[[project_customer_run_20260518]]
