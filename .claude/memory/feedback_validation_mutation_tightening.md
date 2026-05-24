---
name: Validation TC Mutation Must Actually Mutate
description: Many silent-accept FAILs in cards/transactions/etc. are runner-side — classifier didn't drop/mutate the field the scenario name implies. Tighten mutation rules; verify before reporting backend silent-accept.
type: feedback
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
Rule — when running validation TCs, the harness MUST mutate the body in a way that genuinely triggers the validation the scenario name implies. If the scenario says `customer_first_name_missing_rejected`, `missing_request_context_rejected`, `invalid_currency_rejected`, `malformed_json_rejected`, etc. and the body sent is unchanged from the Postman base, a 200 response is a HARNESS bug, not a backend silent-accept defect.

**Why:** User flagged 2026-05-07 cards run. Many `B_silent_accept` FAILs (refresh, loads, unloads, limits, issuance, query, GETs) had bodies that still contained the field the scenario was supposed to drop or break. Backend correctly returned 200 because the input was actually valid. We were misreporting these as backend defects.

**How to apply:**
1. Audit `classify_scenario` and the per-TC mutation block (in each `postman_hybrid_<service>_runner.py`) to ensure every `*_rejected` / `missing_*` / `invalid_*` / `malformed_*` / `blank_*` / `*_max_length_*` / `*_min_length_*` / `unsupported_*` scenario name maps to a concrete `drop_field` / `set_field` / `drop_nested` / `set_nested` / `raw_invalid_json` / `wrong_content_type` / `set_query` / `unknown_id` action that targets the right field.
2. Before reporting a TC as `B_silent_accept`, verify the body sent actually had the mutation applied — log `mutation_note` to evidence and check it.
3. When ambiguous (e.g. `customer_first_name_missing_rejected` could mean dropping `customer.firstName` OR `customerData.firstName` depending on body shape), inspect the Postman base request and target the correct nested path.
4. The Postman collection the user will provide is the canonical source of valid bodies for ALL microservices — use it across cards/transactions/customer/admin/bank/batch/notifications/affiliate.
5. Until classifier coverage is verified end-to-end, do NOT generate backend-asks DOCX claiming silent-accept defects on these endpoints.
