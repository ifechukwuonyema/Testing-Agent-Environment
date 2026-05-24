---
name: Affiliate Hybrid Run 2026-05-12
description: 291/476 PASS (61.1%); 3 harness pool fixes (POST /affiliates onboarding chain, submit draft pool, bank-partnership affiliate pool)
type: project
service: affiliate
run_date: 2026-05-12
tcs: 476
passes: 291
fails: 123
blocked: 62
pass_rate: 61.1
originSessionId: f1d2538a-d992-4d2c-b706-84c5fe821fa8
---
Previous baseline: 281/476 (59.0%)

## Three harness fixes shipped

**Fix 1 — Phase 0c onboarding chain pool (POST /affiliates):** D-AFF-FINALIZE-1 resolved by running own onboarding chains. 15 approved cases + 1 submitted case pooled. POST /affiliates → 75% (30/40).

**Fix 2 — Phase 0d submit-ready draft pool (POST /submit):** Phase 0b provides ONE draftId consumed by TC-001; all subsequent submit TCs 409. Phase 0d creates 16 submit-ready drafts. POST /submit → 34% → 54%.

**Fix 3 — Phase 0e partnership affiliate pool (POST /bank-partnership-requests):** Phase 0e creates 20 fresh affiliates via full onboarding chain. POST /bank-partnership-requests → 39% → 50%.

## 123 FAIL root causes
- D-AFF-1: Auth pipeline ordering (~40 FAILs)
- D-AFF-5: Response shape gap (~16 FAILs)
- Missing state validation (~12 FAILs)
- Scope enforcement missing (~8 FAILs)
- Accept-header not enforced (3 FAILs)

## 62 BLOCKED breakdown
- DB/persistence checks: audit_log_created, record_persisted_in_db, etc. → ~35
- URL manipulation: missing/blank path ID → ~10
- Rate limit: rate_limit_boundary_handled → 5

Harness: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\postman_standalone_affiliate_v2.py`
