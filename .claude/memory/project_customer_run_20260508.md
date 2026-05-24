---
name: Customer Hybrid Run 2026-05-08
description: Customer session across 4 iterative runs + per-TC mutation audit. Pack 120→107 TCs (deleted 13 swagger-misaligned + renamed 4). Per-TC audit confirmed 0 silent-pass risks. Final 75.7%.
type: project
service: customer
run_date: 2026-05-08
tcs: 107
passes: 81
fails: 23
blocked: 3
pass_rate: 75.7
worst_cluster: B_silent_accept
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
Report (run 4): `Downloads\customer_postman_hybrid_report_20260508-043201.yaml`
Backend asks: `Downloads\Kardit\reports\customer_backend_asks_2026-05-08.docx`

Pack: deleted 11 TCs targeting swagger-absent fields, deleted 2 mutation-no-op TCs, renamed 4 to match actual swagger field names.

Defects: D-CUS-AFF-1 (affiliate pre-flight 400, 9 FAILs), D-CUS-AUTH-1 (auth leak, 8 FAILs), D-CUS-SEARCH-1 (search silent-accept, up to 14 FAILs).

See [[reference_customer_backend_asks_20260508]].
