---
name: User API Testing Workflow
description: User conducts API testing using test case documents and Swagger JSON to make actual API calls and verify responses.
type: user
originSessionId: 22c14085-7206-4f95-b584-1dabd79889e5
---
The user conducts API testing with the following approach:
- Uses two files: a test cases JSON (cards_tc.json = draft, cards_TC.json = corrected v4) and Swagger JSON
- Always provides: swagger path, test case path, base URL (host:port), report format file
- No auth required on the test environment (167.172.49.177:8080 used in Cards session)
- Base URL format is bare IP:port (no https, no trailing slash)
- Uses corrected test case file (capital TC) when both versions exist — v4_corrected_paths is authoritative

**Report format:** YAML file with sections: report_metadata, discrepancy_overview, endpoint_summaries, detailed_test_cases
**Report output path:** User's Downloads folder
**After every report:** Review and enhance memory with new findings

**Kardit API patterns confirmed across Cards and Transactions microservices:**
- Date-time format IS validated by ASP.NET model binding → 400 on invalid format (this works consistently)
- All business filters (status, transactionType, bankId, affiliateId, date ranges) ignored → 200 with stub data
- Path parameters ignored — fixed stub data returned regardless of supplied IDs
- No 404 for unknown resource IDs — 200 with stub returned
- No authentication or authorization enforcement in test environment
- Pagination (pageSize) not enforced — response always defaults to pageSize=20
- meta field always null — pagination metadata never populated
- totalRecords frequently inconsistent with actual records in data array
- Duplicate records returned from some list endpoints
- requestContext.requestId validated in Cards (minLength:1 enforced) — not present in Transactions
- Enum fields in Cards validated by model binding; in Transactions body enums (status, transactionType) NOT validated

**Transactions-specific patterns:**
- Export flow broken: POST /export returns exportId="" (empty string)
- Single-item GET (TRX-04) uses collection-style wrapper envelope — wrong response structure
- TRX-06 status param is required but swagger says optional — swagger doc defect
- TRX-09 download endpoint returns JSON status object, not file binary
- Export status inconsistency: poll (TRX-08) returns PENDING, download (TRX-09) returns COMPLETED for same ID

**TC documentation defects found:**
- TRX-01 TC path wrong (missing /transactions suffix)
- TRX-08 and TRX-09 TC paths use /exports/ plural (correct is /export/ singular)
- TRX-05 swagger path documents {query} as path param instead of literal /query

**How to apply:** Pre-fill auth/scope/404/filter/pagination as FAIL for any new Kardit microservice. Also test date-time format as the one reliable validation. Check export flows carefully for empty IDs. Verify swagger paths against actual 200/404 responses before trusting TC paths.
