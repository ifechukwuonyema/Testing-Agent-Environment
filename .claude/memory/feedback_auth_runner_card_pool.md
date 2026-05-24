---
name: feedback_auth_runner_card_pool
description: "Cards auth runner lessons — CTERM last, affiliateId override, IAM URL, card pool validation, payload alignment to Postman"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5a397891-3858-46d1-a7e6-4750ffdda215
---

**Rule 1: CTERM must always be the last endpoint in ENDPOINTS.**
**Why:** CTERM-SC09 terminates the provisioned card. Mid-list → subsequent card endpoints return 500 on bad tokens (state cascade) → ~90-TC PASS regression.
**How to apply:** Any time ENDPOINTS is reordered, move CTERM back to the end.

**Rule 2: Capture affiliateId from Phase 0g (list), not Phase 0h (individual probe).**
**Why:** `GET /api/v1/cards/{cardId}` does NOT return `affiliateId`. Only `GET /api/v1/cards` (list) does. Override `session_vars["affiliateId"]` in Phase 0g right after picking the card.
**How to apply:** After `session_vars["card_id"] = picked`, also set `session_vars["affiliateId"] = best.get("affiliateId")` if different.

**Rule 3: IAM URL is `https://hasham.platform.dev.chamsswitch.com/gateway/token`, NOT port 9000.**
**Why:** Port 9000 connection-resets. The correct URL is in the runner at `IAM_URL` constant.
**How to apply:** If token mint fails, read the runner source for IAM_URL before assuming server is down.

**Rule 4: Phase 0g must filter out orphaned cards (empty customerId or maskedPan).**
**Why:** Backend can provision cards without completing the issuance chain — these cards have `customerId: ""` and `maskedPan: ""`. Fund movement endpoints (loads, unloads) crash with 500 on these cards. As of 2026-05-22, the entire pool of ~115 ACTIVE VIRTUAL cards on bankId `000045f9-d01b-479c-a84d-0fe82454d55a` is orphaned.
**How to apply:** `_card_pool()` filter includes `and c.get("customerId") and c.get("maskedPan")`. If Phase 0g finds no usable cards, the backend needs to provision a properly issued card before SC09 fund-movement tests can pass.

**Rule 5: Cards on port 8082 — affiliateId in list response is AFF-format, not UUID.**
**Why:** `GET /api/v1/cards` returns `affiliateId` as `AFF-9F6EDBBE20DD4C6B97D0B720676506E1`. Filtering by UUID returns 0 results.
**How to apply:** Compare against AFF-format strings when filtering card lists.

**Rule 6: Always align POST payloads to Postman CARDSNEW.json before first run.**
**Why:** Runner bodies built from swagger guesses were missing required fields — CLOADS missing `fundingReference`, CUNLD missing `destinationAccount`, OPLIM sending `{}` instead of full ops payload, CFFRE using undefined body_key `ctx_only`. These caused 500s that looked like backend defects but were runner payload gaps.
**How to apply:** For every new POST endpoint added to ENDPOINTS, pull the corresponding Postman body from `Downloads/CARDSNEW.json` and use it as the template. Never guess required fields from swagger alone.
