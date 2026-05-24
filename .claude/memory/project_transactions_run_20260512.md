---
name: Transactions Hybrid Run 2026-05-12
description: 275/342 PASS (80.4%); 57 FAIL all backend; auth bypass dominant; TRX-09 export download worst at 56.7%
type: project
service: transactions
run_date: 2026-05-12
tcs: 342
passes: 275
fails: 57
blocked: 10
pass_rate: 80.4
originSessionId: f1d2538a-d992-4d2c-b706-84c5fe821fa8
---
Report: `Downloads\transactions_postman_hybrid_report_20260512-193743.yaml`

## Per-endpoint

| API ID | P | F | B | Total | % |
|---|---|---|---|---|---|
| API-TRX-05 | 36 | 0 | 0 | 36 | 100% |
| API-TRX-06 | 34 | 5 | 1 | 40 | 85.0% |
| API-TRX-02 | 33 | 5 | 1 | 39 | 84.6% |
| API-TRX-08 | 25 | 4 | 1 | 30 | 83.3% |
| API-TRX-09 | 17 | 12 | 1 | 30 | 56.7% |

## 57 FAIL root causes

**Auth bypass → 200 (~39F):** TRX-02/03/04/06/08/07/10/11 — platform-wide D-TRX-AUTH-1.

**TRX-09 export download state enforcement (8F):** pending/processing/failed/expired_export_not_downloadable → 200; download_after_retention_expiry → 200; scope_reuse → 200; malformed_url → 200.

**TRX-07 silent accept (3F):** missing/blank/unsupported_exportFormat_rejected → 200.

**TRX-07 ConnectTimeout (1F):** invalid_bankId_filter_rejected → server hangs.

Harness: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\postman_hybrid_transactions_runner.py`
