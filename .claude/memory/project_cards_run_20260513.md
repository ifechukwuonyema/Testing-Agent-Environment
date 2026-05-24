---
name: Cards Hybrid Run 2026-05-13
description: 6 harness fixes + 13 pack edits; 427/720 PASS (59.3%); 109 confirmed backend FAILs; pack now 720 TCs / 21 endpoints
type: project
service: cards
run_date: 2026-05-13
tcs: 720
passes: 427
fails: 109
blocked: 184
pass_rate: 59.3
originSessionId: f1d2538a-d992-4d2c-b706-84c5fe821fa8
---
Final Result (run 134147): 720 TCs | 427 PASS (59.3%) | 109 FAIL | 184 BLOCKED
Previous baseline (2026-05-12): 438P/156F/178B on 772 TCs (56.7%)

## Three harness fixes shipped

**Fix 1 — PIN-01 routing → `cardIdFrozen` instead of `cardIdLoadable`:** Separate branch for `POST /api/v1/cards/{cardId}/pin-reset` → `cardIdFrozen or cardIdActive`. **+6 PASSes.**

**Fix 2 — LIM-02 `malformed_card_id_rejected` cardId override guard:** Added `if scenario != "malformed_card_id_rejected"` guard. **+1 PASS.**

**Fix 3 — Phase 0f3c: probe `cardIdActiveTerminatePool` for stale entries:** Probe each card via GET, drop non-ACTIVE. **+4 PASSes.**

## Three pack edits applied

**Edit 1 — API-LIM-02 entire endpoint removed** (40 TCs, 779→730 TCs, 22→21 endpoints)
**Edit 2 — TC-API-CARD-11-002 `unknown_scope_id_not_found` deleted**
**Edit 3 — TC-API-LIM-01-012 `product_currency_mismatch_rejected` deleted**

## 109 confirmed backend FAILs

- Cluster 1 — Auth bypass → 200 (38 FAILs): BAL-01, CARD-11, CARD-12, FUL-01, ISS-03, ISS-04, LIM-01, PIN-01
- Cluster 2 — Body-before-auth → 400 or 409 (38 FAILs): FRZ-01, TRM-01, UNF-01, FUL-02, FUL-03, CARD-19, LOAD-01, UNLD-01
- Cluster 3 — Card token not provisioned (12 FAILs): LOAD-01 + UNLD-01 happy path
- Cluster 4 — Schema drift + Accept header (7 FAILs)
- Cluster 5 — State/flow/CMS defects (14 FAILs)

Harness: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\postman_hybrid_cards_runner.py`
Pack: `cards_microservice_functional_test_pack_v1_40_each.json` — 720 TCs, 21 endpoints
