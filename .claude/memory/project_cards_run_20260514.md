---
name: project_cards_run_20260514
description: Cards Hybrid Run 2026-05-14 — review-driven 9-TC replay session; all 9 originally-failed TCs fixed and passing
metadata: 
  node_type: memory
  type: project
  originSessionId: 5f2f7813-c7e7-4f05-a43e-70943f5bfa14
---

Focused review-fix session on 9 failed TCs from the prior report. Final result: 9/9 PASS.

**Why:** Backend team reviewed the DOCX findings and returned review.txt with 5 corrections; remaining 4 needed runner/data fixes.

**Changes made:**
- TC-API-FUL-02-037 (`reason_special_chars_safe`) DELETED from pack — FUL-02 refresh has no `reason` field in its request body
- Runner fix: `cardIdRefreshInProgressPool` now seeded only from cards with `fulfillmentStatus=PERSONALIZING` at list level
- Runner fix: `already_target_state_rejected` on FUL-02 now routed to `cardIdFailedFulfillmentPool`
- Runner fix: `cardIdPendingActivationOwnedPool` seeded during Phase 0f1, filtered to canonical affiliateId
- Runner fix: CARD-19 activate happy path re-injects canonical affiliateId UUID into body after override
- Runner fix: `cardIdActivePool` pool head used as fallback when `cardIdActive` scalar is None
- CARD-19 retry on 404 with next PENDING_ACTIVATION pool card
- FUL-02 retry on 409 with next refresh pool card

**How to apply:** Before the next Cards run, check Phase 0f3 log line for `refresh_inprogress` count. If 0, FUL-02 happy paths will BLOCK rather than 409.

Report: `cards_postman_hybrid_report_replay_failed_20260514-180152.yaml` — 9 TCs, 9P/0F/0B
