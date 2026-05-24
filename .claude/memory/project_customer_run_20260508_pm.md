---
name: Customer Hybrid Run 2026-05-08 PM
description: 120 TCs (75P/42F/3B, 62.5%); Customer pack restored from 107 → 120 after scenario revert; FAIL increase comes from re-introduced silent-accept scenarios
type: project
service: Customer
run_date: 2026-05-08
tcs: 120
passes: 75
fails: 42
blocked: 3
pass_rate: 62.5
worst_cluster: pending /breakdown
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
Report: `Downloads\customer_postman_hybrid_report_20260508-170500.yaml`

Pack restored from 107 → 120 (+13 from union-merge). 13.2pt drop vs morning's 75.7% (107-TC pack) — traced to restored scenarios that previously triggered silent-accept FAILs.
