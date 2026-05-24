---
name: Backend areas not implemented (as of 2026-05-11)
description: Auth pipeline, audit/event-history endpoints, and Notifications service are not implemented backend-side; do not include them in backend asks
type: project
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
User confirmed 2026-05-11: **auth pipeline, audit endpoints (and event history), and the Notifications service are not currently implemented backend-side.**

**Why:** Out-of-scope for the current backend roadmap; these aren't being built right now.

**How to apply:**
1. Do NOT include the following items in backend ask DOCXs going forward:
   - Auth / 401 / 403 / role-based access control asks (was D-CARDS-1, D-AFF-3)
   - Audit-log / event-history endpoints (was D-CARDS-2, D-AFF-4)
   - Anything that depends on the Notifications service (NOT-* endpoints)
2. When summarizing test results, classify auth-related FAILs as **expected (not-implemented)** rather than as backend defects.
3. When computing pass-rate ceilings, exclude TCs that depend on auth/audit/notifications from the denominator.
4. If/when the user signals that these are now being built, remove this memory.
