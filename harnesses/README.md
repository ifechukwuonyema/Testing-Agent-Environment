# Kardit Test Harnesses

Postman-driven hybrid test harnesses for the 8 Kardit microservices, plus the chain orchestrator that runs them sequentially and propagates IDs across services.

Moved here from `Downloads\` on 2026-05-03 per /council recommendation — `Downloads\` was the wrong location for load-bearing test infrastructure.

## Files

| File | Purpose |
|---|---|
| `run_sequential_chain.py` | Orchestrator. Runs all 8 service harnesses in chain order (Bank → Affiliate → Customer → Cards → Transactions → Batch → Notifications → Admin). Reads/writes `Downloads\kardit_session_ids.json` between services so each picks up upstream IDs. Auto-writes per-service memories to the Obsidian vault and produces a chain summary YAML + log. |
| `postman_hybrid_bank_runner.py` | Bank service harness — pre-flight verify-loop on seeded bankId; Cluster-C reclassification active. |
| `postman_standalone_affiliate_v2.py` | Affiliate v2 — improved harness with all in-scope runner defects cleared (B2/B3/canonical-schema/classifier patches/synthetic-array/family-equivalence). Use this, not `postman_standalone_runner.py`. |
| `postman_hybrid_customer_runner.py` | Customer — POST /customers/draft pre-flight; B3 fix for body-field validation. |
| `postman_hybrid_cards_runner.py` | Cards — issuance pre-flight; per-TC requestContext rotation; lifecycle order. |
| `postman_hybrid_transactions_runner.py` | Transactions — query-first pre-flight; 4 path drift remaps. |
| `postman_hybrid_batch_runner.py` | Batch — POST /Batches/card-creation/upload mint pre-flight; rows endpoint Page+PageSize injection. |
| `postman_hybrid_notifications_runner.py` | Notifications — list-first pre-flight; 9 product capabilities classified. |
| `postman_hybrid_admin_runner.py` | Admin — onboarding case discovery pre-flight; synthetic-array B7 fix. |

## How to run

**Single service** (from this directory):
```
py postman_hybrid_<service>_runner.py
```

**Full chain** (8 services in order):
```
py run_sequential_chain.py
```

Outputs land in `Downloads\` (per-service YAML + evidence dirs + chain summary). Per-service memories land in the Obsidian vault.

## Hardcoded paths

The harnesses still reference `Downloads\` for inputs (Postman collection, swagger files, test packs) and outputs (evidence dirs, YAML reports, session store). They run correctly from any location.

## Dependencies

- `Downloads\Kardit.Api.postman.collection.json` — Postman collection (source of truth for request shapes)
- `Downloads\kardit_session_ids.json` — shared session store; harnesses read at pre-flight, orchestrator harvests new IDs after each service
- `Downloads\kardit_runner_kit\` — shared utilities (SessionStore, SchemaValidator, etc.)
- Per-service test packs and swagger files in `Downloads\kardit_<service>_api_test_agent_v3_1\`

## Generators (still in `Downloads\`)

The DOCX/YAML report generators stayed in `Downloads\` for now — they're conceptually adjacent but separately useful:
- `generate_<service>_findings_docx.py` (Bank, Affiliate, Cards, Admin)
- `generate_generic_findings_docx.py` (Customer, Transactions, Batch, Notifications)
- `generate_chain_summary_docx.py`
- `generate_chain_report_yaml.py`

If the test infrastructure consolidates further, these would move here too.
