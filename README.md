# Testing Agent Environment

An AI-assisted API testing harness for the **Kardit** fintech microservices platform. Each of the 8 microservices has its own folder containing its runner, evidence logs, and reports. A shared module handles mutations, probing, and evidence writing. The full Claude Code memory export is included so any contributor's AI assistant starts with complete project context.

---

## Repo Structure

```
Testing-Agent-Environment/
│
├── bank/
│   ├── postman_hybrid_bank_runner.py
│   ├── evidence/                        ← per-run audit logs (git-ignored at run level)
│   │   └── run_20260524_143022/         ← created automatically on each run
│   │       ├── audit.log                ← human-readable per-TC log
│   │       ├── summary.json             ← aggregate stats (P/F/B, pass rate, clusters)
│   │       └── tc/                      ← one JSON file per test case
│   │           ├── BNK-01-001.json
│   │           └── BNK-01-002.json
│   └── reports/                         ← DOCX backend-ask documents
│
├── affiliate/
│   ├── postman_standalone_affiliate_v2.py
│   ├── evidence/
│   └── reports/
│
├── customer/
│   ├── postman_hybrid_customer_runner.py
│   ├── evidence/
│   └── reports/
│
├── cards/
│   ├── cards_e2e_runner.py              ← full E2E runner (Bearer + ECDSA signing)
│   ├── cards_auth_runner.py             ← auth-layer standalone runner
│   ├── evidence/
│   └── reports/
│
├── transactions/
│   ├── postman_hybrid_transactions_runner.py
│   ├── evidence/
│   └── reports/
│
├── batch/
│   ├── postman_hybrid_batch_runner.py
│   ├── evidence/
│   └── reports/
│
├── notifications/
│   ├── postman_hybrid_notifications_runner.py
│   ├── evidence/
│   └── reports/
│
├── admin/
│   ├── postman_hybrid_admin_runner.py
│   ├── evidence/
│   └── reports/
│
├── shared/                              ← shared modules imported by all runners
│   ├── evidence_writer.py               ← evidence + audit log writer
│   ├── mutation_engine.py               ← v2 mutation engine
│   ├── probe.py                         ← GET-after-POST persistence probe
│   └── query_mutator.py                 ← body-aware query field mutator
│
├── chain/
│   ├── run_sequential_chain.py          ← orchestrator: Bank→Affiliate→…→Admin
│   └── reports/                         ← chain-level summary reports
│
├── run_target.py                        ← targeted runner: by service / endpoint / TC-ID
│
├── .claude/
│   └── memory/                          ← 150+ Claude Code memory topic files
│       ├── MEMORY.md
│       ├── feedback_*.md
│       ├── project_*.md
│       └── reference_*.md
│
├── CLAUDE.md                            ← full project context (auto-loaded by Claude Code)
├── README.md
├── setup_memory.ps1
└── .gitignore
```

---

## Evidence & Audit Logs

Every run writes structured evidence into `<service>/evidence/run_<timestamp>/`.

### audit.log — human-readable per-TC log

```
================================================================================
SERVICE : BANK
RUN     : 20260524_143022
================================================================================

[14:30:22] BNK-01-001 | ✓ PASS
  Endpoint  : POST /api/v1/banks
  Scenario  : valid_bank_creation_success
  Mutation  : none (happy path)
  Auth      : Bearer eyJhbGciOiJSUzI1NiIsInR5...[truncated]
  Payload   : {"name": "TestBank-A1B2", "country": "NG", "currency": "NGN"}
  Response  : 201 {"bankId": "e9686a3b-...", "name": "TestBank-A1B2"}
  Duration  : 312ms
  Reason    : status 201 matched expected 201

[14:30:23] BNK-01-002 | ✗ FAIL [B_silent_accept]
  Endpoint  : POST /api/v1/banks
  Scenario  : missing_required_name_rejected
  Mutation  : drop_field | field: name | "TestBank-A1B2" → (removed)
  Auth      : Bearer eyJhbGciOiJSUzI1NiIsInR5...[truncated]
  Payload   : {"country": "NG", "currency": "NGN"}
  Response  : 200 {"bankId": "uuid-...", "name": null}
  Duration  : 289ms
  Reason    : expected 400 (validation rejection), got 200 — silent accept

[14:30:24] BNK-02-001 | ○ BLOCKED
  Endpoint  : GET /api/v1/banks/{bankId}
  Scenario  : valid_bank_fetch_success
  Mutation  : none (happy path)
  Auth      : (none — pre-flight failed before token acquired)
  Payload   : (none)
  Response  : (not sent)
  Duration  : —
  Reason    : Phase 0a IAM token acquisition failed — downstream TCs blocked
```

### tc/BNK-01-002.json — full TC detail record

```json
{
  "tc_id": "BNK-01-002",
  "endpoint": "/api/v1/banks",
  "scenario": "missing_required_name_rejected",
  "verdict": "FAIL",
  "cluster": "B_silent_accept",
  "reason": "expected 400 (validation rejection), got 200 — silent accept",
  "mutation": {
    "action": "drop_field",
    "description": "Drop required field to trigger validation rejection",
    "field_targeted": "name",
    "original_value": "TestBank-A1B2",
    "mutated_value": null
  },
  "request": {
    "method": "POST",
    "url": "http://167.172.49.177:8080/api/v1/banks",
    "auth": {
      "type": "Bearer",
      "header": "Bearer eyJhbGciOiJSUzI1NiIsInR5...[truncated]"
    },
    "headers": {
      "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5...[truncated]",
      "Content-Type": "application/json",
      "X-Tenant-ID": "tenant-001"
    },
    "payload": {
      "country": "NG",
      "currency": "NGN"
    }
  },
  "response": {
    "status_code": 200,
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "bankId": "e9686a3b-cba8-4e97-8985-2ce1d9fc91c3",
      "name": null
    },
    "duration_ms": 289
  },
  "timestamp": "2026-05-24T14:30:23.441882"
}
```

