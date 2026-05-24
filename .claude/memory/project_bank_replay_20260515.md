---
name: project_bank_replay_20260515
description: Bank 16-TC replay session 2026-05-15 — all 16 originally failed TCs resolved across 4 iterations; per-TC ID pinning pattern validated
metadata: 
  node_type: memory
  type: project
  originSessionId: 5f2f7813-c7e7-4f05-a43e-70943f5bfa14
---

16 failed TCs (from prior DOCX reports) replayed across 4 iterative batches; all 16 resolved as PASS by final run.

**Why:** Pool IDs from bank_fixtures_v2.json were not actually in pending state on the backend — approve/reject endpoints returned 409 on every pool-drawn ID. Root cause: IDs consumed in prior runs were not reset between sessions.

**How to apply:** When PART-02/03 happy-path TCs all return 409, the pool IDs are stale. Don't chase runner bugs — ask backend to reset IDs and pin fresh ones via TC_REQUEST_ID_OVERRIDE. See [[feedback_tc_request_id_override_pattern]].

### Final override mapping (as of 2026-05-15)

```python
TC_REQUEST_ID_OVERRIDE = {
    "TC-API-BNK-CTRL-01-014": (CANONICAL_BANK_ID, "AFF-SUS-411"),
    "TC-API-BNK-CTRL-01-015": (CANONICAL_BANK_ID, "AFF-SUS-410"),
    "TC-API-BNK-CTRL-02-014": (CANONICAL_BANK_ID, "AFF-BLK-514"),
    "TC-API-BNK-CTRL-02-015": (CANONICAL_BANK_ID, "AFF-BLK-510"),
    "TC-API-BNK-PART-02-001": "REQ-PENDING-904",
    "TC-API-BNK-PART-02-021": "REQ-PENDING-905",
    "TC-API-BNK-PART-02-022": "REQ-PENDING-906",
    "TC-API-BNK-PART-02-026": "REQ-PENDING-907",
    "TC-API-BNK-PART-02-037": "REQ-TEST-NEW-001",
    "TC-API-BNK-PART-03-001": "REQ-PENDING-908",
    "TC-API-BNK-PART-03-022": "REQ-PENDING-909",
    "TC-API-BNK-PART-03-025": "REQ-PENDING-982",
    "TC-API-BNK-PART-03-026": "REQ-PENDING-983",
}
```

D-BNK-AUTH-1 (auth bypass): CTRL state-guard TCs passed once correctly pinned to ACTIVE affiliates — confirms the bypass is at the state-validation layer, not the ID layer.

Consolidated all-16-PASS report: `Downloads\bank_replay_all16_passes_20260515.yaml`
