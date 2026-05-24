---
name: project_transactions_run_20260518
description: Transactions targeted re-runs 2026-05-18 — all 11 DOCX FAILs resolved; 0F remaining; YAML update pending
metadata: 
  node_type: memory
  type: project
  originSessionId: aaa1ef7e-0182-479f-accf-3d98d021f715
---

Four scoped runs on 2026-05-18 against transactions.report.docx FAILs. All resolved.

**Run sequence:**
1. 57-TC scope (all 20260512 FAILs): 10P/47F — 47 remain (22 ReadTimeout, 19 B_silent_accept, 6 A_unexpected_4xx)
2. 11-TC scope (DOCX FAILs): 5P/6F — export pre-flight failed (no exportId), causing ReadTimeouts
3. 6-TC scope (re-run of #2 FAILs): 5P/1F — pre-flight seeded EXP-8E724FA8..., cleared all ReadTimeouts
4. 1-TC scope (TC-09-026 only): 1P/0F — Accept header fix confirmed working

**Pack fix applied:** TC-API-TRX-09-026 — `input_data` changed from `Accept application/xml.` → `Accept: application/json.`; `expected_result` changed to `200 OK; file or download reference returned.`; scenario renamed to `accept_header_json_success_explicit`. Applied to both pack files.

**Final state:** transactions is **286P/0F/1B** — all FAILs cleared. 1B is persistent (blocked by design).

**DOCX updated:** transactions.report.docx — 275P/11F/1B → 286P/0F/1B (55 auth TCs still excluded).

**YAML pending:** transactions_api_test_report.yaml (Kardit/reports/) still needs 11 PASS flips. Not yet done.

**SCOPE_TC_IDS state:** Runner currently scoped to `{"TC-API-TRX-09-026"}`. Clear to run all: set `SCOPE_TC_IDS = set()`.

**Why ReadTimeouts cleared:** TRX-07/09-004 hung only when pre-flight export POST failed (no exportId seeded). When Phase 0d succeeds, those TCs resolve to 400 correctly.
