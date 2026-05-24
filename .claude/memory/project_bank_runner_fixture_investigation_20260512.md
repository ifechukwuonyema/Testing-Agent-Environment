---
name: project_bank_runner_fixture_investigation_20260512
description: Bank runner fixture investigation 2026-05-12 — ID format ecosystem, approve endpoint, suspend/block gaps
metadata: 
  node_type: memory
  type: project
  originSessionId: b4a81de3-50bf-410c-81aa-9f965e5971b8
---

Full investigation into why bank approve/reject and suspend/block TCs were failing.

**ID format ecosystem (confirmed by live probing):**
- `APR-xxx` — returned by `POST /api/v1/admin/banks` in `InternalPartnership.PartnershipRequestId`; ALWAYS created ACTIVE (auto-approved); the ONLY format the approve endpoint accepts (returns 409 "already approved")
- `PRQE-xxx` — returned by `POST /api/v1/affiliates/{affiliateId}/bank-partnership-requests`; creates PENDING_BANK_APPROVAL request; returns 404 on the approve endpoint
- `PARTNERSHIP-xxx` / `PRQ-xxx` — older formats; also return 404 on approve endpoint
- UUID-format affiliates — the only format that works on suspend/block endpoints; AFF-xxx affiliates return 404

**Approve endpoint gap (confirmed backend defect):**
`POST /api/v1/banks/partnerships/{requestId}/approve` only resolves APR-xxx IDs. The affiliate-side partnership request flow (PRQE-xxx) creates PENDING requests but in a format the approve endpoint cannot find. Backend must expose a way to approve PRQE-xxx format requests, or the approve endpoint needs to resolve both ID formats.

**Reject endpoint gap:**
`POST /api/v1/banks/partnerships/{requestId}/reject` has `{requestId:guid}` route constraint — rejects all non-UUID formats with 400. Confirmed backend defect.

**Suspend/block:**
AFF-xxx affiliates (internal bank affiliates) return 404 on suspend/block. Only UUID-format affiliates work. Both canonical UUID affiliates (`a7d5929b` and `b80acd18`) are state-exhausted (BLOCKED).

**How to apply:** When resuming bank runner work, the fixture pools need completely fresh strategy. The approve/reject gap is a backend defect. For suspend/block, need the backend to either provide UUID-format affiliates or fix AFF-xxx support.
