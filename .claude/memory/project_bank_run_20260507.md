---
name: Bank Hybrid Run 2026-05-07
description: Bank session 2026-05-07/08 across 5 iterative runs + per-TC mutation audit. Pack 376→327 TCs. Runner gained CANONICAL_BANK_SEED, RC injection, POSTMAN_KEY_OVERRIDE, unlinked-affiliate discovery. Final 49.8%. Surfaced D-405-1 + D-PERSIST-1 + D-FIXTURE-1.
type: project
service: bank
run_date: 2026-05-08
tcs: 327
passes: 163
fails: 156
blocked: 8
pass_rate: 49.8
worst_cluster: A_unexpected_4xx
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
Report (run 5): `Downloads\bank_postman_hybrid_report_20260508-034147.yaml`
Backend asks: `Downloads\Kardit\reports\bank_backend_asks_2026-05-07.docx`

Key defects: D-405-1 (POST /banks/query 405 — backend implements GET only), D-PERSIST-1 (partnership-request write/read split), D-FIXTURE-1 (CTRL state-cascade — one canonical affiliate for 32 TCs), D-AUTH-1 (34 silent-accepts on read endpoints).

Per-TC audit confirmed runner mutation engine correct. All remaining FAILs are backend-side.

See [[reference_bank_backend_asks_20260507]].
