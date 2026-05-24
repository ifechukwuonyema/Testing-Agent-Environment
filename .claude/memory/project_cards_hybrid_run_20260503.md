---
name: Kardit Cards Hybrid Run 2026-05-03
description: Cards run after swagger update + 10 harness optimizations; 830 TCs (337P/331F/162B); state-effect probe wired; backend ask document filed for verification endpoints
type: project
service: Cards
run_date: 2026-05-03
tcs: 830
passes: 337
fails: 331
blocked: 162
pass_rate: 41
worst_cluster: Z2 schema drift on 4 GETs (121 FAILs)
originSessionId: a00fb0b4-c57c-4815-892a-3966d012e235
---
Cards hybrid run, 2026-05-03 19:09 — first run after swagger.json refresh and the 10-item runner-optimization batch. Counts effectively flat vs 2026-05-01 chain Cards run (modulo run-to-run variance), which itself is the finding: the Z2 schema drift is real backend drift, not stale-spec noise.

## Source artifacts (live at time of run)

- Harness: `~\Kardit\harnesses\postman_hybrid_cards_runner.py` (now imports from `probe.py`; 10 optimizations applied)
- Shared probe module: `~\Kardit\harnesses\probe.py` (NEW — `probe_get_after_post` + `state_effect_probe`)
- Postman: `Downloads\Kardit.Api.postman.collection.json`
- Swagger (refreshed 2026-05-03): `Downloads\swagger.txt` → copied to all 8 service test agent locations; old versions backed up as `swagger.json.bak_20260503`
- Pack: `Downloads\kardit_cards_api_test_agent_v3_1\...\test_pack.json` (21 endpoints, 830 TCs)
- Final YAML: `Downloads\cards_postman_hybrid_report_20260503-190916.yaml`
- Evidence (compressed): `Downloads\evidence_postman_cards_hybrid_20260503-190916.tar.gz`

Base URL: `http://167.172.49.177:8080`. Auth: none. Run mode: `postman_hybrid_cards`.

## Counts: 830 TCs (337 PASS / 331 FAIL / 162 BLOCKED / 0 ERROR)

Cluster-C reclassified: 46. Persistence probe: 18 fired, 18 persisted (100%). State-effect probe: 5 carve-outs ran, 0 reached probe (writes failed upstream).

## Top FAIL clusters

- **Z2 — Schema drift on 2xx (121)** — 4 `{cardId}` GETs (cards/funding-details/fulfillment-status/balance), 31 each. Real backend drift, not stale spec.
- **A — Unexpected 4xx (77)** — `/cards/query` (24), fulfillment refresh/reinitiate (12 each). Overstrict validators.
- **B — Silent accept of bad input (74)** — `/issuance` (14), bank-affiliate state endpoints (9 each).
- **H — 5xx server crashes (55)** — `/ops/limit-requests/complete` (26), `/cards/{cardId}/loads` (23).

## BLOCKED clusters

- **B1 db-verify (118)** — mostly CMS-internal handshake (~58), audit-log (~16), notifications (~13), transaction records (~10). ~9 are state-observable (carved out via T9 registry — currently inert because writes 404/400).
- **C seed-persistence (46)** — concentrated in `{cardId}`-scoped state endpoints (freeze/unfreeze/terminate, 12 each). Persistence probe on `/issuance` confirmed write_did_not_persist=0; the split happens *between* issuance and state-mutation pipelines.

## Persistence probe (POST /cards/issuance + /load-requests)

- Fired: 18 / 18 — all 2xx writes confirmed persisted
- write_did_not_persist=0, read_path_5xx=0, partial_persistence=0
- Cards issuance write path is healthy. The 16 issuance FAILs are silent-accept defects, not persistence defects.

## State-effect probe (NEW T9)

- Registry entries: 5 — `platform_state_updates_after_cms_success` for freeze/unfreeze/terminate/fulfillment.refresh/fulfillment.reinitiate
- Probes fired: 0 — carve-out TCs ran but writes returned 400 (2x) or 404 (3x Cluster-C). State verification correctly stays inert when writes don't reach 2xx.
- Will start producing PASSes once backend fixes the write/read split.

## Single highest-leverage fix

**Z2_schema_drift across the four `{cardId}` GETs (121 FAILs).** One backend DTO refactor closes ~119/121. Expected pass rate: 41% → ~55%.

## How to apply

- Re-run: `cd Downloads && py "C:\Users\Onyema Ifechukwu\Kardit\harnesses\postman_hybrid_cards_runner.py"`
- Scoped: `SCOPE_ENDPOINT="POST /api/v1/cards/issuance" py ...`
- Pre-flight short-circuit: `SKIP_ON_PREFLIGHT_FAIL=1 py ...`
- Keep evidence dir uncompressed: `KEEP_EVIDENCE_DIR=1 py ...`
- Tune probe budget: `CARDS_PROBE_MAX_WAIT_S=10 py ...`

## See also

- [[reference_kardit_harness_optimizations_20260503|Harness optimization batch 2026-05-03]]
- [[feedback_get_after_post_probe|GET-after-POST diagnostic pattern]]
- [[reference_backend_verification_endpoints_ask|Backend ask: read-only verification endpoints]]
- [[project_cards_hybrid_run_20260501|Prior Cards run 2026-05-01]] (840 TCs, 31% — chain run)
