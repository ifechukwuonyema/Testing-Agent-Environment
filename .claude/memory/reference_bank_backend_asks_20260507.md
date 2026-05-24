---
name: Bank Backend Asks DOCX 2026-05-07
description: Pointer to the consolidated bank backend-asks DOCX (9 findings). Documents 161 FAILs + 8 BLOCKED across all 10 bank endpoints. Projected ceiling ~95% if all asks land.
type: reference
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
## Document
`C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\bank_backend_asks_2026-05-07.docx`

## Findings (priority order)

| ID | Severity | FAILs | One-line |
|---|---|---|---|
| D-405-1 | Critical | 26 | POST /api/v1/banks/query returns 405; backend implements GET only |
| D-PERSIST-1 | Critical | 28 | Partnership-request mint write/read inconsistency — mint 2xx, verify GET 404 |
| D-Z2-1 | High | 23 | PART-01 response: onboardingSnapshot null violates swagger non-nullable object |
| D-Z2-2 | High | 14 | CRD-01 response shape contains bankId/page/pageSize/total/cards — none in swagger schema |
| D-AUTH-1 | High | 34 | BNK-02/04/05, PART-01, CRD-01 read endpoints don't enforce auth/scope |
| D-FIXTURE-1 | Medium | ~26 | CTRL-01/02 state-cascade — first TC suspends/blocks affiliate, every subsequent TC 409s |
| D-Z1-1 | Medium | 2 | ProblemDetails RFC-7807 envelope on 4xx not declared in swagger |
| D-RC-1 | Medium | 0 | swagger declares requestContext.required = ['requestId']; backend enforces different fields |
| D-AUDIT-1 | Medium | 8 BLOCKED | Need 3 read endpoints for side-effect verification |

## Projected ceiling
Current 49.9% → + D-PERSIST-1: ~58.2% → + D-405-1: ~66.0% → + Z2 swagger drift: ~77.7% → + D-AUTH-1: ~87.8% → + D-FIXTURE-1: ~95.6% → + D-AUDIT-1: ~98.0%
