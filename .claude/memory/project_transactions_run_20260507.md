---
name: Transactions Hybrid Run 2026-05-07 (7 iterations)
description: Day-over-day +30.5pts (46.8%→77.3%); one backend P0 fix + four harness improvements + two pack curations; defect taxonomy 100% silent-accept dominant
type: project
service: Transactions
run_date: 2026-05-07
tcs: 405
passes: 313
fails: 81
blocked: 11
pass_rate: 77.3
worst_cluster: B_silent_accept (auth pipeline missing)
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
---
Report (run #7): `Downloads\transactions_postman_hybrid_report_20260507-174553.yaml`

Key wins: Backend P0 dict-KeyError fix landed (+9.3pts). Drop fromDate/toDate from base query for 4 read endpoints (+15.9pts). Phase 0c volume-seed discovery. 2 rounds of pack curation.

Real implementations confirmed: /query, /{transactionId}, /cards/{cardId}/[transactions|loads|unloads], /customers/{customerId}, /volume/*.
Stubbed end-to-end: /export, /exports/{exportId}, /exports/{exportId}/download.

81 remaining FAILs: 44 auth-related (54.3%), 10 pagination range, 12 export validation, 12 export download lifecycle, 3 other.

Ceiling: ~95% with auth+scope+validation middleware.
