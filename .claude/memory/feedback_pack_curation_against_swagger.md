---
name: Pack Curation Against Swagger Contract — REVISED
description: DO NOT delete scenarios from packs because the runner can't validate them against swagger. Scenarios are team guidance; runner-classification noise is a runner problem. Supersedes prior swagger-driven deletion policy.
type: feedback
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
revisedOn: 2026-05-08
---
# Pack Curation Against Swagger Contract — REVISED

**The earlier version of this memory was wrong and led to ~500 scenarios being deleted across 8 packs over the 2026-05-07 / 2026-05-08 sessions. Reverted in full on 2026-05-08.**

## The corrected rule

**Do not delete a test-case scenario just because swagger doesn't declare a constraint that would make it fail.** Test packs serve a dual purpose:

1. **Inputs to the automated runner** — fields, payloads, expected codes.
2. **Guidance for the team (developers, manual testers, reviewers)** — what scenarios SHOULD a sane implementation handle, even if swagger is silent. A free-form string field that the contract leaves unconstrained is still expected to behave reasonably under bogus values; the team shouldn't have to rediscover that.

If a scenario "silent-accepts" because swagger doesn't declare the constraint, the issue is one of:
  - **Runner classification** — the runner needs better logic to express "swagger is silent here, so a 200 is expected per spec" without dropping the test from the pack.
  - **Spec gap** — file a backend ask to add the constraint to swagger; the scenario stays in the pack as a placeholder for that ask.
  - **Truly out of scope** — only then consider removing, AND only after explicit user sign-off, not as a unilateral audit call.

## Why the original policy was harmful

- Packs are reference documentation for the team. Removing "the team's TODO list" because the runner can't auto-fail makes the docs incomplete.
- It conflated two questions: "is this a real backend defect?" (runner classification) vs "should this scenario exist?" (pack content). The first does not imply the second.
- It produced an irreversible-feeling cascade: every audit cycle deleted more scenarios, and the run-rate went up because the harder cases were gone — false signal of progress.

## How to apply

- When reviewing a `B_silent_accept` FAIL: do not propose deleting the scenario. Propose **fixing the runner** to mark it as `EXPECTED_PER_SPEC` (or a similar tag) when swagger has no constraint, and/or **filing a backend ask** to add the constraint.
- When auditing a pack against swagger: only the runner's classification list should change, not the pack content.
- Pack edits that **do** make sense: fixing wrong endpoint paths/methods/payloads (so the runner targets the right thing) and renaming scenarios for clarity. These are mechanical fixes, not curation deletions.
- If the user explicitly directs a deletion ("remove these specific scenarios because X"), do it. Otherwise default = keep.
- Auth/forbidden cross-cutting scenarios remain in scope as before — they were never the source of the over-deletion problem.

## Scope of revert

On 2026-05-08, +557 TCs were restored across all 8 Kardit services using a union-merge of every available .bak. See [[project_scenario_revert_20260508]] for the full record.
