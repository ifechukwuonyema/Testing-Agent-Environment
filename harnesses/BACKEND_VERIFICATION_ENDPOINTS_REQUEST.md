# Backend Ask: Read-Only Verification Endpoints

**Audience:** Kardit backend team
**From:** Onyema Ifechukwu (API testing)
**Date:** 2026-05-03
**Priority:** Medium — unlocks ~109 currently-BLOCKED test cases per Cards run

---

## Why this exists

The Postman-hybrid test harness validates side effects by HTTP only. That means:

- Anything observable via `GET /resource/{id}` we can verify directly.
- Anything that happens **inside** the platform (audit-log rows, queued notifications, CMS handshake state, transaction-record inserts, lifecycle events) we **cannot see** from outside the API.

Right now ~118 test cases per Cards run are correctly classified as BLOCKED for this reason. We've added a state-effect probe that recovers the small fraction (~9) where the side effect happens to be visible through an existing GET. The remaining ~109 genuinely need backend cooperation.

This document lists the smallest set of read-only endpoints that would unblock those tests without exposing any sensitive operation.

---

## Endpoints requested

Each is **read-only**, returns no PII beyond what existing endpoints already return, and supports filtering by the request-side identifier we already pass in.

### 1. `GET /api/v1/audit-logs`

**Purpose:** confirm audit-log entries were written for state-changing operations.

**Query params (any combination):**
- `entityId` — cardId, bankId, affiliateId, etc.
- `entityType` — "card", "bank", "affiliate", "limit-request", etc.
- `requestId` — the request-context requestId we send on every TC
- `actionType` — "freeze", "unfreeze", "terminate", "issuance", etc.
- `since` — ISO-8601 timestamp; default: last 1 hour
- `limit` — default 50, max 200

**Response shape:**
```json
{
  "data": [
    {
      "auditLogId": "AUD-...",
      "entityId": "CAR-...",
      "entityType": "card",
      "actionType": "freeze",
      "requestId": "...",
      "actorId": "...",
      "occurredAt": "...",
      "metadata": { ... }
    }
  ],
  "total": 1
}
```

**Unblocks:** ~16 `audit_log_created` BLOCKEDs across freeze/unfreeze/terminate/issuance/loads/unloads/limit-requests/pin-reset.

---

### 2. `GET /api/v1/notifications`

**Purpose:** confirm notifications were queued/dispatched for state-changing operations.

**Query params:**
- `correlationId` — preferred; the requestId we already pass
- `recipientType` — "customer" / "affiliate" / "bank" / "admin"
- `recipientId` — optional
- `eventType` — "card.frozen" / "card.terminated" / "issuance.completed" / etc.
- `since`, `limit` as above

**Response shape:**
```json
{
  "data": [
    {
      "notificationId": "NOT-...",
      "correlationId": "...",
      "recipientType": "customer",
      "recipientId": "...",
      "eventType": "card.frozen",
      "channel": "email",
      "status": "QUEUED",
      "createdAt": "..."
    }
  ],
  "total": 1
}
```

**Unblocks:** ~13 `notification_created_where_required` / `notification_to_*` BLOCKEDs.

---

### 3. `GET /api/v1/cms/request-logs`

**Purpose:** confirm CMS handshake state — that the platform actually called CMS, computed signatures, included MACs, and recorded the round-trip.

**Query params:**
- `requestId` — the platform-side requestId
- `cardId` — optional
- `operation` — "freeze" / "unfreeze" / "terminate" / "load" / "unload" / "pin-reset" / "issue"
- `outcome` — "SUCCESS" / "FAILURE" / "RETRY"
- `since`, `limit`

**Response shape:**
```json
{
  "data": [
    {
      "cmsRequestId": "CMSREQ-...",
      "platformRequestId": "...",
      "cardId": "CAR-...",
      "operation": "freeze",
      "tokenObtained": true,
      "signatureComputed": true,
      "macIncluded": true,
      "outcome": "SUCCESS",
      "responseStatus": 200,
      "retryCount": 0,
      "occurredAt": "..."
    }
  ],
  "total": 1
}
```

**Unblocks:** ~58 CMS-related BLOCKEDs (`cms_token_obtained`, `cms_signature_computed`, `cms_mac_included`, `cms_failure_retry_policy`, `cms_request_log_created`, `cms_*`, etc.).

---

### 4. `GET /api/v1/transactions` *(if not already provided by Transactions service)*

**Purpose:** confirm transaction-record creation for `/loads`, `/unloads`, `/limit-requests/complete`.

**Query params:**
- `cardId`
- `correlationId` / `requestId`
- `type` — "LOAD" / "UNLOAD" / "LIMIT_ADJUSTMENT"
- `since`, `limit`

**Response shape:** existing Transactions DTO; just need correlationId-based filtering.

**Unblocks:** ~10 `transaction_record_created` BLOCKEDs.

---

### 5. `GET /api/v1/cards/{cardId}/lifecycle-events`

**Purpose:** confirm card-lifecycle events were emitted for state changes.

**Response:**
```json
{
  "cardId": "CAR-...",
  "events": [
    {
      "eventId": "EVT-...",
      "eventType": "card.frozen",
      "occurredAt": "...",
      "actorId": "...",
      "metadata": { ... }
    }
  ]
}
```

**Unblocks:** ~10 `card_lifecycle_event_created` BLOCKEDs.

---

## Alternative: requestId propagation

If shipping new endpoints isn't feasible, the next-best option is to **propagate the `requestId` we already pass into every audit-log row, notification, CMS log, transaction record, and lifecycle event.** Once propagated, we can correlate after the fact via existing query mechanisms (admin DB views, log aggregation, etc.).

This is strictly worse than read-only verification endpoints because it requires us to query infrastructure outside the API surface, but it's a viable fallback.

---

## What this unlocks numerically

Per Cards hybrid run (830 TCs):

| Today | After verification endpoints |
|---|---|
| ~118 BLOCKED (B1_db_verify) | ~9 BLOCKED |
| ~14% of the run is unverifiable | ~1% of the run is unverifiable |

Across all 8 services in the chain, we estimate ~600-700 currently-BLOCKED B1 TCs would convert to PASS/FAIL with deterministic attribution.

---

## What this does NOT change

- Existing endpoints are not modified.
- No new write paths are exposed.
- No PII surfaces are widened — these read-only endpoints return the same data the testing harness already has access to via the operations under test.
- Pass-rate metrics will reflect *real* defects more accurately, not artificial PASS inflation.

---

## Suggested rollout order

1. `GET /api/v1/audit-logs` — unblocks the biggest cluster (~16) and is the simplest to ship.
2. `GET /api/v1/cms/request-logs` — unblocks the largest cluster (~58 CMS-related).
3. `GET /api/v1/notifications` — ~13.
4. The remaining two — incremental.

Each can ship independently and unblock its corresponding test cluster the next run.

---

## Contact

`ifechukwuthemagister@gmail.com` for any clarifications on scenario names, query semantics, or response shape preferences.
