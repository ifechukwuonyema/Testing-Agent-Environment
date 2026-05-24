---
name: Notifications Hybrid Run 2026-05-08 PM
description: 186 TCs (20P/98F/68B, 10.8%); WORST pass rate of the day; 5 endpoints, 2 of which (NOT-GET-01, NOT-CRT-01) had +37 freshly authored TCs that mostly hit 5xx/blocked; service-wide brokenness still present
type: project
service: Notifications
run_date: 2026-05-08
tcs: 186
passes: 20
fails: 98
blocked: 68
pass_rate: 10.8
worst_cluster: pending /breakdown
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
WORST service of the day at 10.8%. Pack went 135 → 186 (+51 from revert + phase-2 authoring). The newly authored NOT-GET-01 (+21) and NOT-CRT-01 (+16) drafts mostly land in FAIL/BLOCKED — consistent with the prior memory `[[project_notifications_hybrid_run_20260501]]` finding that the service is service-wide broken (100% of FAILs were 5xx in that run).

- Report YAML: `Downloads\notifications_postman_hybrid_report_20260508-170509.yaml`
- Findings DOCX: `Downloads\notifications_findings_with_fixes_2026-05-08.docx`
- Evidence: `Downloads\evidence_postman_notifications_hybrid_20260508-170509\`
