# Kardit Memory Index

Project-level memory for Claude Code. These files give Claude persistent context across sessions — who built what, what broke, what rules govern the harness, and the full test history.

**Setup**: run `setup_memory.ps1` from repo root to install these into Claude Code's memory system for your local clone path.

---

## Feedback (How to Work)

- [Kill Before Re-run](feedback_kill_before_rerun.md) — `taskkill /F /IM python.exe /T` before every new runner launch
- [Runner Classification Policy](feedback_runner_classification_2026_05_08.md) — PASS/FAIL/BLOCKED only; mutation_misfire tag; scenario-name heuristic
- [Validation TC Mutation Must Actually Mutate](feedback_validation_mutation_tightening.md) — silent-accept FAILs are runner bugs when mutation didn't fire
- [Rotation Before Mutation](feedback_rotation_before_mutation.md) — rotate_*_uniqueness fires BEFORE mutation, never after
- [Per-TC State Provisioning](feedback_per_tc_state_provisioning.md) — state-machine endpoints need fresh entity per TC
- [Validated Pool Single-Use](feedback_validated_pool_single_use.md) — pool IDs consumed per run; supply fresh IDs before each run
- [State-Cascade Endpoints Need Rotating Fixtures](feedback_state_cascade_endpoints.md) — sharing one entity causes fixture exhaustion
- [GET-after-POST Probe](feedback_get_after_post_probe.md) — converts Cluster-C BLOCKEDs to deterministic attribution; never upgrades to PASS
- [Live ID Probe When Fixtures 404](feedback_live_id_probe_for_dead_fixtures.md) — probe live before declaring endpoint broken
- [ID Acquisition via Query Endpoint](feedback_id_acquisition_via_query.md) — use service's query endpoint; don't hardcode or POST-mint unnecessarily
- [Manual Chain Validation First](feedback_manual_chain_validation_first.md) — validate end-to-end manually before adding workarounds
- [Postman Collection Update In-Place](feedback_postman_collection_update_in_place.md) — update in-tree collection; don't swap POSTMAN_PATH
- [Pack Curation Against Swagger (REVISED)](feedback_pack_curation_against_swagger.md) — DO NOT delete scenarios because swagger is silent on a constraint
- [Scenarios Are Team Guidance](feedback_scenarios_are_team_guidance.md) — never delete a scenario to make the runner happy
- [TC Count Band](feedback_tc_count_band.md) — 30 floor, 40 ceiling, 30-35 preferred
- [Bank Dashboard Holdoff](feedback_bank_dashboard_holdoff.md) — /v2/banks/{bankId}/dashboard out of pack until v2 live
- [NO_AUTH Sentinel](feedback_no_auth_sentinel.md) — `__NO_AUTH__` header pattern; `__BANK_TOKEN__` runtime resolution
- [Pre-Script POST Only](feedback_pre_script_post_only.md) — pre-script runs only on POST, never GET
- [ENUMERATED_POOLS Guard](feedback_enumerated_pools_guard.md) — live-enumerated pools must not be contaminated by ACTIVE.txt merge
- [Override URL CardId Pop](feedback_override_url_cardid_pop.md) — pop("cardId") after extracting from override URL
- [Stale ACTIVE.txt Pool Probe](feedback_stale_activetxt_pool_probe.md) — probe specialty pools live before execution
- [Bank Fixture Pool Pattern](feedback_bank_fixture_pool_pattern.md) — 7-key bank_fixtures_v2.json; Phase 0d early-return guard
- [Admin Case Pool One-Time Use](feedback_admin_case_pool_one_time_use.md) — ~20 cases = 1 run; need fresh batch before each run
- [Admin Decision Body](feedback_admin_decision_no_selectedbanksapproved.md) — never include selectedBanksApproved
- [Affiliate State Domain](feedback_affiliate_state_domain.md) — ACTIVE or BLOCKED only; no "pending" observable state
- [Affiliate Owned Pool](feedback_affiliate_owned_pool.md) — PENDING_ACTIVATION cards must be owned by canonical affiliateId
- [FUL-02 Refresh Eligibility](feedback_ful02_refresh_eligibility.md) — determined by list-level fulfillmentStatus=PERSONALIZING
- [Auth Runner Card Pool](feedback_auth_runner_card_pool.md) — CTERM last; Phase 0g capture; IAM URL; AFF-format ID
- [TC Request ID Override Pattern](feedback_tc_request_id_override_pattern.md) — pin specific IDs 1:1 to named TCs for stale pools
- [FORCE_V1_PLAN_SCENARIOS](feedback_force_v1_plan_scenarios.md) — bypass v2 engine for known misclassification cases
- [Backend Response Is Authoritative](feedback_backend_response_authoritative.md) — Z2 FAILs: rename scenario if field under different key; remove TC if genuinely absent
- [Manual Test Confirms Pack Delete](feedback_manual_test_confirms_pack_delete.md) — user confirmation of FAIL → delete TC immediately
- [Path Var Seed After Override](feedback_path_var_seed_after_override.md) — seed path_vars after PATH_TEMPLATE_OVERRIDE re-introduces `{placeholder}` markers
- [Postman-Driven Testing Protocol](feedback_postman_driven_testing.md) — mutate per scenario name; reusable harness pattern
- [Post-Report Memory Enhancement](feedback_post_report_memory.md) — after every report, review and enhance memory
- [Test Report DOCX Format](feedback_test_report_format.md) — YAML schema verbatim; no narrative summaries
- [Breakdown Format](feedback_breakdown_per_endpoint_format.md) — per-endpoint deep sections; list every TC ID + scenario; never truncate
- [Test-Case Doc 6-Column Format](feedback_test_case_doc_format.md) — Endpoint, TCID, Scenario, Description, Precondition, Expected Result
- [Invalid ID Inventory Section](feedback_invalid_id_inventory_section.md) — add side-by-side invalid/valid table to backend asks DOCX
- [Codex Council Workflow](feedback_codex_council_workflow.md) — 5-stage pipeline for logic-touching changes
- [Self-Review Protocol](feedback_self_review_protocol.md) — concrete checks after multi-fix sessions
- [Deep Audit Dimensions](feedback_deep_audit_dimensions.md) — 10 dimensions; run when standard audit clean but FAILs remain
- [Swagger-Driven Runner Audit](feedback_swagger_driven_runner_audit.md) — 4-dimension audit; pass rate drop after fixes is information gain
- [Obsidian Run Workflow](feedback_obsidian_run_workflow.md) — every run produces vault rollup + per-service memory files

