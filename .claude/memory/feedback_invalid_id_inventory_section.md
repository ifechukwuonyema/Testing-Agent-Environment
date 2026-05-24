---
name: Backend Asks DOCX — Invalid ID Inventory Section
description: When backend ships fixtures with wrong-format IDs, add a side-by-side "invalid vs valid" inventory section to the recommendations DOCX so backend sees the exact mismatch, not just a complaint
type: feedback
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
# Backend Asks DOCX — Invalid ID Inventory Section

**Rule:** When a session surfaces backend-shipped fixture IDs in the wrong format, add a dedicated section (e.g. "4.2 Invalid ID Inventory") to the recommendations DOCX with a side-by-side table:

| Slot | Backend shipped (invalid) | Actually accepted (valid) | Discovery method |
|---|---|---|---|

**Why:** Onyema requested this explicitly on 2026-05-10 ("include to backend that they included invalid ID's and that we had to find ways to retrieve those id's to test state the invalid ID's and the valid beside it"). Listing only the bad ID reads as a complaint; a side-by-side pair makes it actionable — backend can replace the fixture entry directly without re-deriving the format.

**How to apply:**
- Reference implementation: `Downloads\generate_transactions_recommendations_docx.py` (section 4.2 with 10 invalid/valid pairs across TXN/CARD/CUST/BANK/AFF prefixes).
- Always include the **discovery method** column (live probe, /query call, swagger pattern match, prior session) so backend can verify.
- Add a "5 patterns observed" paragraph after the table cataloging what the mismatch reveals (fixture format drift, sequential vs random, fixture not loaded, dual population across endpoints, etc.).
- File matching backend asks: D-{SVC}-IDS-1 (invalid fixtures) and D-{SVC}-IDS-2 (dual population) when applicable.
- Apply to every service DOCX where fixtures were wrong, not just transactions — customer, bank, etc. all had variants of this problem.
