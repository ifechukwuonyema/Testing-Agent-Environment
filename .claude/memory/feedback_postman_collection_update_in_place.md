---
name: Postman Collection Updates In-Place
description: When given a new Postman collection file, update the existing in-tree collection in place rather than swapping to the new path
type: feedback
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
When the user provides a new Postman collection (e.g. CardsPMC.json, transactions_pm.json, etc.), do NOT swap the runner's `POSTMAN_PATH` to point at the new file. Instead, **overwrite the in-tree collection** the runner already references (e.g. `Downloads\Kardit.Api.postman.collection.json`) with the new file's content.

**Why:** All 8 service runners share the same `POSTMAN_PATH` constant; swapping per-service breaks chain runs and makes drift hard to track. Keeping a single canonical in-tree collection that gets updated in place keeps every runner pointing at the same source-of-truth and makes Postman changes show up uniformly across the platform. Confirmed 2026-05-05 PM during Cards swagger-additions session.

**How to apply:**
- Given a new PMC file, first diff it against the current in-tree collection so the user sees what's changing.
- Then overwrite the in-tree file (e.g. copy `CardsPMC.json` content to `Kardit.Api.postman.collection.json`).
- Invalidate any cached `.pmidx.cache` next to the collection so runners rebuild their index.
- Do NOT introduce service-specific `POSTMAN_PATH` overrides.
