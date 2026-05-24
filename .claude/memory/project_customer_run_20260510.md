---
name: Customer Hybrid Run 2026-05-10
description: v2-engine wired + live ID probe replaced dead CUST-ACME-XXX fixtures with CUS-32hex; landed at 38.3% with 0 misfires
type: project
service: Customer
run_date: 2026-05-10
tcs: 120
pass_rate: 38.3
worst_cluster: H_5xx_server_error
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
**Result:** 120 TCs, 38.3% pass rate, 0 mutation_misfire.

**Why:** Customer v2-engine pilot. Discovered fixture IDs `CUST-ACME-XXXXX` 404 against GET — backend accepts `CUS-<32hex>` only. Patched `KNOWN_GOOD_CUSTOMER_REF_ID` to `CUS-72F7245C07714B6AB31ABD27B78FC3D5` after live probe.

Most remaining FAILs trace to D-CUS-GET-2 (backend 500 on `kyc.idType` deserialization — finds customer in DB but response builder crashes on idType field that doesn't deserialize to `Kardit.Domain.Models.IdType` enum).

## Harness changes

- `inject_seeded_path_vars` unconditionally seeds `customerRefId`/`customerId`/`id` with canonical CUS-32hex
- `normalize_path` collapses literal IDs in URLs to `{id}` for pack lookup
- v2 mutation engine wired with Wave 1.1 fallback

## Backend asks documented

9 asks in `Downloads\customer_recommendations_2026-05-10.docx`:
- D-CUS-GET-2: kyc.idType deserialization 500 (highest leverage)
- D-CUS-AFF-1, D-CUS-AUTH-1, D-CUS-SEARCH-1 (carried from 2026-05-08)
- D-CUS-IDS-1: fixture IDs in CUST-ACME-* format don't match read endpoint CUS-32hex format
