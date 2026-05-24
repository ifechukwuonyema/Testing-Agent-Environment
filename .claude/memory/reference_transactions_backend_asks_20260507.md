---
name: Transactions Backend Asks DOCX 2026-05-07
description: Pointer to the transactions backend-asks DOCX. D-TRX-1 (key-not-in-dictionary on 4 GETs) + D-TRX-2 (/query handler crash) + D-05 auth + D-TRX-3 audit-log endpoint. Projected ceiling ~99.6%.
type: reference
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
## Document
`C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\transactions_backend_asks_2026-05-07.docx`

## Source run
`Downloads\transactions_postman_hybrid_report_20260507-000119.yaml` — 440 TCs · 178P / 251F / 11B → 40.5%

## Asks (priority order)
1. **D-TRX-1** — `"The given key was not present in the dictionary."` 500 on 4 GET endpoints. 156 fails. +35.5pp.
2. **D-TRX-2** — POST /transactions/query handler aborts connection. 38 fails. +8.6pp.
3. **D-05** (cross-service) — Auth/RBAC. 55 transactions fails. +12.5pp.
4. **D-TRX-3** — Expose `GET /transactions/audit-logs?correlationId=X`. +2.5pp.

## Projected ceiling
- Current: 40.5% → + D-TRX-1: ~76.0% → + D-TRX-2: ~84.6% → + D-05 auth: ~97.1% → + D-TRX-3: ~99.6%

## Generator
`Downloads\generate_transactions_backend_asks_20260507.py`
