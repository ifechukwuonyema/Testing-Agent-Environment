---
name: project_affiliate_run_20260513
description: Affiliate standalone run 2026-05-13 — 455 TCs (302P/97F/56B, 66.4%); pack 474→455 after Z2 purge; runner +SCOPE_TC_IDS +6 classifier fixes; Z2 cluster fully eliminated
metadata: 
  node_type: memory
  type: project
  originSessionId: 3f6cd432-c48e-496c-917d-c90225f796c8
---

## Result
455 TCs | 302 PASS (66.4%) | 97 FAIL | 56 BLOCKED

Previous baseline (2026-05-12): 476 TCs | 291P (61.1%) | 123F | 62B

Pack reduced 474 → 455 (-19 removed + 1 dedup) after response-field audit.

Policy applied: [[feedback_backend_response_authoritative]] — backend response shape is ground truth; fix pack scenario names to match actual response keys.

## Runner changes

**SCOPE_TC_IDS env var** — targeted rerun without running full suite

**6 classifier fixes:**
1. `unknown_bankid_not_found` → `set_field("selectedBankIds", [ZERO_UUID])`
2. `unknown_ownerbankid_not_found` → `set_field("ownerBankId", ZERO_UUID)`
3. `missing_affiliate_id` → `set_path_var("affiliateId", "")`
4. `missing_bank_id` → `drop_field("bankId")`
5. `blank_bank_id` → `set_field("bankId", "")`
6. `missing_caseid_path_segment` → `set_path_var("caseId", "")`

## FAIL breakdown (97 total)

| Cluster | Count | Root cause |
|---|---|---|
| B_silent_accept | 77 | D-AFF-1 auth pipeline — backend processes before auth check |
| A_unexpected_4xx | 11 | issuing-banks returns 401 instead of 403 |
| G_4xx_where_2xx_expected | 6 | Unicode in body rejected + draft state issues |
| Z_other | 3 | unsupported_accept_header → 200 not 406 |
| Z2_schema_drift | 0 | Clean — fully eliminated |

## BLOCKED breakdown (56 total)
- 49 B1_db_verify — audit_log_created, record_persisted_in_db checks
- 7 rate_limit_intentional

Harness: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\postman_standalone_affiliate_v2.py`
Ceiling: ~99.3%
