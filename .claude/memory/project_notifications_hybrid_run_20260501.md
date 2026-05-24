---
name: Kardit Notifications Hybrid Run 2026-05-01
description: Notifications run with full classifier patches; 120 TCs (19P/99F/2B); 1 runner-side defect (B9 misclassification); backend CATASTROPHIC — 100% of FAILs are 500 server errors
type: project
service: Notifications
run_date: 2026-05-01
tcs: 120
passes: 19
fails: 99
blocked: 2
pass_rate: 16
worst_cluster: H 5xx (100% of FAILs)
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
Final Notifications run, 2026-05-01 23:29 — canonical Notifications record.

## Source artifacts

- Harness: `Downloads\postman_hybrid_notifications_runner.py` (cloned from batch hybrid; pre-flight via list-first GET /notifications)
- Pack: `Downloads\kardit_notifications_api_test_agent_v1\kardit_notifications_api_test_agent_v1\data\notifications_TC.json` (120 TCs)
- Swagger: pointed at master swagger (notifications has no service-specific swagger — config references `data/swagger.json` but file missing)
- Final YAML: `Downloads\notifications_postman_hybrid_report_20260501-232937.yaml`

## Counts: 120 TCs (19 PASS / 99 FAIL / 2 BLOCKED / 0 ERROR)

## Pack drift handled (uniform)

All 3 endpoints: pack `/api/v1/notifications/*` → Postman `/notifications/*` (no /api/v1 prefix). Pack is wrong; Postman trusted as source of truth (matches deployed backend pattern).

## Pre-flight outcome

- GET `/notifications` returned non-2xx → list-discovery FAILED
- No Postman literal usable
- Verify not attempted; PATCH ran without seeded notificationId

## Critical finding: 100% of FAILs are 5xx

**ALL 99 FAILs are 500 server errors** — single cluster H total dominance.

| Endpoint | P | F | B | Pass rate |
|---|---:|---:|---:|---:|
| GET `/notifications` | 2 | 38 | 0 | 5% |
| PATCH `/notifications/{notificationId}` | 9 | 30 | 1 | 23% |
| POST `/notifications/settings` | 8 | 31 | 1 | 21% |

Same shape as Customer + Transactions read subsystem: validation runs, then crashes. The 19 PASSes are all required-field/blank-field validation rejections returning clean 400 before the crash point.

## 9 product capabilities tested (45 unique scenarios)

The classifier patches operationalized 9 product behaviors that the test pack asks about. When the next fix lands, these are what to verify:

1. **List filtering & pagination** (10 scenarios) — status enum/case validation, totalCount accuracy, default sort (createdAt DESC), <3s SLA on 100 items
2. **List response contract** (2 scenarios) — every notification must have `notificationId, type, entityId/relatedEntityId, status, createdAt, readAt`
3. **PATCH input validation** (6 scenarios) — reject non-string status, off-enum values, case-mismatched enums, empty/case-altered IDs
4. **PATCH state machine** (5 scenarios) — READ → readAt set; UNREAD → readAt cleared; only `status + updatedAt` change (message/type/createdAt immutable); notification not deleted
5. **PATCH idempotency** (2 scenarios) — re-marking same status is 200 no-op (no 409, no readAt rewrite)
6. **Tenant isolation** (2 scenarios) — foreign-tenant PATCH returns 403/404 without leaking existence
7. **Settings — toggle granularity** (10 scenarios) — per-channel (email/sms/inApp) + per-event (cardFreeze/cardTerminate/limitRequest) + bulk
8. **Settings — type validation** (4 scenarios) — rejects non-boolean values
9. **Settings — persistence semantics** (4 scenarios) — POST is overwrite (not merge), response echoes request, takes effect on subsequent dispatches

Every one of these capabilities triggered a 500 instead of working correctly.

## Engineering ownership

100/120 (83%) backend-owned: 99 FAIL + ~1 B1 BLOCKED. Runner residual: 1 B9 misclassification (TC-API-NOT-03-036, `unknown_*` regex caught it before specific rule).

## Critical fix priority

1. **Read 99 stack traces** — likely a shared middleware/DTO/DB defect spraying 500s across all 3 endpoints. Server logs during 23:29 run window. Triggering bodies in `Downloads\evidence_postman_notifications_hybrid_20260501-232937\`.
2. **GET `/notifications` 95% crash rate** even on basic happy-path read — list endpoint is unconditionally broken. Single highest-leverage fix.
3. **Service-wide brokenness, not endpoint-specific** — fix the shared cause and the entire suite should improve dramatically.
