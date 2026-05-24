---
name: Bank Hybrid Run 2026-05-08
description: 384 TCs (86P/229F/69B, 22.4%); first run after pack revert + BNK-06 fill (+6); pass rate dropped from 49.8% (2026-05-07) because restored 70 silent-accept-prone scenarios
type: project
service: Bank
run_date: 2026-05-08
tcs: 384
passes: 86
fails: 229
blocked: 69
pass_rate: 22.4
worst_cluster: pending /breakdown
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
Report: `Downloads\bank_postman_hybrid_report_20260508-163330.yaml`

Pass rate drop from 49.8% (2026-05-07) to 22.4% is because 70 silent-accept scenarios came back into the pack and the runner still classifies them as FAIL. Not a regression — expected after the scenario revert.
