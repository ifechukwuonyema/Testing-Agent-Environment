---
name: Runner classification policy (post-2026-05-08 redesign)
description: 3-state PASS/FAIL/BLOCKED, no EXPECTED_PER_SPEC; mutations must always fire; mutation_misfire tag for unfireable mutations; scenario-name heuristic drives mutation selection
type: feedback
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
# Runner classification policy (post-2026-05-08 redesign)

After the scenario-revert + rebalance work earlier in the day, user directed how the runner should classify going forward. This supersedes any prior runner-logic memories.

## States

The runner emits exactly **3 execution states**: `PASS`, `FAIL`, `BLOCKED`. Do **not** introduce `EXPECTED_PER_SPEC` or any other classification. Pass rate = PASS / (PASS + FAIL + BLOCKED).

## Decision rule

`expected_result` (status code parsed from the TC's expected_result string) must equal the actual response status code.
- match → PASS
- mismatch → FAIL
- pre-flight or seed-acquisition failed → BLOCKED

**Why:** Backend returning 200 to a "should be 4xx" scenario IS a real defect under the team-guidance rule (`[[feedback_scenarios_are_team_guidance]]`). The runner shouldn't excuse swagger-silent constraints — those are still expectations the team wants enforced.

## Mutation guarantee

**Every TC's mutation must actually fire.** A scenario like `missing_tenantId_rejected` MUST drop the `tenantId` field from the request before sending. Today's `B_silent_accept` cluster is largely the result of mutations failing to fire (the field stays in the payload, backend correctly returns 200, runner says FAIL).

If a mutation cannot be applied (e.g., scenario `missing_X_rejected` but field X isn't in the happy-path payload), the runner:
- Sends the request anyway (unmutated).
- Records `mutation: { action: misfire, reason: <why>, target: <X> }` in the per-TC YAML record.
- Marks the TC `FAIL` with `mutation_misfire` tag.

User's preference is FAIL+tag, **not** BLOCK. The intent: surface misfires loudly so the pack/payload pair gets fixed, not buried in BLOCKED.

## Mutation source

**Pure scenario-name heuristic.** The mutation engine parses the scenario name to determine action:
- `missing_<field>_rejected` → drop `<field>`
- `empty_<field>_rejected` → set `<field>` to `""`
- `null_<field>_rejected` → set `<field>` to `null`
- `invalid_<field>_format` → set `<field>` to a value that violates declared format/pattern
- `expired_token_rejected` → swap auth header to expired JWT
- `malformed_token_rejected` → swap auth to non-JWT garbage
- `unauthenticated_rejected` → strip auth header
- `wrong_role_rejected` / `forbidden_*` → swap auth to a token with insufficient role
- `oversized_<field>_rejected` → set `<field>` to >server-limit length
- ...etc.

No per-TC `mutation` field in the pack (no retrofit of 2,861 TCs needed).

## Code change timing

User said any modifications to the mutation engine **wait until the new Postman collection arrives**. The mutation engine is what enforces the guarantee, and it needs the canonical happy-path payloads to mutate against.

## Until then

- Runners patched 2026-05-08 to load `MainSwagger.txt` instead of per-agent `swagger.json` (see `[[reference_main_swagger]]`).
- Outdated test packs + per-agent swaggers moved to `Documents\trash\kardit_outdated_2026-05-08\` (see `[[reference_trash_housekeeping_20260508]]`).
- Pre-run mutation-misfire audit tool deferred per user instruction; build it once Postman arrives.
