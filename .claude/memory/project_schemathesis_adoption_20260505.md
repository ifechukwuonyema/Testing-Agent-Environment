---
name: Schemathesis Adoption Project
description: Phased rollout of Schemathesis property-based contract testing as a complementary lane to Postman-hybrid runner; pilot on Batch, then high-5xx services (Customer/Notifications/Transactions read); targets H_5xx_server_error and B_silent_accept clusters
type: project
start_date: 2026-05-05
status: phase-0-complete
originSessionId: c5d57ed4-97aa-4fd6-9131-0f65dc2c5d28
---
Plan document: `C:\Users\Onyema Ifechukwu\Downloads\schemathesis_adoption_plan.md`

**Why:** The Postman-hybrid runner is scenario-driven — it tests cases I or Postman thought to write. The dominant FAIL clusters across the 8 services (`H_5xx_server_error` 100% on Customer/Notifications, `B_silent_accept` 11/46 on Admin banks, `Z2_schema_drift_on_2xx` Cards platform-wide) tell us the fuzzer-shaped coverage gap is large. Schemathesis derives tests directly from swagger and exercises legal-but-unexplored input shapes — exactly what surfaces 5xx and silent-accept defects.

**How to apply:**
- Schemathesis runs are **additive**, never replacing Postman-hybrid runs. Both lanes coexist; vault tags fuzz-discovered findings with `discovered_by: schemathesis`.
- Per-service runner module at `~\Kardit\harnesses\kit\schemathesis_runner.py` (Phase 1) emits same YAML schema as Postman-hybrid so all downstream tooling (DOCX generators, breakdown skill, vault rollups) accepts it unchanged.
- Custom check `negative_data_rejection` is required to detect `B_silent_accept` from Schemathesis (built-in checks don't cover this).

**Decisions locked 2026-05-05:**
1. Pilot on Batch first (healthiest service, clean signal), then Customer/Notifications in Phase 2
2. Swagger audit backend ask filed in Phase 0 — see [[reference_backend_swagger_audit_ask]]
3. Vault tagging: `discovered_by: schemathesis` field on existing run schema (default; pending confirmation)
4. Run in parallel with affiliate-onboarding backend fixes — no dependency

**Phase status:**
- Phase 0 (Batch pilot, 1 day) — COMPLETE 2026-05-05 — venv at `~\Kardit\harnesses\.venv-schemathesis\`; Schemathesis 4.17.0 installed; smoke run on Batches tag (6 endpoints, 50 generated cases) produced 10 unique findings; report at `~\Kardit\harnesses\schemathesis_runs\batch_phase0\batch_smoke.xml`; findings appended to swagger audit ask Section 5.1 (3 request strictness gaps, 4 response schema gaps, 4 `text/json` content-type gaps); pipeline mechanics validated
- Phase 1 (custom checks + YAML emission, 2 days) — pending — needs `kit/schemathesis_runner.py` skeleton matching Postman-hybrid YAML schema; custom checks: `negative_data_rejection`, `auth_enforced_on_protected_endpoints`, `correlation_id_present`
- Phase 2 (Customer/Notifications value pilot, 2 days) — pending
- Phase 3 (stateful testing, 3 days) — pending; depends on backend `links` decision
- Phase 4 (chain integration + nightly, 2 days) — pending

**Phase 0 environment notes (Windows-specific):**
- Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` before running Schemathesis CLI (default cp1252 console encoding cannot render the unicode header characters; throws `UnicodeEncodeError` immediately on `display_header`)
- v4.17.0 CLI flag is `--max-examples` (not `--hypothesis-max-examples` as documented in older Schemathesis tutorials)
- Use `--include-tag <TagName>` matching exact swagger tag casing (e.g. `Batches` not `batch`)

**Cluster mapping (Schemathesis check → existing taxonomy):**
| Schemathesis check | Maps to |
|---|---|
| `not_a_server_error` | `H_5xx_server_error` |
| `status_code_conformance` | `G_4xx_where_2xx_expected` + `A_unexpected_4xx` |
| `response_schema_conformance` | `Z2_schema_drift_on_2xx` + `Z1_envelope_drift_on_4xx` |
| `negative_data_rejection` (custom) | `B_silent_accept` |
| `content_type_conformance` | New cluster — currently uncaught |

**Known risks:**
- Loose swagger → noise floor (mitigated by audit ask)
- Catastrophic-tier services may produce 100+ findings each — group tickets by endpoint × shape, not per example
- Stateful mode requires OpenAPI 3 `links`, likely missing platform-wide
- Runtime cost — keep `--hypothesis-max-examples` modest (50–100) for nightly

**Success metrics (4-week look-back):**
- 50+ net-new defects vs scenario-driven Postman
- 20-percentage-point pass-rate lift on Customer/Notifications/Transactions read after backend acts
- 7 consecutive unattended nightly runs
- +25% combined endpoint coverage vs Postman alone
- At least one service migrates POST/GET verification to stateful Schemathesis (retires `get_after_post_probe`)

## See also

- [[reference_backend_swagger_audit_ask|Swagger audit backend ask]]
- [[project_kardit_platform_health_20260501|Platform health snapshot driving service prioritization]]
- [[feedback_get_after_post_probe|Probe pattern that stateful mode partially replaces]]
- [[feedback_codex_council_workflow|Phase 1 runner code goes through this pipeline]]
