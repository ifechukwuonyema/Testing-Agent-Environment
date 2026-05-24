---
name: Swagger-Driven Runner Audit Methodology
description: Use swagger as source of truth to audit every TC's request payload, mutation, and response — exposes false-PASSes that pure pass-rate hides
type: feedback
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
---
When the user wants thorough verification that the runner is doing the right thing, run a swagger-driven audit across four dimensions:

1. **Right payload** — request body validates against swagger request schema (lite type/enum check is enough; don't enforce required for fields the harness seeds at runtime)
2. **Mutation actually applied** — for each TC, derive expected mutation from scenario name + endpoint schema and verify the body reflects it (drop_field actually drops, set_field actually sets the right key, raw_invalid_json sends a string not a dict, etc.)
3. **Response body matches swagger response schema** — for 2xx, validate against the declared response schema. Catches backend drift (e.g. `source: "CACHED"` vs swagger enum `["CMS"]`)
4. **`response_includes_X` field actually present** — walk response body and require the named field; otherwise FAIL even on rc=200

**Why:** Pass rate alone hides false-PASSes — TCs that match expected status by accident while sending the wrong payload, no mutation, or where the response is missing fields the contract implies. The audit converts those into real signal.

**How to apply:**
- Build a per-service auditor (template: `Downloads\comprehensive_cards_audit.py`, `Downloads\thorough_affiliate_scenario_audit.py`)
- Run after every classifier change to catch regressions
- Distinguish real runner bugs from auditor false positives by inspecting actual `mutation.note` and `input_data.body` for the flagged TCs — many "unrecognized" or "contract-invalid" findings are the runner's explicit handlers that the auditor's pattern matcher doesn't recognize
- Real runner bugs to fix: regex anchor errors capturing trailing "rejected", post-processors re-injecting fields after classifier mutation, set_field that fails when key doesn't exist (use set_nested instead), shape-blind precision/value mutations on object-shaped fields

**Common false-positive sources:**
- Auditor's regex doesn't match runner's explicit literal-scenario handlers
- Canonical override sends backend-curated body that auditor doesn't recognize as a valid mutation
- State-dependent scenarios where backend returns 4xx by design but auditor expects body mutation

**Pass rate trajectory after thorough audit:**
- Pass rate WILL drop 1-3 percentage points after fixing — this is informational gain, not regression
- Each percentage point that disappears was a false-PASS hiding a real backend defect or a no-op mutation
- After fixes, pass rate plateaus and only moves with backend changes
