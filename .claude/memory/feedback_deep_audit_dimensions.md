---
name: Deep per-TC audit — 10 verification dimensions
description: After standard mutation/response audit comes back clean but FAILs remain, run a deep 10-dimension audit to confirm whether the bottleneck is runner, pack, swagger, or backend. Pattern crystallized 2026-05-08 on transactions session.
type: feedback
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
**Rule**: When the standard per-TC mutation+response audit shows ~0 silent-pass risks but the harness still has substantial FAIL volume (e.g. >50 FAILs / >10% rate), the next step is a 10-dimension deep audit before assuming all remaining FAILs are backend-side. The deep audit distinguishes runner, pack, swagger, and backend issues.

**Why**: On 2026-05-08 transactions session, the standard audit came back clean (0 silent-pass risks across 391 TCs after pack cleanup). But 71 FAILs remained. The deep audit revealed the swagger has ZERO required fields, ZERO enums, ZERO formats, ZERO patterns across all 11 transactions endpoints — meaning the backend has no contract to enforce, and the runner can't generate meaningfully invalid mutations against an empty contract. Without the deep audit, this would have been mis-attributed to "backend silent-accept defect" alone, missing the upstream swagger fix that gates the entire validation pipeline.

**How to apply**:
The 10 dimensions, in order:
1. **D1 endpoint contract** — pack endpoint resolves to a real swagger path+method (after PACK_TO_POSTMAN/PATH_TEMPLATE_OVERRIDE)
2. **D2 path-var format** — URL values match swagger param schema (UUID/pattern)
3. **D3 missing required body** — sent body includes every swagger-required field (allowing intentional drops for missing_X tests)
4. **D4 type compliance** — sent body field types match swagger (string/int/array/object)
5. **D5 enum compliance** — enum-restricted fields use declared values (allowing intentional violations for unsupported_X tests)
6. **D6 additionalProperties** — sent body has no fields outside swagger when addProps:false
7. **D7 mutation meaningfulness** — for negative tests, mutated value actually violates swagger constraints
8. **D8 status verdict** — runner verdict logic correct (pack expected codes vs actual)
9. **D9 response schema drift** — response 2xx shape matches swagger response schema
10. **D10 response required fields** — 200 responses include swagger-required-response props

Reference implementation: `Downloads\_audit_transactions_DEEP_20260508.py`. Adaptable per service by changing PACK_TO_SWAGGER_PATH map.

**Diagnostic heuristics from the dimensions**:
- D3+D4+D5 all 0 with no constraints declared in swagger → swagger is the bottleneck. File a swagger-constraint-audit ask before chasing backend behavior.
- D6 violations → pack sends extra fields not in swagger. Pack-side rename or delete.
- D9 drifts → backend returns shape swagger doesn't declare. Backend ask to update response schema.
- D10 missing required → backend returns incomplete responses. Backend defect.
- D7 always n/a when swagger has no constraints. Surface this loudly — implies the entire negative-test category is unenforceable.

**When NOT to run**: skip the deep audit if the standard audit already explains all FAILs (e.g. catastrophic Z2 schema drift on 50+ TCs is its own story; deep audit adds little). Use deep audit specifically when standard audit shows clean signal yet FAILs remain unexplained.
