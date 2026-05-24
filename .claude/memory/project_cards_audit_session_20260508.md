---
name: Cards Audit Session 2026-05-08
description: Swagger-driven thorough audit of cards runner; iteratively shipped 9 classifier/dispatch fixes until 0 real runner bugs remain; final 464P/159F/214B at 55.4%
type: project
service: cards
run_date: 2026-05-08
tcs: 837
passes: 464
fails: 159
blocked: 214
pass_rate: 55.4
worst_cluster: C_seed_persistence (D-CARDS-3 affiliate-bank linkage)
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
---
Report: `Downloads\cards_postman_hybrid_report_20260508-061302.yaml`
Backend asks: `Downloads\Kardit\reports\cards_backend_asks_2026-05-08.docx` (D-CARDS-1..5)

9 runner fixes shipped. 32 pack TCs pruned (contract-invalid). Runner audit: 4 dimensions clean. Response-field check wired (reveals D-CARDS-4: 20 fields missing).

What's left (all backend): 91 C_seed BLOCKED (bulk endpoints, D-CARDS-3), 123 B1 BLOCKED (CMS/audit endpoints, D-CARDS-2), 159 FAILs (auth, state-conflict, missing response fields).

Ceiling: ~92.6%.

See [[reference_cards_backend_asks_20260508]].
