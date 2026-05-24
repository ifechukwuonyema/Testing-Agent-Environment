---
name: Transactions Hybrid Run 2026-05-06
description: Transactions run 18.2% → 46.8% after fixing 6 endpoints that had the literal-URL trap (Postman path used hardcoded IDs like CARD-2026-00003 without :variable). Required PACK_TO_POSTMAN remap + PATH_TEMPLATE_OVERRIDE + path-var seed.
type: project
service: transactions
run_date: 2026-05-06
tcs: 440
passes: 206
fails: 223
blocked: 11
pass_rate: 46.8
worst_cluster: H_5xx_server_error
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
Report: `Downloads\transactions_postman_hybrid_report_20260506-073034.yaml`

Root cause: 6 endpoints had hardcoded literal URLs in Postman. PACK_TO_POSTMAN lookup missed because index had literal path not template. Fix: remap + PATH_TEMPLATE_OVERRIDE + KNOWN_GOOD_FALLBACK. See [[feedback_path_var_seed_after_override]].

Remaining catastrophic: 156 FAILs all trace to "The given key was not present in the dictionary" backend exception on 4 read endpoints (/cards/{cardId}, /cards/{cardId}/loads, /cards/{cardId}/unloads, /customers/{customerId}).