### summary.json — aggregate run stats

```json
{
  "service": "bank",
  "run_ts": "20260524_143022",
  "started_at": "2026-05-24T14:30:22.000000",
  "finished_at": "2026-05-24T14:45:11.000000",
  "total": 184,
  "passed": 90,
  "failed": 48,
  "blocked": 46,
  "pass_rate": 48.9,
  "clusters": {
    "B_silent_accept": 37,
    "H_5xx": 8,
    "C_blocked_dependency": 46
  }
}
```

---

## Shared Modules

| Module | Purpose |
|---|---|
| `shared/evidence_writer.py` | Writes audit.log, summary.json, and per-TC JSON for every run |
| `shared/mutation_engine.py` | v2 mutation engine — maps scenario name to payload mutation |
| `shared/probe.py` | GET-after-POST persistence probe — confirms writes actually persisted |
| `shared/query_mutator.py` | Body-aware query field mutator for POST-body pagination/filter endpoints |

### Using evidence_writer in a runner

```python
from shared.evidence_writer import EvidenceRun, mutation_record, request_record, response_record

run = EvidenceRun(service="bank", evidence_root=Path("bank/evidence"))

run.record_tc(
    tc_id="BNK-01-002",
    endpoint="/api/v1/banks",
    scenario="missing_required_name_rejected",
    verdict="FAIL",
    cluster="B_silent_accept",
    reason="expected 400, got 200 — silent accept",
    mutation=mutation_record(
        action="drop_field",
        description="Drop required field to trigger validation rejection",
        field_targeted="name",
        original_value="TestBank-A1B2",
        mutated_value=None,
    ),
    request=request_record(
        method="POST",
        url="http://host:8080/api/v1/banks",
        headers={"Authorization": "Bearer eyJ...", "Content-Type": "application/json"},
        payload={"country": "NG", "currency": "NGN"},
    ),
    response=response_record(
        status_code=200,
        body={"bankId": "uuid-...", "name": None},
        duration_ms=289,
    ),
)

run.close()
```

---

## Microservices Under Test

| Service | Port | Role | Last Pass Rate |
|---|---|---|---|
| Bank | 8080 | Bank onboarding, affiliate approval, partnerships | 48.9% |
| Affiliate | 8081 | Affiliate onboarding, KYC, partner relationships | 66.4% |
| Customer | — | Customer lifecycle and search | 66.7% |
| Cards | 8082 | Card issuance, fulfillment, lifecycle, limits | ~99%+ |
| Transactions | — | Transaction query, export, volume analytics | ~99%+ |
| Batch | — | Bulk file upload, validate, submit, download | 80.6% |
| Notifications | — | Notification delivery | 10.8% |
| Admin | — | Onboarding case management, bank management | 74.5% |

---

## Prerequisites

- Python 3.9+
- `pip install requests pyyaml jsonschema cryptography`
- Access to a running Kardit backend
- Postman collection (test pack) per service — set `POSTMAN_PATH` in each runner
- `MainSwagger.txt` — canonical OpenAPI 3.0.1 contract

---

## Getting Started

### 1. Clone

```bash
git clone https://github.com/ifechukwuonyema/Testing-Agent-Environment.git
cd Testing-Agent-Environment
```

### 2. Install dependencies

```bash
pip install requests pyyaml jsonschema cryptography
```

### 3. Verify canonical test entities exist

```bash
python seed.py
```

Connects to the shared backend, confirms the canonical bankId and affiliateId used by all runners are present, and writes `shared/session_ids.json`. If you are running against a **fresh** backend instance, use `python seed.py --mint` instead — it mints the entities and prints the IDs to set as env vars.

### 4. Set up Claude Code memory

```powershell
.\setup_memory.ps1
```

> **Other LLMs:** paste `CLAUDE.md` as your system prompt.

### 5. Run a specific test case, endpoint, or service

Use `run_target.py` for targeted execution. It auto-detects which service owns a TC-ID and scopes the runner to only that test.

```bash
# Run a single TC (service auto-detected from TC-ID)
python run_target.py --tc TC-API-ISS-02-001

# Run all TCs for one endpoint
python run_target.py --service cards --api-id API-ISS-02

# Run a full service
python run_target.py --service cards

# Explore before running
python run_target.py --service cards --list                         # all endpoints + TC counts
python run_target.py --service cards --api-id API-ISS-02 --list    # all TC-IDs for that endpoint

# Preview the command without executing
python run_target.py --tc TC-API-ISS-02-001 --dry-run
```

After the run completes, `run_target.py` prints the TC verdict (PASS / FAIL / BLOCKED), HTTP code, and failure cause directly in the terminal, then points to the full YAML report.

**Supported services:** `bank`, `affiliate`, `customer`, `cards`, `transactions`, `batch`, `notifications`, `admin`

### 6. Run a single service directly

```bash
python bank/postman_hybrid_bank_runner.py
```

Evidence logs appear in `bank/evidence/run_<timestamp>/` automatically.

### 7. Run the full chain

```bash
python chain/run_sequential_chain.py
```

Order: **Bank → Affiliate → Customer → Cards → Transactions → Batch → Notifications → Admin**

---

## Before Every Run

```bash
taskkill /F /IM python.exe /T
```

Two concurrent runners race on backend state and corrupt results.

---

## AI Context

`CLAUDE.md` is loaded automatically by Claude Code when you open this repo — full platform context, all defects, all harness rules, no setup required. Run `setup_memory.ps1` once for persistent per-session memory across conversations.
