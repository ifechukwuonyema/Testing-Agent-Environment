---
name: Mutation Audit Session 2026-05-10
description: Cross-service mutation correctness audit — fixed 6 distinct pagination/filter mutation bugs across 8 runners + audit module + engine; all fixes verified across 7 services
type: project
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
User caught a real runner-quality issue 2026-05-10: pagination + filter mutation scenarios were silently no-op'ing in many cases, producing false silent-accept FAILs in prior reports. After audit + patch, **all 67 fix-relevant TCs across 7 services now correctly mutate the backend-read field**, and prior published B_silent_accept counts were inflated by ~30+ TCs across services.

## Bugs found and fixed (2026-05-10)

| Tag | Bug | Fix location |
|---|---|---|
| **A** | TRX `invalid_<field>_filter_rejected` appended `<field>_filter=` to URL instead of overwriting body filter | `Downloads\_mutation_audit.py` — moved rule above conflicting catch-all |
| **B** | TRX `invalid_status_filter_rejected` falsely matched `_status_` observational rule | Same — moved above the `^(\w+)_status_*` observational catch-all |
| **C/E** | Bank/Batch/Notifications/Affiliate `set_field` no-op'd on GET endpoints; request sent unchanged → backend returned 200 → false silent-accept | All 4 runners' engine `set_field` block now falls back to `smart_set_query` when body has no match |
| **D** | Bank/Notifications/Affiliate filter mutations lowercased camelCase fields; .NET query-param parser is case-sensitive → backend ignored | All 3 runners' regex now matches against `scenario` (original case) |
| **1** | TRX `pagination_page_zero_rejected` appended `?page=0` instead of overwriting `pageNumber=1` | `Kardit\harnesses\mutation_engine.py` — added `_paginator_variants()` helper |
| **2** | `page_two_success` ran as_is and never advanced to page 2 | `_mutation_audit.py` reorder + `mutation_engine.py` page_two/page_one edits + 5 v1-classifier explicit branches |

**Zero misfires** detected across 1900 TCs in the post-patch runs.

## Files patched

1. `Downloads\_mutation_audit.py`
2. `Kardit\harnesses\mutation_engine.py`
3. `Kardit\harnesses\postman_hybrid_bank_runner.py`
4. `Kardit\harnesses\postman_hybrid_batch_runner.py`
5. `Kardit\harnesses\postman_hybrid_transactions_runner.py`
6. `Kardit\harnesses\postman_hybrid_customer_runner.py`
7. `Kardit\harnesses\postman_hybrid_admin_runner.py`
8. `Kardit\harnesses\postman_hybrid_cards_runner.py`
9. `Kardit\harnesses\postman_hybrid_notifications_runner.py`
10. `Kardit\harnesses\postman_standalone_affiliate_v2.py`
