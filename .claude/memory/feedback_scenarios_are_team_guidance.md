---
name: Test-pack scenarios are team guidance, not just runner inputs
description: Never delete a scenario from a pack to make the runner happy; the pack documents what the team should think about. Fix the runner instead.
type: feedback
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
# Test-pack scenarios are team guidance, not just runner inputs

Every test-case in a Kardit pack does double duty:
- It feeds the automated runner.
- It documents — for developers, manual testers, reviewers — what scenarios a sane implementation should handle.

If the runner can't validate a scenario (because swagger doesn't declare the constraint, because the runner's classifier is too coarse, etc.), that is a **runner problem**, not a pack problem. **Do not delete the scenario from the pack.**

**Why:** On 2026-05-07 / 2026-05-08, ~500 scenarios were deleted across 8 packs under the rationale "swagger doesn't declare this constraint, so a 200 response is per-spec, so the test is invalid." The user told me on 2026-05-08 that this was wrong: the scenarios encode product expectations and team guidance even when swagger is silent or vague. The deletions were reverted in full.

**How to apply:**
- A scenario producing a confusing PASS or FAIL → upgrade the runner's classification (e.g., add `EXPECTED_PER_SPEC`, `BACKEND_NOT_CONTRACT_BOUND`) so the runner reports it without dropping it. Keep the scenario.
- A scenario revealing a swagger gap → file a backend ask to add the constraint. Keep the scenario.
- An entire endpoint is no longer in swagger (deleted from contract) → THAT endpoint and its scenarios may be removed, with the user's explicit sign-off. Verify against the canonical swagger first (see [[reference_main_swagger]]).
- Mechanical fixes (wrong path, wrong method, wrong payload shape, scenario rename for clarity) are still fine.
- When in doubt: ask the user before deleting anything from a pack.
