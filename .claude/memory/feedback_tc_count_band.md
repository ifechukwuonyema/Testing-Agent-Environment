---
name: TC count band per endpoint
description: Each pack endpoint must have ≥30 TCs (hard floor) and ≤40 TCs (hard ceiling). 30-35 preferred. Below 30 → author new scenarios; above 40 → dedup by meaning, never bulk-delete.
type: feedback
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
# TC count band per endpoint

**Hard floor:** 30 TCs.
**Preferred range:** 30–35 TCs.
**Hard ceiling:** 40 TCs.

If an endpoint falls outside the band, the response depends on which side:

- **Under 30** → author new scenarios to reach 30+. Drafts must come for the user's review before write. Use the canonical pack TC schema (tc_id, scenario, test_type, test_description, preconditions, input_data, steps, expected_result, fr_coverage, priority).
- **Over 40** → dedup by meaning, **never bulk-delete**. Identify semantically duplicate scenarios within the endpoint (often the result of union-merging renamed and original versions, or template+specific TC sets stacked together) and merge. If the endpoint is still > 40 after dedup, surface for the user — do not delete arbitrarily.

**Why:** Established 2026-05-08 right after the scenario revert. The 30-floor ensures meaningful coverage per endpoint. The 40-ceiling reflects the practical limit before scenarios start to duplicate each other rather than add coverage. The "dedup not delete" rule sits inside the broader [[feedback_scenarios_are_team_guidance]] policy: scenarios are guidance, so we collapse duplicates without losing distinct guidance.

**How to apply:**
- After any pack edit (revert, fill, manual change), run a band audit (`Downloads\_check_tc_band.py`) and report any out-of-band endpoints.
- For under-30: ask the user to confirm the fill plan, draft new TCs, then write.
- For over-40: detect "template" prefix (the prefix containing padding placeholders like `*_padding_*` or "Reserved for future") and propose dropping it wholesale; user confirms before write.
- Compliance band is at the per-endpoint level, not aggregate.
