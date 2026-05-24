---
name: Transactions Backend Asks DOCX 2026-05-08
description: Pointer to consolidated transactions backend-asks DOCX. 5 findings; root cause is swagger has zero constraints; 69 of 71 FAILs are silent-accept.
type: reference
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
## Document
`C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\transactions_backend_asks_2026-05-08.docx`

## Source
- Run: `Downloads\transactions_postman_hybrid_report_20260508-050319.yaml` (391 TCs / 309P / 71F / 11B = 79.0%)
- Generator: `Downloads\generate_transactions_backend_asks_20260508.py`

## Findings (priority order)

| ID | Severity | FAILs | One-line |
|---|---|---|---|
| D-TRX-EXP-1 | Critical | ~14 | POST /transactions/export silent-accepts invalid filters/formats/unauth requests |
| D-TRX-AUTH-1 | High | ~30 | All read endpoints accept unauth/foreign-scope with 200 |
| D-TRX-EXPSTATE-1 | High | ~10 | GET /exports/{exportId}/download has no state gate |
| D-TRX-VOL-1 | Medium | ~10 | Volume endpoints accept invalid scope IDs and date ranges |
| D-TRX-PAG-1 | Medium | ~12 | Pagination validation gaps |

## Cross-cutting root cause
**Transactions swagger is catastrophically permissive** — 0 required body fields, 0 enum constraints, 0 format/pattern declarations, 0 required response fields. Resolving these findings requires the swagger constraint pass first.

## Projected ceiling
Current: 79.0% → ~86.7% (D-TRX-AUTH-1) → ~90.3% (D-TRX-EXP-1) → ~92.8% (D-TRX-EXPSTATE-1) → ~98.5% (D-TRX-PAG-1)
