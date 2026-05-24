---
name: feedback_admin_decision_no_selectedbanksapproved
description: "POST /admin/onboarding/cases/{cid}/decision must NOT include selectedBanksApproved — causes FAIL_DECISION and empties Phase 0c approved pool"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e8d110a8-aab4-44fc-958a-f620f302bf47
---

Never include `selectedBanksApproved` in the admin decision body when calling the approve endpoint programmatically.

**Why:** The admin decision endpoint rejects requests that include `selectedBanksApproved` in the body (confirmed in admin runner session 2026-05-13 and affiliate runner Phase 0c 2026-05-18). When present, all approve calls return non-2xx → `status=FAIL_DECISION` → `approved_pool=0` → downstream TCs that need fresh affiliates get 422 "Trading Name differs from onboarding data".

**How to apply:** Decision body should only contain `decision`, `reviewerNotes`, `decisionReason`. Drop `selectedBanksApproved` from any runner that calls this endpoint. Applies to: affiliate runner `_run_single_onboarding_chain`, and any future runner that builds an onboarding chain. See also [[project_admin_onb09_selectedbankids_fix]].
