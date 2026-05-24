---
name: Backend Ask — Read-Only Verification Endpoints
description: Document filed 2026-05-03 requesting 5 read-only verification endpoints from backend team to unblock ~109 of 118 B1_db_verify BLOCKEDs per Cards run; ~600-700 across the chain
type: reference
originSessionId: a00fb0b4-c57c-4815-892a-3966d012e235
---
Document file: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\BACKEND_VERIFICATION_ENDPOINTS_REQUEST.md`

**Why:** ~118 B1_db_verify BLOCKEDs per Cards run (~14% of the suite) are correctly classified as unverifiable from outside the API. Of those, ~9 are observable via existing GETs (handled runner-side by state_effect_probe). The remaining ~109 require backend cooperation. This document is the formal ask.

**Endpoints requested (priority order in the doc):**

1. `GET /api/v1/audit-logs` — filterable by entityId/entityType/requestId/actionType/since. Unblocks ~16 audit_log_created TCs.
2. `GET /api/v1/cms/request-logs` — CMS handshake state (token obtained, signature computed, MAC included, retry outcome). Unblocks ~58 CMS-related TCs (the LARGEST cluster).
3. `GET /api/v1/notifications` — filterable by correlationId. Unblocks ~13 notification_created TCs.
4. `GET /api/v1/transactions` (or extension if Transactions service already provides this) — filterable by correlationId. Unblocks ~10 transaction_record_created TCs.
5. `GET /api/v1/cards/{cardId}/lifecycle-events` — unblocks ~10 card_lifecycle_event_created TCs.

**Alternative if endpoints are infeasible:** propagate the requestId we already pass on every TC into all audit-log rows, notifications, CMS logs, transaction records, and lifecycle events. Then we can correlate post-hoc via existing infra. Strictly worse than verification endpoints, but viable.

**Numerical impact per Cards run:**

- Today: ~118 BLOCKED (B1) ≈ 14% of run unverifiable
- After endpoints: ~9 BLOCKED ≈ 1% unverifiable

**Across all 8 chain services:** estimated ~600-700 currently-BLOCKED B1 TCs would convert to PASS/FAIL with deterministic attribution.

**No PII risk:** these endpoints return only metadata about operations the harness is already exercising — no widening of sensitive data exposure.

**How to follow up:**

When backend ships any one of these endpoints, the relevant subset of B1 BLOCKEDs needs the harness updated to call the new endpoint after each write and verify the side effect. Add the call into `state_effect_probe` (or a sibling helper) keyed off the scenario keyword. Then re-run the chain and update the leaderboard.

## See also

- [[feedback_get_after_post_probe|GET-after-POST probe pattern]]
- [[project_cards_hybrid_run_20260503|Cards run 2026-05-03]]
- [[reference_kardit_harness_optimizations_20260503|Harness optimizations 2026-05-03]]
