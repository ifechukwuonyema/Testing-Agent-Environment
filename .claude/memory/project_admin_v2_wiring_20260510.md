---
name: Admin v2 Engine Wiring Pilot 2026-05-10
description: First per-service runner wired to v2 mutation engine; admin landed 54-58% pass rate with 0 mutation_misfire; pilot blueprint for customer/transactions
type: project
service: Admin
run_date: 2026-05-10
pass_rate: 56
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
**Result:** 54-58% pass rate, 0 mutation_misfire on admin pack.

**Why:** Admin chosen as first v2 pilot — smallest pack, cleanest classifier surface, lowest blast radius for engine wiring bugs.

**How to apply:** Pattern reused for customer → transactions. When wiring a new service to v2 engine:

1. Import `mutation_engine.apply_mutation` at top of runner
2. Wire Wave 1.1 fallback in `classify_scenario` — unrecognized names route to `engine_drive` (not silent-no-op)
3. Add `mutation_misfire` FAIL tag when engine returns "no edit applied"
4. Verify path-var precedence: engine tries path-var replacement BEFORE body/query fallbacks for `*Id`-shaped targets
5. Run admin pilot first to validate kwarg forwarding before scaling out

## Engine bugs fixed during pilot

- **kwarg forwarding bug**: 14 wrapper primitives called `_m_set_field` without `**kw`, losing endpoint context. Fixed all wrappers.
- **boundary_pagination didn't recognize `exceeds_limit`/`maximum_page_size`**: silent no-ops. Patched.
- **Diagnostic message lied**: said "Engine applied X" when engine wasn't called. Fixed.
