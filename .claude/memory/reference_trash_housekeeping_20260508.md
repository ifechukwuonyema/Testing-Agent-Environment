---
name: Trash housekeeping 2026-05-08
description: 72 outdated files moved to Documents\trash\kardit_outdated_2026-05-08\ — 8 per-agent swaggers + 64 obsolete .bak* test packs; today's safety nets preserved
type: reference
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
User directed that MainSwagger.txt is canonical and previous outdated test packs / per-agent swaggers should go to a trash folder.

## What moved (72 files)

**Per-agent swagger.json files (8):** all `kardit_<svc>_api_test_agent_*\...\data\swagger.json` files plus `Kardit\reports\swagger.json`.

**Outdated test-pack .bak files (64):** every `*_test_pack*.bak*` and `notifications_TC.json.bak*` in `Downloads\` from sessions before today.

## What stayed (today's safety nets)

These tagged backups remain in `Downloads\` for rollback safety from today's revert + rebalance session:
- `*.bak-2026-05-08-pre-revert`
- `*.bak-2026-05-08-pre-dedup`
- `*.bak-2026-05-08-pre-author`
- `*.bak-2026-05-08-pre-author-phase2`
- `*.bak-2026-05-08-pre-dashboard-v2-restore`

## Trash location

`C:\Users\Onyema Ifechukwu\Documents\trash\kardit_outdated_2026-05-08\`

## Runner change

All 8 runners in `Kardit\harnesses\` were patched to load `Downloads\MainSwagger.txt` instead of their per-agent `swagger.json` files.
