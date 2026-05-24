---
name: feedback_backend_response_authoritative
description: "For response_includes_ Z2 FAILs, backend response shape is ground truth — fix pack scenario names to match actual response keys; do not file backend asks for absent Z2 fields"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3f6cd432-c48e-496c-917d-c90225f796c8
---

When `response_includes_X` scenarios fail with Z2 (schema_drift on 2xx), the fix workflow is:

1. Check if the field exists in the actual response body under a different key name (e.g., `onboardingCaseId` → `onboardingSnapshot.caseId`)
2. If it does: rename the scenario to `response_includes_<actual_key>` — the runner walks the response recursively, so nested keys work
3. If it doesn't exist anywhere in the response: remove the TC from the pack entirely
4. Do NOT file a backend ask for missing response fields unless there is a confirmed contract (swagger response schema, product spec) that requires the field

**Why:** "Whatever was in the response is what is correct" — user confirmed on 2026-05-13 that backend response shape is authoritative. Filing asks for Z2 misses is noise when the pack was simply using wrong field names. This applies to any service, not just affiliate.

**How to apply:** Before classifying any Z2 cluster as backend defects, audit each failing `response_includes_X` scenario against the actual `response_body` in the YAML report. Categorize as: rename (field present under different key) vs. remove (field absent entirely). Only escalate to backend ask if a swagger response schema explicitly requires the field.

**Reference:** [[project_affiliate_run_20260513]] — session where all 25 Z2 FAILs resolved via 7 renames + 19 removals + 1 dedup; Z2 dropped to 0.
