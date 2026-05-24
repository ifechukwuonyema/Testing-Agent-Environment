---
name: reference_admin_tenant_leakage
description: Admin tenant scope leakage — ONB-10 TC-023 returns 200 for foreign-tenant case; distinct from auth bypass
metadata:
  node_type: memory
  type: reference
  originSessionId: current
---

Confirmed 2026-05-13 (run 184514). `GET /api/v1/admin/onboarding/cases/{caseId}` (API-ONB-10) returns 200 and the full case object when called with a valid admin token that belongs to a **different tenant** than the case owner.

- TC: `TC-ONB-10-023 | foreign_tenant_case_not_visible`
- Expected: 403 or 404
- Got: 200 + full case data

**Why it's distinct from D-ADMIN-AUTH-1 (auth bypass):** The token is valid and the auth check passes — the problem is that the backend does not enforce tenant scope on the case lookup. A cross-tenant admin can read any case by ID.

**Defect ID:** D-ADMIN-TENANT-1

**How to apply:** File as a separate backend ask from the auth bypass cluster. Requires the case-fetch handler to validate that the requesting tenant matches the case's owning tenant before returning data.

[[project_admin_run_20260513]] [[reference_admin_auth_bypass_confirmed]]
