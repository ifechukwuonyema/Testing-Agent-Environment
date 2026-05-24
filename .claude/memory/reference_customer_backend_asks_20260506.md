---
name: Customer Backend Asks DOCX 2026-05-06
description: Pointer to the customer backend-asks DOCX. D-CUS-2 (/search filter validation) + D-CUS-3 (GET tenant-scope leakage) + D-CUS-4 (/search malformed JSON) + D-05 context. Projected ceiling ~94%.
type: reference
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
## Document
`C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\customer_backend_asks_2026-05-06.docx`

## Source run
`Downloads\customer_postman_hybrid_report_20260506-231759.yaml` — 120 TCs · 85P / 32F / 3B → 70.8%

## Asks (priority order)
1. **D-CUS-2** — /customers/search filter validation missing. +8.3pp.
2. **D-CUS-3** — GET /customers/{customerId} cross-tenant/affiliate scope leakage. +2.5pp.
3. **D-CUS-4** — /customers/search accepts malformed JSON without 400. +0.8pp.
4. **D-05** (cross-service) — Auth/RBAC middleware. +9.2pp customer-side.

## Projected ceiling
- Current: 70.8%
- + D-CUS-2: ~79.1%
- + D-CUS-3: ~81.6%
- + D-05 auth: ~91.6%
- + audit-log read endpoint: ~94.1%

## Generator
`Downloads\generate_customer_backend_asks_20260506.py`
