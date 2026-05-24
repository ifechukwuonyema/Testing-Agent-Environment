# Kardit API Testing Platform — Project Context

## What This Is

Kardit is a fintech microservices platform. This repo contains the full API test harness: Postman-hybrid test runners, scenario packs (test cases), report generators, a sequential chain orchestrator, and all accumulated test findings.

Anyone who clones this repo and runs the harness will be testing the same live platform. This file gives your AI assistant the full context so it can assist without re-learning from scratch.

---

## Platform Architecture

### 8 Microservices

| Service | Port | Role |
|---|---|---|
| Bank | 8080 | Bank onboarding, affiliate approval, partnership management |
| Affiliate | 8081 | Affiliate onboarding, KYC, partner relationships |
| Customer | — | Customer lifecycle, search, archived status |
| Cards | 8082 | Card issuance, fulfillment, lifecycle, PIN, limits |
| Transactions | — | Transaction query, export, volume analytics |
| Batch | — | Bulk file upload, validate, submit, download |
| Notifications | — | Notification delivery (service-wide broken as of last test) |
| Admin | — | Onboarding case management, bank management |

### ID Format Ecosystem

| Service | ID Format | Notes |
|---|---|---|
| Bank | UUID | e.g. `e9686a3b-...` |
| Affiliate | `AFF-<32hex>` | e.g. `AFF-9F6EDBBE20DD4C6B97D0B720676506E1` |
| Customer | `CUS-<32hex>` | `CUST-ACME-XXX` fixtures are wrong — 404 |
| Cards | UUID | cardId is UUID |
| Transactions | Dual | `/query` returns `TXN-2026-XXXXX`; GET accepts `TRA-<32hex>` only — same entity |
| Batch | UUID | batchId is UUID |
| Onboarding cases | `APR-xxx` or `PRQE-xxx` | APR = auto-approved; PRQE = PENDING_BANK_APPROVAL |

### Auth Stack

- IAM URL: `https://hasham.platform.dev.chamsswitch.com/gateway/token`
- Cards (port 8082): 2-layer — Bearer via IAM + ECDSA-SHA256 signing on 19 signed endpoints
- AFF-format affiliateId on port 8082 (not UUID)

### Platform-Wide Defect — AUTH BYPASS

**Every service accepts requests with no Authorization header → returns 200.** This is the single biggest blocker across all 8 services. Fixing this would add 20-40pp to every service's pass rate. Auth middleware is missing platform-wide across all routes.

---

## Current Test State

### Pass Rate Leaderboard (as of 2026-05-24)

| Service | Pass Rate | TCs | Last Run | Ceiling | Primary Blocker |
|---|---|---|---|---|---|
| Transactions | ~99%+ | 286P/0F/1B | 2026-05-18 | ~99.6% | Auth bypass (not-impl) |
| Cards | ~99%+ ceiling | ~880 | 2026-05-23 | ~99%+ | 11 backend defects |
| Batch | 80.6% | 252 | 2026-05-21 | ~95%+ | Auth bypass (31F all) |
| Admin | 74.5% | 153 | 2026-05-13 | ~90% | Auth bypass + tenant leakage |
| Affiliate | 66.4% | 455 | 2026-05-13 | ~99.3% | Auth bypass (77F) |
| Customer | 66.7% | 117 | 2026-05-18 | ~94% | Auth bypass + validation gaps |
| Bank | 48.9% | 184 | 2026-05-14 | ~80% | Auth bypass + PERSIST defect |
| Notifications | 10.8% | 186 | 2026-05-08 | unknown | Service-wide broken (5xx) |

---

## File Layout

