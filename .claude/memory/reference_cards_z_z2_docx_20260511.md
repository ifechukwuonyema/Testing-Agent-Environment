---
name: Cards Z & Z2 Recommendation DOCX 2026-05-11
description: DOCX with per-TC recommendation tables for Z2 (schema drift) and Z_other clusters from cards replay 2026-05-11
type: reference
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
`Downloads\cards_z_z2_recommendations_2026-05-11.docx`

Generator: `Downloads\generate_cards_z_z2_recommendations_docx.py`

**Z2 findings (8) — three rename patterns:**
- Pattern A (4 TCs): `actionedAt` → `timestamp` on FRZ-01, UNF-01, TRM-01, FUL-02 responses
- Pattern B (1 TC): `productType` → `cardType` on CARD-13 (POST /cards/query) array items
- Pattern C (3 TCs): `fulfillment.status` undeclared + `failureReason` missing (FUL-01); `virtualAccount.bankId` undeclared + `virtualAccountStatus` missing (ISS-04 ×2)

**Z_other findings (2):**
- ISS-03: 406 Not Acceptable not returned when `Accept: text/plain` sent
- FUL-02: `timestamp` field absent in response body; backend returns `updatedAt` instead

All 8 Z2 FAILs fixed by renaming 3 field patterns in backend response serialization.
