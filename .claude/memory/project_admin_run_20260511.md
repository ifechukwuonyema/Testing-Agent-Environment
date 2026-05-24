---
name: Admin Runner BNK-PRV-01 Fix Session 2026-05-11
description: 4 BNK-PRV-01 engine misclassification fixes shipped; 5 new PASSes including ONB-10-012
type: project
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
Fixed 4 BNK-PRV-01 engine misclassifications in `postman_hybrid_admin_runner.py`.

**Root cause:** v2 mutation engine was overriding mutations the runner classifier had already applied:
- `drop_field` (top-level) is a no-op on nested keys → `drop_nested` scenarios got wrong mutation
- `drop_filter_field` overrode `set_field country=XX` → invalid country scenarios sent valid country

**Fixes:**
1. Added `"set_field"` and `"drop_nested"` to `ENGINE_RUNNER_PRESERVED` — engine must not re-mutate when runner classifier already chose the exact field+value or nested path.
2. TC-013 `duplicate_bank_code_rejected`: classifier now returns `{"action": "as_is"}` to send static `bankCode: "EXB001"` and trigger a 409 duplicate conflict.
3. `rotate_bank_uniqueness` skipped for `duplicate_bank_code_rejected` scenario.

**Country constraint:** `country: "NG"` is the only valid value.

**Result:** 5 new PASSes including ONB-10-012.

**How to apply:** When adding new classifiers that set specific field values or target nested paths, add the action type to ENGINE_RUNNER_PRESERVED.
