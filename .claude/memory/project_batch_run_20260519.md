---
name: project_batch_run_20260519
description: Batch Hybrid Run 2026-05-19 — 153P/57F/12B (69%); harness fixes for state-gate provisioning, classifier bugs, and row limits
metadata: 
  node_type: memory
  type: project
  originSessionId: c5e9fedc-d329-4c60-8f32-02637a0c5ac0
---

Baseline: 153P/57F/12B (69%) from report `batch_postman_hybrid_report_20260519-173812.yaml`.

## Harness fixes applied this session

1. **Row limit corrections** — actual limits are 100 rows / 5MB:
   - `oversized_file_rejected`: 51 → 101 rows
   - `large_valid_file_accepted_within_limit`: 50 → 99 rows

2. **`duplicate_submit_same_request_safe` classifier** — was generating a fake `submitSameRequest` field. Now routes to `idempotency_double_send`.

3. **Verdict evaluator scenario-name hint** — when `expected_codes` is empty and response is 4xx, check scenario name: if `_rejected`, `_not_allowed`, `_blocked`, or `_capped` present → PASS.

4. **BATCH-06 per-TC state provisioning** — state-gate scenarios were all using `COMPLETED_BATCH_ID`. New routing:
   - `reject_uploaded_batch_download` → mint fresh (UPLOADED)
   - `reject_validated_batch_download` → pop from validated pool (VALIDATED)
   - `reject_processing_batch_download` → `PROCESSING_BATCH_ID`
   - `reject_failed_no_artifact_download` → `FAILED_BATCH_ID = "fcfd5758-0829-4d45-abb6-6328e90568d2"`

5. **Impossible scenarios BLOCKED in classifier:**
   - `completed_no_artifact_rejected` → COMPLETED always has artifact
   - `download_after_artifact_expiry_rejected` → IAM auth embedded in URL; URLs don't expire

## Batch API design facts confirmed

- Download token = filename from `downloadUrl` last path segment
- `COMPLETED_BATCH_ID = "ef57c562-4a98-4c46-b8ec-13e36a1a3ebe"`
- `FAILED_BATCH_ID = "fcfd5758-0829-4d45-abb6-6328e90568d2"`

## Remaining backend defects (57 FAILs)

- **D-BATCH-AUTH-1**: 40 B_silent_accept — auth middleware missing on all 7 endpoints (+18pp if fixed)
- **D-BATCH-TOKEN-1**: 10 H_5xx on BATCH-07 (+4.5pp if fixed)
- **Z_other (5)**: BATCH-03 submit returning 202 where 401/403 expected
