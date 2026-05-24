---
name: Generic Per-TC Audit Script (5 services)
description: Pointer to the config-driven 10-dimension per-TC audit script that handles bank/cards/affiliate/batch/admin/notifications via a CONFIGS dict; reusable for any new service by adding a config entry.
type: reference
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
## Script
`C:\Users\Onyema Ifechukwu\Downloads\_audit_generic_per_tc.py`

## What it does
Runs the 10-dimension deep audit (D1-D10 from `feedback_deep_audit_dimensions`) across multiple services with a single CONFIGS dict. Distinguishes runner / pack / swagger / backend bottlenecks for each service.

## Key behaviors baked in
- **Latest-report selection**: uses `max(reports, key=os.path.getmtime)` — NOT lexical sort
- **Drift heuristics** for pack→swagger path resolution: case-insensitive matching, `/drafts` ↔ `/draft`, strip `/api/v1` prefix when pack uses it but swagger doesn't
- **PACK_TO_POSTMAN / PATH_TEMPLATE_OVERRIDE** support per service

## CONFIGS coverage
- Bank, Cards, Affiliate, Batch, Admin, Notifications, Customer, Transactions
- Each entry: pack path, swagger path, postman path, report glob, optional override maps

## When to run
Per `feedback_deep_audit_dimensions`: run AFTER the standard mutation/response audit comes back clean but FAILs remain unexplained. Standard audit clean + non-trivial FAILs = swagger or backend bottleneck; deep audit attributes which.

## Output
JSON sidecar with per-TC dimension verdicts; print summary to stdout.
