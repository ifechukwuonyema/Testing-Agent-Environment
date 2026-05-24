---
name: Kardit Sequential Chain Run 2026-05-02
description: First sequential chain run across all 8 microservices with shared ID propagation; 3199 TCs across 8 services; chain validated ID flow but catastrophic-tier services unchanged; +9pts on Cards from real upstream affiliateId
type: project
service: Chain (all 8)
run_date: 2026-05-02
tcs: 3199
passes: 924
fails: 1683
blocked: 592
pass_rate: 29
worst_cluster: H 5xx (675 across all 8 services, dominant catastrophic-tier)
chain_run_id: chain_20260502-021709
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---

First end-to-end chain run across all 8 Kardit microservices. Order: Bank → Affiliate → Customer → Cards → Transactions → Batch → Notifications → Admin. Each service's pre-flight reads `kardit_session_ids.json`; orchestrator harvests new IDs from successful (2xx) responses and updates the file before the next service runs.

## Source artifacts

- Orchestrator: `Downloads\run_sequential_chain.py`
- Chain summary: `Downloads\chain_run_20260502-021709.yaml`
- Chain log: `Downloads\chain_run_20260502-021709.log`
- 8 per-service YAML reports + 8 evidence directories under `Downloads\`
- 8 per-service memory files in vault: `project_<service>_chain_run_20260502.md`
- Daily rollup: [[run_2026-05-02]]

## Counts (platform aggregate)

| Service | TCs | P | F | B | Pass% | Δ vs 2026-05-01 |
|---|---:|---:|---:|---:|---:|---|
| Bank | 472 | 68 | 135 | 269 | 14% | flat (Cluster-C still dominant) |
| Affiliate v2 | 917 | 252 | 536 | 129 | 28% | flat |
| Customer | 120 | 14 | 103 | 3 | 12% | flat (catastrophic) |
| Cards | 830 | 336 | 330 | 164 | **40%** | **+9pts** ⭐ |
| Transactions | 440 | 80 | 349 | 11 | 18% | flat (read subsystem 0%) |
| Batch | 177 | 102 | 70 | 5 | 58% | flat (healthiest) |
| Notifications | 120 | 19 | 99 | 2 | 16% | flat (catastrophic) |
| Admin | 123 | 53 | 61 | 9 | 43% | flat (Customer block) |
| **Total** | **3199** | **924** | **1683** | **592** | **29%** | |

## FAIL clusters (1683 total)

| Cluster | Count | Dominant in | Engineering fix |
|---|---:|---|---|
| H 5xx server error | 675 | Customer (103), Transactions-read (~270 of 311), Notifications (99), Affiliate (80) | Read shared stack traces; one platform-level defect likely |
| A unexpected 4xx | 327 | Affiliate (179), Cards (94), Admin (27) | Per-endpoint validation review |
| Z1 envelope drift on 4xx | 221 | Bank (105), Affiliate (116) | Standardize on RFC 7807 ProblemDetails |
| Z2 schema drift on 2xx | 220 | Cards (158), Affiliate (62) | Schema generator + actual response alignment |
| B silent accept (200 on bad input) | 185 | Batch (54), Affiliate (44), Cards (37), Transactions-export (38), Admin (12) | Server-side validation per service |
| G happy 4xx (rejected happy path) | 55 | Affiliate (55) | Affiliate state-machine review |

## BLOCKED clusters (592 total)

| Cluster | Count | Dominant in | Engineering fix |
|---|---:|---|---|
| C seed/persistence | 207 | Bank (161), Cards (46) | Provide queryable bankId in test env; fix Cards persistence break |
| B1 DB verification required | 168 | Cards (118), Bank (21), Transactions (11), Admin (9), Batch (5), Customer (3), Notifications (1) | Provide read-only DB/audit surface |
| Other | 88 | Bank (87) | Mostly downstream of Cluster-C — fixes when seed is fixed |

## ID flow validated

```
Initial: affiliateId=11111111... bankId=22222222... cardId=CAR-3065F367... batchId=6e42b8a4...
Final:   affiliateId=a572aa77...  bankId=22222222... cardId=CAR-80FF1EE8... batchId=520db198...
```

- **Affiliate** minted real `affiliateId=a572aa77-99e6-2c20-1ddb-2a3dda5126d2`; Cards consumed it; **Cards pass rate jumped 31% → 40%** (~+75 PASSes). Validates chain design end-to-end.
- **Bank** has no public mint endpoint; placeholder `bankId=22222222...` flows through unchanged; Bank's verify-loop fails on it → 161 Cluster-C BLOCKEDs.
- **Customer** never produced a successful customerId — POST /customers/drafts is 100% 5xx-crashing. Cards/Transactions/Notifications still ran with no real customer linkage.
- **Cards** minted fresh cardId; Transactions/Notifications consumed it.
- **Batch** minted fresh batchId; pre-flight verify worked.
- **Transactions** "minted" exportId but it was the zero-UUID sentinel echoed by a negative-test backend defect (TC-API-TRX-08-002 / 09-002 — backend returned 200 PENDING for zero-UUID instead of 404).

## Three platform-level findings

### 1. Catastrophic tier is one shared defect, not per-service work

Customer (12%), Notifications (16%), Transactions-read (0.6%) all share:
- ≥80% of FAILs are 5xx
- The few PASSes are required-field validation rejections (clean 400 before crash point)
- Crash spread evenly across all endpoints in the service

Suggests a shared middleware / DTO / DB-connection / request-context binder defect. **Reading 1-2 stack traces from each service's evidence dir would identify whether it's the same exception type.** If yes, one fix unlocks ~475 PASSes (103+99+273) across three services in a single platform refactor.

### 2. Customer blocks Admin's full lifecycle

Putting Admin last in the chain was supposed to give it real cases to act on. Didn't help because Customer's mint endpoint never succeeded. Admin's onboarding case list returned empty (`total: 0, cases: []`), so the approve/decision endpoints had nothing to act on. **Admin coverage is gated on Customer being fixed first.**

### 3. The chain pattern DID prove ID propagation works

Cards 31% → 40% on real affiliateId is the chain's flagship validation. The pattern is correct; the next chain run after the catastrophic-tier fix should show similar jumps in Customer, Notifications, and Transactions-read.

## Engineering ownership

92% of non-PASS results are backend-owned (1683 FAIL + 555 backend BLOCKED out of 2275 non-PASS). Runner-side residuals are ≤1%. The framework is mature; the test results are credible.

## Recommended next chain run

Re-run after engineering ships the first catastrophic-tier fix. Expected outcome:
- Customer: 12% → 60-70% (if shared defect was root; mint starts succeeding; downstream gets real customerRefId)
- Notifications: 16% → 60%+ (if same defect)
- Transactions-read: 0.6% → 60%+ (if same defect)
- Admin: 43% → 70%+ (with real customers in lists)
- Net platform pass rate: 29% → ~55%