```
Kardit/
├── CLAUDE.md                       ← this file
├── harnesses/                      ← all 8 runners + chain orchestrator
│   ├── postman_hybrid_bank_runner.py
│   ├── postman_standalone_affiliate_v2.py
│   ├── postman_hybrid_customer_runner.py
│   ├── cards_e2e_runner.py
│   ├── postman_hybrid_transactions_runner.py
│   ├── postman_hybrid_batch_runner.py
│   ├── postman_hybrid_notifications_runner.py
│   ├── postman_hybrid_admin_runner.py
│   └── run_sequential_chain.py     ← chain orchestrator (Bank→Affiliate→Customer→Cards→Transactions→Batch→Notifications→Admin)
├── reports/                        ← DOCX + YAML test reports
│   ├── *.docx                      ← per-service backend ask documents
│   └── *.yaml                      ← raw run reports
└── .claude/
    └── memory/                     ← individual memory topic files (Claude Code picks these up)

Downloads/   (outside repo, on the test machine)
├── MainSwagger.txt                 ← canonical OpenAPI 3.0.1 contract — source of truth for all 8 services
├── *.json                          ← per-service Postman collections (test packs)
└── _audit_*.py                     ← audit scripts
```

---

## Harness Architecture

### Runner Type
Postman-Hybrid: uses Postman collection as source for endpoint definitions, base request bodies, and scenario names. The Python harness mutates payloads, manages pre-flight state provisioning, and classifies results.

### Classification: 3 States Only
- **PASS** — response status code matches `expected_result` in scenario
- **FAIL** — mismatch; tagged `mutation_misfire` if mutation didn't actually fire
- **BLOCKED** — pre-flight phase failed; TC couldn't execute

### Mutation Engine
- v2 engine: reads scenario name, extracts clause, selects mutation action automatically
- v1 handler: fallback for scenarios v2 misclassifies
- `FORCE_V1_PLAN_SCENARIOS` constant: bypass v2 for known misclassification cases (e.g. `underage_customer_rejected_where_policy_requires`)
- Mutation MUST fire before any rotation/uniqueness logic — `rotate_*_uniqueness` must run BEFORE mutation, never after
- Pre-script runs ONLY on POST requests — never on GET endpoints

### Pre-flight Phases
Each runner has numbered phases that mint/probe live entities before test execution:
- Phase 0a: IAM token acquisition
- Phase 0b: seed entity lookup
- Phase 0c/d/e/f: service-specific entity minting and pool building
- Phase failure → downstream TCs are BLOCKED

### Key Runtime Patterns

| Pattern | How It Works |
|---|---|
| NO_AUTH sentinel | `override_headers["Authorization"] = "__NO_AUTH__"` → deleted at execute() time |
| BANK_TOKEN | `__BANK_TOKEN__` resolved to bank-scoped Bearer at runtime |
| GET-after-POST probe | Diagnostic — converts ambiguous BLOCKED → deterministic attribution; never upgrades result to PASS |
| Live ID probe | When fixture IDs 404, probe live with swagger-format ID before declaring endpoint broken |
| TC_REQUEST_ID_OVERRIDE | Pin specific IDs 1:1 to named TCs when pool IDs are stale |
| ENUMERATED_POOLS guard | When Phase 0f1 live-enumerates pools, ACTIVE.txt merge must skip those pools entirely |
| Override URL cardId pop | After extracting path vars from override URL, always `pop("cardId")` — live pool cardId is authoritative |
| Stale specialty pool probe | Probe ACTIVE.txt pools live before execution; drop cards no longer in expected state |

### State-Machine Endpoints (Critical)
Endpoints that advance entity state (validate, submit, activate, approve) need **per-TC entity minting**. Sharing one entity causes fixture exhaustion — TC#1 burns the state, TC#2+ get 409.

Gate per-TC provisioning on: `plan["action"] not in ("unknown_id", "set_path_var")`.

Route "wrong state expected" scenarios to pre-provisioned IDs, not fresh mints.

---

## Service-Specific Context

### Bank
- Fixture pool: 7-key `bank_fixtures_v2.json` (suspend_pool, block_pool, approve_pool, reject_pool, part01_pool, already_approved_pool, already_rejected_pool)
- Phase 0d: early-return if SUSPEND+BLOCK pools pre-loaded
- Duplicate-decision: route to already_approved/rejected pools, never fresh PENDING pool
- `GET /api/v2/banks/{bankId}/dashboard` is in MainSwagger but backend v2 is not ready — do NOT add to test pack until user signals v2 is live
- **D-BNK-PERSIST-1**: new IDs also 404 on approve/suspend/block — not just stale fixtures
- **D-BNK-AUTH-1**: state-validation layer bypass

