---
name: project_admin_run_20260512
description: Admin hybrid run 2026-05-12 — results, provision defect, pool exhaustion pattern
metadata: 
  node_type: memory
  type: project
  originSessionId: b4a81de3-50bf-410c-81aa-9f965e5971b8
---

Run 1: 155 TCs | 106P/36F/13B | 68.4% — report: `admin_postman_hybrid_report_20260512-225141.yaml`

**Why:** Fresh BACKEND_SUBMITTED_POOL (20 cases from query.txt) wired before running; Postman collection admin section updated (bankCode 01234→01239).

**D-ADMIN-PROV-1 (confirmed backend defect):**
Error: `"Failed to provision affiliate: Failed to provision affiliate: BadRequest, \"selectedBankIds cannot be empty.\""`
The provision DTO (`ProvisionAffiliateRequestDto`) has `additionalProperties: false` and does NOT include `selectedBankIds`. Backend's internal provision handler calls a downstream service requiring bank IDs but the DTO doesn't accept or forward them. Cannot fix harness-side — backend must either accept `selectedBankIds` in the DTO or derive approved banks from the case record.

**Case pool exhaustion:**
The 20 submitted cases are one-time-use (decision endpoint puts them in terminal state). Run 2 hit "already APPROVED/REJECTED" on all ONB-08 happy-path TCs. Need fresh query.txt from backend before each run or minting must be re-enabled.

**How to apply:** Before next admin run, get fresh submitted case IDs and update BACKEND_SUBMITTED_POOL. Flag D-ADMIN-PROV-1 in backend asks — provision endpoint is ceiling blocker at 48%.
