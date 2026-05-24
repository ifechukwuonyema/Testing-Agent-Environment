---
name: feedback_admin_case_pool_one_time_use
description: Admin submitted case pool is one-time-use — need fresh IDs from backend before each run
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b4a81de3-50bf-410c-81aa-9f965e5971b8
---

BACKEND_SUBMITTED_POOL cases in the admin runner are consumed permanently by decision TCs. Each decision call (Approve/Reject/Clarify) puts the case in a terminal state. Run 2 hit "Cannot change decision: case is already APPROVED/REJECTED" on every happy-path TC because run 1 had already consumed all 20 cases.

**Current pool status (as of 2026-05-13):** The 20-case pool refreshed 2026-05-12 (BBB43F…, 45A09B…, etc.) is fully exhausted — consumed across the 2026-05-12 full run and the 2026-05-13 replay. A fresh batch is required before the next run.

**Why:** The decision endpoint is a state-mutating write with no rollback. Cases cannot be reused across runs.

**How to apply:** Before any admin run, confirm a fresh batch of SUBMITTED case IDs is available from the backend (via query.txt or equivalent). Update BACKEND_SUBMITTED_POOL in `postman_hybrid_admin_runner.py` lines 104–126. 20 cases gives ~1 full run (10 happy-path decision TCs consume 10 cases; the other 10 are for validation/error scenarios that reuse the same case). File is at `Kardit\harnesses\postman_hybrid_admin_runner.py`.

[[project_admin_run_20260513]]
