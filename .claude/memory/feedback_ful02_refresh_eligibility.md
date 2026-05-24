---
name: feedback_ful02_refresh_eligibility
description: "FUL-02 refresh eligibility is determined by list-level fulfillmentStatus=PERSONALIZING, not bureauStatus from the individual /fulfillment/status endpoint"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5f2f7813-c7e7-4f05-a43e-70943f5bfa14
---

For `POST /api/v1/cards/{cardId}/fulfillment/refresh`, the backend returns 409 "Fulfillment refresh is only allowed while card fulfillment is in progress" for any card that does not have `fulfillmentStatus=PERSONALIZING` at the list level.

**Why:** The individual `GET /cards/{cardId}/fulfillment/status` endpoint returns `fulfillment.bureauStatus` (e.g. SENT, FAILED) — a different field that is NOT the discriminator for refresh eligibility. Cards with `bureauStatus=SENT` still 409 on refresh if their list-level `fulfillmentStatus` is not PERSONALIZING. Confirmed empirically 2026-05-14.

**How to apply:** When seeding `cardIdRefreshInProgressPool`, query `GET /api/v1/cards?status=<S>&productType=PHYSICAL` for statuses ACTIVE, PENDING_ACTIVATION, PENDING_ISSUANCE and check top-level `fulfillmentStatus` field on each item. Only include cards where that field == "PERSONALIZING". Never use `bureauStatus` from the individual endpoint as a proxy.
