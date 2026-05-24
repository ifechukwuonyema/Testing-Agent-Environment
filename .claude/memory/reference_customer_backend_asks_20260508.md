---
name: Customer Backend Asks DOCX 2026-05-08
description: Pointer to consolidated customer backend-asks DOCX. 5 findings; ceiling ~95% if all asks land. Per-TC audit confirmed runner correctness — all FAILs are backend-side.
type: reference
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
## Document
`C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\customer_backend_asks_2026-05-08.docx`

## Source
- Run: `Downloads\customer_postman_hybrid_report_20260508-043201.yaml` (107 TCs / 81P / 23F / 3B = 75.7%)
- Generator: `Downloads\generate_customer_backend_asks_20260508.py`

## Findings (priority order)

| ID | Severity | FAILs | One-line |
|---|---|---|---|
| D-CUS-AFF-1 | Critical | 9 | POST /api/v1/affiliates/query 400 blocks customer-draft pre-flight |
| D-CUS-AUTH-1 | High | 8 | GET /api/v1/customers/{customerRefId} accepts unauth/foreign-scope/wrong-role with 200 |
| D-CUS-SEARCH-1 | High | up to 14 | POST /customers/search silent-accepts invalid filter values |
| D-CUS-WS-1 | Low | 1 | Whitespace-padded customerRefId returns 400 |
| D-CUS-DOC-1 | Low | 0 | Swagger 200 response schema for GET /customers/{customerRefId} is empty |

## Projected ceiling
- Current: 75.7% → + D-CUS-AFF-1: ~84.1% → + D-CUS-AUTH-1: ~91.6% → + D-CUS-SEARCH-1: ~94.4% → + D-CUS-WS-1: ~95.3%
