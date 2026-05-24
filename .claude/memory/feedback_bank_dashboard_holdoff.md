---
name: Bank dashboard endpoints stay out of pack until v2 is implemented
description: Don't add GET /api/v[12]/banks/{bankId}/dashboard to the bank pack despite swagger declaring v2 — backend implementation isn't ready yet.
type: feedback
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
# Bank dashboard endpoints stay out of pack until v2 is implemented

`MainSwagger.txt` declares `GET /api/v2/banks/{bankId}/dashboard`, and there are 40 historical scenarios for it in older bank-pack `.bak` files. Despite that, **do not restore it to the bank pack** at this time.

**Why:** On 2026-05-08 I proposed restoring it because swagger declares it. User overrode: it's in scope on paper, but the v2 backend implementation isn't ready yet, so adding the test cases now would generate noise (every TC would 404/501 against real backend). Hold off until the v2 implementation is shipped.

**How to apply:**
- During pack curation / revert sessions: skip dashboard restoration for bank pack.
- If the user later signals "v2 dashboard is live now," then restore using the existing scenarios in `bank_microservice_functional_test_pack_v1_40_each.json.bak.dashboard_v2_b3removed` (40 TCs).
- Don't re-raise the proposal in subsequent sessions just because swagger declares it; the gating condition is implementation readiness, not contract presence.
