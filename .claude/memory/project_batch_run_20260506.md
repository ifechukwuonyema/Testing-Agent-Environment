---
name: Batch Hybrid Run 2026-05-06
description: Batch run 57.6% → 62.7% after fixing the BATCH-05 PageSize=6231 default in Postman that violated backend's 1-100 cap. Surfaced backend stub-shaped behavior across all 6 endpoints (canned 200 responses regardless of input).
type: project
service: batch
run_date: 2026-05-06
tcs: 177
passes: 111
fails: 61
blocked: 5
pass_rate: 62.7
worst_cluster: B_silent_accept
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
Report: `Downloads\batch_postman_hybrid_report_20260506-082405.yaml`

Fix: PageSize=6231 default in Postman was exceeding backend's 1-100 cap. Added normalizer to force Page=1 and clamp PageSize to 10 when outside valid range. Unblocked BATCH-05 (+9 PASS).

Backend appears stub-shaped: BATCH-01 never decodes base64, BATCH-02/04 return identical canned values, BATCH-06 returns placeholder `https://example.com/...` URL for every input.