### Affiliate
- Two observable states: ACTIVE (provisioned) or BLOCKED (IAM revocation) — no "pending" state observable via API
- `affiliate_not_approved_rejected` scenarios → BLOCKED (cannot seed or reset BLOCKED via HTTP)
- Canonical affiliate UUIDs: `a7d5929b-cba8-4e97-8985-2ce1d9fc91c3`, `b80acd18-...`
- Decision body: only `decision`, `reviewerNotes`, `decisionReason` — **never include `selectedBanksApproved`**
- **D-AFF-1**: auth bypass (~40F per run; fixing = +19.3pp)
- **D-AFF-5**: 19 response-shape fields missing on /profile + /kyb-snapshot

### Customer
- ID format: `CUS-<32hex>` only — `CUST-ACME-XXX` fixtures are dead (404)
- `rewrite_customer_search_criteria()` forces body to `{}` for POST /search — bypass for cross-field validation TCs using `_idtype_idnumber_cross_field` flag
- `idType`/`idNumber` must be present in Postman base for search TCs
- **D-CUS-SEARCH-1**: cross-field co-validation not enforced backend-side
- **D-CUS-AUTH-1**: auth bypass + scope enforcement missing

### Cards (port 8082)
- 2-layer auth: Bearer (IAM) + ECDSA-SHA256 signing on 19 endpoints
- Card state lifecycle: PENDING_ACTIVATION → ACTIVE → FROZEN → TERMINATED (CTERM is one-way; run LAST)
- FUL-02 refresh eligibility: determined by list-level `fulfillmentStatus=PERSONALIZING`, NOT bureauStatus from /fulfillment/status endpoint
- CARD-19 activate happy paths: need PENDING_ACTIVATION card owned by canonical affiliateId (`a7d5929b-...`); wrong-affiliate cards 404 even with correct body
- ~115 ACTIVE VIRTUAL cards are orphaned (empty customerId/maskedPan) — unusable for limit requests; Phase 0g filters these
- `SKIP_BULK_TERMINATE_SC09=True` by default
- **D-CARDS-TENANT-1** CRITICAL (20F): tenant isolation missing
- **D-CARDS-AUTHZ-2** CRITICAL (1F): authorization bypass
- **D-CARDS-VALIDATION-1** High (16F): input validation gaps
- **D-CARDS-AUTH-1** Medium (16F): auth middleware missing on some endpoints
- GET /auth/permissions: completely open — returns 200 on all auth scenarios

### Transactions
- Dual ID population: /query returns `TXN-2026-XXXXX`; GET /transactions/{id} accepts `TRA-<32hex>` only — same entity, round-trip always 404
- Swagger is catastrophically permissive: 0 required body fields, 0 enum constraints, 0 format/pattern declarations
- /export end-to-end is stubbed (not implemented)
- All read endpoints accept unauthenticated requests with 200
- `SCOPE_TC_IDS` env var: currently scoped to specific TCs when doing targeted reruns

### Batch
- Real row/size limits: 100 rows max, 5MB max per file
- Validated pool IDs go PROCESSING after submit — single-use per run; ~35 IDs consumed per run; need fresh IDs before each run
- Seed IDs: `AFFILIATE_ID_SEED = "AFF-9F6EDBBE20DD4C6B97D0B720676506E1"`, `PROCESSING_BATCH_ID = "952480b6-61d2-4299-a6ca-430dce7a316c"`, `COMPLETED_BATCH_ID = "ef57c562-4a98-4c46-b8ec-13e36a1a3ebe"`
- **D-BATCH-AUTH-1**: all 31 FAILs = platform auth bypass
- **D-BATCH-TOKEN-1**: BATCH-07 crashes the token handler

