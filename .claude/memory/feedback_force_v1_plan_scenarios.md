---
name: feedback_force_v1_plan_scenarios
description: FORCE_V1_PLAN_SCENARIOS constant — bypass v2 engine for specific scenarios it misclassifies; use v1 classify_scenario instead
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 25aa212c-6d82-4928-b581-3037666efbae
---

Add scenarios to `FORCE_V1_PLAN_SCENARIOS` (a set constant after `ENGINE_RUNNER_PRESERVED`) when the v2 engine returns the wrong plan for a specific scenario name.

**Why:** v2 engine infers mutation type from scenario text with a generic classifier. For nuanced scenarios like `underage_customer_rejected_where_policy_requires`, v2 returned `observational_response_shape` (sent body unchanged) instead of mutating dob to a child date. FORCE_V1_PLAN_SCENARIOS bypasses v2 for these scenarios and falls through to the v1 `classify_scenario` handler which has explicit logic.

**How to apply:** 
1. If a scenario is failing with no mutation applied (check `mutation_applied` or logs showing body sent as-is)
2. And the v1 `classify_scenario` handler has correct logic for it
3. Add the scenario name to FORCE_V1_PLAN_SCENARIOS
4. Verify the v1 handler uses `set_field` (deep search) not `set_nested` (requires exact path) — wrong path is a silent no-op

Check the condition gate: `if (MUTATION_ENGINE_VERSION == "v2" and plan["action"] not in ENGINE_RUNNER_PRESERVED and scenario not in FORCE_V1_PLAN_SCENARIOS):`

**Second confirmed use case (2026-05-21):** `missing_id_number_when_id_type_supplied_rejected` and `missing_id_type_when_id_number_supplied_rejected` — v2 engine's generic `missing_(.+?)` regex extracted `id_number_when_id_type_supplied` (the full clause) as the field name, tried to drop `idNumberWhenIdTypeSupplied` (doesn't exist → trivially satisfied → body unchanged → 200). Fix: add both to FORCE_V1_PLAN_SCENARIOS + add explicit `drop_field: idNumber` / `drop_field: idType` handlers in `classify_scenario()` BEFORE the generic regex.

[[feedback_customer_search_rewrite_bypass]]
