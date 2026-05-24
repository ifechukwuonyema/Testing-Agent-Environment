---
name: Transactions Hybrid Run 2026-05-10
description: v2-engine pilot + 6 harness fixes drove transactions from 19.2% → 69.1% pass rate; dual ID population (TXN-2026-XXX vs TRA-32hex) discovered live
type: project
service: Transactions
run_date: 2026-05-10
tcs: 440
pass_rate: 69.1
worst_cluster: B_silent_accept
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
**Result:** 440 TCs, pass rate 69.1% (up from 19.2% pre-fix on same pack). 0 mutation_misfire after engine v2 wiring.

## 6 harness fixes shipped

1. **normalize_path with `_LITERAL_ID_RE`** — collapses literal UUIDs/PREFIXED-IDs from Postman URLs to `{id}` for pack lookup
2. **PACK_TO_POSTMAN fallback chain** — tries `{id}`-collapsed AND literal-ID-collapsed lookup before giving up
3. **PATH_TEMPLATE_OVERRIDE extended** to customers/export/volume endpoints
4. **KNOWN_GOOD_FALLBACK** probed-live values per ID kind (TRA-, CAR-, CUS-, BAN-, AFF-, TXN-2026-…)
5. **Pre-flight body** changed to `{"filters": {}, "pageNumber": 1, "pageSize": 5}`
6. **`rewrite_query_filters()`** runner-side function — swaps dead Postman placeholder filter values for live read-endpoint-format IDs

## Dual ID population finding

Transactions backend uses **two different ID formats for the same logical entity**:
- `/query` and POST minting return `TXN-2026-XXXXX` (sequential)
- GET read endpoints (`/transactions/{id}`, `/customers/{customerId}`) accept `TRA-<32hex>` only

Fixtures shipped by backend use `TXN-2026-*` — these 404 against read endpoints. Documented as D-TRX-IDS-2.

Ceiling ~98% requires swagger constraint pass + 8 backend asks in `transactions_recommendations_2026-05-10.docx`.
