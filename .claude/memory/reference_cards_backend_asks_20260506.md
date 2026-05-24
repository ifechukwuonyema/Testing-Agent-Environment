---
name: Cards Backend Asks DOCX 2026-05-06
description: Pointer to the comprehensive cards backend-asks DOCX. Lists D-02/D-04..D-11 defects + 8 test-data needs + projected ~95% pass-rate ceiling once resolved.
type: reference
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
## Document
`C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\cards_backend_asks_2026-05-06.docx`

## Summary of asks (priority order)

1. **D-08** — Tenant/affiliate ID scope alignment between Issuance and Activate
2. **D-09** — Add public path PENDING_ISSUANCE → PENDING_ACTIVATION
3. **§5.1** — Pre-seed 50+ ACTIVE-status cards (system has 0 today)
4. **§5.2** — Pre-seed cards in EVERY legal state (READY, FROZEN, etc.)
5. **§5.3** — Provision virtual accounts end-to-end during issuance
6. **§5.4-5.5** — Pre-seed 10+ limitRequestId and loadRequestId values in PENDING state
7. **§5.6** — Provide a second test actorUserId (checker) for maker-checker scenarios
8. **§5.7** — Expose `GET /admin/audit-logs?correlationId=<X>` for B1_db_verify scenarios
9. **§5.8** — Pre-seed a foreign-tenant scope
10. **D-04/D-05/D-06** — Add validation + auth + state-machine middleware platform-wide
11. **D-02** — Fix LDR-02 approve handler 500-on-every-input
12. **D-10** — Reorder middleware so auth fires BEFORE state-check
13. **D-11** — Consolidate the two parallel UserType enums

## Projected ceiling
~95% pass rate once asks 1-12 resolved.

## Generator script
`Downloads\generate_cards_backend_asks_20260506.py`
