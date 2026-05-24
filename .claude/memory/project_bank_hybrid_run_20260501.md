---
name: Kardit Bank Hybrid Postman-Driven Run 2026-05-01
description: Bank hybrid harness with pre-flight verify-loop and Cluster-C reclassification; 472 TCs (66P/138F/268B); seed not queryable confirmed; dashboard v2 reconciled
type: project
service: Bank
run_date: 2026-05-01
tcs: 472
passes: 66
fails: 138
blocked: 268
pass_rate: 14
worst_cluster: Z1 envelope + Cluster-C seed
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
Bank hybrid run, 2026-05-01 17:41 — replaces all earlier Bank standalone/hybrid runs as the canonical Bank record.

## Source artifacts (live at time of run)

- Harness: `Downloads\postman_hybrid_bank_runner.py` (canonical Bank hybrid; has pre-flight POST, verify-loop, Cluster-C reclassification, family equivalence, full-context per-TC entries)
- Standalone variant (kept for reference): `Downloads\postman_standalone_bank_v2.py`
- Findings DOCX generator: `Downloads\generate_bank_findings_docx.py`
- Postman: `Downloads\Kardit.Api.postman.collection.json`
- Pack: `Downloads\bank_microservice_functional_test_pack_v1_40_each.json` (472 TCs after path remaps + 8 residual TC removals)
- Final YAML: `Downloads\bank_postman_hybrid_report_20260501-174156.yaml`
- Findings DOCX: `Downloads\bank_findings_with_fixes_2026-05-01.docx`
- Evidence: `Downloads\evidence_postman_bank_hybrid_20260501-174156\`

Base URL: `http://167.172.49.177:8080`. Auth: none. Run mode: `postman_hybrid_bank`.

## Counts: 472 TCs (66 PASS / 138 FAIL / 268 BLOCKED / 0 ERROR)

Cluster-C reclassified: 160 (FAILs reclassified as BLOCKED with `cluster: C, defect_class: seed_not_queryable`).

## Pre-flight outcome

- POST `/api/v1/admin/banks` to mint a fresh bankId: **FAIL** (non-2xx)
- Fallback to SessionStore-seeded `22222222-2222-2222-2222-222222222222`
- Verify GET `/api/v1/banks/{bankId}/affiliates`: **404 after 3 attempts**, `cluster_c_suspected=True`
- Conclusion: seeded bankId is unusable across the platform. Either provide a stable persistently-queryable bankId in the test environment, or fix POST `/admin/banks` persistence so hybrid pre-flight can mint one per run.

## Pack reconciliation (path remaps applied 2026-05-01)

- `GET /api/v2/banks/{bankId}/dashboard` — confirmed v2 in both pack AND Postman; was misconfigured to map to non-existent v1 entry, fixed during this session.
- `BNK-PART-01/02/03` paths remapped (was: `/partnership-requests` listing; now: `/affiliate-partnership-requests/{requestId}` GET + `/partnerships/{requestId}/{approve,reject}` POSTs without bank-scope prefix).
- B3 removal: 6 URL-shape-impossible TCs dropped (missing path-var TCs); 2 residual TCs (`unknown_bank_not_found` + `malformed_bank_id_rejected` on `/banks/query` filter-body endpoint) dropped.

## Top FAIL clusters

- **Z1 — Right code, wrong error envelope: 105** — backend returns 400/404/etc. (family-equivalent) but body shape doesn't match swagger. Different endpoints emit different shapes. Single ProblemDetails refactor closes most.
- **H — 5xx server errors: 19** — `/banks/query`, partnership approve/reject, `/admin/banks` write surface. Wrap in exception handlers.
- **Z2 — Response-shape no parseable expected: 5** — depends on Cluster-C resolution.
- **C — Residual seeded-resource 404: 4** — edge cases the auto-reclassification rule didn't catch (paths without `{bankId}`/`{affiliateId}` tokens or different ID forms).

## BLOCKED clusters

- **Cluster-C reclassified: 160** — single backend root cause (seed_not_queryable). After fix, expect ~80-100 to flip to PASS.
- **B6 Postman gap: 40** — `POST /api/v1/banks/{bankId}/cards/query` has no Postman entry (dashboard reconciled this run).
- **B5 Classifier residual: ~38** — Bank-specific scenario names (`relationship_status_updated`, `actor_metadata_recorded`, etc.). Most are DB-verifications anyway.
- **B1 DB-verify: 21** — audit log / notification / status_history side-effect verifications.
- **B7 Array-injection inapplicable: 5** — needs synthetic-array port from Affiliate v2.
- **B9 Other: ~4** — single-TC edge cases.

## Per-endpoint (P / F / B)

| Endpoint | P | F | B |
|---|---:|---:|---:|
| POST `/api/v1/admin/banks` | 7 | 19 | 14 |
| GET `/api/v2/banks/{bankId}/dashboard` | 9 | 2 | 29 |
| GET `/api/v1/banks/{bankId}/affiliates` | 11 | 1 | 28 |
| POST `/api/v1/banks/{bankId}/cards/query` | 0 | 0 | 40 (B6) |
| POST `/api/v1/banks/{bankId}/audit-logs` | 10 | 2 | 28 |
| POST `/api/v1/banks/{bankId}/reports` | 10 | 2 | 28 |
| POST `/api/v1/banks/query` | 0 | 36 | 2 |
| POST `/api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend` | 5 | 9 | 24 |
| POST `/api/v1/banks/{bankId}/affiliates/{affiliateId}/block` | 3 | 12 | 23 |
| GET `/api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}` | 1 | 11 | 28 |
| POST `/api/v1/partnerships/{requestId}/approve` | 5 | 22 | 12 |
| POST `/api/v1/partnerships/{requestId}/reject` | 5 | 22 | 12 |

`POST /banks/query` is the worst-performing endpoint (0 PASS / 36 FAIL): every input is rejected with 400 or crashes with 500. Likely unimplemented filter validation or a state-machine guard.

## Engineering ownership

406/472 (86%) backend-owned: 138 FAIL + 268 BLOCKED, of which only ~47 (B5+B7+B9) are runner-side residual.

## How to apply

- Re-run: `cd Downloads && py postman_hybrid_bank_runner.py`
- DOCX render: `py generate_bank_findings_docx.py [yaml_path]`
- Single endpoint: `SCOPE_ENDPOINT="POST /api/v1/banks/query" py postman_hybrid_bank_runner.py`

## Recommended fix order (engineering)

1. **Cluster-C seed (highest leverage)** — 160 reclassified + 4 residual = 164 TCs depend on this. Provide stable queryable bankId or fix `/admin/banks` persistence.
2. **H — 5xx server errors (19 FAILs)** — wrap write endpoints in proper exception handling.
3. **Z1 — Error envelope drift (105 FAILs)** — standardize on RFC 7807 ProblemDetails for all 4xx.
4. **POST `/banks/query` zero-PASS** — investigate as a single endpoint defect; either filter validation is broken or the endpoint is rejecting all inputs by design.
5. **B1 — DB-side verifications (21 BLOCKED)** — provide read-only verification endpoints or DB access.
