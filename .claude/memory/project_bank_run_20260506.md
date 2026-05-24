---
name: Bank Hybrid Run 2026-05-06
description: Bank run 39.9% → 50.5% via 3 harness fixes (HB-01 BNK-05 pagination clamp, HB-02 BNK-06 currency drop + nested pagination, HB-03 partnership-request mint via /affiliates/query). Pack restructured against Bendpoint.txt + backend false-positive feedback. Surfaced D-15 (mint silently rebinds bankId) and D-16 (CRD-01 swagger response drift).
type: project
service: bank
run_date: 2026-05-06
tcs: 376
passes: 190
fails: 104
blocked: 82
pass_rate: 50.5
worst_cluster: A_unexpected_4xx
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
Report: `Downloads\bank_postman_hybrid_report_20260506-145808.yaml`
Backend asks: `Downloads\Kardit\reports\bank_backend_asks_2026-05-06.docx`

3 harness fixes: HB-01 pagination clamp, HB-02 currency+nested pagination, HB-03 partnership-request via /affiliates/query.

Defects: D-15 (mint rebinds bankId silently), D-16 (CRD-01 swagger drift), D-13 (no affiliates under test bank), D-14 (no cards under test bank).

See [[reference_bank_backend_asks_20260506]].
