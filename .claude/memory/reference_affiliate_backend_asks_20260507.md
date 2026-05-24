---
name: Affiliate Backend Asks DOCX 2026-05-07
description: Pointer to the Affiliate backend-asks DOCX filed after run #10; D-AFF-1..4 + ceiling projection
type: reference
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
---
## Pointer

- DOCX: `Downloads\Kardit\reports\affiliate_backend_asks_2026-05-07.docx`
- Generator: `Downloads\generate_affiliate_backend_asks_20260507.py`
- Run baseline: 257 PASS / 127 FAIL / 56 BLOCKED = 58.4% pass-rate

## Asks summary

- **D-AFF-1 (Critical, +19.3pp)**: Auth/RBAC pipeline missing on 9 of 13 endpoints. 85 fails are HTTP 200 returned where 401/403/404 expected.
- **D-AFF-2 (High, +12.7pp)**: Audit-log + persistence read endpoints. 56 BLOCKED scenarios. Suggested: GET /audit-logs, /events, /drafts/{id}, /sessions/{id}.
- **D-AFF-3 (Test-data, +8.9pp)**: Repeatable happy-path support. 39 fails are 409 conflicts on POST /affiliates, /submit, /bank-partnership-requests.
- **D-AFF-4 (Pipeline)**: Auth check must run BEFORE state-conflict check.

## Ceiling

Current 58.4% → ~77.7% (with D-AFF-1) → ~86.6% (with D-AFF-3) → ~99.3% (with D-AFF-2).
