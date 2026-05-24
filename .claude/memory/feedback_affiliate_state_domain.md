---
name: feedback_affiliate_state_domain
description: "Affiliate state domain — no \"unapproved\" state exists; ACTIVE once provisioned; blocking is IAM-only (full privilege revocation)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e8d110a8-aab4-44fc-958a-f620f302bf47
---

Affiliates have exactly two observable states from the HTTP API: **ACTIVE** (provisioned) or **BLOCKED** (IAM revocation). There is no "unapproved" or "pending" affiliate state.

**Why:** User confirmed 2026-05-18. Once an onboarding case is approved and the affiliate is provisioned via POST /api/v1/affiliates, the affiliate is immediately ACTIVE. Blocking happens through the IAM layer and revokes all privileges — it cannot be seeded or reset via the HTTP API runner.

**How to apply:**
- Any scenario named `affiliate_not_approved_rejected` or similar that assumes an "unapproved" affiliate state → classify as BLOCKED with reason explaining this state doesn't exist via HTTP.
- Do NOT attempt to mint or seed an "unapproved" affiliate for test isolation.
- If a scenario intends to test a BLOCKED/IAM-revoked affiliate, flag it as untestable via the runner and document as a backend/infra test-data ask.
