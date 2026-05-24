---
name: Batch Hybrid Run 2026-05-08 PM
description: 188 TCs (116P/65F/7B, 61.7%); pack went 158 → 177 → 188 (revert + +11 fill on BATCH-03/04); BLOCKED very low (3.7%); FAILs are validation-pattern
type: project
service: Batch
run_date: 2026-05-08
tcs: 188
passes: 116
fails: 65
blocked: 7
pass_rate: 61.7
worst_cluster: pending /breakdown
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
Report: `Downloads\batch_postman_hybrid_report_20260508-170507.yaml`

BLOCKED only 3.7% — healthiest service ratio. FAILs are swagger-silent pattern (no required fields, no enums). Pack had BATCH-03/04 filled to 30+ TCs each.