### Notifications
- 5 endpoints, service-wide broken — all FAILs are 5xx
- Do not file backend asks until service is fundamentally fixed
- Exclude from ceiling pass-rate projections

### Admin
- BACKEND_SUBMITTED_POOL: one-time-use cases (~20 cases = 1 full run); need fresh batch from backend before each run
- Decision body: `decision`, `reviewerNotes`, `decisionReason` only — never `selectedBanksApproved`
- Canonical bank UUIDs for provision: `e9686a3b-...` and `96da6f8e-...`
- Country constraint: `country: "NG"` is the only valid value
- Ghost banks created during auth testing: TestBank-8892CABD, TestBank-046D8AA7, TestBank-FFBBB2BE, TestBank-164DBB1D, TestBank-B4BEFF67
- **D-ADMIN-AUTH-1**: all `/api/v1/admin/*` endpoints return 200 with no auth (confirmed)
- **D-ADMIN-TENANT-1**: GET /admin/onboarding/cases/{caseId} returns 200 for foreign-tenant admin — cross-tenant data leak
- **D-ADMIN-PROV-1**: provision DTO rejects `selectedBankIds`

---

## TC Pack Rules (Hard Rules)

| Rule | Value |
|---|---|
| Hard floor | 30 TCs per endpoint |
| Preferred range | 30–35 TCs per endpoint |
| Hard ceiling | 40 TCs per endpoint |
| Under 30 | Author new scenarios |
| Over 40 | Dedup by meaning — never bulk-delete |

- **Never delete a scenario to make the runner happy** — fix the runner or file a backend ask instead
- Scenarios represent team guidance, not just runner inputs
- Only delete if the endpoint is removed from MainSwagger.txt (user must explicitly sign off)
- DO NOT delete scenarios just because MainSwagger.txt is silent on a constraint

---

## Report & Documentation Rules

- **DOCX format**: render YAML schema verbatim — no narrative summaries, no paraphrasing
- **Test case columns**: Endpoint | TCID | Scenario | Description | Precondition | Expected Result (6 columns, tabular only)
- **Breakdown format**: per-endpoint deep sections — cluster table + response codes + backend ask per endpoint + cross-endpoint patterns; never stop at high-level summary; list every TC ID + scenario by name; never truncate
- **Invalid ID Inventory**: when fixtures have wrong-format IDs, add a side-by-side table (invalid | valid | discovery method) to backend asks DOCX
- **After every report**: review and update memory files with new findings

---

## Workflow Rules (Critical — Follow These Every Run)

1. **Kill before re-run**: always `taskkill /F /IM python.exe /T` before launching any new runner; two concurrent runners race on backend state
2. **Swagger source of truth**: always use `MainSwagger.txt` — per-agent swagger.json files may be stale
3. **Postman collection updates**: when given a new PMC, update the in-tree collection in place — don't swap POSTMAN_PATH
4. **Manual chain validation first**: when pre-flight has been failing for days, validate end-to-end manually before adding workaround logic
5. **Rotation before mutation**: `rotate_*_uniqueness` fires BEFORE mutation — post-mutation rotation overwrites invalid values, producing silent-accept false PASSes
6. **Live ID probe**: when fixtures return 404, probe live with swagger-shaped ID format before declaring the endpoint broken; patch KNOWN_GOOD_FALLBACK with discovered value
7. **ID acquisition order**: use service's query endpoint to get real IDs; don't hardcode or POST-mint unnecessarily
8. **GET-after-POST probe**: diagnostic tool only — converts ambiguous Cluster-C BLOCKEDs to deterministic attribution; never upgrade BLOCKED → PASS except in explicit state-effect carve-out
9. **State-cascade endpoints**: need rotating fixtures — sharing one seeded entity causes fixture exhaustion; ask backend for rotating fixtures or per-TC reset
10. **Code delivery workflow**: Draft → Codex review → Council triage → Update → Self-review (5-stage) for any logic-touching change before shipping

---

## Open Backend Defects (Summary)

