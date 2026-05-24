---
name: Cards Hybrid Run 2026-05-11
description: Two runner fixes (ENUMERATED_POOLS guard + override cardId pop + Phase 0f4 pool fallback) yielded 10 PASSes on replay; remaining 123 FAILs are all backend defects
type: project
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
Replay of 133 failed TCs → 10 PASS, 123 FAIL, 0 BLOCKED (7.5%).

**Three runner fixes shipped this session:**

1. **ENUMERATED_POOLS guard** — `cardIdActivePool` and other status pools filled by live Phase 0f1 enumeration must not be merged with ACTIVE.txt entries. ACTIVE.txt IDs are not reset between runs and include TERMINATED cards. Guard skips merge for any key in `ENUMERATED_POOLS` set when a live pool is already populated.

2. **Override cardId pop** — `failed_payload_overrides.json` TC-level override URLs contain hardcoded cardIds that go stale. Dispatcher now calls `override_path_vars.pop("cardId", None)` so the live pool-selected cardId is never replaced by an override URL's stale cardId.

3. **Phase 0f4 three-tier fallback** — `pre_flight_mint_limit_request_pool` falls back to probing `cardIdActivePool` when both the ACTIVE.txt seeded card and the constant `_PROVISIONED_LIM_OPS_CARD_ID` are TERMINATED.

**PASSes recovered:**
- LIM-02: 5 (happy_path, min_fields, contract_valid, read_after_action, script_rejected)
- FRZ-01: 3 (happy_path, min_fields, state_updates)
- FUL-02: 1, TRM-01: 1

**Remaining 123 FAILs — all backend:**
- B_silent_accept (53): auth middleware absent on all read/GET card endpoints
- A_unexpected_4xx (43 auth): state-guard fires before auth — backend returns 400/409 instead of 401/403
- FUL-03 (14): no FAILED-state physical cards seeded
- Z2_schema_drift (8): field rename mismatches

**Z/Z2 recommendation DOCX:** `Downloads\cards_z_z2_recommendations_2026-05-11.docx`
