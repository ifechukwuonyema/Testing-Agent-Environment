---
name: project_batch_run_20260518
description: Batch Hybrid Run 2026-05-18 — 12 runs, baseline 38.3% → final 56.3% (125P/70F/27B); per-TC state provisioning shipped; harness clean; all 70 FAILs are backend
metadata:
  node_type: memory
  type: project
  originSessionId: d1e37d49-4e83-461c-9c37-9235a6636bf2
---

Final run (Run 12): **125P / 70F / 27B = 56.3%** (222 TCs, 7 endpoints)
Baseline (Run 8/9): 85P / 110F / 27B = 38.3%
Net gain: **+40 PASSes** from harness fixes only.

**Why:** validate and submit each consume the batch state. A single Phase 0 minted batch was being shared across all BATCH-02 and BATCH-03 TCs. TC-02-001 burned UPLOADED→VALIDATED; TC-03-001 burned VALIDATED→PROCESSING; every subsequent TC got 409 "wrong state". See [[feedback_per_tc_state_provisioning]].

**Endpoint breakdown (Run 12):**
- BATCH-01 POST /upload: 16P/12F/2B (53.3%)
- BATCH-02 POST /validate: 26P/2F/2B (86.7%) — was 3P; +23 from per-TC minting
- BATCH-03 POST /submit: 26P/6F/2B (76.5%) — was 9P; +17 from per-TC mint+validate
- BATCH-04 GET /status: 30P/4F/0B (88.2%)
- BATCH-05 GET /rows: 7P/8F/15B (23.3%) — 15B all Cluster-C persistence split
- BATCH-06 GET /results/download: 19P/11F/2B (59.4%)
- BATCH-07 GET /results/download/{token}: 1P/27F/4B (3.1%) — 27F all 500 (D-BATCH-07-CRASH)

**All 70 remaining FAILs are backend defects:**
- 22 auth bypass (D-BATCH-AUTH-1)
- 27 token handler crash (D-BATCH-07-CRASH)
- 12 CSV/file/product validation not enforced
- 8 rows persistence split (D-BATCH-05-ROWS)
- 11 state checks not enforced on download

**Backend provisions confirmed working:**
- AFFILIATE_ID_SEED: `AFF-9F6EDBBE20DD4C6B97D0B720676506E1`
- PROCESSING_BATCH_ID: `952480b6-61d2-4299-a6ca-430dce7a316c`
- COMPLETED_BATCH_ID: `ef57c562-4a98-4c46-b8ec-13e36a1a3ebe`

**Backend asks DOCX:** `C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\batch_backend_asks_20260518.docx`
**Harness:** `C:\Users\Onyema Ifechukwu\Kardit\harnesses\postman_hybrid_batch_runner.py`
