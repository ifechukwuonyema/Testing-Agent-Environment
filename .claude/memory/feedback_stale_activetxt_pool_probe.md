---
name: Stale ACTIVE.txt Specialty Pool Probe
description: ACTIVE.txt specialty pools (e.g. cardIdActiveTerminatePool) go stale between runs; probe and drop non-ACTIVE entries before execution
type: feedback
originSessionId: f1d2538a-d992-4d2c-b706-84c5fe821fa8
---
ACTIVE.txt specialty pools must be probed live before the test execution phase to drop cards that are no longer in the expected state.

**Why:** ACTIVE.txt labels like "ACTIVE:(terminate)" are written once and never updated. Across successive runs, TRM-01 (and similar state-mutating endpoints) consume those cards permanently. On the next run, the pool still lists them but they're now TERMINATED — backend returns 400 "Card is already terminated." Harness falls through to the live-enumerated pool (cardIdActivePool) only if the specialty pool is empty; stale entries block that fallback.

**How to apply:** After Phase 0f2 (ACTIVE.txt load) and before Phase 0f4 (LIM-02 mint), add Phase 0f3c (or equivalent letter):
```python
_pool_before = list(session_ids.get("cardIdActiveTerminatePool") or [])
if _pool_before:
    _kept = []
    for _cid in _pool_before:
        try:
            _r = requests.get(f"{BASE_URL}/api/v1/cards/{_cid}",
                              headers={"Accept": "application/json"}, timeout=10)
            _status = (_r.json().get("status") or "") if _r.status_code == 200 else ""
        except Exception:
            _status = ""
        if _status == "ACTIVE":
            _kept.append(_cid)
    session_ids["cardIdActiveTerminatePool"] = _kept
```

Apply the same pattern to any other ACTIVE.txt specialty pool where state is consumed and not replenished between runs (e.g. cardIdActivePhysicalPool if used for one-shot mutations). The live-enumerated pools (cardIdActivePool, cardIdFrozenPool etc.) don't need this — they're always fresh from Phase 0f1.
