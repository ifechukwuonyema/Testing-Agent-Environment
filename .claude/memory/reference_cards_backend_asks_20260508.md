---
name: Cards Backend Asks DOCX 2026-05-08
description: Pointer to Cards backend-asks DOCX filed after run 03:20 with all 3 audit fixes; D-CARDS-1..6 + ceiling projection
type: reference
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
---
## Pointer

- DOCX: `Downloads\Kardit\reports\cards_backend_asks_2026-05-08.docx`
- Generator: `Downloads\generate_cards_backend_asks_20260508.py`
- Run baseline: 468 PASS / 158 FAIL / 216 BLOCKED = 55.6% pass-rate (842 TCs)

## Asks summary

- **D-CARDS-1 (Critical, +4.7pp)**: Auth/RBAC pipeline missing on 8 of 22 endpoints. 40 silent-accepts.
- **D-CARDS-2 (High, +14.6pp)**: Audit-log + persistence read endpoints. 123 BLOCKED across 19 endpoints.
- **D-CARDS-3 (Critical, +10.7pp)**: Test-data — link canonical affiliate to canonical bank. 90 cluster-C 404 BLOCKEDs.
- **D-CARDS-4 (Medium, +2.4pp)**: Missing response fields — virtualAccountStatus, failureReason, cardType, timestamp, etc.
- **D-CARDS-5 (Test-data, +4.6pp)**: Repeatable happy-path support. 39 state-conflict 409s.

## Ceiling

Current 55.6% → ~60.3% (D-CARDS-1) → ~71.0% (+D-CARDS-3) → ~75.6% (+D-CARDS-5) → ~78.0% (+D-CARDS-4) → ~92.6% (+D-CARDS-2).

Note: superseded by [[reference_cards_backend_asks_20260523]] for current defect register.
