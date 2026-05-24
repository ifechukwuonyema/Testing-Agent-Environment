---
name: feedback_validated_pool_single_use
description: Validated batch pool IDs are single-use — submitting transitions them to PROCESSING; pool resets on Python restart causing stale-ID 409 cascade
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c5e9fedc-d329-4c60-8f32-02637a0c5ac0
---

**Rule:** Never reuse validated batch pool IDs across runs. Empty the pool or supply fresh IDs from the user before each run session.

**Why:** Submitting a VALIDATED batch transitions it to PROCESSING. The pool list is hardcoded in the runner source. On every Python restart the list resets to the original 40 IDs. If those IDs were already submitted in a prior run, every subsequent BATCH-03 happy-path TC gets 409 "Batch must be in VALIDATED status to submit. Current status: PROCESSING" — cascading from 26P to 9P in a single run.

Discovered 2026-05-21: run 1 consumed ~31 pool IDs (submitted → PROCESSING). Run 2 restarted Python → pool reset to same 40 stale IDs → BATCH-03 went from 27P/5F to 9P/23F. Wasted a full run.

**How to apply:**
- Before each batch runner session, user provides 40 fresh VALIDATED IDs (batch provisioned but not yet submitted).
- Update `_VALIDATED_BATCH_POOL` in the runner with new IDs.
- Pool comment in source now documents single-use nature.
- Fallback to live mint+validate fires only when pool is empty (not when full of stale IDs) — so an empty pool is safer than a stale-filled one.
- ~35 IDs consumed per run (BATCH-03 has ~27 happy-path TCs that draw from pool + BATCH-06 draws 1 + Phase 0d draws 1).

See [[project_batch_run_20260521]] for the regression incident.
