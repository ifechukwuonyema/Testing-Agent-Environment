---
name: feedback_rotation_before_mutation
description: "rotate_*_uniqueness must fire BEFORE mutation, not after — post-mutation rotation clobbers invalid values set by set_field and v2 engine"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 25aa212c-6d82-4928-b581-3037666efbae
---

Always apply `rotate_*_uniqueness` (or any uniqueness-freshening function) BEFORE the mutation step, not after.

**Why:** `_set(d, key, val)` only writes to existing keys. If a mutation drops a field (`drop_field`), the key is gone and `_set` can't re-add it — that's safe. But if a mutation sets an invalid value (`set_field`, v2 engine), the key still exists. Post-mutation rotation will then overwrite the invalid value with a fresh valid one, turning a FAIL scenario into a silent-accept. This is what caused ~8 validation TCs (blank_first_name, invalid_email, invalid_dob_format, etc.) to get 200 instead of 400 — the invalid value was overwritten before the request was sent.

**How to apply:** In all hybrid runners, place `rotate_*_uniqueness` immediately after the Postman base body is loaded (before `classify_scenario` / mutation block). Remove any post-mutation rotation calls. The affiliate-pool retry path has its own per-retry rotation which fires last for happy-path TCs — that's fine because happy-path TCs don't have invalid mutations.

See customer runner change: `body = rotate_customer_uniqueness(body, None)` added at line ~1645, removed from `else` path at ~1949.
