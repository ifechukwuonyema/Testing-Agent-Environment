---
name: Admin Hybrid Run 2026-05-06
description: Admin run 43.1% (2026-05-01) → 74.0% (10 progressive iterations). Adminfeedback.txt fixes + ONB-10 endpoint added (30 TCs) + mint-flow enabled with matched primaryContact, unblocking all 10 ONB-09 happy paths.
type: project
service: admin
run_date: 2026-05-06
tcs: 154
passes: 114
fails: 27
blocked: 13
pass_rate: 74.0
worst_cluster: B_silent_accept
originSessionId: ca8ea338-76f5-42d0-a615-c3321c15cc2e
---
Report: `Downloads\admin_postman_hybrid_report_20260506-224624.yaml`

10 iterations in one session. Key win: mint-flow enabled with matched primaryContact unlocked all ONB-09 happy paths (was 0/10 PASS on provision).

Defects: D-15bis (POST /admin/banks not idempotent on legalName). 22 B_silent_accept FAILs = auth not yet shipped (D-05).

Ceiling: 91.5% when auth ships, 95.5% when audit-log endpoint ships.
