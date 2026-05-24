---
name: feedback_per_tc_state_provisioning
description: State-machine endpoints need per-TC batch minting — sharing one batch across all TCs causes fixture exhaustion; first TC burns the state, all subsequent TCs get 409 wrong-state
metadata:
  node_type: memory
  type: feedback
  originSessionId: d1e37d49-4e83-461c-9c37-9235a6636bf2
---

When an endpoint is a state-transition operation (validate, submit, activate, etc.), sharing one seeded entity across all TCs is wrong. The first happy-path TC consumes the state; every subsequent TC gets "wrong state" errors (409) regardless of what it's trying to test.

**Why:** Discovered on Batch BATCH-02/03 — 3 PASSes → 43 PASSes (+40) after per-TC minting was added. Was previously misdiagnosed as "batch auto-advances to PROCESSING before validate fires". Actual cause was fixture exhaustion: TC-02-001 burned UPLOADED→VALIDATED, TC-03-001 burned VALIDATED→PROCESSING.

**How to apply:**
- For any endpoint whose call changes entity state (validate, submit, approve, activate, close, etc.): mint a fresh entity per TC before executing.
- Gate on `plan["action"] not in ("unknown_id", "set_path_var")` — those scenarios are mutating the ID themselves, no pre-mint needed.
- Route "wrong state expected" scenarios to the appropriate pre-provisioned ID (PROCESSING, COMPLETED, etc.) rather than minting fresh — otherwise they get the right state and the expected rejection never fires.
- If the mutated CSV/data causes the upload to fail (backend validates at upload), fall back to clean data for the mint so the batch reaches UPLOADED state; the TC will still fail (wrong result from validate) but the error is now honest signal, not a state machine artifact.

**Implementation pattern (Batch harness):**
```python
# Scenario routing sets:
_ENDPOINT_USE_PROCESSING_ID = {"validate_non_uploaded_batch_rejected", ...}
_ENDPOINT_USE_UPLOADED_ONLY  = {"reject_uploaded_batch", ...}   # mint but don't advance
_ENDPOINT_USE_COMPLETED_ID   = {"reject_completed_batch_duplicate", ...}

# Per-TC block before mutation:
_pre_tc_entity_id = session_ids.get("entityId")
if api_id == "API-VALIDATE" and plan["action"] not in ("unknown_id", "set_path_var"):
    if scenario in _ENDPOINT_USE_PROCESSING_ID:
        session_ids["entityId"] = PROCESSING_ID
        _tc_provisioned = True
    else:
        fresh = _mint_entity(...)
        if not fresh and csv_mutation:
            fresh = _mint_entity(clean_data)  # fallback
        if fresh:
            session_ids["entityId"] = fresh
            _tc_provisioned = True

# Restore after TC:
if _tc_provisioned:
    session_ids["entityId"] = _pre_tc_entity_id
```

Related: [[feedback_state_cascade_endpoints]]
