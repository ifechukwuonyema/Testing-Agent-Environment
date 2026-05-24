---
name: Affiliate Postman-Hybrid Run 2026-05-07
description: Standalone v2 run after harness fixes (classifier wins + fresh-session minting + body-injection overwrite) — 58.4% pass; remaining gaps are auth pipeline + audit endpoints + test-isolation
type: project
service: affiliate
run_date: 2026-05-07
tcs: 440
passes: 257
fails: 127
blocked: 56
pass_rate: 58.4
worst_cluster: B_silent_accept (auth pipeline missing across 9 endpoints)
originSessionId: d2908732-cf86-43ab-944b-db047e23e0e8
---
Report: `Downloads\affiliate_postman_standalone_v2_report_20260507-221037.yaml`
Backend asks: `Downloads\Kardit\reports\affiliate_backend_asks_2026-05-07.docx`

3 harness fixes: pack reconciled to AFFendpoints.txt, classifier quick-wins, Phase 0b randomizes email/phone, body-injection overwrites stale onboardingSessionId.

Backend asks: D-AFF-1 (auth/RBAC +19.3pp), D-AFF-2 (audit endpoints +12.7pp), D-AFF-3 (repeatable happy-path +8.9pp), D-AFF-4 (pipeline ordering).
Projected ceiling: ~99.3%.

See [[reference_affiliate_backend_asks_20260507]].
