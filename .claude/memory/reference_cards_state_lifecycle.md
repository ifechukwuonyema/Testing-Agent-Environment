---
name: Cards state lifecycle and per-endpoint state allowlists
description: Observed (not documented) card lifecycle states and which endpoints accept which states. Captured 2026-05-06 from live backend probes.
type: reference
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
## States observed in the live system

| State | Description | How a card reaches this state |
|---|---|---|
| PENDING_ISSUANCE | Just minted via /cards/issuance, awaiting CMS provisioning | POST /cards/issuance returns 200 |
| PENDING_ACTIVATION | CMS-provisioned, ready to activate | **No public path observed** — D-09 |
| ACTIVE | Activated, in use | POST /cards/{cardId}/activate (only valid from PENDING_ACTIVATION) |
| READY | Post-personalization, delivered, ready to use | Backend-only transition — no public API |
| FROZEN | Suspended | POST /cards/{cardId}/freeze (from ACTIVE or READY) |
| TERMINATED | Permanent | POST /cards/{cardId}/terminate (from any non-TERMINATED state) |

## Per-endpoint state allowlists (verified 2026-05-06 via 400 response detail strings)

| Endpoint | Accepted states | Rejection signal |
|---|---|---|
| POST /cards/{cardId}/activate | PENDING_ACTIVATION only | 422 "Card cannot be activated from status 'PENDING_ISSUANCE'. Expected 'PENDING_ACTIVATION'." |
| POST /cards/{cardId}/freeze | ACTIVE, READY | 4xx with state-mismatch detail |
| POST /cards/{cardId}/unfreeze | FROZEN | 4xx |
| POST /cards/{cardId}/pin-reset | ACTIVE, FROZEN (NOT READY, NOT PENDING_*) | 400 "PIN reset is not allowed for card status '<X>'. Allowed statuses: ACTIVE, FROZEN." |
| POST /cards/{cardId}/loads | ACTIVE (with funded virtual account) | 4xx if non-ACTIVE |
| POST /cards/{cardId}/limit-requests | ACTIVE | 4xx if non-ACTIVE |
| POST /cards/{cardId}/fulfillment/refresh | only "in-progress" fulfillment | 409 "Fulfillment refresh is only allowed while card fulfillment is in progress." |
| POST /cards/{cardId}/fulfillment/reinitiate | PHYSICAL only | 400 "Fulfillment re-initiation applies to physical cards only." |

## System state distribution (2026-05-06)

| Status | Total records |
|---|---|
| TERMINATED | 285 |
| PENDING_ISSUANCE | 152 |
| FROZEN | 19 |
| ACTIVE | **0** |

**The harness cannot get a real ACTIVE card via the public API.** Issuance creates PENDING_ISSUANCE; there's no public path to PENDING_ACTIVATION; activate only works from PENDING_ACTIVATION.
