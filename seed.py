"""
seed.py — Verify or mint the canonical entity IDs required by all Kardit runners.

Usage:
    python seed.py              # verify canonical IDs exist; print status
    python seed.py --mint       # if canonical IDs are missing, mint new ones and
                                # print the IDs to set as CANONICAL_* env vars

The shared backend at KARDIT_BASE_URL already has the canonical IDs seeded.
Run this script with --mint only when testing against a FRESH backend instance.

Auth note: port 8080 services do not enforce auth (platform defect D-BATCH-AUTH-1),
so no credentials are required to verify or mint on those endpoints.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import requests

BASE_URL  = os.getenv("KARDIT_BASE_URL", "http://167.172.49.177:8080")
TIMEOUT   = 15
MINT_MODE = "--mint" in sys.argv

# Canonical IDs — override via env when running against a fresh backend
CANONICAL_BANK_ID      = os.getenv("CANONICAL_BANK_ID",      "000045f9-d01b-479c-a84d-0fe82454d55a")
CANONICAL_AFFILIATE_ID = os.getenv("CANONICAL_AFFILIATE_ID", "a7d5929b-cba8-4e97-8985-2ce1d9fc91c3")

HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

_SHARED = Path(__file__).resolve().parent / "shared"


# ─── helpers ─────────────────────────────────────────────────────────────────

def get(path: str) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=TIMEOUT)

def post(path: str, body: dict) -> requests.Response:
    return requests.post(f"{BASE_URL}{path}", headers=HEADERS,
                         data=json.dumps(body), timeout=TIMEOUT)

def put(path: str, body: dict) -> requests.Response:
    return requests.put(f"{BASE_URL}{path}", headers=HEADERS,
                        data=json.dumps(body), timeout=TIMEOUT)

def ok(r: requests.Response) -> bool:
    return r.status_code in (200, 201)


# ─── verify helpers ───────────────────────────────────────────────────────────

def verify_bank(bank_id: str) -> bool:
    try:
        r = post("/api/v1/banks/query", {"page": 1, "pageSize": 5})
        if ok(r):
            items = r.json().get("data", r.json().get("items", r.json().get("content", [])))
            return any(b.get("bankId") == bank_id or b.get("id") == bank_id for b in items)
        # fall back to direct GET
        r2 = get(f"/api/v1/banks/{bank_id}")
        return ok(r2)
    except Exception as e:
        print(f"  WARN: bank verify error: {e}")
        return False

def verify_affiliate(affiliate_id: str) -> bool:
    try:
        r = get(f"/api/v1/affiliates/{affiliate_id}/profile")
        if ok(r):
            return True
        # try query endpoint
        r2 = post("/api/v1/affiliates/query", {"page": 1, "pageSize": 5})
        if ok(r2):
            items = r2.json().get("data", r2.json().get("items", r2.json().get("content", [])))
            return any(a.get("affiliateId") == affiliate_id or a.get("id") == affiliate_id
                       for a in items)
        return False
    except Exception as e:
        print(f"  WARN: affiliate verify error: {e}")
        return False


# ─── mint helpers ─────────────────────────────────────────────────────────────

def mint_bank() -> str | None:
    """POST /api/v1/admin/banks → returns bankId string or None."""
    name = f"SeedBank-{uuid.uuid4().hex[:8].upper()}"
    body = {
        "name": name,
        "country": "NG",
        "currency": "NGN",
        "requestContext": {
            "requestId": str(uuid.uuid4()),
            "idempotencyKey": str(uuid.uuid4()),
        },
    }
    try:
        r = post("/api/v1/admin/banks", body)
        if ok(r):
            data = r.json()
            return data.get("bankId") or data.get("id")
        print(f"  WARN: /admin/banks returned {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  WARN: mint_bank error: {e}")
        return None

def mint_affiliate(bank_id: str) -> str | None:
    """
    Full affiliate onboarding flow (session → draft → submit → admin approve).
    Returns affiliateId or None.
    """
    try:
        # Step 1: open session
        r1 = post("/api/v1/affiliates/onboarding/sessions", {
            "requestContext": {"requestId": str(uuid.uuid4()), "idempotencyKey": str(uuid.uuid4())},
        })
        if not ok(r1):
            print(f"  WARN: onboarding/sessions {r1.status_code}")
            return None
        d1 = r1.json()
        draft_id = d1.get("draftId") or d1.get("id") or d1.get("data", {}).get("draftId")
        if not draft_id:
            print(f"  WARN: no draftId in session response: {d1}")
            return None

        # Step 2: set organisation details
        r2 = put(f"/api/v1/affiliates/onboarding/drafts/{draft_id}/organization", {
            "organizationName": f"SeedAffiliate-{uuid.uuid4().hex[:6].upper()}",
            "organizationType": "FINTECH",
            "primaryContact": {"firstName": "Seed", "lastName": "User",
                               "email": f"seed-{uuid.uuid4().hex[:6]}@test.kardit.io",
                               "phoneNumber": "+2348012345678"},
            "requestContext": {"requestId": str(uuid.uuid4()), "idempotencyKey": str(uuid.uuid4())},
        })
        if not ok(r2):
            print(f"  WARN: /organization {r2.status_code}: {r2.text[:200]}")

        # Step 3: set issuing banks
        r3 = put(f"/api/v1/affiliates/onboarding/drafts/{draft_id}/issuing-banks", {
            "selectedBankIds": [bank_id],
            "requestContext": {"requestId": str(uuid.uuid4()), "idempotencyKey": str(uuid.uuid4())},
        })
        if not ok(r3):
            print(f"  WARN: /issuing-banks {r3.status_code}: {r3.text[:200]}")

        # Step 4: submit draft
        r4 = post(f"/api/v1/affiliates/onboarding/drafts/{draft_id}/submit", {
            "requestContext": {"requestId": str(uuid.uuid4()), "idempotencyKey": str(uuid.uuid4())},
        })
        if not ok(r4):
            print(f"  WARN: /submit {r4.status_code}: {r4.text[:200]}")
            return None
        d4 = r4.json()
        affiliate_id = d4.get("affiliateId") or d4.get("id") or d4.get("data", {}).get("affiliateId")
        case_id      = d4.get("caseId")    or d4.get("data", {}).get("caseId")

        # Step 5: admin approve (if we have a caseId)
        if case_id:
            r5 = post(f"/api/v1/admin/onboarding/cases/{case_id}/decision", {
                "decision": "APPROVED",
                "selectedBankIds": [bank_id],
                "requestContext": {"requestId": str(uuid.uuid4()), "idempotencyKey": str(uuid.uuid4())},
            })
            if not ok(r5):
                print(f"  WARN: admin/decision {r5.status_code}: {r5.text[:200]}")

        return affiliate_id

    except Exception as e:
        print(f"  WARN: mint_affiliate error: {e}")
        return None


# ─── session_ids.json writer ─────────────────────────────────────────────────

def write_session_ids(bank_id: str, affiliate_id: str) -> None:
    ids_path = _SHARED / "session_ids.json"
    existing: dict = {}
    if ids_path.exists():
        try:
            existing = json.loads(ids_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing["bankId"]      = bank_id
    existing["affiliateId"] = affiliate_id
    ids_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"  Written: {ids_path}")


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Kardit seed — backend: {BASE_URL}")
    print(f"Mode: {'MINT (fresh backend)' if MINT_MODE else 'VERIFY (shared backend)'}\n")

    # ── Bank ──────────────────────────────────────────────────────────────────
    print(f"[1/2] Bank  id: {CANONICAL_BANK_ID}")
    bank_ok = verify_bank(CANONICAL_BANK_ID)
    print(f"       verify: {'PASS' if bank_ok else 'FAIL — not found in backend'}")

    new_bank_id = CANONICAL_BANK_ID
    if not bank_ok and MINT_MODE:
        print("       minting new bank...")
        new_bank_id = mint_bank()
        if new_bank_id:
            print(f"       minted: {new_bank_id}")
        else:
            print("       FAILED to mint bank — check backend connectivity and auth")
            sys.exit(1)

    # ── Affiliate ─────────────────────────────────────────────────────────────
    print(f"\n[2/2] Affiliate id: {CANONICAL_AFFILIATE_ID}")
    aff_ok = verify_affiliate(CANONICAL_AFFILIATE_ID)
    print(f"       verify: {'PASS' if aff_ok else 'FAIL — not found in backend'}")

    new_aff_id = CANONICAL_AFFILIATE_ID
    if not aff_ok and MINT_MODE:
        print(f"       minting new affiliate (bankId={new_bank_id})...")
        new_aff_id = mint_affiliate(new_bank_id)
        if new_aff_id:
            print(f"       minted: {new_aff_id}")
        else:
            print("       FAILED to mint affiliate — see warnings above")
            sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if not bank_ok or not aff_ok:
        if MINT_MODE:
            write_session_ids(new_bank_id, new_aff_id)
            print("\nSet these env vars (or update .env):")
            print(f"  CANONICAL_BANK_ID={new_bank_id}")
            print(f"  CANONICAL_AFFILIATE_ID={new_aff_id}")
        else:
            print("One or more canonical IDs not found.")
            print("If you are using a fresh backend, re-run with:  python seed.py --mint")
            sys.exit(1)
    else:
        write_session_ids(new_bank_id, new_aff_id)
        print("All canonical IDs verified. shared/session_ids.json updated.")
        print("You are ready to run any service runner.")

if __name__ == "__main__":
    main()
