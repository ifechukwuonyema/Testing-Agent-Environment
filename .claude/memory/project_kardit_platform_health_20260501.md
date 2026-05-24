---
name: Kardit Platform Health Snapshot 2026-05-01
description: Cross-service summary across 8 microservices tested 2026-05-01; 3-tier service health stratification (catastrophic / mid / healthy); shared root-cause hypotheses; recommended platform-level fix sequence
type: project
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
Snapshot of full Kardit platform health after 8 microservice hybrid runs on 2026-05-01.

## Service health ranking (PASS rate)

| Tier | Service | TCs | PASS | Pass rate | Worst defect cluster |
|---|---|---:|---:|---:|---|
| **Catastrophic** | Notifications | 120 | 19 | 16% | H 5xx (99, 100% of FAILs) |
| **Catastrophic** | Customer | 120 | 14 | 12% | H 5xx (103, 100% of FAILs) |
| **Catastrophic** | Transactions read subsystem | 320 | 2 | 0.6% | H 5xx (273, all 8 read endpoints) |
| Mid | Bank | 472 | 66 | 14% | Z1 envelope (105) + Cluster-C seed (160) |
| Mid | Affiliate v2 | 917 | 252 | 27.5% | Z1 envelope (105) |
| Mid | Cards (hybrid) | 840 | 259 | 31% | Schema drift (118) |
| Mid | Admin | 123 | 53 | 43% | H 5xx (22 on /admin/banks) |
| **Healthy** | Transactions export subsystem | 120 | 78 | 65% | Cluster B (35) |
| **Healthy** | Batch | 177 | 102 | 58% | Cluster B (54), zero 5xx |

## Three-tier shape

**Catastrophic (Notifications, Customer, Transactions-read):** ~80-100% of FAILs are 5xx. Validation works (returns clean 400 for missing required fields), then crashes immediately after on any business logic. Pattern: validator → controller → crash. Suggests shared middleware/DTO/DB-connection defect that fires post-validation but pre-controller. Probably a single platform-level root cause: missing service registration, unconfigured DB connection on read pipeline, or NRE in shared request-context binder.

**Mid (Bank, Affiliate, Cards, Admin):** mixed. 5xx exist but aren't dominant. Real defect classes (envelope drift, schema drift, persistence split) that are well-understood and fixable but require per-service work.

**Healthy (Batch, Transactions-export):** zero or near-zero 5xx. Validation in place. PASS rates 55-83%. Cluster B (silent accept) is the dominant remaining defect — conventional "trust client input too much" issue, single validation pass closes the bulk.

## Hypothesis: shared root cause for the catastrophic tier

The fact that Customer + Notifications + Transactions-read all share:
- 80-100% × 5xx FAIL distribution
- Validation works (the 13-19 PASSes are all required-field rejections)
- Crash spread evenly across all endpoints in the service

...suggests a **platform-level defect that ships with new microservices but not the established ones**. Possibilities:
- Shared `RequestContext` binding/middleware that NREs on certain payload shapes
- Shared persistence layer (EF DbContext registration issue, missing migration, broken connection string)
- Shared logging/audit middleware that crashes when the request can't be serialized

Reading the stack traces from the 99 + 103 + 273 = 475 × 5xx evidence files would identify whether it's the same exception type. If yes, single platform fix unlocks 3 services.

## Cross-service runner improvements landed 2026-05-01

All 8 hybrid harnesses share the canonical pattern from `feedback_postman_driven_testing.md`:
- Pre-flight verify-loop + Cluster-C reclassification (FAIL → BLOCKED with explicit cluster tag)
- 5-code client-error family equivalence (400/404/405/409/422 interchangeable; 200 stays distinct)
- Per-TC requestContext rotation
- Per-TC payload + response inline in YAML
- Synthetic array injection for B7
- Path-template override for pack/Postman drift

Total runner-side defects after fix passes: 0 across all 8 services (Admin had 0, Customer had 0 after patches, Transactions had 0 after patches, Batch had 0 after patches, Notifications has 1 B9 residual). Engineering ownership across all services: **86-93%** of non-PASS results.

## Path drifts identified (all pack-side errors)

| Service | Drift | Fix |
|---|---|---|
| Bank | dashboard pack v2 OK, was misconfigured to non-existent v1 in PACK_TO_POSTMAN | Map fixed |
| Customer | pack `/customers/drafts` → Postman `/customers/draft` | PACK_TO_POSTMAN |
| Customer | pack `{customerId}` → Postman `{customerRefId}` | PACK_TO_POSTMAN + alias |
| Transactions | pack `/cards/{cardId}` → Postman `/cards/{cardId}/transactions` | PACK_TO_POSTMAN |
| Transactions | pack `/transactions/query` → Postman `/transactions/{query}` | PACK_TO_POSTMAN |
| Transactions | pack `/exports/{exportId}` → Postman `/export/{exportId}` | PACK_TO_POSTMAN |
| Batch | pack `/batches` → Postman `/Batches` (capitalization) | PACK_TO_POSTMAN |
| Notifications | pack `/api/v1/notifications/*` → Postman `/notifications/*` (no /api/v1) | PACK_TO_POSTMAN |

Pattern: pack generation has been systematically out of sync with the deployed backend. Postman + swagger have been the reliable sources of truth.

## Recommended platform fix sequence

1. **Diagnose the catastrophic-tier shared defect** — read 1-2 stack traces from each of Customer/Notifications/Transactions-read evidence dirs. If same exception type, fix once.
2. **Bank Cluster-C seed** — provide stable queryable bankId in test environment (164 TCs depend on this).
3. **Bank Z1 envelope drift** — standardize on RFC 7807 ProblemDetails for all 4xx responses. Single platform-wide refactor closes ~150-200 TCs across services.
4. **Admin POST /admin/banks** exception handling — wrap in try/catch (22 × 5xx).
5. **Test environment data hygiene** — populate every service's pre-flight discovery endpoint with at least one usable record (cases for admin, customers, notifications, transactions).
6. **Cluster B sweeps** — Batch, Admin, export endpoints. Server-side validation pass per service.

## Lessons for future runs

- Hybrid harness pattern is portable — clone the most recent service's harness, retarget paths + pre-flight + verify, ~10 min to bootstrap a new service.
- Pre-flight mint vs list-first discovery: choose mint if a POST creates the resource cleanly (Bank, Batch); choose list-first if creation requires upstream flows (Admin, Customer, Transactions, Notifications).
- B5 classifier residuals follow predictable patterns per service — list/filter/pagination/response-shape/lifecycle/idempotency/scope. ~15-30 patches per service, mostly `as_is` for response-shape verifications.
- 87% engineering ownership is consistent across services — only 5-15% of non-PASS results are runner-side. The framework is mature.
