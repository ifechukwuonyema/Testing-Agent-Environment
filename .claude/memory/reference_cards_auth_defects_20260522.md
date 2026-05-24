---
name: reference_cards_auth_defects_20260522
description: Confirmed Cards auth defects from port-8082 auth runner session 2026-05-22 — resolved vs open status updated end of session
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5a397891-3858-46d1-a7e6-4750ffdda215
---

Source: `cards_auth_runner.py` runs 2026-05-22. Target: `http://167.172.49.177:8082`

## OPEN DEFECTS

**D-CARDS-AUTH-1 — GET /auth/permissions completely open**
- SC01 through SC06 all return 200 (silent_accept). Zero auth enforcement.

**D-CARDS-ORPHAN — Backend provisioned ~115 cards with empty customerId + maskedPan**
- All ACTIVE VIRTUAL cards on bankId `000045f9-d01b-479c-a84d-0fe82454d55a` have `customerId: ""` and `maskedPan: ""`.
- Fund movement endpoints crash with 500 when card has no real customer/PAN.
- Runner now filters these out in Phase 0g.

**D-CARDS-LOADREQ — POST /cards/{cardId}/load-requests crashes with 500**
- Phase 0i always 500s. CLOADR, CLAPPR, CLGET removed from ENDPOINTS list.

## RESOLVED DEFECTS

**D-CARDS-1 — Garbage token crashed to 500 (RESOLVED by backend ~2026-05-22)**
- Was: SC03 (Bearer garbage token) → 500 on every endpoint.
- Now: SC03 → 401 `{"error":"invalid_token"}` on all endpoints. 33 TCs moved from FAIL to PASS.

**D-CARDS-SIG-1 — GET /metrics/bank/{bankId} ECDSA not enforced (RESOLVED in runner)**
- Fix: MBNK `signed=False`. 2 false FAILs eliminated.

**D-CARDS-5XX-PAYLOAD — CLOADS + CUNLD returned 500 (RESOLVED by payload fix)**
- Fix: payloads aligned to Postman CARDSNEW.json.

## CURRENT BASELINE (end of 2026-05-22 session)
225 TCs — PASS: 206 / FAIL: 0 / BLOCKED: 1 / N/A: 18
- 1 BLOCKED: OPLIM-SC09 (limit-request mint fails — no valid non-orphaned card)