---

## References (Where Things Live)

- [Main Swagger](reference_main_swagger.md) — `Downloads/MainSwagger.txt`; OpenAPI 3.0.1; canonical source of truth
- [Downloads Directory Layout](reference_downloads_layout.md) — Kardit/reports, Kardit/evidence, Personal/, Archive/, etc.
- [Kardit Harness Relocation](reference_kardit_harness_relocation_20260503.md) — 9 files in `Kardit/harnesses/`; git-versioned
- [Harness Optimizations 2026-05-03](reference_kardit_harness_optimizations_20260503.md) — shared probe.py module; T7-T17 optimizations
- [Cards State Lifecycle](reference_cards_state_lifecycle.md) — PENDING_ACTIVATION→ACTIVE→FROZEN→TERMINATED; per-endpoint allowlists
- [Cards Z & Z2 DOCX 2026-05-11](reference_cards_z_z2_docx_20260511.md) — schema drift catalogue
- [Cards Backend Defects DOCX 2026-05-23](reference_cards_backend_asks_20260523.md) — 11 defects; supersedes 2026-05-08 doc
- [Cards Auth Defects 2026-05-22](reference_cards_auth_defects_20260522.md) — TENANT-1, AUTHZ-2, ORPHAN, LOADREQ open
- [Bank Backend Asks DOCX 2026-05-07](reference_bank_backend_asks_20260507.md) — 9 findings; D-405-1, D-PERSIST-1 critical
- [Bank Backend Asks DOCX 2026-05-06](reference_bank_backend_asks_20260506.md) — D-04..D-16 + 5 test-data needs
- [Affiliate Backend Asks DOCX 2026-05-07](reference_affiliate_backend_asks_20260507.md) — D-AFF-1..4; ceiling ~99.3%
- [Customer Backend Asks DOCX 2026-05-08](reference_customer_backend_asks_20260508.md) — 5 findings; ceiling ~95%
- [Customer Backend Asks DOCX 2026-05-06](reference_customer_backend_asks_20260506.md) — D-CUS-2..D-05
- [Transactions Backend Asks DOCX 2026-05-08](reference_transactions_backend_asks_20260508.md) — 5 findings; ceiling ~98%
- [Transactions Backend Asks DOCX 2026-05-07](reference_transactions_backend_asks_20260507.md) — D-TRX-1..3
- [Transactions Backend Asks DOCX 2026-05-10](reference_transactions_backend_asks_20260510.md) — 8 asks + Invalid ID Inventory
- [Transactions Dual ID Population](reference_transactions_dual_id_population.md) — TXN-2026-XXX vs TRA-32hex; same entity, round-trip 404
- [Admin Auth Bypass Confirmed](reference_admin_auth_bypass_confirmed.md) — ghost banks; missing middleware on all admin routes
- [Admin Tenant Leakage](reference_admin_tenant_leakage.md) — D-ADMIN-TENANT-1; GET case by ID leaks cross-tenant
- [Backend Verification Endpoints Ask](reference_backend_verification_endpoints_ask.md) — 5 read-only endpoints requested; unblocks ~600-700 chain BLOCKEDs
- [Backend Onboarding Flow Ask](reference_backend_onboarding_flow_ask.md) — 500 + issuing-banks 404/500 block
- [Backend Swagger Audit Ask](reference_backend_swagger_audit_ask.md) — gates Schemathesis signal quality
- [Generic Per-TC Audit Script](reference_generic_per_tc_audit_script.md) — `Downloads/_audit_generic_per_tc.py`
- [CTO Test-Case Doc Workflow](reference_cto_test_case_doc_workflow.md) — generator + Drive uploader scripts
- [Trash Housekeeping 2026-05-08](reference_trash_housekeeping_20260508.md) — 72 outdated files archived

