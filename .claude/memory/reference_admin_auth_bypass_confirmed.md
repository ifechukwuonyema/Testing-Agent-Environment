---
name: reference_admin_auth_bypass_confirmed
description: Admin auth bypass confirmed live 2026-05-13 — all 5 endpoints return 200 with no auth; BNK-PRV-01 created real banks
metadata: 
  node_type: memory
  type: reference
  originSessionId: ffbb37a1-b336-43b6-9f12-6ac506bcf721
---

Confirmed 2026-05-13 via replay run. Every admin endpoint returns 200 and processes the request fully when sent with **no Authorization header at all**.

| Endpoint | What happened with no auth |
|---|---|
| GET `/admin/onboarding/cases` | 200 + 432 real cases returned |
| GET `/admin/onboarding/cases/{id}` | 200 + full case object returned |
| POST `/admin/onboarding/cases/{caseId}/decision` | 400 (business logic, not auth) — case already approved |
| POST `/admin/onboarding/cases/{caseId}/provision` | 400 (DTO validation, not auth) — selectedBankIds empty |
| POST `/admin/banks` | 200 + **real bank created** in the system |

**Ghost banks created during auth testing** (need cleanup from test env):
- TestBank-8892CABD, TestBank-046D8AA7, TestBank-FFBBB2BE, TestBank-164DBB1D, TestBank-B4BEFF67

**Why ONB-08/09 return 400 instead of 200:** Auth middleware is absent, so unauthenticated requests reach the business logic handler. ONB-08 hits state validation, ONB-09 hits DTO validation. The 400 masks the auth bypass.

**How to apply:** When filing this as a backend defect, classify as critical/security. The missing auth guard is platform-wide across `/api/v1/admin/*`.

[[project_admin_run_20260513]]
