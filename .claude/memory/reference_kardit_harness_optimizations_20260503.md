---
name: Kardit Harness Optimization Batch 2026-05-03
description: 10 of 11 runner optimizations landed in Cards harness (T7-T17); shared probe module created; T11 parallelization deferred; foundation for porting probe pattern to remaining 6 services
type: reference
originSessionId: a00fb0b4-c57c-4815-892a-3966d012e235
---
On 2026-05-03 a 10-item optimization batch landed across the Kardit hybrid harnesses, anchored by lifting the GET-after-POST probe into a shared module. T7→T17 inclusive; T11 deferred.

## Shared module

**File:** `C:\Users\Onyema Ifechukwu\Kardit\harnesses\probe.py`

**Exports:**
- `probe_get_after_post(resource_id, base_url, execute, primary_path_template, secondary_path_template=None, token_replacements=None, max_retries=2, delay_s=1.0, max_wait_s=None)` — GET-after-POST persistence probe. Returns dict with `kind` ∈ {persisted, not_persisted, read_path_5xx, partial_persistence, transport_error, skipped}.
- `state_effect_probe(resource_id, base_url, execute, verify_path_template, expected_field_path, expected_value, ...)` — verifies state changes via existing GET endpoints. Supports literal values OR predicates. Returns dict with `kind` ∈ {state_confirmed, state_mismatch, state_field_missing, state_get_failed, skipped}.

**Token substitution order (caller-supplied wins):** `token_replacements` dict applies first; standard tokens (`{cardId}`, `{bankId}`, `{affiliateId}`, `{batchId}`, `{customerId}`, `{transactionId}`, `{notificationId}`, `{loadRequestId}`, `{limitRequestId}`) replace any remaining placeholders with `resource_id`.

**Max wait:** `PROBE_MAX_WAIT_S` env var (or per-service override like `CARDS_PROBE_MAX_WAIT_S` / `BANK_PROBE_MAX_WAIT_S`). Default 6s.

**Guardrail:** probe NEVER upgrades a verdict to PASS *except* in the state-effect carve-out path where the verdict was BLOCKED for db-verify reasons — there, `state_confirmed` legitimately upgrades to PASS because the side effect was directly verified.

## Optimization manifest

| ID | Item | Status | Where applied |
|---|---|---|---|
| T7 | Lift probe into shared module | Done | `probe.py` + Bank/Cards harnesses import from it |
| T8 | Port persistence probe to mint endpoints | Done | Cards: `/issuance` + `/load-requests`; state-mutation endpoints intentionally use T9 instead |
| T9 | State-effect probe + registry + carve-out | Done | Cards: 5 registry entries for `platform_state_updates_after_cms_success` on freeze/unfreeze/terminate/fulfillment.refresh/fulfillment.reinitiate |
| T10 | Pre-flight short-circuit (`SKIP_ON_PREFLIGHT_FAIL=1`) | Done | Cards |
| T11 | ThreadPoolExecutor TC parallelization | **Deferred** | Refactor scope ~250 lines of per-TC closure; needs dedicated session, not safe in batch |
| T12 | Postman parse cache (pickle, mtime-keyed) | Done | Cards `postman_index()` |
| T13 | B5 classifier residual scenario patterns | Done | 8 new keywords added to db-verify block |
| T14 | Auto-suggest `PATH_TEMPLATE_OVERRIDE` (informational only) | Done | Cards startup, prints suggestions for unmatched pack endpoints |
| T15 | Compress evidence dir to `.tar.gz` post-run | Done | Cards (opt out via `KEEP_EVIDENCE_DIR=1`) |
| T16 | `SCOPE_ENDPOINT` typo suggestion via difflib | Done | Cards |
| T17 | Doc note: probe supersedes `read_after_write_chain` for covered endpoints | Done | Comment in classify_scenario |

## Bank harness state

Bank harness (`postman_hybrid_bank_runner.py`) was refactored to import from `probe.py` during T7. Per-TC probe scope unchanged (still only `POST /api/v1/admin/banks`). T8-T17 changes are in Cards only — same patterns will be ported when the other 6 services are upgraded (Affiliate, Customer, Transactions, Batch, Notifications, Admin).

## Porting playbook (for remaining 6 services)

1. Add `sys.path.insert(0, str(Path(__file__).parent))` + `from probe import probe_get_after_post, state_effect_probe`
2. Define thin per-service wrappers (so default path templates can be service-specific)
3. Identify mint endpoints → wire persistence probe
4. Identify state-mutation endpoints with observable effects → build STATE_VERIFY_REGISTRY
5. Add the same per-TC reclassification logic (mirror Cards lines ~1250-1370)
6. Add `state_effect_probe_summary` and `persistence_probe_summary` to YAML metadata
7. Add T10/T12/T15/T16 boilerplate (small, mostly env-var gated)

## Why T11 was deferred

Per-TC loop body is ~250 lines with closures over local state (`path_vars`, `body`, `override_headers`), mutation actions that fork the request flow, and accumulator dicts (`counts`, `ep_counts`, `detailed`, `endpoint_summaries`). Some actions (`concurrent_parallel_send`, `idempotency_double_send`) must stay sequential within their TC. Order preservation in YAML output requires indexed result aggregation. Estimated 2-3h focused work + a clean baseline-vs-parallel comparison run to validate result parity. Not safe to ship at the bottom of a 10-item batch without dedicated test cycle.

## See also

- [[project_cards_hybrid_run_20260503|Cards run 2026-05-03]]
- [[feedback_get_after_post_probe|GET-after-POST diagnostic pattern]]
- [[reference_backend_verification_endpoints_ask|Backend ask document]]
- [[reference_kardit_harness_relocation_20260503|Earlier relocation 2026-05-03]]
