---
name: Kardit Runner Fix Session 2026-04-30 — Coverage Layer Added
description: All 8 runners are wired end-to-end, refactored onto kardit_runner_kit, and the chain now reports endpoint + FR coverage with chain-level preconditions. Auth coverage intentionally deferred.
type: project
originSessionId: 0411d92a-9f5c-409d-9909-039a9cddde3b
---
Session 2026-04-30 (third pass): added a coverage layer on top of the refactored runners. Endpoint coverage diffs swagger paths against test-pack endpoints (scoped per service via `service_paths`); FR coverage diffs SRS FR IDs against `tc.fr_coverage`; chain orchestrator enforces preconditions and emits a unified `kardit_chain_report.yaml`.

## Files of record

- `C:\Users\Onyema Ifechukwu\Downloads\kardit_runner_kit\` — shared library
  - `session_store.py` — SessionStore (kardit_session_ids.json)
  - `lifecycle.py` — LifecycleOrderer (sorts endpoints by `order:`)
  - `schema_validator.py` — SchemaValidator (inlines $ref, validates 2xx + 4xx response bodies)
  - `setup_reporter.py` — SetupReporter (records pre-loop setup steps to evidence/_setup_*.json)
  - `verification_hooks.py` — VerificationRegistry + maybe_lift_blocked (pluggable, empty by default)
  - `coverage.py` — diff_service + compute_fr_coverage
- `C:\Users\Onyema Ifechukwu\Downloads\run_all.py` — orchestrator. Flags: `--reset`, `--only <names>`, `--coverage-only`. Output: `kardit_chain_report.yaml` (full run) or `kardit_coverage_report.yaml` (coverage-only).
- Per-service `lifecycle_order.yaml` (4 v3.1 runners) — declares `requires`, `produces`, `service_paths`, `order`. Used by both LifecycleOrderer and run_all.py.

## Coverage observed (snapshot 2026-04-30, pre-run)

Endpoint coverage (swagger ops in service scope vs test-pack ops, exact path match):
- affiliate: 29 in scope, 23 tested, 44.83% match — 6 swagger ops untested + path-naming gaps
- customer: 3 in scope, 3 tested, 33.33% match — pack uses different path spellings than swagger
- cards: 16 in scope, 21 tested, 100% match — fully covered (extras are normalized duplicates)
- transactions: 11 in scope, 11 tested, 63.64% match — `/export` vs `/exports` and similar path mismatches

FR coverage: 153 of 691 SRS FRs tested (22.14%). 538 SRS FRs have no test case in any pack. 188 pack FR refs don't appear in SRS (likely bank/admin/notifications/batch test packs the matrix doesn't yet ingest because their test_pack paths aren't declared in CHAIN — this is a known gap).

## Architecture

Each v3.1 runner does the following in run_tc():
1. classify() returns initial verdict (status code based)
2. SchemaValidator overrides verdict to FAIL with `Schema Mismatch` if response body violates swagger (now also for 4xx error envelopes — 2xx-only guard removed)
3. maybe_lift_blocked() consults VerificationRegistry; if a hook is registered for the BLOCKED category and returns PASS/FAIL, verdict is lifted

Each v3.1 runner does the following in run():
1. Lifecycle orderer sorts endpoints by `order:` list before iteration
2. Schema validator + verification hooks fire per test case
3. SessionStore.save() persists IDs that downstream runners need

run_all.py drives the chain:
1. Optional `--reset` wipes kardit_session_ids.json
2. For each runner: load lifecycle, check `requires` against current session_ids — if missing, mark BLOCKED_UPSTREAM and skip
3. Crash halts chain; FAIL test cases do not
4. After chain (or with `--coverage-only`), emit endpoint + FR coverage
5. Final `kardit_chain_report.yaml` has: chain_metadata, session_ids_final, endpoint_coverage, fr_coverage, chain_log (with schema_mismatches count + setup_status per runner)

## What's still uncovered (intentional deferrals)

- **Auth/authorization scope.** All `config.yaml` files have `auth: type: none` because the test environment doesn't enforce auth. Token plumbing is in place via `choose_token_for_scenario()`; once the team provides KARDIT_*_TOKEN values, flip `auth.type` to `bearer`.
- **Side-effect verification implementations.** VerificationRegistry is the scaffold; no concrete hooks for audit logs, notifications, IAM provisioning, persistence are registered. Adding them is per-customer/env work — register via `VerificationRegistry.register("audit", my_hook)` in a project-local bootstrap.
- **Per-run teardown.** Swagger lacks deletes for most resources; cleanup needs tenant rotation or manual reset.
- **Idempotency-repeat scenario.** New test-pack authoring; not a runner change.
- **FR coverage for non-v3.1 packs (bank/admin/notifications/batch).** CHAIN entries for these don't yet declare test_pack paths to the FR matrix. Fix by adding `test_pack:` keys for those services in run_all.CHAIN.

## How to apply

- Run the full chain: `cd Downloads && py run_all.py --reset`
- Coverage-only (no live calls): `py run_all.py --coverage-only`
- Subset: `py run_all.py --only affiliate cards`
- Open `kardit_chain_report.yaml` for the unified picture; per-runner detail still lives in each `reports/` folder.

## KEY FACTS (verified 2026-04-30)

- Bank UUID: `22222222-2222-2222-2222-222222222222`
- Affiliate UUID: `11111111-1111-1111-1111-111111111111`
- Card ID format: `CAR-{32 hex chars}`
- Tenant ID: `TNT-AFF-10291`
- Base URL: `http://167.172.49.177:8080`
- `/api/v1/cards/{cardId}/activate` does NOT exist in cards swagger — Cards/Transactions setup no longer calls it.