### Platform-Wide
- **D-PLATFORM-AUTH-1** CRITICAL: all 8 services accept unauthenticated requests with 200; auth middleware missing platform-wide

### Bank
D-BNK-PERSIST-1 (approve/suspend/block 404 on new IDs), D-BNK-AUTH-1 (state-validation bypass), D-405-1 (405 on valid methods), D-Z2-1/Z2-2 (response schema drift)

### Affiliate
D-AFF-1 (auth bypass, +19.3pp if fixed), D-AFF-2 (audit endpoints missing), D-AFF-3 (repeatable happy-path), D-AFF-4 (pipeline ordering), D-AFF-5 (19 response-shape fields missing), D-AFF-SCOPE-1, D-AFF-SCOPE-2, D-AFF-ACCEPT-1

### Customer
D-CUS-SEARCH-1 (cross-field co-validation not enforced), D-CUS-AUTH-1 (auth+scope), D-CUS-AFF-1 (affiliate pre-flight 400)

### Cards
TENANT-1 CRITICAL (20F), AUTHZ-2 CRITICAL (1F), TENANT-2 High (10F), VALIDATION-1 High (16F), 500-1 High (6F), BUSINESS-1 High (4F), BULK-1 High (30B), AUTH-1 Medium (16F), STATEMACHINE-1 High, SCHEMA-1/2 Low

### Transactions
D-TRX-AUTH-1 (all read endpoints accept unauth), D-TRX-EXP-1 (export silent-accepts invalid), D-TRX-EXPSTATE-1 (download no state gate), D-TRX-VOL-1 (volume invalid scope), D-TRX-PAG-1 (pagination gaps), D-TRX-IDS-2 (dual ID format, round-trip 404)

### Batch
D-BATCH-AUTH-1 (31F platform auth), D-BATCH-TOKEN-1 (BATCH-07 crash), CSV/file validation gaps

### Admin
D-ADMIN-AUTH-1 (full bypass on all admin routes), D-ADMIN-TENANT-1 (tenant scope leakage), D-ADMIN-PROV-1 (selectedBankIds DTO gap)

---

## Not Currently Implemented (Exclude from Backend Asks)

- Auth/auth pipeline enforcement (platform-wide — being built separately)
- Audit/event-history endpoints
- Notifications service (fundamentally broken, not just missing auth)

---

## Audit Scripts

- `Downloads/_audit_generic_per_tc.py` — 10-dimension deep audit across all 8 services via CONFIGS dict; uses most-recent report auto-detection
- `Downloads/_audit_transactions_DEEP_20260508.py` — reference implementation of 10-dimension audit

### 10 Audit Dimensions
D1 endpoint contract, D2 path-var format, D3 missing required body, D4 type compliance, D5 enum compliance, D6 additionalProperties, D7 mutation meaningfulness, D8 status verdict, D9 response schema drift, D10 response required fields

When to run deep audit: standard audit clean but FAILs remain unexplained.

---

## Chain Test

Sequential order: **Bank → Affiliate → Customer → Cards → Transactions → Batch → Notifications → Admin**

IDs flow downstream — bankId seeds affiliateId, affiliateId seeds customerId, etc. Cards pass rate improves significantly when real upstream affiliateId is used (vs hardcoded seed).

Orchestrator: `Kardit/harnesses/run_sequential_chain.py`

Artifacts produced per chain run: 8 per-service findings DOCX + chain summary DOCX + chain report YAML + daily rollup note + cross-service chain memory + MEMORY.md update.

---

## Setting Up Memory for Claude Code

If you want Claude Code to have persistent memory (not just this file), run the setup script after cloning:

```powershell
# Copy memory files to Claude Code's project memory location
$target = "$env:USERPROFILE\.claude\projects\" + ($PWD.Path -replace '[:\\]', '-') + "\memory"
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item ".claude\memory\*" $target -Force
Write-Host "Memory files copied to $target"
```

For other LLMs: paste this entire CLAUDE.md as your system prompt or project context. All context needed is contained here.
