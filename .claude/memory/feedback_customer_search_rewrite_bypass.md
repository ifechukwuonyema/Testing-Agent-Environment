---
name: feedback_customer_search_rewrite_bypass
description: "Customer runner has rewrite_customer_search_criteria() that forces search body to {} — must bypass it for cross-field validation scenarios"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: dcda5f54-9fac-460c-a328-13eff2763c0a
---

`rewrite_customer_search_criteria()` in `postman_hybrid_customer_runner.py` always returns `{}` for `POST /api/v1/customers/search` before any mutation fires. Written 2026-05-10 when the backend rejected all non-empty search bodies.

As of 2026-05-21, the backend accepts structured criteria bodies (idType/idNumber added to swagger). Cross-field validation TCs now bypass the rewrite:

```python
_idtype_idnumber_cross_field = scenario in (
    "missing_id_number_when_id_type_supplied_rejected",
    "missing_id_type_when_id_number_supplied_rejected",
)
if pack_ep == "POST /api/v1/customers/search" and allow_seed_substitution and not _idtype_idnumber_cross_field:
    body = rewrite_customer_search_criteria(body, session_ids)
```

**Why:** If rewrite isn't bypassed, drop_field fires on `{}`, finds nothing, body stays `{}`, backend returns 200 → FAIL for wrong reason.

**How to apply:** Any future search validation TC that needs non-empty criteria must similarly bypass the rewrite. Check if backend still rejects structured bodies before removing the rewrite wholesale.

[[feedback_force_v1_plan_scenarios]]
