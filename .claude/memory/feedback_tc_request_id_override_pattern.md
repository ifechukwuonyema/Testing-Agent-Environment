---
name: feedback_tc_request_id_override_pattern
description: TC_REQUEST_ID_OVERRIDE pattern — pin specific IDs 1:1 to named TCs when pool IDs are stale or state-guard TCs need specific entity states
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5f2f7813-c7e7-4f05-a43e-70943f5bfa14
---

When pool-drawn IDs return 409/404 on happy-path TCs, or state-guard TCs need entities in a specific state, use `TC_REQUEST_ID_OVERRIDE` to pin fresh IDs directly to named TCs — bypassing pool rotation entirely.

**Why:** Pool IDs get consumed across runs and may not be reset. Relying on pool rotation for TCs with strict ID-state requirements produces unstable results. Per-TC pinning makes state deterministic and replay-safe.

**How to apply:**
- String value → PART endpoints (requestId injected into path_vars)
- Tuple value `(bankId, affiliateId)` → CTRL endpoints (both injected into path_vars)
- Override only fires when `allow_seed_substitution=True` — mutation TCs (set_path_var, unknown_id) are never overridden
- The early `session_ids["requestId"] = override` line is WRONG for tuple values — the downstream `isinstance(_pool_item, tuple/str)` block handles injection correctly; never re-add the early assignment
- Each TC must have its own unique ID — never share one ID across two TCs that write to the same endpoint (409 on TC#2)
- After getting fresh IDs from backend, confirm they're actually in the expected state before running; a 409 on a "pending" ID means it was never reset
- Use per-batch replay YAMLs (`_replay_N_fails.yaml`) to scope runs to only the TCs with overrides; don't run the full pack just to verify a handful of pinned IDs
