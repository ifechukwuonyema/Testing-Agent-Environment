---
name: Seed path_vars after PATH_TEMPLATE_OVERRIDE
description: When a runner's PATH_TEMPLATE_OVERRIDE re-introduces a {placeholder} into a template that was built from a literal-URL Postman entry, base.path_vars is empty and substitution leaves the literal "{placeholder}" in the URL. Always extract placeholders from the new template and pre-seed base.path_vars.
type: feedback
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
When a Postman entry has a hardcoded literal URL (e.g. `/api/v1/customers/CUST-ACME-00001` with no `:variable`), `build_base_request` returns `path_vars = {}`. If the runner then applies `PATH_TEMPLATE_OVERRIDE` to introduce `{placeholder}` markers, the substitution loop has nothing to fill in and the literal text `{customerRefId}` ends up in the request URL.

**Why:** This was the root cause of the Customer 2.5% pass rate on 2026-05-06 (and earlier the Transactions 18.2% pass rate). Same harness bug pattern in two services. Backend response for the malformed URL was `"No customer found matching the search criteria"` with HTTP 500 — masquerading as a backend defect when it was actually a harness substitution failure.

**How to apply:**

In every runner that defines `PATH_TEMPLATE_OVERRIDE`, after applying the override, extract `{placeholder}` markers from the new template and pre-seed them into `base["path_vars"]`. Reference implementation:

```python
import re
if pack_ep in PATH_TEMPLATE_OVERRIDE:
    path_template = PATH_TEMPLATE_OVERRIDE[pack_ep]
    for _ph in re.findall(r"\{(\w+)\}", path_template):
        base["path_vars"].setdefault(_ph, "")
    drift_findings.append({...})
```

After this, `inject_seeded_path_vars` will iterate over the seeded keys and substitute from `session_ids` (or the runner's KNOWN_GOOD_FALLBACK constants).

**Where this is already applied:**
- `Kardit\harnesses\postman_hybrid_customer_runner.py` line 1473-1485
- `Kardit\harnesses\postman_hybrid_transactions_runner.py` (same pattern)

**Where it's NOT needed (Postman uses :variable syntax properly):**
- Cards runner — Postman entries use `:cardId` etc., so `build_base_request` populates `path_vars` correctly without override.
- Bank, Admin, Affiliate, Notifications — verified via Postman audit on 2026-05-06.

**KNOWN_GOOD_FALLBACK pattern:**
Always provide a Postman-literal fallback constant for the seeded ID type so substitution doesn't leave the URL with an empty placeholder if session has no value. Examples:
- Customer runner: `KNOWN_GOOD_CUSTOMER_REF_ID = "CUST-ACME-00001"`
- Transactions runner: `KNOWN_GOOD_FALLBACK = {"cardId": "CARD-2026-00003", "transactionId": "TXN-2026-00014", ...}`
