---
name: reference_cards_backend_asks_20260523
description: Cards backend defects DOCX 2026-05-23 — 11 defects, 71 FAILs + 31 BLOCKEDs documented
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5a397891-3858-46d1-a7e6-4750ffdda215
---

**Path:** `C:\Users\Onyema Ifechukwu\Kardit\reports\cards_backend_defects_20260523.docx`

Also at: `Downloads\cards_backend_defects_20260523.docx`

Generator script: `Downloads\_gen_cards_backend_doc.py`

**Supersedes:** [[reference_cards_backend_asks_20260508]] (this is the complete post-E2E-runner register)

## Defect register summary

| ID | Severity | Impact |
|---|---|---|
| D-CARDS-TENANT-1 | CRITICAL | 20F — foreign tenant reads any card (200) |
| D-CARDS-AUTHZ-2 | CRITICAL | 1F — SERVICE_PROVIDER writes on refresh (200) |
| D-CARDS-TENANT-2 | High | 10F — state machine before authZ |
| D-CARDS-VALIDATION-1 | High | 16F — silent accept invalid/missing fields |
| D-CARDS-500-1 | High | 6F — null crash on missing fields (500 not 400) |
| D-CARDS-BUSINESS-1 | High | 4F — no balance/destination/currency guards |
| D-CARDS-BULK-1 | High | 30B — bulk endpoints 404 (persistence split) |
| D-CARDS-STATEMACHINE-1 | High | confirmed prior — no state guards on activate/unfreeze/terminate |
| D-CARDS-AUTH-1 | Medium | 16F — bank token 401 not 403 |
| D-CARDS-SCHEMA-1 | Low | 1F — failureReason absent from fulfillment/status |
| D-CARDS-SCHEMA-2 | Low | 1B — fulfillment.status absent after reinitiate |
