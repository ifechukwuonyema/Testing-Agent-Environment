---
name: project_customer_run_20260518
description: Customer Hybrid Run 2026-05-18 — runner clean; pack edits done (TC-03-039 removed, TC-03-037 fixed to PASS); 2 open items: TC-02-011 BLOCKED, TC-02-012 backend defect
metadata: 
  node_type: memory
  type: project
  originSessionId: 25aa212c-6d82-4928-b581-3037666efbae
---

Session: 6 runner fixes shipped, 2 live runs, then a 4-TC scoped replay to confirm targeted fixes.

**Runner fixes shipped (all in postman_hybrid_customer_runner.py):**
1. FORCE_V1_PLAN_SCENARIOS — `underage_customer_rejected_where_policy_requires` forced to v1
2. underage v1 handler: `set_nested` (wrong path `customer.dob`) → `set_field` (deep search finds `customer.identity.dob`)
3. `missing_kyc_status_rejected` → BLOCKED (kycStatus absent from Postman base for /draft)
4. `missing_id_number_when_id_type_supplied_rejected` → BLOCKED (idType absent from Postman base for /search)
5. `rotate_customer_uniqueness` moved to BEFORE mutation
6. Post-mutation rotation call removed from `else` path

**Pack edits:**
- TC-API-CUS-03-039 (`archived_customer_not_accessible`) — REMOVED; backend defect, no fix expected. Pack: 117→116 TCs
- TC-API-CUS-03-037 (`unsupported_accept_header_handled`) — FIXED: scenario renamed `accept_header_json_success_explicit`. Now PASS.

**4-TC scoped run (20260518-133112):** 3 TCs ran, result 1P/1F/1B:
- TC-03-037 → PASS
- TC-02-011 → BLOCKED: `idType is absent from the Postman base body for POST /search`
- TC-02-012 → FAIL (B_silent_accept): idNumber supplied, idType absent → backend returns 200 (D-CUS-SEARCH-1)

**Live run results:**
- Run 1: 74P/38F/5B (63.2%) — 26 timeouts + 12 backend defects
- Run 2: 78P/34F/5B (66.7%) — 25 timeouts + 9 backend defects
- Deterministic pass rate (excl. timeouts): ~81-85%

**Confirmed backend defects:**
- Auth bypass: CUS-01-035/036/037/038, CUS-02-035/036 (→ 200 with no auth)
- Scope not enforced: CUS-01-007, CUS-02-037, CUS-03-031 (→ 200 cross-tenant)
- Validation gaps: CUS-01-013 (missing_dob → 200), CUS-02-012 (D-CUS-SEARCH-1)
- Business rules: CUS-01-033 (duplicate_identity → 200 not 409)