---

## Project State (Run History)

### Chain Runs
- [Sequential Chain Run 2026-05-02](project_chain_run_20260502.md) — 3199 TCs (924P/1683F/592B); first end-to-end chain

### Batch Run Rollups
- [Run 2026-05-01](run_2026-05-01.md)
- [Run 2026-05-02](run_2026-05-02.md)
- [Run 2026-05-03](run_2026-05-03.md)
- [Run 2026-05-05](run_2026-05-05.md)
- [Run 2026-05-06](run_2026-05-06.md)
- [Run 2026-05-08](run_2026-05-08.md)

### Per-Service Recent Runs (Latest First)

**Cards**
- [Cards E2E Run 2026-05-23](project_cards_e2e_run_20260523.md) — ~880 TCs; 71F/31B all backend; ceiling ~99%+
- [Cards Auth Runner 2026-05-22](project_cards_auth_runner_20260522.md) — 225 TCs; 206P/0F/1B/18N/A; ECDSA signing verified
- [Cards Run 2026-05-14](project_cards_run_20260514.md) — 9-TC review-driven replay; all PASS
- [Cards Run 2026-05-13](project_cards_run_20260513.md) — 720 TCs (427P/109F/184B); 3 harness fixes
- [Cards Run 2026-05-12](project_cards_run_20260512.md) — 779 TCs (450P/140F/189B); schema drift catalogue
- [Cards Run 2026-05-11](project_cards_run_20260511.md) — 133 failed TCs replayed; Z/Z2 DOCX produced

**Transactions**
- [Transactions Targeted Reruns 2026-05-18](project_transactions_run_20260518.md) — all 11 DOCX FAILs resolved; 286P/0F/1B
- [Transactions Run 2026-05-12](project_transactions_run_20260512.md) — 342 TCs (275P/57F/10B, 80.4%)
- [Transactions Run 2026-05-08](project_transactions_run_20260508.md) — 391 TCs (309P/71F/11B, 79.0%); deep audit
- [Transactions Run 2026-05-07](project_transactions_run_20260507.md) — 405 TCs (313P/81F/11B, 77.3%); +30.5pp day-over-day

**Batch**
- [Batch Run 2026-05-21](project_batch_run_20260521.md) — 252 TCs (203P/31F/18B, 80.6%); BATCH-08 wired
- [Batch Run 2026-05-18](project_batch_run_20260518.md) — 12 runs; baseline 38.3%→56.3%; per-TC provisioning shipped
- [Batch Run 2026-05-19](project_batch_run_20260519.md) — 153P/57F/12B (69%)
- [Batch Run 2026-05-17](project_batch_run_20260517.md) — 222 TCs (16.7%); pre-flight write/read divergence

**Admin**
- [Admin Run 2026-05-13](project_admin_run_20260513.md) — 114P/26F/13B (74.5%); all 26F backend
- [Admin Run 2026-05-12](project_admin_run_20260512.md) — 106P/36F/13B (68.4%)
- [Admin ONB-09 Fix](project_admin_onb09_selectedbankids_fix.md) — bank injection removed; ONB-09 now 25P/4F/2B

**Affiliate**
- [Affiliate Fix Session 2026-05-18](project_affiliate_fix_session_20260518.md) — 18 FAILs resolved; 2 backend defects remain
- [Affiliate Run 2026-05-13](project_affiliate_run_20260513.md) — 455 TCs (302P/97F/56B, 66.4%); pack audited
- [Affiliate Run 2026-05-12](project_affiliate_run_20260512.md) — 476 TCs (291P, 61.1%); 3 pre-flight fixes

**Customer**
- [Customer Run 2026-05-21](project_customer_run_20260521.md) — 3/3 PASS; cross-field bypass fix
- [Customer Run 2026-05-18](project_customer_run_20260518.md) — 74P/38F/5B (63.2%) → 78P/34F/5B (66.7%)

**Bank**
- [Bank Replay 2026-05-15](project_bank_replay_20260515.md) — 16 PASS; TC_REQUEST_ID_OVERRIDE validated
- [Bank Run 2026-05-14](project_bank_run_20260514.md) — 90P/48F/46B (48.9%); 4 fixture fixes

---

## User Context

- [User API Testing Workflow](user_api_testing.md) — conducts API testing using test cases and Swagger JSON

---

## Scenario Revert History

- [Scenario Revert 2026-05-08](project_scenario_revert_20260508.md) — +557 TCs restored; 2,410→2,861 TCs across 8 packs

---

## Schemathesis

- [Schemathesis Adoption 2026-05-05](project_schemathesis_adoption_20260505.md) — phased rollout; Batch pilot; targets H_5xx and B_silent_accept via fuzzer
