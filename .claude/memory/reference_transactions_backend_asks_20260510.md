---
name: Transactions Backend Asks DOCX 2026-05-10
description: 8 asks + Invalid ID Inventory section (4.2) showing 10 invalid backend-shipped IDs side-by-side with valid IDs we had to discover live
type: reference
service: Transactions
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
**Path:** `C:\Users\Onyema Ifechukwu\Downloads\transactions_recommendations_2026-05-10.docx`
**Generator:** `C:\Users\Onyema Ifechukwu\Downloads\generate_transactions_recommendations_docx.py`
**Source YAML:** `transactions_postman_hybrid_report_20260510-020510.yaml`

## 8 asks

| ID | Topic |
|---|---|
| D-TRX-AUTH-1 | Auth pipeline |
| D-TRX-EXPORT-3 | Export status endpoint (stubbed) |
| D-TRX-QUERY-2 | /query handler crash — 500 on unconstrained filter values |
| D-TRX-EXPORT-2 | Export download (stubbed) |
| D-TRX-EXPORT-1 | Export create (stubbed) |
| **D-TRX-IDS-1** | Invalid IDs in fixtures — backend shipped TXN-2026-* / CARD-2026-* / CUST-2026-* etc. that don't match the formats their own read endpoints accept |
| **D-TRX-IDS-2** | Dual ID population — /query returns TXN-2026-XXXXX; GET endpoints accept TRA-32hex only |
| D-TRX-VAL-1 | Swagger constraints — no required/enum/format/pattern |
| D-TRX-VERIFY-1 | Verification endpoints — read-only endpoints to confirm POST persisted |

## Section 4.2 — Invalid ID Inventory

Side-by-side table of 10 invalid/valid ID pairs (TXN-2026-00014 → TRA-1234…, CARD-2026-00003 → CAR-A61BCD8A…, CUST-2026-00019 → CUS-1234…, etc.), each row tagged with discovery method.

**Ceiling estimate:** ~98% if backend completes swagger constraint pass + ships D-TRX-IDS-1/2 fixture fixes.
