---
name: project_notifications_run_20260521
description: Notifications hybrid run session 2026-05-20/21 — 10.8% → 80.1%; 6 harness fixes; backend defects confirmed
metadata: 
  node_type: memory
  type: project
  originSessionId: b8767143-319e-427d-89d5-8b5ce6dd85b8
---

Final result: 149P/30F/7B (80.1%) across 186 TCs (5 endpoints). Started at 10.8% (2026-05-08 baseline).

**Why:** Full harness rebuild session to get Notifications runner production-quality.

## 6 harness fixes shipped

1. **POSTMAN_PATH** — updated to `Kardit.Api.postman_collection (8).json`
2. **Pre-flight mint** — added `_mint_seed_notification()` that POSTs to `/notifications/create` with real random UUIDs; force-persists the returned `NOT-2026-xxx` ID even when verify returns 404 (Cluster-C split)
3. **PATCH base status normalization** — PMC base has `status="string"` (placeholder); normalized to `"READ"` in main loop
4. **PATCH explicit UNREAD handlers** — mark_notification_unread_success, mark_already_unread_as_unread_idempotent, read_at_cleared_when_marked_unread explicitly set `status="UNREAD"`
5. **GET /notifications base query normalization** — stripped any query param whose value is literal `"string"`; fixed 26 G_4xx in one change
6. **`no_notifications_returns_empty`** — changed from `set_query status=NONEXISTENT_STATUS_XYZ` to `as_is`

## Backend defects confirmed (30 FAILs)

- **D-NOT-AUTH-1**: 25 B_silent_accept — all 5 endpoints accept unauthenticated/invalid-token requests with 200
- **D-NOT-EVENTS-1**: 5 G_4xx — `events` field not in `UpdateNotificationSettingsRequest` .NET DTO
- **D-NOT-SLA-1**: 1 Z_other — GET /notifications returned 18.3s for 13 records (threshold: 2s)

## Key discoveries

- `NOT-2026-xxx` is the notificationId format (not a UUID)
- NotificationType enum: OnboardingCaseSubmitted, OnboardingCaseApprovedForBankReview, OnboardingCaseApproved, OnboardingCaseRejected
- Valid PATCH status values: `"READ"`, `"UNREAD"`
- Cluster-C write/read split was transient: by 2026-05-21 run the minted ID was queryable
