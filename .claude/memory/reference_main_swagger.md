---
name: Canonical Kardit swagger is MainSwagger.txt
description: Use Downloads\MainSwagger.txt as the source of truth for which Kardit endpoints exist. Per-agent data\swagger.json files can be stale or partial.
type: reference
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
**Path:** `C:\Users\Onyema Ifechukwu\Downloads\MainSwagger.txt`
**Format:** OpenAPI 3.0.1 JSON (despite the `.txt` extension), Kardit.Api v1.0.

This is the canonical contract for **all 8 Kardit microservices**. The per-agent `kardit_<svc>_api_test_agent_*\data\swagger.json` files are sometimes stale or contain a slimmed-down subset.

**Confirmed authoritative on:** 2026-05-08 (user instruction).

**How to apply:**
- Pack-vs-swagger reconciliation, endpoint-existence checks, method/path verification → query `MainSwagger.txt`.
- Per-agent swaggers can still be referenced when the agent harness loads them at runtime, but treat divergence from `MainSwagger.txt` as the per-agent file being stale.
- If a removed-endpoint candidate appears here, it is in-contract and its scenarios should likely come back.
