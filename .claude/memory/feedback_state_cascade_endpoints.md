---
name: State-cascade endpoints need rotating fixtures
description: When a write endpoint mutates state on a single seeded entity, every TC after the first 409s on already-mutated state. Don't read this as a backend defect; it's a test-fixture problem. Backend ask is for rotating fixtures or a per-TC reset endpoint.
type: feedback
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
**Rule**: When a state-mutation endpoint operates on a single seeded entity (e.g., one affiliate, one card, one partnership-request), the first TC of the run that exercises it succeeds; every subsequent TC against the same entity 409s on "already in target state". The cascade masks every downstream test (auth tests, malformed-input tests, even other happy paths) because the state machine rejects before validators or auth even run.

**Why**: Observed sharply on Bank 2026-05-07 — CTRL-01 (suspend) and CTRL-02 (block) each have 32 TCs against ONE canonical affiliate; the first TC suspends/blocks the affiliate; the next 14+ TCs see 409 regardless of intent. Cards saw the same pattern earlier sessions. Pre-patch the cascade was hidden behind a 400 (Postman base body missing required field); post-patch the body is valid, the first TC succeeds, and the cascade surfaces as 409s.

**How to apply**:
- When triaging FAIL@409 clusters on a write endpoint, check if every FAIL touches the SAME path-var (single seeded entity). If yes, this is state-cascade, not 14 individual defects.
- Don't classify these as backend defects — backend behaviour is correct (the entity IS already in that state).
- The fix is fixture-side: ask backend for either (a) rotating affiliate/card/request pool of N fixtures the runner cycles through per TC, or (b) a test-only reset endpoint that returns the entity to its initial state. Document the ask under D-FIXTURE-* in the backend ask DOCX.
- Until backend ships fixtures, accept that state-cascade endpoints can only validate one happy path + one 4xx variant per run. Shrink the test pack accordingly OR mark the FAIL@409 cluster as "fixture-blocked" rather than chasing it as defect.
- For the runner's pre-flight, prefer minting a fresh entity over using a seeded one when the endpoint is a state mutator — `discover_unlinked_affiliate_for_bank` is the partnership-request example.
