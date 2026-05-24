---
name: Test-Case Doc 6-Column Format
description: When documenting verified test cases for stakeholder handoff (CTO/PM), use the 6-column tabular format Endpoint, TCID, Scenario, Description, Precondition, Expected Result. No narrative.
type: feedback
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
**Rule**: Stakeholder-facing test-case documents (e.g. CTO handoff Google Doc) use the canonical 6-column tabular format:

| Endpoint | TCID | Scenario | Description | Precondition | Expected Result |

No summaries, no narrative, no findings — just one table per service.

**Why**: User explicitly rejected the 4-column variant (TC ID/Endpoint/Scenario/Expected Result) on 2026-05-08 with "the format you used is not good enough Endpoint,TCID,Scenario,Description,Precondition,Expected Result use this as the format". Description and Precondition columns add the context engineering reviewers need to evaluate test intent without bouncing back to the JSON pack. Endpoint-first ordering groups TCs visually by endpoint when scanning.

**How to apply**:
- Pull `tc_id`, `scenario`, `test_description`, `preconditions`, `expected_result` from each TC entry; pair with the `endpoint` from the parent endpoints[] block.
- Order columns exactly as: Endpoint → TCID → Scenario → Description → Precondition → Expected Result.
- Apply to DOCX, HTML, and Markdown renders consistently — the generator at `Downloads\generate_all_service_test_cases_for_cto.py` is the reference implementation.
- Do not fall back to a narrower format "for brevity" — if a column is empty in the source pack, leave the cell blank rather than dropping the column.
