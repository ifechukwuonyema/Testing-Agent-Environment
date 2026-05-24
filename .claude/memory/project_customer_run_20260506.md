---
name: Customer Hybrid Run 2026-05-06
description: Customer hybrid run 35.8% → 69.2%. Root cause was a harness PATH_TEMPLATE_OVERRIDE bug — when override re-introduces a {placeholder} into a template built from a literal-URL Postman entry, base.path_vars stays empty and the literal "{customerRefId}" leaks into the request URL.
type: project
service: customer
run_date: 2026-05-06
tcs: 120
passes: 83
fails: 34
blocked: 3
pass_rate: 69.2
worst_cluster: H_5xx_server_error
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
Report: `Downloads\customer_postman_hybrid_report_20260506-033125.yaml`

Root cause: Postman entry for GET /customers/{customerRefId} used hardcoded literal URL. PATH_TEMPLATE_OVERRIDE re-introduced `{customerRefId}` but base.path_vars was empty, so the literal `{customerRefId}` ended up in the request URL. Backend returned 500 trying to look up a customer with ID `{customerRefId}`.

Fix: extract placeholders from override template and setdefault into base path_vars. See [[feedback_path_var_seed_after_override]].

Remaining: CUS-01 drafts A_4xx + CUS-02 search B_silent_accept + CUS-03 H_5xx remnant.
