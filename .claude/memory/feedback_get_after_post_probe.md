---
name: GET-after-POST Persistence Probe Pattern
description: Diagnostic pattern that converts ambiguous Cluster-C BLOCKEDs into deterministic write_did_not_persist / partial_persistence / read_path_5xx attribution; never upgrades verdicts to PASS except in explicit state-effect carve-out
type: feedback
originSessionId: a00fb0b4-c57c-4815-892a-3966d012e235
---
Per-TC GET-after-POST probe that reads back the resource just minted by a 2xx write. Originated 2026-05-03 from a question Onyema's engineer raised: "if you call the corresponding GET of that endpoint it should solve the problem."

**Why:** before the probe, every FAIL on a write endpoint had ambiguous root cause — was it a write defect, a read defect, a schema defect, an envelope drift? The probe converts speculation into deterministic attribution. The same pattern doubles as a contract assertion: a 2xx write that emits an id which is unretrievable on the read path is a confirmed write-path defect, not "seed not queryable" ambiguity.

**How to apply:**

- Use for **mint endpoints** that produce a new resource id in their 2xx response (cardId, bankId, loadRequestId, etc.). Wire `probe_get_after_post()` from `~\Kardit\harnesses\probe.py` into the per-TC loop. Fire only when write returns 2xx AND the id is extractable.
- Use **state_effect_probe** (same module) for state-mutation endpoints whose side effect is visible via an existing GET (e.g. `/freeze` → `GET /cards/{cardId}` → status field). Build a STATE_VERIFY_REGISTRY mapping `(scenario_keyword, endpoint) → (verify_path, field, expected_predicate)`. The harness carves these scenarios out of the "BLOCKED for db-verify" classifier and runs them — when the probe confirms the state change, the verdict legitimately becomes PASS.
- **Never let the persistence probe upgrade a verdict to PASS.** Its only legal moves are FAIL→BLOCKED (refining attribution) or BLOCKED→BLOCKED-with-tighter-reason. State_effect_probe is the only probe allowed to upgrade BLOCKED→PASS, and only when the carve-out registered explicit verification.
- **Default cadence:** 3 attempts with 1s/2s/3s linear backoff (~6s total budget). Tunable via `PROBE_MAX_WAIT_S` env var. Document this as the eventual-consistency contract the harness expects.
- **Secondary probe path** disambiguates "read path 5xx" from "id not persisted." Use a different read endpoint (e.g. primary `/cards/{cardId}`, secondary `/cards/{cardId}/balance`). If primary 5xx and secondary 2xx → `partial_persistence`. If both 5xx → `read_path_5xx`. If primary 404 retried + secondary 404 → confirmed `write_did_not_persist`.

**What this is NOT:**

- Not a fix for **B1_db_verify** writ large. Audit-log creation, notification queueing, CMS handshake state, transaction-record inserts, lifecycle event emission — none of these are observable from the API surface. They need backend cooperation (read-only verification endpoints, requestId propagation, or DB read access). See [[reference_backend_verification_endpoints_ask|Backend ask document]].
- Not a fix for **5xx writes**. If the write itself returns 500/400, there's nothing for the probe to verify — it correctly stays inert. The 5xx is a separate Cluster-H defect.
- Not a fix for **schema/envelope drift** (Z1/Z2). Those are response-shape defects on writes that DID persist; the probe's persistence-confirmed result actually strengthens the case that the FAIL is shape-only.

**Empirical results (Cards 2026-05-03):**

- Persistence probe fired on 18/18 2xx issuance writes; 18/18 confirmed persisted. Diagnosed 16 issuance FAILs as silent-accept (not persistence) defects.
- State-effect carve-out ran 5 TCs (would otherwise be BLOCKED); 0 reached the probe stage because the writes themselves returned 400/404. Probe correctly inert.
- Reduction in B1 BLOCKEDs: ~9 of 118 are runner-side recoverable; ~109 need backend-side endpoints. Initial estimate of 40-60 was wrong; corrected after inspecting actual scenario distribution.

**Trigger words for future invocation:**

When the user asks "did the writes land," "is this a write or read defect," "why is this BLOCKED," "what's actually broken vs ambiguous," "Cluster-C reclassification," or "seed not queryable" — the probe pattern is the right tool. Wire it to the relevant endpoint, run, and report.
