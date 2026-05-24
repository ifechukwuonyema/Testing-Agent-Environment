---
name: Canonical Test Report DOCX Format
description: All Kardit test execution DOCX reports must follow the YAML schema rendered into DOCX, exactly as defined in Test Report YAML.docx and reportformat.txt
type: feedback
originSessionId: a91892d8-a56c-4238-aeae-b3626879bb7e
---
All test execution DOCX reports for Kardit microservices must follow the canonical YAML-rendered-as-DOCX format defined in `C:\Users\Onyema Ifechukwu\Downloads\Test Report YAML.docx` and `C:\Users\Onyema Ifechukwu\Downloads\reportformat.txt`.

**Why:** This is the user's standard reporting format across all Kardit API testing sessions. Custom narrative formats (executive summary + tables + headings) are NOT acceptable — the user wants the YAML structure preserved verbatim with bold keys and indented values, so the DOCX can be diffed against the source YAML report 1:1.

**Schema (top-level keys, in order):**
1. `report_metadata` — report_date, tester, base_api_url, swagger_source, overall_status, total_endpoints_processed, total_test_cases, passed_test_cases, failed_test_cases, blocked_test_cases
2. `discrepancy_overview.critical_issues[]` — description, endpoint, test_case_ids[], severity, finding_type, cause, result
3. `endpoint_summaries[]` — api, name, endpoint, status, issue_count, issues[] (description, test_case_ids[], cause, result)
4. `detailed_test_cases[]` — test_case_id, scenario, endpoint_feature, precondition, input_data, expected_result, actual_result (description, cause, result), response_code, execution_status, finding_type, severity, defect_id, executed_by, executed_at

**Per-test requirement** (from reportformat.txt last line): include description, cause, and result for each test.

**Reference generator:** `C:\Users\Onyema Ifechukwu\Downloads\generate_cards_report.py`. Reusable pattern — point at any runner's YAML report and regenerate. Uses python-docx, monospaced font (Consolas 10pt), bold keys, indented values, dash-prefixed list items.

**How to apply:** When asked to generate a DOCX test report, render the source YAML in this schema verbatim. Do NOT add executive summary sections, custom tables, or narrative analysis unless explicitly requested as a separate document. The DOCX is a faithful rendering of the YAML, not a re-interpretation.

**Output path:** DOCX reports must be written next to the source YAML, inside the runner's `reports/` folder (e.g. `kardit_cards_api_test_agent_v3_1/.../reports/kardit_cards_test_report_<date>.docx`). NOT at Downloads root. Only chain-level files (`kardit_chain_report.yaml`, `kardit_coverage_report.yaml`) belong at Downloads root because they aren't per-runner.
