---
name: Kardit Harness Relocation 2026-05-03
description: Test harness scripts moved from Downloads to dedicated Kardit\harnesses\ directory; git-versioned; run_sequential_chain.py updated to reference new path in memory writes
type: reference
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
On 2026-05-03 the 9 chain-related Python files were moved out of `Downloads\` into a dedicated, git-versioned location per /council recommendation.

## New location

```
C:\Users\Onyema Ifechukwu\Kardit\
├── .git/                              (git init done 2026-05-03)
└── harnesses/
    ├── README.md                       (describes each harness + how to run)
    ├── run_sequential_chain.py        (orchestrator)
    ├── postman_hybrid_admin_runner.py
    ├── postman_hybrid_bank_runner.py
    ├── postman_hybrid_batch_runner.py
    ├── postman_hybrid_cards_runner.py
    ├── postman_hybrid_customer_runner.py
    ├── postman_hybrid_notifications_runner.py
    ├── postman_hybrid_transactions_runner.py
    └── postman_standalone_affiliate_v2.py
```

## What stayed in Downloads\

- The DOCX/YAML report generators (`generate_*_findings_docx.py`, `generate_chain_summary_docx.py`, `generate_chain_report_yaml.py`) — separately useful, kept where they were for now.
- All test data: Postman collection, swagger files, test packs, kardit_runner_kit, kardit_session_ids.json, evidence directories, YAML reports.
- The harnesses still reference `Downloads\` for those inputs/outputs — paths are absolute and continue to work.

## What changed in the orchestrator

`run_sequential_chain.py` line 254 patched: per-service memory writes now reference `Kardit\harnesses\<script>` instead of `Downloads\<script>`. Future chain runs will produce memories with correct paths.

## What did NOT change

- Obsidian vault location and contents — unaffected; the vault is at `~\.claude\projects\C--WINDOWS-system32\memory\`, completely separate from the harness scripts.
- Existing project memories from 2026-04-30 through 2026-05-02 still reference `Downloads\<harness>.py` in their text — those references are now stale but functionally harmless (Obsidian doesn't follow them as links; they're just descriptive prose).
- Hardcoded `DOWNLOADS = Path(...)` constants inside each harness — the harnesses still read inputs from `Downloads\` and write outputs to `Downloads\`; only their own location changed.

## How to apply

When invoking a harness or the chain runner, use the new path:
```
cd C:\Users\Onyema Ifechukwu\Kardit\harnesses
py run_sequential_chain.py
```

Or with absolute path from anywhere:
```
py "C:\Users\Onyema Ifechukwu\Kardit\harnesses\run_sequential_chain.py"
```

The Saturday 2026-05-09 follow-up should use the new path. The scheduled cron task references `Downloads\run_sequential_chain.py` in its prompt — that's stale but the user's been instructed to ping me for follow-up runs, so the cron mismatch is moot.
