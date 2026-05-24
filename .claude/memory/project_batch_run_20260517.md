---
name: project_batch_run_20260517
description: Batch Hybrid Run 2026-05-17 — 37P/97F/88B (16.7%); Cluster-C batchId not queryable; needs backend-supplied batchId
metadata: 
  node_type: memory
  type: project
  originSessionId: 25aa212c-6d82-4928-b581-3037666efbae
---

Full batch run: 222 TCs total, 37P/97F/88B (16.7%).

**Pre-flight result:** POST /upload minted `batchId=6c988e66-3a78-44b1-a7be-44312b8b0088` but GET /api/v1/Batches/{batchId} returned 404 on 3 consecutive attempts → `cluster_c_suspected=True`.

**Root cause of BLOCKED:** write/read cluster divergence — POST /upload writes to one cluster, GET reads from another. Same pattern as other services (bank, transactions).

**Blocked surface:** All state-dependent endpoints (downstream of batchId resolution) are BLOCKED. Only BATCH-01 POST /upload ran meaningfully.

**What's needed from backend:**
1. A valid queryable batchId (one that GET /Batches/{batchId} can resolve) to seed pre-flight Phase 0b
2. Updated PMC entry for `GET /Batches/results/download/{token}` (currently missing from Postman collection)

**How to apply:** Don't re-run batch until backend provides a seeded batchId or fixes cluster divergence. The pass rate (16.7%) is not meaningful until the Cluster-C issue is resolved.
