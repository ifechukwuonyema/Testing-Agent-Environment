---
name: feedback_kill_before_rerun
description: Always kill active runner processes before launching a new batch/test run
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c5e9fedc-d329-4c60-8f32-02637a0c5ac0
---

Always run `cmd.exe /c "taskkill /F /IM python.exe /T"` before launching a new test runner. Never start a new run while a previous one is still alive.

**Why:** Two concurrent runners race on backend state, consume shared seeds simultaneously, and produce conflicting reports. User explicitly called this out 2026-05-19.

**How to apply:** Before every `python postman_hybrid_batch_runner.py` (or any runner) call, issue the taskkill command first. No exceptions.
