---
name: Self-Review Protocol After Multi-Fix Sessions
description: Specific failure modes I exhibit when applying many fixes in one pass; concrete checks to run before declaring "done"
type: feedback
originSessionId: cd1b62a4-e023-4d8e-93ef-715c9ff3b17f
---
## Operating principle (2026-05-04, after user called out laziness)

Before editing any code, trace the change end-to-end. Read every call site of what I'm modifying — not the diff, the surrounding flow. Run one realistic input through the changed code mentally, including the loops and conditionals around my edit. If I can't do that without re-reading, I don't understand it well enough to ship.

Before declaring done: I have to do the trace-through myself — but I cannot self-certify the result. I have author bias on every change I make; I will never grade my own code a fail. That bias is exactly why Codex exists in this workflow.

**Codex's role (clarified by user 2026-05-04):** Codex is the unbiased reviewer because it has no investment in having authored the code. I can't claim my work is "sound" before Codex sees it — that claim itself is the bias trap. My job is to do the rigorous trace-through, ship the best work I can, and then let Codex assess without pretending I already know it's good. If Codex finds a regression, that's the system working as designed, not a failure of intent — but it is still a signal that my pre-ship trace-through wasn't deep enough, and the trace-through standard goes up.

What I do NOT do: tell the user "this is sound, Codex is just a polish pass." That phrasing reintroduces the bias the workflow is built to remove.

After a multi-fix session, before I tell the user "all done," I must run the following checks against my own changes. These are calibrated to specific failure modes the user has already caught:

1. **Cross-fix interaction check.** For each pair of fixes, ask: "does fix B trust the data from fix A correctly, or does fix B bypass the safeguard fix A was supposed to install?" Specifically — if I add a verified flag in fix A and a harvest function in fix B, fix B must consume the flag. Don't trust that "I just wrote it, of course it's consistent."

2. **Author-blind reread.** After finishing edits, read the final state of each modified file *as if I were Codex* — no investment in having authored it. Look for: assumptions, partial coverage, sentinel-value leakage, contracts not enforced.

3. **Schema parity check.** If I apply the same fix pattern to multiple services, open the Postman/swagger source for each and confirm the assumed shape matches before trusting that the fix transferred. Drift between services is the default expectation in this codebase, not the exception.

4. **Re-grep my own assumptions.** If I wrote an earlier message saying "X is now an array" or "Y has shape Z," and a later fix sets X to a scalar or assumes Y has a different shape, that's the bug. Check the conversation transcript for my own prior claims before shipping the fix.

5. **Class-of-bug check, not ticket-of-bug check.** When closing a finding, ask: "is this a one-off or a pattern? Where else would the same pattern apply?" If the answer is "5 other harnesses might have the same issue," port the fix or explicitly note the deferral.

5a. **Generalization footprint check.** When the fix broadens a matcher, lookup, alias set, or any "accept more inputs" structure, ALSO ask: "does this broaden over-match in scopes I didn't intend?" Specifically — if data flows through this structure in a loop over MULTIPLE keys/fields, the broadened set is consulted for each one, and contamination across keys becomes the failure mode. Test the fix with **multi-key calls** that match the real call site, not single-key smoke tests. (2026-05-04 incident: extending a universal alias list `(bank_id, card_id, customer_ref_id, …)` made every requested ID_HARVEST key match every alias, so a Customer setup containing only `customer_ref_id` populated `customerRefId`, `customerId`, AND `draftId` with the same value. Single-key test missed it; per-key isolation was the actual fix.)

6. **Dry-run after the change, not just before.** A pre-change dry-run validates the diagnosis. A post-change dry-run validates the fix. Both are needed. `ast.parse` only tells you the syntax compiles, not that the behavior is correct.

7. **Audit cadence.** For sessions with 4+ fixes, run Codex (or equivalent) after every batch of 3-4 fixes, not at the end. Lets context inform follow-up fixes while it's still hot. The fix pass on 2026-05-04 batched all 13 then audited; that flow produced 4 direct regressions Codex caught and I had not.

**Why this matters:** The user explicitly opted into a Codex+Council review architecture because Claude alone was not catching enough. Treat every Codex finding as a data point about my own review quality, not just about the code. When Codex finds something I should have caught, save the failure mode (like this memory) instead of just fixing the bug.
