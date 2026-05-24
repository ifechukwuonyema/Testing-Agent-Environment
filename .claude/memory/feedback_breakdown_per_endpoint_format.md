---
name: Breakdown Format — Per-Endpoint Plain-English with Per-TC Detail
description: Whenever Onyema asks for a "breakdown", default to per-endpoint plain-English sections that list every FAIL and BLOCKED TC by scenario, grouped by cluster within each endpoint
type: feedback
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---

When the user asks for "breakdown" (or invokes the breakdown skill), default to the **per-endpoint plain-English format** described below. The reference artifacts are:
- `Downloads\transactions_recommendations_2026-05-10.docx`
- `Downloads\customer_recommendations_2026-05-10.docx`
- The inline Bank breakdown produced 2026-05-10 in chat (after he corrected me twice)

These all use the same shape. Do NOT stop at the canonical breakdown-skill output (consolidated cluster tables + one-line-per-endpoint + single-fix paragraph). That summary is a starter, not the deliverable.

**Why:** Onyema files per-endpoint backend asks after every run. He needs to read the breakdown like a backend reviewer would — endpoint by endpoint, with the actual scenario names, the actual status codes, what the test was trying to verify, what the backend actually did, and why that's wrong. Plain English (no jargon-only short forms) so he can paste it directly into backend asks DOCX or share with non-test-runner readers. He has corrected me twice when I gave the cluster-summary format instead.

**How to apply — required structure:**

1. **Lead with one line:** service, run timestamp, totals (TCs, P/F/B, pass%).
2. **For each endpoint** (numbered, sorted by api_id or pass-rate ascending), produce:
   - Heading: `## N. API-XXX-NN — METHOD /path`
   - Header line: `**TCs:** total · **P/F/B:** P/F/B · **Pass:** NN.N%`
   - **What it does:** one plain-English sentence describing the endpoint's purpose
   - **What's broken (in plain English):** 2–4 sentences narrating the cluster of issues — what the tests tried to do, what the backend actually returned, and what the implication is. No cluster jargon at this level.
   - **Sub-section per cluster present** (with plain-English title, NOT the cluster code):
     - e.g. "Response shape doesn't match the contract (25 TCs)" instead of "Z2_schema_drift_2xx (25 TCs)"
     - One short paragraph in plain English explaining what the TCs in this group share
     - **Bulleted list of every TC in the group** with format `TC-API-...-NNN — scenario_name — got=NNN, expected=...` (plain language for expected if useful)
     - For unique TCs that diverge from the group pattern, call them out individually
   - **BLOCKED sub-section** (same per-TC list)
   - **Fix:** 1–2 lines naming the backend ask (or runner-side action) that resolves all the FAILs/BLOCKEDs at this endpoint
3. **Close with cross-endpoint patterns** — 4–8 numbered themes that consolidate fixes filed once but resolving multiple endpoints. Each theme: which endpoints, total FAIL count covered, the one-line fix in plain English.

**Plain-English cluster names to use in headings:**
- `Z2_schema_drift_2xx` → "Response shape doesn't match the contract"
- `Z1_envelope_drift_4xx` → "Error response shape doesn't match the contract"
- `B_silent_accept` → "Backend accepts requests it should reject"
- `H_5xx` → "Backend crashes on these inputs"
- `A_unexpected_4xx` → "Wrong 4xx code returned"
- `G_4xx_where_2xx` → "Happy path got rejected"
- `C_seed_404_happy` → "Seeded resource not found on happy path"
- `Other_blocked` (no execution / Postman gap) → "Tests skipped — runner couldn't execute"
- `B1_db_verify` → "Tests skipped — needs database/audit-log verification endpoint"

**What NOT to do:**
- Don't summarize: list every FAIL and BLOCKED TC by ID + scenario.
- Don't use cluster jargon as section headings; use the plain-English equivalents above.
- Don't drop BLOCKED — they're as important as FAIL for backend conversations.
- Don't truncate when the size scares you. Onyema asked twice; ship the full breakdown even if it's 600 lines.
- Don't re-paste evidence verbatim for every TC if 25 TCs share one schema error — explain once, list TC IDs.
- Don't skip the "What it does" / "What's broken in plain English" lines — that narrative is what makes the format usable for him.

**When NOT to use this format:**
- Chain runs with all 8 services: lead with the per-service leaderboard table BEFORE the per-endpoint detail, otherwise the reader can't navigate 50+ endpoints.
- User explicitly says "high-level only" / "just the clusters" / "skip per-endpoint".

**Generator reference:** the DOCX format is produced by scripts in `Downloads\generate_<service>_recommendations_docx.py` (admin/customer/transactions/cards). To produce a Bank version: copy `generate_transactions_recommendations_docx.py`, swap the YAML path + service-specific narrative, redefine `aggregate_backend_asks` with D-BNK-* asks, and re-run. Bank generator drafted 2026-05-10 at `Downloads\generate_bank_recommendations_docx.py` (do NOT auto-run without confirmation — Onyema interrupted the auto-run; he wants inline output by default).
