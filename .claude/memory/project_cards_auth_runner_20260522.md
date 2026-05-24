---
name: project_cards_auth_runner_20260522
description: Cards Auth Runner on port 8082 — design, Phase 0 chain, payload fixes, card validation, and stable results as of 2026-05-22
metadata: 
  node_type: memory
  type: project
  originSessionId: 5a397891-3858-46d1-a7e6-4750ffdda215
---

Standalone Cards Authentication Test Runner targeting `http://167.172.49.177:8082`.
File: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\cards_auth_runner.py`
Reports: `C:\Users\Onyema Ifechukwu\Downloads\Kardit\reports\cards_auth_report_*.yaml`

**Why:** Port 8080 strips Authorization headers — all auth TCs there are meaningless. Port 8082 is the env where auth is actually implemented.

**Design:**
- 25 endpoints × 9 scenarios = 225 TCs; 18 N/A (unsigned endpoints skip sig scenarios)
- 2-layer auth: (1) Bearer via `https://hasham.platform.dev.chamsswitch.com/gateway/token` with client_credentials; (2) ECDSA-SHA256 signing on 19 signed endpoints
- 9 scenarios: missing_header, empty_bearer, garbage_token, truncated_token, expired_token, wrong_audience_token, missing_iam_signature, invalid_iam_signature, happy_path

**Removed endpoints (backend broken — fund-movement family):**
- CLOADR, CLAPPR, CLGET — 500 always; depended on CLOADR

**Phase 0 chain:**
- 0a-0e: validate env, mint tokens, load signing key, start refresh thread
- 0f: load affiliateId + bankId + seed cardId from `Downloads\kardit_session_ids.json`
- 0g: mint card via live GET /api/v1/cards query filtered by ACTIVE+VIRTUAL+maskedPan+customerId non-empty
- 0h: probe card, capture currency
- 0j: mint limit-request → limitRequestId (needed for OPLIM SC9)

**Card pool state (2026-05-22):**
- bankId `000045f9-d01b-479c-a84d-0fe82454d55a`: ~115 ACTIVE VIRTUAL cards but ALL orphaned (empty customerId + maskedPan). Backend provisioned cards without completing the issuance chain.
- Phase 0g filter now skips orphaned cards

**Stable result (2026-05-22 end of session):** PASS: 206 / FAIL: 0 / BLOCKED: 1 / N/A: 18
- 1 BLOCKED = OPLIM-SC09 (Phase 0j can't mint limit-request — no valid non-orphaned card)

**CTERM ordering:** CTERM runs LAST. SC9 happy_path terminates the card — mid-list causes state-cascade 500s on all subsequent card endpoints.

**How to apply:** Before running, verify at least one card on bankId `000045f9-d01b-479c-a84d-0fe82454d55a` has non-empty `customerId` AND `maskedPan`. If all cards are orphaned, OPLIM-SC09 will be BLOCKED.
