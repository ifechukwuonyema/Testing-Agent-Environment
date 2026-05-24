---
name: Cards Hybrid Run 2026-05-06
description: Cards run after pack expansion (21→25 endpoints, 830→987 TCs), 4 new endpoints wired, LDR-01 contract patches, card-pool routing extension. Surfaced D-08 (scope mismatch) and D-09 (state advancement gap).
type: project
service: cards
run_date: 2026-05-06
tcs: 987
passes: 547
fails: 226
blocked: 214
pass_rate: 55.4
worst_cluster: B_silent_accept
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
Report: `Downloads\cards_postman_hybrid_report_20260506-130006.yaml`
Pack: `Downloads\cards_microservice_functional_test_pack_v1_40_each.json` (25 endpoints, 987 TCs)
Backend asks: `Downloads\Kardit\reports\cards_backend_asks_2026-05-06.docx`

Defects surfaced: D-02 (LDR-02 500), D-07 (LDR-03 non-deterministic 500), D-08 (scope mismatch issuance vs activate), D-09 (no public PENDING_ISSUANCE→PENDING_ACTIVATION advancement), D-10 (state check before auth on PIN-01), D-11 (dual UserType enums).

See [[reference_cards_backend_asks_20260506]] for full details.
