---
name: feedback_affiliate_owned_pool
description: CARD-19 activate happy paths need a PENDING_ACTIVATION card owned by the canonical affiliate; wrong-affiliate cards return 404 even when the body carries the right affiliateId
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5f2f7813-c7e7-4f05-a43e-70943f5bfa14
---

When the runner re-injects canonical affiliateId (`a7d5929b-cba8-4e97-8985-2ce1d9fc91c3`) into the CARD-19 activate request body, but the card in `path_vars.cardId` belongs to a different affiliate (`AFF-8C992302453946C7A03D2D7EF8670B49`), the backend returns 404 "Card not found." Backend enforces that the card must be owned by the affiliate making the request.

**Why:** The list endpoint `GET /api/v1/cards?status=PENDING_ACTIVATION` returns cards from all affiliates. Phase 0f3d probed for phantom cards but couldn't filter by affiliate because GET /cards/{id} doesn't always return affiliateId — so `dropped_wrong_affiliate` stayed 0.

**How to apply:** During Phase 0f1 PENDING_ACTIVATION enumeration, build a separate `cardIdPendingActivationOwnedPool` for cards where list-level `affiliateId == session_ids["affiliateId"]`. Route CARD-19 activate happy paths to this owned pool first, falling back to the full pool only if exhausted. Same pattern applies to any write endpoint that checks affiliate ownership server-side.
