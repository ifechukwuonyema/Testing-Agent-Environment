---
name: Customer Hybrid Run 2026-05-12
description: 97/117 PASS (82.9%); 17 FAIL all backend; body-before-auth on CUS-01; cross-field validation missing on CUS-02
type: project
service: customer
run_date: 2026-05-12
tcs: 117
passes: 97
fails: 17
blocked: 3
pass_rate: 82.9
originSessionId: f1d2538a-d992-4d2c-b706-84c5fe821fa8
---
Report: `Downloads\customer_postman_hybrid_report_20260512-224739.yaml`

## 17 FAIL root causes

**API-CUS-01 — body-before-auth (5F)**
unauthenticated_rejected, invalid_token_rejected, bank_user_rejected, service_provider_write_rejected, foreign_affiliate_scope_rejected → all 400. Backend validates request body before checking auth.

**API-CUS-02 — auth bypass + silent accept (5F)**
- unauthenticated_rejected, invalid_token_rejected, foreign_scope_filter_rejected → 200 (auth bypass)
- missing_id_number_when_id_type_supplied_rejected, missing_id_type_when_id_number_supplied_rejected → 200 (cross-field validation not enforced)

**API-CUS-03 — auth bypass + lifecycle (7F)**
- unauthenticated_rejected, invalid_token_rejected, foreign_affiliate_scope_rejected, tenant_scope_isolation, forbidden_no_data_leak → 200 (auth bypass)
- archived_customer_policy → 200 (archived customers still served)
- unsupported_accept_header_handled → 200 (406 not returned)

Harness: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\postman_hybrid_customer_runner.py`
