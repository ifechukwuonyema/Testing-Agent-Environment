---
name: Kardit Cards API Test Findings
description: Key defect patterns found during Cards microservice API testing on 2026-04-23.
type: project
originSessionId: 22c14085-7206-4f95-b584-1dabd79889e5
---
Cards API testing completed 2026-04-23 against http://167.172.49.177:8080

**Summary:** 315 TCs | 88 PASS | 127 FAIL | 100 BLOCKED

**Critical defects logged:**
- DEF-CARDS-001: No authentication enforcement (all 21 endpoints)
- DEF-CARDS-002: No authorization/scope enforcement (all 21 endpoints)
- DEF-CARDS-003: Path parameters ignored; fixed stub data returned; no 404 for unknown IDs
- DEF-CARDS-004: No lifecycle state machine enforcement (freeze/unfreeze/terminate)
- DEF-CARDS-005: Required fields beyond requestContext not validated
- DEF-CARDS-006: Invalid business values (currency, amount, outcome) accepted
- DEF-CARDS-007: Query filters not applied
- DEF-CARDS-008: Pagination not enforced
- DEF-CARDS-009: No max-length validation on string fields
- DEF-CARDS-010: 5 endpoints not implemented (metrics + bulk affiliate ops)

**Test data discovered:**
- CARD-2026-000551: VIRTUAL, ACTIVE, BNK-ZEN-002, AFF-2026-00012, CUST-ACME-00091
- CARD-2026-000552: PHYSICAL, PERSONALIZING, BNK-UBA-001, AFF-2026-00015, CUST-ACME-00092

**Report file:** C:\\Users\\Onyema Ifechukwu\\Downloads\\cards_api_test_report.yaml

**Why:** Cards microservice appears to be in early stub/mock stage — most endpoints return hardcoded responses, suggesting the implementation layer is not yet connected to actual business logic.

**How to apply:** When testing other Kardit microservices on the same server, expect similar stub behavior until confirmed otherwise. Flag auth/scope/404 issues as systemic platform-level findings, not per-endpoint bugs.

---

## Re-test 2026-05-01 (hybrid Postman-driven, 840 TCs)

Newer findings supersede some 04-23 patterns. See `project_cards_hybrid_run_20260501.md` for full detail. Key updates:

- **Schema drift on every successful read** — backend now returns extra fields (`cardToken`, fulfillment.deliveryAddress*, virtualAccount.accountName/Number/bankName) AND `status: "PENDING_ACTIVATION"` not in swagger enum. Platform-wide; either swagger is stale or backend is leaking.
- **Issuance produces a cardId not visible to downstream endpoints** — POST issuance returns a real-looking `CAR-...` id but freeze/unfreeze/terminate return 404 for that id. Persistence break confirmed.
- **Bulk bank-scoped variants pass at 28/40** while single-card siblings (FRZ-01/UNF-01/TRM-01) pass at 5/40 — suspicious asymmetry, possibly different code paths.
- **Validation gaps on issuance worse than expected** — missing requestContext / bankId / productId / customer payload all return 200 instead of 4xx. 11 of 17 ISS-02 FAILs are this pattern.
- **All 21 pack endpoints have exact-match Postman entries** — no drift, unlike Affiliate.
