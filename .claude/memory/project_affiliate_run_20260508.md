---
name: Affiliate Postman-Standalone Run 2026-05-08
description: 511 TCs (277P/137F/97B, 54.2%); pack went 434 → 631 → 511 (revert + mega-dedup); pass rate dropped 4pts vs 2026-05-07 baseline (58.4%)
type: project
service: Affiliate
run_date: 2026-05-08
tcs: 511
passes: 277
fails: 137
blocked: 97
pass_rate: 54.2
worst_cluster: pending /breakdown
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
Report: `Downloads\affiliate_postman_standalone_v2_report_20260508-163957.yaml`

First run on post-dedup affiliate pack. 3 mega-endpoints (AFF-07/10/11) collapsed from 80/76/75 → 40/36/35 by dropping template-prefix duplicates. Pass rate held within ~4pts of 2026-05-07 baseline.
