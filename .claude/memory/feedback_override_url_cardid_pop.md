---
name: Override URL CardId Pop — Never Let Override URLs Replace Live Pool CardIds
description: dispatcher must pop cardId from override_path_vars so stale override URL cardIds never replace the live pool-selected card
type: feedback
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
`failed_payload_overrides.json` TC-level overrides embed specific cardIds in their URLs (e.g. `{{baseUrl}}/api/v1/cards/CAR-7EAAE15.../freeze`). These cardIds go stale between runs as cards get TERMINATED.

**Fix:** In the dispatcher, after extracting path vars from the override URL, always call `override_path_vars.pop("cardId", None)` before merging into `path_vars`. The pool-selected cardId (from live Phase 0f1 enumeration) is authoritative.

```python
override_path_vars = extract_path_vars_from_override_url(override["url"], path_template)
if override_path_vars:
    override_path_vars.pop("cardId", None)   # override URL cardIds go stale across runs
    path_vars = {**path_vars, **override_path_vars}
```

**Why:** FRZ-01 happy-path TCs were returning 400 "Only ACTIVE cards can be frozen. Current status is TERMINATED" because override URL pinned `CAR-7EAAE15DD68348A3A60B07D46EFCD7CB` (now TERMINATED) over the pool-selected ACTIVE card.

**How to apply:** This applies to any endpoint where the override URL contains a resource ID that the runner also selects from a live pool. Always pop those IDs from override path_vars. If the override URL also contains other path vars (e.g. `limitRequestId`), those are fine to keep.
