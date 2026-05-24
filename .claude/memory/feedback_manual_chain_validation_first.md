---
name: Manual chain validation before harness changes
description: When a pre-flight phase has been failing for days/weeks, ALWAYS run the chain manually with curl/requests BEFORE writing more workaround logic. Don't accept long-standing pre-flight failures as known/working-around — they may be hiding the actual defect.
type: feedback
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
When a pre-flight phase prints a failure every run (e.g. cards Phase 0c "activate_status=FAIL response=404" since 2026-04-23), do NOT keep adding workaround logic around it. **Run the chain manually first.**

**Why:** The Phase 0c 404 was treated for 2+ weeks as a "write/read store split" backend defect (D-01) and the harness routed around it via /cards/query pools. A 30-second manual `requests.post(BASE+"/cards/issuance", ...)` followed by `requests.post(BASE+"/cards/{id}/activate", ...)` exposed the real cause in 5 minutes — the issuance and activate Postman bodies use different tenant-ID validators (D-08) and even with aligned scope, no public path advances PENDING_ISSUANCE → PENDING_ACTIVATION (D-09). The user correctly called out this process gap on 2026-05-06: "you are supposed to have checked all these things before running please crosscheck your processes."

**How to apply:**
- Before adding any new state-routing / pool consumption / fallback logic that depends on a backend lifecycle phase succeeding: **first reproduce the chain manually with the actual Postman bodies and confirm every step works end-to-end.**
- If a step fails, capture the error body verbatim and reason about whether it's a contract issue (Postman body wrong), a scope issue (different tenant in different bodies), a state issue (wrong precondition), or a real backend bug. The category dictates the fix path.
- A multi-step chain validation script in Python takes 30-60 seconds to write. It's always cheaper than another runner change + 15-min harness re-run + post-mortem.
- Treat persistent pre-flight failures as **investigation tasks** with priority above any other harness change. Do not normalize their presence in the run output.
- The 4 manual cross-check steps for any new lifecycle endpoint:
  1. Hit issue/mint endpoint with literal Postman body — confirm shape and 2xx
  2. GET the resource — confirm it's queryable and inspect its state
  3. Try the next step in the lifecycle (activate / submit / approve / etc.) — confirm what state/scope/auth conditions it actually enforces
  4. Only THEN write or modify routing logic
