---
name: Affiliate Audit Session 2026-05-08
description: Swagger-driven thorough audit of affiliate runner; shipped same classifier-bug family as cards plus affiliate-specific handlers; final 251P/133F/56B at 57.0%
type: project
service: affiliate
run_date: 2026-05-08
tcs: 440
passes: 251
fails: 133
blocked: 56
pass_rate: 57.0
worst_cluster: B_silent_accept (D-AFF-1 auth pipeline)
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
---
Report: `Downloads\affiliate_postman_standalone_v2_report_20260508-043153.yaml`

8 runner fixes shipped (cross-service with cards). Response-field check surfaced D-AFF-5: 19 fields missing across /profile and /kyb-snapshot.

All remaining FAILs are backend-side. Runner mutation-correct end-to-end.
