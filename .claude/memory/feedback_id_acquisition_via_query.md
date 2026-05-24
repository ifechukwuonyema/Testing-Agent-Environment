---
name: ID Acquisition via Query Endpoint
description: For Affiliate, Cards, Bank, Transactions — fetch legitimate IDs via the service's query endpoint instead of minting via POST
type: feedback
originSessionId: cd1b62a4-e023-4d8e-93ef-715c9ff3b17f
---
When a test or harness needs a real ID (bankId, affiliateId, cardId, transactionId) from Affiliate, Cards, Bank, or Transactions microservices, the acquisition order is:

1. **Try mint first** — POST to the service's create endpoint to generate a fresh ID. If successful and an ID is returned, use it.
2. **Fallback to query** — if mint fails (non-2xx, transport error, or 2xx with no extractable ID), POST to the service's query endpoint and pick the first persisted ID from the response.
3. **Never** silently fall back to a hardcoded SessionStore seed (e.g. `22222222-...`) — those have proven non-queryable and pollute results.

Transactions is special: there's no client-mintable transaction endpoint (transactions originate upstream from card load/unload flows), so it goes straight to query-first.

Known query endpoints on the Kardit platform:
- Bank: `POST /api/v1/banks/query`
- Affiliate: query endpoint exists (use the affiliate query route from Postman)
- Cards: query endpoint exists
- Transactions: query endpoint exists

**Why:** The 2026-05-01 Bank hybrid run failed pre-flight because `POST /admin/banks` was non-2xx and the seeded `22222222-...` bankId wasn't queryable — 160 TCs got reclassified as `seed_not_queryable` (Cluster-C). Querying for an existing ID sidesteps both the broken mint path and the stale-seed problem, and guarantees the ID is actually persisted and joinable across the chain.

**How to apply:**
- In any new harness or pre-flight step: try the mint POST first; if it doesn't yield a usable ID, run the service's query endpoint and use the first result.
- If both mint and query are broken (e.g. Bank's `/banks/query` was 0/36 PASS on 2026-05-01), flag both as blocked rather than falling back to a seed.
- Per-service runners under `~\Kardit\harnesses\` and the chain orchestrator follow the mint→query→fail order. The chain orchestrator's downstream handoffs reuse harvested upstream IDs and only re-acquire if the service can't proceed without a fresh one.
