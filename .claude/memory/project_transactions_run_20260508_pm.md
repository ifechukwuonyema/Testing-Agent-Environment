---
name: Transactions Hybrid Run 2026-05-08 PM
description: 438 TCs (266P/161F/11B, 60.7%); pass rate dropped from morning's 79.0% (391 TCs) with 47 restored silent-accept TCs
type: project
service: Transactions
run_date: 2026-05-08
tcs: 438
passes: 266
fails: 161
blocked: 11
pass_rate: 60.7
worst_cluster: pending /breakdown
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
Report: `Downloads\transactions_postman_hybrid_report_20260508-170504.yaml`

Pack restored 391 → 438 (+47 from union-merge). 18.3pt drop from morning's 79.0% — the 47 restored scenarios were the ones the runner classified as B_silent_accept against the contract-poor swagger.
