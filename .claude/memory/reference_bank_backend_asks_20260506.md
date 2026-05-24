---
name: Bank Backend Asks DOCX 2026-05-06
description: Pointer to the bank backend-asks DOCX. Lists D-04, D-05, D-12, D-13, D-14, D-15, D-16 + 5 test-data needs. Projected ceiling ~80-83% with backend fixes.
type: reference
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
## Document
`C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\bank_backend_asks_2026-05-06.docx`

## Summary of asks (priority order)

1. **D-15** — Partnership-request mint must honor request body's bankId, not silently rebind to affiliate's owning bank
2. **D-16** — Document POST /banks/{bankId}/cards response schema in swagger
3. **§5.1 D-13** — Pre-seed affiliate→bank link (5+ APPROVED affiliates with ACTIVE partnership)
4. **§5.2 D-14** — Pre-seed 50+ cards under test bank across multiple statuses
5. **D-04** — Add request validation pipeline
6. **D-05** — Auth middleware order: auth → scope → state → business
7. **D-12** — Suspend/Block must validate bankId exists

## Projected ceiling
- Current (post HB-01 + HB-02): 50.5%
- + D-15 + D-16 fixes: ~61%
- + Backend test-data seeds: ~67%
- + D-04 validation pipeline: ~74%
- + D-05 auth/RBAC: ~80-83%

## Generator script
`Downloads\generate_bank_backend_asks_20260506.py`
