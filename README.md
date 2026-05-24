# Testing Agent Environment

An AI-assisted API testing harness for the **Kardit** fintech microservices platform. This repo contains 8 per-service test runners, a sequential chain orchestrator, 2,800+ test cases, and a full Claude Code memory export so any contributor's AI assistant hits the ground running with complete project context.

---

## What's Inside

| Layer | What it is |
|---|---|
| **Harnesses** | Python test runners for all 8 Kardit microservices |
| **CLAUDE.md** | Full project context — loaded automatically by Claude Code on repo open |
| **`.claude/memory/`** | 150+ topic files covering run history, defects, workflow rules, and conventions |
| **Reports** | DOCX backend-ask documents generated from test runs |

---

## Microservices Under Test

| Service | Port | Role |
|---|---|---|
| Bank | 8080 | Bank onboarding, affiliate approval, partnerships |
| Affiliate | 8081 | Affiliate onboarding, KYC, partner relationships |
| Customer | — | Customer lifecycle and search |
| Cards | 8082 | Card issuance, fulfillment, lifecycle, limits |
| Transactions | — | Transaction query, export, volume analytics |
| Batch | — | Bulk file upload, validate, submit, download |
| Notifications | — | Notification delivery |
| Admin | — | Onboarding case management, bank management |

---

## Prerequisites

- Python 3.9+
- Access to a running Kardit backend (base URLs configured in each runner)
- A Postman collection per service (test packs) — referenced inside each runner via `POSTMAN_PATH`
- `MainSwagger.txt` — the canonical OpenAPI 3.0.1 contract for all 8 services

---

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/ifechukwuonyema/Testing-Agent-Environment.git
cd Testing-Agent-Environment
```

### 2. Install Python dependencies

```bash
pip install requests
```

### 3. Set up Claude Code memory (Claude users only)

Run once to install the memory topic files into your local Claude Code:

```powershell
.\setup_memory.ps1
```

This copies `.claude/memory/*.md` into Claude Code's project memory path for your clone location. After this, Claude Code will have full persistent context across sessions — not just the current conversation.

> **Other LLMs:** paste `CLAUDE.md` as your system prompt. Everything needed is in that file.

### 4. Configure your runner

Each runner has a config block near the top. Set:

```python
BASE_URL = "http://<your-kardit-host>:<port>"
POSTMAN_PATH = r"path\to\your\service_postman_collection.json"
```

### 5. Run a single service

```bash
python harnesses/postman_hybrid_bank_runner.py
```

### 6. Run the full chain (all 8 services in sequence)

```bash
python harnesses/run_sequential_chain.py
```

Chain order: **Bank → Affiliate → Customer → Cards → Transactions → Batch → Notifications → Admin**

IDs flow downstream — the bankId minted in Bank seeds Affiliate, which seeds Customer, and so on.

---

## Repo Structure

```
Testing-Agent-Environment/
│
├── CLAUDE.md                        ← full project context for Claude Code
├── README.md                        ← this file
├── setup_memory.ps1                 ← one-time memory installer for new cloners
├── .gitignore
│
├── harnesses/                       ← test runners
│   ├── run_sequential_chain.py      ← chain orchestrator (all 8 services)
│   ├── postman_hybrid_bank_runner.py
│   ├── postman_standalone_affiliate_v2.py
│   ├── postman_hybrid_customer_runner.py
│   ├── postman_hybrid_cards_runner.py
│   ├── cards_e2e_runner.py          ← Cards with ECDSA signing
│   ├── postman_hybrid_transactions_runner.py
│   ├── postman_hybrid_batch_runner.py
│   ├── postman_hybrid_notifications_runner.py
│   ├── postman_hybrid_admin_runner.py
│   ├── mutation_engine.py           ← v2 mutation engine (shared)
│   ├── probe.py                     ← shared live-probe utilities
│   └── query_mutator.py
│
├── reports/                         ← generated DOCX backend-ask documents
│
└── .claude/
    └── memory/                      ← Claude Code persistent memory
        ├── MEMORY.md                ← index
        ├── feedback_*.md            ← harness rules and workflow conventions
        ├── project_*.md             ← per-service run history and fix sessions
        ├── reference_*.md           ← backend ask docs, swagger notes
        └── run_*.md                 ← daily rollup notes
```

---

## How the AI Context Works

This repo ships with two layers of AI context:

**`CLAUDE.md` (always active)** — Claude Code reads this automatically when you open the project. It contains the full platform architecture, current pass rates per service, all open backend defects, harness conventions, TC pack rules, and workflow rules. Zero setup required.

**`.claude/memory/` (persistent across sessions)** — 150+ individual topic files that give Claude Code granular memory: each run's findings, each defect's details, each feedback rule's reasoning. After running `setup_memory.ps1`, Claude Code remembers everything across new conversations — not just the current session.

---

## Test Classification

Every test case produces one of three results:

| Result | Meaning |
|---|---|
| **PASS** | Response status matched the expected result |
| **FAIL** | Status mismatch — tagged `mutation_misfire` if the payload mutation didn't fire |
| **BLOCKED** | Pre-flight phase failed; the TC could not execute |

---

## Current Platform State (as of 2026-05-24)

| Service | Pass Rate | Last Run | Primary Blocker |
|---|---|---|---|
| Transactions | ~99%+ | 2026-05-18 | Auth bypass (not yet implemented) |
| Cards | ~99%+ ceiling | 2026-05-23 | 11 confirmed backend defects |
| Batch | 80.6% | 2026-05-21 | Auth bypass (31 FAILs) |
| Admin | 74.5% | 2026-05-13 | Auth bypass + tenant leakage |
| Affiliate | 66.4% | 2026-05-13 | Auth bypass (77 FAILs) |
| Customer | 66.7% | 2026-05-18 | Auth bypass + validation gaps |
| Bank | 48.9% | 2026-05-14 | Auth bypass + persist defect |
| Notifications | 10.8% | 2026-05-08 | Service-wide 5xx |

> **Platform-wide:** all 8 services accept requests with no `Authorization` header and return 200. Fixing auth middleware is the highest-leverage single change across the entire platform.

---

## Before Every Run

Always kill any existing Python runner before starting a new one:

```powershell
taskkill /F /IM python.exe /T
```

Two concurrent runners race on backend state and produce corrupted results.
