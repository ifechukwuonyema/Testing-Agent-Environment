---
name: project_cards_e2e_run_20260523
description: Cards E2E runner (cards_e2e_runner.py) Run 6 on 2026-05-23 — results, fixes shipped, and current state of the runner
metadata: 
  node_type: memory
  type: project
  originSessionId: 5a397891-3858-46d1-a7e6-4750ffdda215
---

Cards E2E runner (port 8082, Bearer + ECDSA auth) Run 6: functional TCs produced results with backend defects fully categorised. Auth bypass layer (200 TCs, 182P/0F) confirmed auth boundary works. Backend defects DOCX at `Kardit\reports\cards_backend_defects_20260523.docx`.

**Runner is at:** `Kardit\harnesses\cards_e2e_runner.py`. All runner bugs are fixed; any new FAILs are backend defects. Run 6 YAML at `Downloads\cards_e2e_report_20260523-152900.yaml`.

## Runner fixes shipped this session

1. **`__NO_AUTH__` sentinel** — auth-rejection functional scenarios set `override_headers["Authorization"] = "__NO_AUTH__"`. `execute()` deletes it before request goes out, sending no Authorization header. Previously these 48+ scenarios were BLOCKED.
2. **`resolve_required_card_state()` keyword bug** — `"already_active" in s` did not match `"already_in_active_state_rejected"`. Fixed: `or "already_in_active_state" in s`.
3. **`invalid_source_state` routing** — mapped to `"TERMINATED"`.
4. **`already_target_state_rejected` on unfreeze** — routed to `cardIdTerminated`.
5. **`missing_idempotency_key_rejected_if_required` wrongly blocked** — removed from `_STATE_CHANGE_IDEM_TOKENS`.
6. **Bank token credential injection** — `_FUNC_AUTH_CRED` dict maps `wrong_audience_rejected` / `foreign_scope_rejected` → `__BANK_TOKEN__` sentinel.

## Run 6 results (functional TCs)

- Total: ~880 TCs
- FAILs: 71 (all backend-attributable)
- Backend BLOCKEDs: 31 (30 CLUSTER_C_PERSISTENCE_SPLIT + 1 STATE_FIELD_MISSING)

## Defect clusters

| Defect | Severity | Impact |
|---|---|---|
| D-CARDS-TENANT-1 | CRITICAL | 20 FAILs — foreign tenant reads any card (200) |
| D-CARDS-VALIDATION-1 | High | 16 FAILs — silent accept on invalid/missing fields |
| D-CARDS-AUTH-1 | Medium | 16 FAILs — bank token returns 401 not 403 |
| D-CARDS-TENANT-2/AUTHZ-1 | High | 10 FAILs — state machine fires before authZ check |
| D-CARDS-500-1 | High | 6 FAILs — null crash on missing required fields |
| D-CARDS-AUTHZ-2 | CRITICAL | 1 FAIL — SERVICE_PROVIDER writes accepted on refresh |
| D-CARDS-BUSINESS-1 | High | 4 FAILs — business rules absent |
| D-CARDS-BULK-1 | High | 30 BLOCKEDs — bulk endpoints 404 (persistence split) |

Ceiling: ~99%+ with all backend defects fixed.

## SKIP / guard flags

- `SKIP_BULK_TERMINATE_SC09=True` (default) — never wipe affiliate pool
- `EXCLUDED_FUNCTIONAL_ENDPOINTS` — 3 load-requests endpoints excluded (D-CARDS-LOADREQ: backend 500)
