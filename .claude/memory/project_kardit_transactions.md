---
name: Kardit Transactions API Test Findings
description: Defect patterns and test data from Transactions microservice API testing on 2026-04-23.
type: project
originSessionId: 5ca056cc-59f9-4eaf-8dc0-7a3236a2b6ea
---
Transactions API testing completed 2026-04-23 against http://167.172.49.177:8080

**Summary:** 165 TCs (11 endpoints × 15) | 30 PASS | 88 FAIL | 47 BLOCKED

**Critical defects logged:**
- DEF-TRX-001: No authentication enforcement (all 11 endpoints)
- DEF-TRX-002: No authorization/scope enforcement (all 11 endpoints)
- DEF-TRX-003: Path parameters ignored; stub data returned regardless of supplied IDs; no 404 for unknown resources
- DEF-TRX-004: Business filters not applied (status, transactionType, bankId, affiliateId, customerId filters ignored)
- DEF-TRX-005: Pagination not enforced (pageSize ignored; response always shows pageSize=20)
- DEF-TRX-006: meta field always null — pagination metadata never populated
- DEF-TRX-007 (TC Doc): API-TRX-01 TC path wrong — /transactions/cards/{cardId} → 404; correct is /transactions/cards/{cardId}/transactions
- DEF-TRX-008: TRX-06 status param is required but swagger docs it as optional (swagger documentation error)
- DEF-TRX-009: POST /transactions/export returns exportId="" (empty string) — export flow broken
- DEF-TRX-010 (TC Doc): TRX-08 and TRX-09 TC paths use /exports/ (plural) → 404; correct is /export/ (singular)
- DEF-TRX-011: TRX-03 duplicate unload records (UNLD-2026-00012 twice); response pageSize=1 but 2 records returned
- DEF-TRX-012: TRX-01 collection transaction objects have null cardId/customerId/bankId/affiliateId; createdAt=0001-01-01 (default)
- DEF-TRX-013: TRX-03 totalRecords mismatch; TRX-01 totalRecords=0 despite data present
- DEF-TRX-014: Swagger path for TRX-05 wrong — documents as /transactions/{query} with path param; actual callable path is /transactions/query literal
- DEF-TRX-015: TRX-08 returns PENDING, TRX-09 returns COMPLETED for same exportId — lifecycle state inconsistency
- DEF-TRX-016: TRX-08 downloadUrl uses wrong /exports/ path in response body
- DEF-TRX-017: TRX-09 returns JSON status object instead of file binary/stream
- DEF-TRX-018: TRX-11 volumes response incomplete — only totalFundingVolume; missing totalUnloadVolume and totalTransactionVolume
- DEF-TRX-019: TRX-10/11 path params partially echoed — bankId/affiliateId in response doesn't match requested

**Stub data discovered:**
- TXN-000122: POS, 12000 NGN, SUCCESS, Amazon, E-commerce, CARD-2026-000551, CUST-2026-00088, BANK-2026-00012, AFF-2026-00045
- TXN-000123: POS, 5000 NGN, FAILED, Jumia, E-commerce, CARD-2026-000551, CUST-2026-00088, BANK-2026-00012, AFF-2026-00045
- FND-2026-00088: Load, 750000 NGN, VIRTUAL_ACCOUNT_TRANSFER, COMPLETED, balanceAfter=895000
- UNLD-2026-00012: Unload, 5000 NGN, ACCESS_BANK, 0123456789 (masked), COMPLETED, balanceAfter=890000
- Export stub: fileName=transaction_history_2026_00021.csv, TRX-EXP-2026-00021
- Bank volume stub: bankId=BNK-UBA-001, funding=5M, unload=2M, transaction=15M NGN
- Affiliate volume stub: affiliateId=AFF-UBA-001, funding=5M NGN only

**Report file:** C:\Users\Onyema Ifechukwu\Downloads\transactions_api_test_report.yaml

**Why:** Transactions microservice shows same stub/mock pattern as Cards — endpoints are wired up and routing works, but business logic (filtering, auth, pagination, real IDs) not yet implemented. Export flow is additionally broken (empty exportId).

**How to apply:** When testing other Kardit microservices, expect auth/scope/404/filter defects as systemic. Flag export-flow-broken as Transactions-specific. Date-time format IS validated (400) — this is the only consistent validation working across services.
