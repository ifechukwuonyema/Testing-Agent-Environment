#!/usr/bin/env python3
"""
Cards Authentication Test Runner
Target: http://167.172.49.177:8082 (auth test environment — separate from main harness at :8080)
Coverage: 28 endpoints x 9 auth scenarios (~232 runnable TCs, ~20 NOT_APPLICABLE on unsigned endpoints)

Auth layers tested:
  Layer 1 — Bearer token (OAuth2 client_credentials via IAM)
  Layer 2 — ECDSA-SHA256 request signing (X-IAM-Signature/Timestamp/Nonce) on 19 signed endpoints

Run:
  python cards_auth_runner.py
  python cards_auth_runner.py --dry-run
  python cards_auth_runner.py --scenarios 1,6,9
  python cards_auth_runner.py --endpoint AUTH-01
  python cards_auth_runner.py --workers 3
"""

import sys
import os
import json
import uuid
import time
import hashlib
import base64
import threading
import argparse
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

# Force UTF-8 on Windows terminals that default to cp1252
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — override via environment variables if needed
# ─────────────────────────────────────────────────────────────────────────────
BASE_URL = os.getenv("CARDS_AUTH_BASE_URL", "http://167.172.49.177:8082")
IAM_URL  = os.getenv("CARDS_IAM_URL", "https://hasham.platform.dev.chamsswitch.com/gateway/token")

CARDS_CLIENT_ID = os.getenv("CARDS_CLIENT_ID", "platform-kardit-card-api")
BANK_CLIENT_ID  = os.getenv("BANK_CLIENT_ID",  "platform-kardit-bank-api")

# Secrets — no defaults; must be set in .env or environment before running
require("CARDS_CLIENT_SECRET", "BANK_CLIENT_SECRET", "CARDS_SIGNING_KEY_PEM")
CARDS_CLIENT_SECRET = os.environ["CARDS_CLIENT_SECRET"]
BANK_CLIENT_SECRET  = os.environ["BANK_CLIENT_SECRET"]
SIGNING_KEY_PEM     = os.environ["CARDS_SIGNING_KEY_PEM"]

EXPIRED_TOKEN = os.getenv("CARDS_EXPIRED_TOKEN", "expired.token.sentinel")

_SVC_DIR   = Path(__file__).resolve().parent
_REPO_ROOT = _SVC_DIR.parent
_SHARED    = _REPO_ROOT / "shared"
import sys as _sys
_sys.path.insert(0, str(_SHARED))
from load_env import load_env, require  # noqa: E402
load_env()  # load .env before any os.getenv calls
SESSION_IDS_PATH = os.getenv(
    "KARDIT_SESSION_IDS",
    str(_SHARED / "session_ids.json"),
)

TENANT_ID     = "00000000-0000-0000-0000-000000000001"
CUSTOMER_ID   = os.getenv("CARDS_CUSTOMER_ID", "62a855d9-cc62-4233-88fe-856d901b0a04")
PRODUCT_ID    = os.getenv("CARDS_PRODUCT_ID",  "d475e7e2-0685-4bb6-9ef0-95fec4fcb495")
REPORT_DIR    = Path(os.getenv("KARDIT_REPORT_DIR", str(_SVC_DIR / "reports")))
REQUEST_TIMEOUT = 15  # seconds per request

# ─────────────────────────────────────────────────────────────────────────────
# SIGNING — ECDSA-SHA256 with DER-encoded output
# Canonical string verified against Postman pre-request script and signatureVerifier.ts:
#   METHOD\nPATH\nQUERY_SORTED\nSHA256_HEX(BODY)\nTIMESTAMP_MS\nNONCE
# Python's cryptography.sign() returns DER directly (same as Postman's p1363ToDer output)
# ─────────────────────────────────────────────────────────────────────────────
EMPTY_BODY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def load_private_key(pem: str):
    return serialization.load_pem_private_key(pem.strip().encode("ascii"), password=None, backend=default_backend())


def sorted_query_string(params: dict) -> str:
    if not params:
        return ""
    # Mirror JS: .split('&').sort().join('&') — sort whole key=value strings
    parts = sorted(f"{k}={v}" for k, v in params.items())
    return "&".join(parts)


def sign_request(method: str, path: str, query_str: str, body_bytes: bytes, private_key) -> tuple:
    timestamp_ms = str(int(time.time() * 1000))
    nonce        = str(uuid.uuid4())  # matches crypto.randomUUID() format
    body_hash    = hashlib.sha256(body_bytes).hexdigest() if body_bytes else EMPTY_BODY_SHA256
    canonical    = "\n".join([method.upper(), path, query_str, body_hash, timestamp_ms, nonce])
    sig_der      = private_key.sign(canonical.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    sig_b64      = base64.b64encode(sig_der).decode("ascii")
    return sig_b64, timestamp_ms, nonce


# ─────────────────────────────────────────────────────────────────────────────
# TOKEN MANAGER — thread-safe dual-token rotation
# ─────────────────────────────────────────────────────────────────────────────
class TokenManager:
    _REFRESH_SECS = 540  # 9 minutes (token TTL is 900s)

    def __init__(self):
        self._cards_token: Optional[str] = None
        self._bank_token:  Optional[str] = None
        self._lock  = threading.Lock()
        self._stop  = threading.Event()

    def _mint(self, client_id: str, client_secret: str) -> str:
        # IAM uses HTTP Basic Auth for client credentials; JSON body carries only grant_type
        resp = requests.post(
            IAM_URL,
            json={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise RuntimeError(f"IAM {resp.status_code} for {client_id} — body: {resp.text[:400]}")
        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError(f"IAM returned no access_token for {client_id}: {resp.text[:200]}")
        return token

    def init(self) -> None:
        """Mint both tokens synchronously. Raises on failure — caller must abort."""
        self._cards_token = self._mint(CARDS_CLIENT_ID, CARDS_CLIENT_SECRET)
        self._bank_token  = self._mint(BANK_CLIENT_ID,  BANK_CLIENT_SECRET)

    def get_cards(self) -> str:
        with self._lock:
            return self._cards_token

    def get_bank(self) -> str:
        with self._lock:
            return self._bank_token

    def start_background_refresh(self) -> None:
        t = threading.Thread(target=self._refresh_loop, daemon=True, name="token-refresh")
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self._REFRESH_SECS):
            try:
                new_cards = self._mint(CARDS_CLIENT_ID, CARDS_CLIENT_SECRET)
                new_bank  = self._mint(BANK_CLIENT_ID,  BANK_CLIENT_SECRET)
                with self._lock:
                    self._cards_token = new_cards
                    self._bank_token  = new_bank
            except Exception as e:
                print(f"[TOKEN] Background refresh failed: {e}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT REGISTRY
# signed=True  → Postman pre-request script attaches X-IAM-Signature/Timestamp/Nonce
# body_key     → which body builder to use (None = no request body)
# vars         → path variable names in order of appearance
# ─────────────────────────────────────────────────────────────────────────────
ENDPOINTS = [
    # Auth introspection (unsigned, no body)
    {"code": "AUTH-01", "method": "GET",  "path": "/api/v1/auth/permissions",                                           "signed": False, "vars": [],                              "body_key": None},
    {"code": "AUTH-02", "method": "GET",  "path": "/api/v1/auth/me",                                                    "signed": False, "vars": [],                              "body_key": None},
    # CardBanks — bulk affiliate-level ops (signed POST, no requestContext in body)
    {"code": "CBNK-01", "method": "POST", "path": "/api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/freeze",       "signed": True,  "vars": ["bankId", "affiliateId"],       "body_key": "bank_action"},
    {"code": "CBNK-02", "method": "POST", "path": "/api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/unfreeze",     "signed": True,  "vars": ["bankId", "affiliateId"],       "body_key": "bank_action"},
    {"code": "CBNK-03", "method": "POST", "path": "/api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/terminate",    "signed": True,  "vars": ["bankId", "affiliateId"],       "body_key": "bank_action"},
    # Metrics (bank variant is signed, affiliate variant is not)
    {"code": "MBNK",    "method": "GET",  "path": "/api/v1/cards/metrics/bank/{bankId}",                                "signed": False, "vars": ["bankId"],                      "body_key": None},
    {"code": "MAFF",    "method": "GET",  "path": "/api/v1/cards/metrics/affiliate/{affiliateId}",                      "signed": False, "vars": ["affiliateId"],                 "body_key": None},
    # Card list/query (CardsQueryRequestDto has no requestContext)
    {"code": "CQRY",    "method": "POST", "path": "/api/v1/cards/query",                                                "signed": True,  "vars": [],                              "body_key": "cards_query"},
    {"code": "CLIST",   "method": "GET",  "path": "/api/v1/cards",                                                      "signed": False, "vars": [],                              "body_key": None},
    # Core card operations
    {"code": "CISS",    "method": "POST", "path": "/api/v1/cards/issuance",                                             "signed": True,  "vars": [],                              "body_key": "issuance"},
    {"code": "CGET",    "method": "GET",  "path": "/api/v1/cards/{cardId}",                                             "signed": False, "vars": ["cardId"],                      "body_key": None},
    {"code": "CFUND",   "method": "GET",  "path": "/api/v1/cards/{cardId}/funding-details",                             "signed": False, "vars": ["cardId"],                      "body_key": None},
    {"code": "CFFST",   "method": "GET",  "path": "/api/v1/cards/{cardId}/fulfillment/status",                          "signed": False, "vars": ["cardId"],                      "body_key": None},
    {"code": "CFFRE",   "method": "POST", "path": "/api/v1/cards/{cardId}/fulfillment/refresh",                         "signed": True,  "vars": ["cardId"],                      "body_key": "ctx_reason"},
    {"code": "CFFRI",   "method": "POST", "path": "/api/v1/cards/{cardId}/fulfillment/reinitiate",                      "signed": True,  "vars": ["cardId"],                      "body_key": "ctx_reason"},
    {"code": "CFRZC",   "method": "POST", "path": "/api/v1/cards/{cardId}/freeze",                                      "signed": True,  "vars": ["cardId"],                      "body_key": "ctx_reason"},
    {"code": "CUFZC",   "method": "POST", "path": "/api/v1/cards/{cardId}/unfreeze",                                    "signed": True,  "vars": ["cardId"],                      "body_key": "ctx_reason"},
    {"code": "CBAL",    "method": "GET",  "path": "/api/v1/cards/{cardId}/balance",                                     "signed": False, "vars": ["cardId"],                      "body_key": None},
    {"code": "CLREQ",   "method": "POST", "path": "/api/v1/cards/{cardId}/limit-requests",                              "signed": True,  "vars": ["cardId"],                      "body_key": "limit_request"},
    {"code": "CPIN",    "method": "POST", "path": "/api/v1/cards/{cardId}/pin-reset",                                   "signed": True,  "vars": ["cardId"],                      "body_key": "ctx_reason"},
    {"code": "CLOADS",  "method": "POST", "path": "/api/v1/cards/{cardId}/loads",                                       "signed": True,  "vars": ["cardId"],                      "body_key": "load_request"},
    {"code": "CUNLD",   "method": "POST", "path": "/api/v1/cards/{cardId}/unloads",                                     "signed": True,  "vars": ["cardId"],                      "body_key": "unload"},
    {"code": "CACT",    "method": "POST", "path": "/api/v1/cards/{cardId}/activate",                                    "signed": True,  "vars": ["cardId"],                      "body_key": "ctx_reason"},
    # Ops — internal limit completion (empty body, needs limitRequestId)
    {"code": "OPLIM",   "method": "POST", "path": "/api/v1/ops/cards/{cardId}/limit-requests/{limitRequestId}/complete","signed": True,  "vars": ["cardId", "limitRequestId"],    "body_key": "empty"},
    # CTERM runs last — SC09 happy_path terminates the card; keep it at end to avoid state-cascade into other endpoints
    {"code": "CTERM",   "method": "POST", "path": "/api/v1/cards/{cardId}/terminate",                                   "signed": True,  "vars": ["cardId"],                      "body_key": "ctx_reason"},
]

# Scenario index → name
SCENARIO_NAMES = {
    1: "missing_header",
    2: "empty_bearer",
    3: "garbage_token",
    4: "truncated_token",
    5: "expired_token",
    6: "wrong_audience_token",
    7: "missing_iam_signature",
    8: "invalid_iam_signature",
    9: "happy_path",
}


# ─────────────────────────────────────────────────────────────────────────────
# BODY BUILDERS
# ─────────────────────────────────────────────────────────────────────────────
def _make_request_context(session_vars: dict) -> dict:
    return {
        "requestId":     str(uuid.uuid4()),
        "actorUserId":   str(uuid.uuid4()),
        "userType":      "AFFILIATE",
        "tenantId":      TENANT_ID,
        "affiliateId":   session_vars.get("affiliateId"),
        "idempotencyKey": str(uuid.uuid4()),
        "role":          "AFFILIATE",
    }


def _build_body(body_key: str, session_vars: dict) -> dict:
    ctx = _make_request_context(session_vars)

    if body_key == "ctx_only":
        return {"requestContext": ctx}

    elif body_key == "ctx_reason":
        return {"requestContext": ctx, "reason": "auth_test"}

    elif body_key == "bank_action":
        # FreezeAffiliateCardsRequestDto / Unfreeze / Terminate — no requestContext
        return {"reason": "auth_test"}

    elif body_key == "cards_query":
        # CardsQueryRequestDto — no requestContext
        return {
            "filters": {"affiliateId": session_vars.get("affiliateId")},
            "page": 1,
            "pageSize": 10,
        }

    elif body_key == "issuance":
        # Port 8082 issuance requires customer.embeddedPayload.kyc + .identity (KYC data)
        # Backend team must supply the embeddedPayload format before this can mint fresh cards
        return {
            "requestContext": ctx,
            "customer": {
                "customerId":      session_vars.get("customerId"),
                "embeddedPayload": {},
            },
            "issuance": {
                "bankId":      session_vars.get("bankId"),
                "productId":   session_vars.get("productId"),
                "productType": "VIRTUAL",
                "currency":    "NGN",
            },
        }

    elif body_key == "limit_request":
        return {
            "requestContext":  ctx,
            "requestedLimit":  {"amount": 50000.0, "currency": "NGN"},
            "reason":          "auth_test",
        }

    elif body_key == "load_request":
        return {
            "requestContext":   ctx,
            "amount":           {"value": 1000.0, "currency": session_vars.get("card_currency", "NGN")},
            "fundingReference": {
                "virtualAccountNumber": "8917024177",
                "bankId":               "BNK-WEM-002",
                "bankTransferReference":"TRF-2026-009811",
                "proofType":            "BANK_TRANSFER_CONFIRMED",
            },
        }

    elif body_key == "load_approve":
        return {
            "requestContext": ctx,
            "decision":       "APPROVE",
            "remarks":        "auth_test",
        }

    elif body_key == "unload":
        return {
            "requestContext":     ctx,
            "amount":             {"value": 100.0, "currency": session_vars.get("card_currency", "NGN")},
            "destinationAccount": {
                "accountId":           "ACC-REG-00081",
                "bankCode":            "058",
                "accountNumberMasked": "01******89",
            },
            "reason": "CUSTOMER_CASH_OUT",
        }

    elif body_key == "empty":
        return {
            "requestContext": ctx,
            "outcome":        "COMPLETED",
            "appliedLimit":   {"amount": 400000, "currency": session_vars.get("card_currency", "NGN")},
            "external":       {"cmsReference": "CMS-LIM-992201"},
            "opsRemarks":     "auth_runner_probe",
        }

    return {}


# ─────────────────────────────────────────────────────────────────────────────
# HEADER BUILDER — assembles headers per scenario
# For signed endpoints and scenarios 2-9: include a valid signature alongside
# whatever Bearer manipulation is happening (isolates Bearer layer from sig layer)
# Exception: scenario 1 sends nothing; scenario 7 sends valid Bearer but no sig
# ─────────────────────────────────────────────────────────────────────────────
def _build_headers(
    scenario: int,
    endpoint: dict,
    body_bytes: bytes,
    url_path: str,
    query_str: str,
    token_manager: TokenManager,
    private_key,
) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    method  = endpoint["method"]
    signed  = endpoint["signed"]

    def add_valid_sig():
        if signed:
            sig, ts, nonce = sign_request(method, url_path, query_str, body_bytes, private_key)
            headers["X-IAM-Signature"] = sig
            headers["X-IAM-Timestamp"] = ts
            headers["X-IAM-Nonce"]     = nonce

    cards_token = token_manager.get_cards()
    bank_token  = token_manager.get_bank()

    if scenario == 1:
        # No auth headers at all
        pass

    elif scenario == 2:
        headers["Authorization"] = "Bearer "
        add_valid_sig()

    elif scenario == 3:
        headers["Authorization"] = "Bearer garbage_invalid_token_abc123xyz_not_a_jwt"
        add_valid_sig()

    elif scenario == 4:
        truncated = cards_token[:-20] if len(cards_token) > 20 else cards_token[:10]
        headers["Authorization"] = f"Bearer {truncated}"
        add_valid_sig()

    elif scenario == 5:
        headers["Authorization"] = f"Bearer {EXPIRED_TOKEN}"
        add_valid_sig()

    elif scenario == 6:
        # Bank service account token — wrong audience, no kardit:cards:* permissions
        headers["Authorization"] = f"Bearer {bank_token}"
        add_valid_sig()

    elif scenario == 7:
        # Valid Bearer, no IAM signature headers (signed endpoints only — N/A on unsigned)
        headers["Authorization"] = f"Bearer {cards_token}"

    elif scenario == 8:
        # Valid Bearer, garbage ECDSA signature
        headers["Authorization"]   = f"Bearer {cards_token}"
        if signed:
            headers["X-IAM-Signature"] = "aGFja2Vk"  # base64("hacked") — invalid DER
            headers["X-IAM-Timestamp"] = str(int(time.time() * 1000))
            headers["X-IAM-Nonce"]     = str(uuid.uuid4())

    elif scenario == 9:
        # Full valid auth
        headers["Authorization"] = f"Bearer {cards_token}"
        add_valid_sig()

    return headers


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────
def _classify(scenario: int, status_code: int) -> tuple:
    """Returns (execution_status, evaluation_reason, defect_tag)"""

    if scenario in (1, 2, 3, 4, 5, 6):
        if status_code in (401, 403):
            return "PASS", f"auth enforced: {status_code} received as expected for {SCENARIO_NAMES[scenario]}", None
        elif 200 <= status_code < 300:
            return "FAIL", f"silent_accept: {status_code} returned with {SCENARIO_NAMES[scenario]} — backend accepted unauthenticated/invalid request — D-CARDS-1", "D-CARDS-1"
        else:
            return "FAIL", f"unexpected_{status_code}: expected 401/403 for {SCENARIO_NAMES[scenario]}, got {status_code} — auth not checked before request processing (D-CARDS-1)", "D-CARDS-1"

    elif scenario in (7, 8):
        if status_code in (401, 403):
            return "PASS", f"signature enforcement confirmed: {status_code} for {SCENARIO_NAMES[scenario]}", None
        elif 200 <= status_code < 300:
            return "FAIL", f"signature_not_enforced: {status_code} returned with {SCENARIO_NAMES[scenario]} — ECDSA layer not validated — D-CARDS-SIG-1", "D-CARDS-SIG-1"
        else:
            return "FAIL", f"unexpected_{status_code}: expected 401/403 for {SCENARIO_NAMES[scenario]}, got {status_code} — D-CARDS-SIG-1", "D-CARDS-SIG-1"

    elif scenario == 9:
        if status_code in (401, 403):
            return "FAIL", f"valid_credentials_rejected: {status_code} — valid Bearer + valid ECDSA signature was rejected — D-CARDS-AUTH-REJECT", "D-CARDS-AUTH-REJECT"
        elif 500 <= status_code < 600:
            return "FAIL", f"server_error: {status_code} on authenticated happy_path request — investigate backend crash", "D-CARDS-5XX"
        elif 200 <= status_code < 300:
            return "PASS", f"auth_passed_functional_success: {status_code} — endpoint accepted valid credentials", None
        else:
            # 4xx from business logic = auth passed (document functional failure but auth is OK)
            return "PASS", f"auth_passed_functional_failure: {status_code} from business logic — auth layer not blocking valid credentials (functional result documented above)", None

    return "FAIL", "unclassified_scenario", None


# ─────────────────────────────────────────────────────────────────────────────
# TC EXECUTION
# ─────────────────────────────────────────────────────────────────────────────
def _find_nested(d, key):
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = _find_nested(v, key)
            if r:
                return r
    elif isinstance(d, list):
        for item in d:
            r = _find_nested(item, key)
            if r:
                return r
    return None


def _redact_auth(headers: dict) -> dict:
    out = {}
    for k, v in headers.items():
        if k.lower() == "authorization" and v and len(v) > 30:
            out[k] = v[:20] + "...[redacted]"
        else:
            out[k] = v
    return out


def _auth_payload_tag(scenario: int, signed: bool) -> str:
    """Short descriptor of what auth payload the TC sends — derived deterministically from scenario + signed."""
    sig = "+valid_sig" if signed else ""
    return {
        1: "no_auth",
        2: f"Bearer_empty{sig}",
        3: f"Bearer_garbage{sig}",
        4: f"Bearer_truncated{sig}",
        5: f"Bearer_expired{sig}",
        6: f"Bearer_bank{sig}",
        7: "Bearer_valid+no_sig" if signed else "n/a",
        8: "Bearer_valid+invalid_sig" if signed else "n/a",
        9: f"Bearer_valid{sig}",
    }.get(scenario, "n/a")


def _blocked(tc_id: str, endpoint: dict, scenario: int, reason: str) -> dict:
    return {
        "tc_id": tc_id,
        "endpoint": f"{endpoint['method']} {endpoint['path']}",
        "scenario": SCENARIO_NAMES[scenario],
        "auth_layer": "bearer_and_signature" if endpoint["signed"] else "bearer_only",
        "signing_included": False,
        "auth_payload": _auth_payload_tag(scenario, endpoint["signed"]),
        "input_data": {},
        "response_data": {},
        "execution_status": "BLOCKED",
        "evaluation_reason": reason,
        "defect_tag": None,
    }


def _not_applicable(tc_id: str, endpoint: dict, scenario: int) -> dict:
    return {
        "tc_id": tc_id,
        "endpoint": f"{endpoint['method']} {endpoint['path']}",
        "scenario": SCENARIO_NAMES[scenario],
        "auth_layer": "bearer_only",
        "signing_included": False,
        "auth_payload": "n/a",
        "input_data": {},
        "response_data": {},
        "execution_status": "NOT_APPLICABLE",
        "evaluation_reason": f"Endpoint is unsigned — {SCENARIO_NAMES[scenario]} (ECDSA scenario) does not apply",
        "defect_tag": None,
    }


def execute_tc(tc: dict, token_manager: TokenManager, private_key, session_vars: dict, dry_run: bool) -> dict:
    endpoint = tc["endpoint"]
    scenario = tc["scenario"]
    tc_id    = tc["tc_id"]

    # Scenarios 7 and 8 are not applicable on unsigned endpoints
    if scenario in (7, 8) and not endpoint["signed"]:
        return _not_applicable(tc_id, endpoint, scenario)

    # Resolve path variables
    path_template = endpoint["path"]
    resolved_path = path_template
    blocked_reason = None

    for var in endpoint["vars"]:
        if var == "cardId":
            val = session_vars.get("card_id")
            if not val:
                return _blocked(tc_id, endpoint, scenario, "Phase 0g: card_id not available — issuance failed on port 8082")

        elif var == "bankId":
            val = session_vars.get("bankId")
            if not val:
                return _blocked(tc_id, endpoint, scenario, "Phase 0f: bankId not loaded from session IDs")

        elif var == "affiliateId":
            val = session_vars.get("affiliateId")
            if not val:
                return _blocked(tc_id, endpoint, scenario, "Phase 0f: affiliateId not loaded from session IDs")

        elif var == "loadRequestId":
            val = session_vars.get("load_request_id")
            if not val:
                if scenario == 9:
                    return _blocked(tc_id, endpoint, scenario, "Phase 0i: load_request_id not available — load-request minting failed")
                else:
                    val = str(uuid.uuid4())  # dummy UUID for auth-negative TCs; auth should reject before ID lookup

        elif var == "limitRequestId":
            val = session_vars.get("limit_request_id")
            if not val:
                if scenario == 9:
                    return _blocked(tc_id, endpoint, scenario, "Phase 0j: limit_request_id not available — limit-request minting failed")
                else:
                    val = str(uuid.uuid4())  # dummy UUID for auth-negative TCs

        else:
            val = str(uuid.uuid4())

        resolved_path = resolved_path.replace(f"{{{var}}}", str(val))

    full_url   = BASE_URL + resolved_path
    query_str  = ""  # no signed endpoints have query params in this matrix

    # Build body
    body_bytes: bytes = b""
    body_dict = None
    if endpoint["body_key"] is not None:
        body_dict  = _build_body(endpoint["body_key"], session_vars)
        body_bytes = json.dumps(body_dict, separators=(",", ":")).encode("utf-8")

    # Build headers
    headers = _build_headers(scenario, endpoint, body_bytes, resolved_path, query_str, token_manager, private_key)

    signing_included = (
        endpoint["signed"]
        and scenario not in (1, 7)  # 1=no auth, 7=missing sig on purpose
        and "X-IAM-Signature" in headers
    )

    if dry_run:
        return {
            "tc_id": tc_id,
            "execution_status": "DRY_RUN",
            "endpoint": f"{endpoint['method']} {endpoint['path']}",
            "scenario": SCENARIO_NAMES[scenario],
            "auth_layer": "bearer_and_signature" if endpoint["signed"] else "bearer_only",
            "signing_included": signing_included,
            "auth_payload": _auth_payload_tag(scenario, endpoint["signed"]),
            "url": full_url,
            "headers_keys": list(headers.keys()),
            "body_preview": body_dict,
            "evaluation_reason": "dry_run — no HTTP call made",
            "defect_tag": None,
        }

    # Execute HTTP request
    start = time.time()
    try:
        resp = requests.request(
            method=endpoint["method"],
            url=full_url,
            headers=headers,
            data=body_bytes if body_bytes else None,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        try:
            resp_body = resp.json()
        except Exception:
            resp_body = resp.text[:600] if resp.text else None

        exec_status, eval_reason, defect_tag = _classify(scenario, resp.status_code)

        return {
            "tc_id": tc_id,
            "endpoint": f"{endpoint['method']} {endpoint['path']}",
            "scenario": SCENARIO_NAMES[scenario],
            "auth_layer": "bearer_and_signature" if endpoint["signed"] else "bearer_only",
            "signing_included": signing_included,
            "auth_payload": _auth_payload_tag(scenario, endpoint["signed"]),
            "input_data": {
                "method":       endpoint["method"],
                "url":          full_url,
                "headers_sent": _redact_auth(headers),
                "body":         body_dict,
            },
            "response_data": {
                "status_code": resp.status_code,
                "elapsed_ms":  elapsed_ms,
                "body":        resp_body,
            },
            "execution_status":  exec_status,
            "evaluation_reason": eval_reason,
            "defect_tag":        defect_tag,
        }

    except requests.exceptions.Timeout:
        return _blocked(tc_id, endpoint, scenario, f"TIMEOUT: request timed out after {REQUEST_TIMEOUT}s at {full_url}")
    except requests.exceptions.ConnectionError as e:
        return _blocked(tc_id, endpoint, scenario, f"CONNECTION_ERROR: {e}")
    except Exception as e:
        return _blocked(tc_id, endpoint, scenario, f"{type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 0 — Pre-flight provisioning
# ─────────────────────────────────────────────────────────────────────────────
def run_phase0(token_manager: TokenManager, private_key, setup_log: list) -> dict:
    session_vars: dict = {}

    def log(step: str, status: str, msg: str, detail: str = None):
        entry = {"step": step, "status": status, "message": msg}
        if detail:
            entry["detail"] = str(detail)[:300]
        setup_log.append(entry)
        icon = "OK" if status == "OK" else ("WARN" if status == "WARN" else status)
        print(f"  [{step}] {icon}: {msg}", flush=True)
        if detail:
            print(f"  [{step}]      body: {detail}", flush=True)

    # 0f — Load session IDs
    try:
        with open(SESSION_IDS_PATH, "r", encoding="utf-8") as f:
            ids = json.load(f)
        session_vars["affiliateId"]    = ids.get("affiliateId")
        session_vars["bankId"]         = ids.get("bankId")
        session_vars["customerId"]     = CUSTOMER_ID   # UUID format required by port 8082
        session_vars["productId"]      = PRODUCT_ID
        session_vars["seed_card_id"]   = ids.get("cardId")  # fallback if issuance fails on port 8082
        log("0f", "OK", f"Loaded affiliateId={session_vars['affiliateId']}  bankId={session_vars['bankId']}  customerId={session_vars['customerId']}  productId={session_vars['productId']}  seed_card_id={session_vars['seed_card_id']}")
    except Exception as e:
        print(f"\n  ABORT: Cannot load session IDs from {SESSION_IDS_PATH}: {e}", flush=True)
        raise SystemExit(1)

    # Pre-flight gate — GET /auth/me: confirm auth is evaluating requests at all
    gate_path = "/api/v1/auth/me"
    print(f"\n  [pre-flight gate] Probing {gate_path} ...", flush=True)

    # Gate A: valid credentials
    try:
        r = requests.get(
            BASE_URL + gate_path,
            headers={"Authorization": f"Bearer {token_manager.get_cards()}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        log("gate-valid-auth", "OK" if r.status_code < 500 else "WARN",
            f"/auth/me with valid Bearer → HTTP {r.status_code}",
            r.text[:300])
        if r.status_code >= 500:
            print(f"\n  !! WARNING: /auth/me returned {r.status_code} with valid credentials.", flush=True)
            print("     Port 8082 may be returning 5xx regardless of auth state.", flush=True)
            print("     Results may not cleanly isolate auth enforcement. Use --force to continue.", flush=True)
    except Exception as e:
        log("gate-valid-auth", "WARN", f"/auth/me valid-auth probe failed: {e}")

    # Gate B: no credentials
    try:
        r_no = requests.get(BASE_URL + gate_path, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
        log("gate-no-auth", "OK" if r_no.status_code in (401, 403) else "WARN",
            f"/auth/me with no auth → HTTP {r_no.status_code}",
            r_no.text[:300])
        if r_no.status_code not in (401, 403):
            print(f"\n  !! WARNING: /auth/me returned {r_no.status_code} without any auth.", flush=True)
            print("     Auth may NOT be enforced on port 8082 (same as D-CARDS-1 on port 8080).", flush=True)
            print("     Auth-negative TCs will likely FAIL (silent_accept). This is the defect we're documenting.", flush=True)
    except Exception as e:
        log("gate-no-auth", "WARN", f"/auth/me no-auth probe failed: {e}")

    print("", flush=True)

    # 0g — Acquire a usable card (issuance → live query → static seed, in order)
    session_vars["card_id"] = None

    # Strategy 1: mint fresh card via issuance
    iss_path  = "/api/v1/cards/issuance"
    iss_body  = {
        "requestContext": _make_request_context(session_vars),
        "customer": {
            "customerId":      session_vars["customerId"],
            "embeddedPayload": {},
        },
        "issuance": {
            "bankId":      session_vars["bankId"],
            "productId":   session_vars["productId"],
            "productType": "VIRTUAL",
            "currency":    "NGN",
        },
    }
    iss_bytes = json.dumps(iss_body, separators=(",", ":")).encode("utf-8")
    sig, ts, nonce = sign_request("POST", iss_path, "", iss_bytes, private_key)
    try:
        r = requests.post(
            BASE_URL + iss_path,
            headers={
                "Authorization":   f"Bearer {token_manager.get_cards()}",
                "Content-Type":    "application/json",
                "Accept":          "application/json",
                "X-IAM-Signature": sig,
                "X-IAM-Timestamp": ts,
                "X-IAM-Nonce":     nonce,
            },
            data=iss_bytes,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code in (200, 201):
            data     = r.json()
            card_id  = data.get("cardId") or data.get("id") or _find_nested(data, "cardId")
            session_vars["card_id"] = card_id
            log("0g", "OK", f"Card minted via issuance: {card_id}")
        else:
            log("0g", "WARN", f"Issuance HTTP {r.status_code} -- falling back to live card query", r.text[:400])
    except Exception as e:
        log("0g", "WARN", f"Issuance request failed: {e} -- falling back to live card query")

    # Strategy 2: query live cards list for an ACTIVE card on our bankId
    if not session_vars["card_id"]:
        try:
            list_r = requests.get(
                f"{BASE_URL}/api/v1/cards",
                headers={"Authorization": f"Bearer {token_manager.get_cards()}", "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            if list_r.status_code == 200:
                cards   = list_r.json() if isinstance(list_r.json(), list) else []
                our_bank      = session_vars.get("bankId", "")
                our_affiliate = session_vars.get("affiliateId", "")
                # Prefer ACTIVE over FROZEN; same affiliate preferred over cross-affiliate
                def _card_pool(status):
                    return [c for c in cards
                            if c.get("status") == status
                            and c.get("bankId") == our_bank
                            and c.get("productType") == "VIRTUAL"
                            and c.get("customerId")   # skip orphaned cards with no customer
                            and c.get("maskedPan")]    # skip cards with no PAN
                candidates = [c for c in _card_pool("ACTIVE") if c.get("affiliateId") == our_affiliate]
                if not candidates:
                    candidates = _card_pool("ACTIVE")
                    if candidates:
                        log("0g-live", "WARN",
                            f"No ACTIVE VIRTUAL cards on our affiliateId — using cross-affiliate card (may affect 500 vs 401 on invalid-token scenarios)")
                if not candidates:
                    candidates = _card_pool("FROZEN")
                    if candidates:
                        log("0g-live", "WARN",
                            f"No ACTIVE VIRTUAL cards available — falling back to FROZEN card (auth tests still valid; happy_path may return 4xx)")
                if candidates:
                    # sort newest-first so CTERM's side-effect burns the freshest card last
                    candidates.sort(key=lambda c: c.get("issuedAt", ""), reverse=True)
                    # prefer NGN to match runner defaults
                    ngn = [c for c in candidates if (c.get("funding") or {}).get("currency") == "NGN" or c.get("currency") == "NGN"]
                    best = (ngn or candidates)[0]
                    picked = best["cardId"]
                    session_vars["card_id"] = picked
                    # override affiliateId so requestContext matches card's owner — prevents 500 on write ops
                    card_aff = best.get("affiliateId", "")
                    if card_aff and card_aff != session_vars.get("affiliateId"):
                        session_vars["affiliateId"] = card_aff
                    log("0g-live", "OK", f"Live query picked {picked} status={best.get('status')} aff={card_aff} issuedAt={best.get('issuedAt','')[:10]} pool={len(candidates)}")
                else:
                    log("0g-live", "WARN", f"Live query returned no usable VIRTUAL cards on bankId {our_bank}")
            else:
                log("0g-live", "WARN", f"Card list HTTP {list_r.status_code}", list_r.text[:200])
        except Exception as e:
            log("0g-live", "WARN", f"Live card query failed: {e}")

    # Strategy 3: static seed from session_ids.json (last resort)
    if not session_vars["card_id"]:
        seed_card_id = session_vars.get("seed_card_id")
        if seed_card_id:
            try:
                probe_r = requests.get(
                    f"{BASE_URL}/api/v1/cards/{seed_card_id}",
                    headers={"Authorization": f"Bearer {token_manager.get_cards()}", "Accept": "application/json"},
                    timeout=REQUEST_TIMEOUT,
                )
                if probe_r.status_code == 200:
                    card_data = probe_r.json()
                    if card_data.get("status") == "ACTIVE":
                        session_vars["card_id"] = seed_card_id
                        log("0g-seed", "OK", f"Static seed card ACTIVE and accessible: {seed_card_id}")
                    else:
                        log("0g-seed", "WARN",
                            f"Static seed card status={card_data.get('status')} -- not ACTIVE, card-dependent TCs may fail")
                        session_vars["card_id"] = seed_card_id  # use anyway; status noted
                else:
                    log("0g-seed", "WARN",
                        f"Static seed card inaccessible (HTTP {probe_r.status_code}) -- card-dependent TCs BLOCKED")
            except Exception as e:
                log("0g-seed", "WARN", f"Static seed probe failed: {e}")

    # 0h -- Probe card (verify it's queryable); capture currency for use in 0i/0j
    session_vars["card_currency"] = "NGN"  # default; overwritten if probe succeeds
    if session_vars.get("card_id"):
        try:
            r = requests.get(
                f"{BASE_URL}/api/v1/cards/{session_vars['card_id']}",
                headers={"Authorization": f"Bearer {token_manager.get_cards()}", "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                card_data = r.json()
                currency = (
                    card_data.get("currency")
                    or (card_data.get("funding") or {}).get("currency")
                    or _find_nested(card_data, "currency")
                    or "NGN"
                )
                session_vars["card_currency"] = currency
                # Use card's own affiliateId in requestContext so write ops don't get 500 on mismatch
                card_aff = card_data.get("affiliateId")
                if card_aff and card_aff != session_vars.get("affiliateId"):
                    session_vars["affiliateId"] = card_aff
                    log("0h", "OK", f"Card probe HTTP 200 — currency={currency}  affiliateId overridden to card's={card_aff}")
                else:
                    log("0h", "OK", f"Card probe HTTP 200 — currency={currency}")
            else:
                log("0h", "WARN", f"Card probe HTTP {r.status_code}")
        except Exception as e:
            log("0h", "WARN", f"Card probe failed: {e}")

    # 0i — Mint load-request (needed for CLAPPR + CLGET happy_path)
    if session_vars.get("card_id"):
        lr_path  = f"/api/v1/cards/{session_vars['card_id']}/load-requests"
        lr_body  = {
            "requestContext": _make_request_context(session_vars),
            "amount": {"value": 1000.0, "currency": session_vars.get("card_currency", "NGN")},
        }
        lr_bytes = json.dumps(lr_body, separators=(",", ":")).encode("utf-8")
        sig, ts, nonce = sign_request("POST", lr_path, "", lr_bytes, private_key)
        try:
            r = requests.post(
                BASE_URL + lr_path,
                headers={
                    "Authorization":   f"Bearer {token_manager.get_cards()}",
                    "Content-Type":    "application/json",
                    "Accept":          "application/json",
                    "X-IAM-Signature": sig,
                    "X-IAM-Timestamp": ts,
                    "X-IAM-Nonce":     nonce,
                },
                data=lr_bytes,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code in (200, 201):
                data = r.json()
                load_req_id = (
                    data.get("loadRequestId")
                    or data.get("id")
                    or _find_nested(data, "loadRequestId")
                )
                session_vars["load_request_id"] = load_req_id
                log("0i", "OK", f"Load-request minted: {load_req_id}")
            else:
                log("0i", "WARN", f"Load-request HTTP {r.status_code} — CLAPPR/CLGET happy_path will be BLOCKED", r.text[:200])
                session_vars["load_request_id"] = None
        except Exception as e:
            log("0i", "WARN", f"Load-request minting failed: {e}")
            session_vars["load_request_id"] = None
    else:
        session_vars["load_request_id"] = None
        log("0i", "SKIP", "No card_id — load-request minting skipped")

    # 0j — Mint limit-request (needed for OPLIM happy_path)
    if session_vars.get("card_id"):
        lim_path  = f"/api/v1/cards/{session_vars['card_id']}/limit-requests"
        lim_body  = {
            "requestContext":  _make_request_context(session_vars),
            "requestedLimit":  {"amount": 50000.0, "currency": session_vars.get("card_currency", "NGN")},
            "reason":          "auth_runner_probe",
        }
        lim_bytes = json.dumps(lim_body, separators=(",", ":")).encode("utf-8")
        sig, ts, nonce = sign_request("POST", lim_path, "", lim_bytes, private_key)
        try:
            r = requests.post(
                BASE_URL + lim_path,
                headers={
                    "Authorization":   f"Bearer {token_manager.get_cards()}",
                    "Content-Type":    "application/json",
                    "Accept":          "application/json",
                    "X-IAM-Signature": sig,
                    "X-IAM-Timestamp": ts,
                    "X-IAM-Nonce":     nonce,
                },
                data=lim_bytes,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code in (200, 201):
                data = r.json()
                lim_req_id = (
                    data.get("limitRequestId")
                    or data.get("id")
                    or _find_nested(data, "limitRequestId")
                )
                session_vars["limit_request_id"] = lim_req_id
                log("0j", "OK", f"Limit-request minted: {lim_req_id}")
            else:
                log("0j", "WARN", f"Limit-request HTTP {r.status_code} — OPLIM happy_path will be BLOCKED", r.text[:200])
                session_vars["limit_request_id"] = None
        except Exception as e:
            log("0j", "WARN", f"Limit-request minting failed: {e}")
            session_vars["limit_request_id"] = None
    else:
        session_vars["limit_request_id"] = None
        log("0j", "SKIP", "No card_id — limit-request minting skipped")

    return session_vars


# ─────────────────────────────────────────────────────────────────────────────
# TC PLAN BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_tc_plan(
    scenarios_filter: Optional[list] = None,
    endpoint_filter: Optional[str] = None,
) -> list:
    active_scenarios = scenarios_filter or list(range(1, 10))
    tcs = []

    for ep in ENDPOINTS:
        if endpoint_filter and ep["code"] != endpoint_filter:
            continue
        for sc_num in active_scenarios:
            tcs.append({
                "tc_id":         f"AUTH-CARDS-{ep['code']}-SC{sc_num:02d}",
                "endpoint":      ep,
                "scenario":      sc_num,
                "scenario_name": SCENARIO_NAMES[sc_num],
            })

    return tcs


# ─────────────────────────────────────────────────────────────────────────────
# YAML REPORT WRITER
# ─────────────────────────────────────────────────────────────────────────────
def _ys(s) -> str:
    """Safe YAML scalar — double-quote if the value contains YAML-special chars."""
    s = str(s)
    need_quote = any(c in s for c in (':', '#', '{', '}', '[', ']', ',', '&', '*',
                                       '?', '|', '-', '<', '>', '=', '!', '%', '@',
                                       '`', '"', "'", '\n', '\r'))
    if need_quote or (s and s[0] in ' \t'):
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '') + '"'
    return s or '""'


def write_yaml_report(
    setup_log: list,
    results: list,
    session_vars: dict,
    args,
    start_time: datetime,
) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts    = datetime.now().strftime("%Y%m%d-%H%M%S")
    path  = os.path.join(REPORT_DIR, f"cards_auth_report_{ts}.yaml")

    passed         = sum(1 for r in results if r.get("execution_status") == "PASS")
    failed         = sum(1 for r in results if r.get("execution_status") == "FAIL")
    blocked        = sum(1 for r in results if r.get("execution_status") == "BLOCKED")
    na             = sum(1 for r in results if r.get("execution_status") == "NOT_APPLICABLE")
    silent_accept  = sum(1 for r in results if r.get("defect_tag") == "D-CARDS-1")
    sig_bypass     = sum(1 for r in results if r.get("defect_tag") == "D-CARDS-SIG-1")
    valid_rejected = sum(1 for r in results if r.get("defect_tag") == "D-CARDS-AUTH-REJECT")

    L = []
    def ln(s=""): L.append(s)

    ln("report_metadata:")
    ln(f"  service: cards_auth")
    ln(f"  run_mode: cards_auth_runner_v1")
    ln(f"  base_url: {_ys(BASE_URL)}")
    ln(f"  iam_url: {_ys(IAM_URL)}")
    ln(f"  phase0_card_id: {_ys(str(session_vars.get('card_id', 'null')))}")
    ln(f"  phase0_load_request_id: {_ys(str(session_vars.get('load_request_id', 'null')))}")
    ln(f"  phase0_limit_request_id: {_ys(str(session_vars.get('limit_request_id', 'null')))}")
    ln(f"  total_test_cases: {len(results)}")
    ln(f"  passed_test_cases: {passed}")
    ln(f"  failed_test_cases: {failed}")
    ln(f"  blocked_test_cases: {blocked}")
    ln(f"  not_applicable_tcs: {na}")
    ln(f"  silent_accept_count: {silent_accept}")
    ln(f"  signature_bypass_count: {sig_bypass}")
    ln(f"  valid_creds_rejected_count: {valid_rejected}")
    ln(f"  run_started_at: {start_time.isoformat()}")
    ln(f"  run_completed_at: {datetime.now(timezone.utc).isoformat()}")
    ln(f"  dry_run: {args.dry_run}")
    ln()

    ln("setup_steps:")
    for entry in setup_log:
        ln(f"  - step: {entry['step']}")
        ln(f"    status: {entry['status']}")
        ln(f"    message: {_ys(entry['message'])}")
        if entry.get("detail"):
            ln(f"    detail: {_ys(entry['detail'])}")
    ln()

    ln("detailed_test_cases:")
    for r in results:
        ln(f"  - test_case_id: {r.get('tc_id', 'unknown')}")
        ln(f"    endpoint: {_ys(r.get('endpoint', ''))}")
        ln(f"    scenario: {r.get('scenario', '')}")
        ln(f"    auth_layer: {r.get('auth_layer', '')}")
        ln(f"    signing_included: {r.get('signing_included', False)}")
        ln(f"    auth_payload: {r.get('auth_payload', 'n/a')}")

        inp = r.get("input_data") or {}
        if inp:
            ln(f"    input_data:")
            ln(f"      method: {inp.get('method', '')}")
            ln(f"      url: {_ys(str(inp.get('url', '')))}")
            headers_str = json.dumps(inp.get("headers_sent", {}))
            ln(f"      headers_sent: {_ys(headers_str)}")
            if inp.get("body") is not None:
                ln(f"      body: {_ys(json.dumps(inp['body']))}")

        resp = r.get("response_data") or {}
        if resp:
            ln(f"    response_data:")
            ln(f"      status_code: {resp.get('status_code', 'null')}")
            ln(f"      elapsed_ms: {resp.get('elapsed_ms', 'null')}")
            body_val = resp.get("body")
            if body_val is not None:
                try:
                    ln(f"      body: {_ys(json.dumps(body_val))}")
                except Exception:
                    ln(f"      body: {_ys(str(body_val)[:600])}")

        ln(f"    execution_status: {r.get('execution_status', 'UNKNOWN')}")
        ln(f"    evaluation_reason: {_ys(r.get('evaluation_reason', ''))}")
        if r.get("defect_tag"):
            ln(f"    defect_tag: {r['defect_tag']}")
        if r.get("error_type"):
            ln(f"    error_type: {r['error_type']}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    return path


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Cards Authentication Test Runner — targets port 8082")
    parser.add_argument("--dry-run",   action="store_true",  help="Print TC plan without HTTP calls")
    parser.add_argument("--workers",   type=int, default=5,  help="Thread pool size (default: 5)")
    parser.add_argument("--scenarios", type=str, default=None, help="Comma-separated scenario numbers e.g. 1,2,9")
    parser.add_argument("--endpoint",  type=str, default=None, help="Run single endpoint code e.g. AUTH-01")
    args = parser.parse_args()

    scenarios_filter = None
    if args.scenarios:
        try:
            scenarios_filter = [int(s.strip()) for s in args.scenarios.split(",")]
            invalid = [s for s in scenarios_filter if s not in range(1, 10)]
            if invalid:
                print(f"Error: invalid scenario numbers {invalid} — must be 1-9")
                sys.exit(1)
        except ValueError:
            print("Error: --scenarios must be comma-separated integers e.g. 1,2,9")
            sys.exit(1)

    start_time = datetime.now(timezone.utc)
    setup_log: list = []

    print("=" * 70, flush=True)
    print("  Kardit Cards Auth Runner", flush=True)
    print(f"  Target  : {BASE_URL}", flush=True)
    print(f"  IAM     : {IAM_URL}", flush=True)
    print(f"  Started : {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", flush=True)
    print("=" * 70, flush=True)

    # ── Dry-run fast path — no HTTP calls needed ──────────────────────────
    if args.dry_run:
        all_tcs = build_tc_plan(scenarios_filter, args.endpoint)
        print(f"\n[DRY RUN] {len(all_tcs)} test cases planned:\n", flush=True)
        for tc in all_tcs:
            ep      = tc["endpoint"]
            sig_tag = "[signed]  " if ep["signed"] else "[unsigned]"
            print(f"  {tc['tc_id']:<37} {tc['scenario_name']:<26} {sig_tag}  {ep['method']} {ep['path']}", flush=True)
        print(f"\nTotal: {len(all_tcs)} TCs (dry-run — no HTTP calls made)", flush=True)
        return

    # Phase 0a — validate required config
    print("\n[Phase 0] Pre-flight checks ...", flush=True)
    if not CARDS_CLIENT_ID or not CARDS_CLIENT_SECRET:
        print("  ABORT: CARDS_CLIENT_ID or CARDS_CLIENT_SECRET is empty", flush=True)
        sys.exit(1)
    setup_log.append({"step": "0a", "status": "OK", "message": "Credentials configured"})
    print("  [0a] OK: Credentials configured", flush=True)

    # Phase 0b/0c — mint tokens
    token_manager = TokenManager()
    print("  [0b-0c] Minting Cards + Bank tokens ...", flush=True)
    try:
        token_manager.init()
        setup_log.append({"step": "0b-0c", "status": "OK", "message": "Cards and Bank tokens minted successfully"})
        print("  [0b-0c] OK: Both tokens acquired", flush=True)
    except Exception as e:
        print(f"\n  ABORT: Token minting failed: {e}", flush=True)
        print("  Check: IAM reachable from this machine? Client credentials correct?", flush=True)
        setup_log.append({"step": "0b-0c", "status": "ABORT", "message": str(e)})
        sys.exit(1)

    # Phase 0d — load ECDSA key
    print("  [0d] Loading EC P-256 signing key ...", flush=True)
    try:
        private_key = load_private_key(SIGNING_KEY_PEM)
        setup_log.append({"step": "0d", "status": "OK", "message": "EC P-256 PKCS8 private key loaded"})
        print("  [0d] OK: Signing key loaded", flush=True)
    except Exception as e:
        print(f"\n  ABORT: Cannot load signing key: {e}", flush=True)
        setup_log.append({"step": "0d", "status": "ABORT", "message": str(e)})
        sys.exit(1)

    # Phase 0e — start background refresh
    token_manager.start_background_refresh()
    setup_log.append({"step": "0e", "status": "OK", "message": "Background token refresh thread started (540s interval)"})
    print("  [0e] OK: Token refresh thread started", flush=True)

    # Phases 0f-0j
    session_vars = run_phase0(token_manager, private_key, setup_log)

    # Build TC plan
    all_tcs = build_tc_plan(scenarios_filter, args.endpoint)
    print(f"\n[TC Plan] {len(all_tcs)} test cases planned", flush=True)
    if args.endpoint:
        print(f"  Scope   : endpoint={args.endpoint}", flush=True)
    if scenarios_filter:
        names = [SCENARIO_NAMES[s] for s in scenarios_filter]
        print(f"  Scope   : scenarios={names}", flush=True)

    # Execute TCs
    print(f"\n[Execution] {len(all_tcs)} TCs | {args.workers} workers ...\n", flush=True)
    results = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_tc = {
            executor.submit(execute_tc, tc, token_manager, private_key, session_vars, False): tc
            for tc in all_tcs
        }
        done_count = 0
        for future in as_completed(future_to_tc):
            try:
                result = future.result()
            except Exception as e:
                tc = future_to_tc[future]
                result = _blocked(tc["tc_id"], tc["endpoint"], tc["scenario"], f"Unhandled executor error: {e}")
            results.append(result)
            done_count += 1

            status       = result.get("execution_status", "?")
            tc_id        = result.get("tc_id", "?")
            scenario     = result.get("scenario", "?")
            auth_payload = result.get("auth_payload", "n/a")
            http_code    = result.get("response_data", {}).get("status_code", "-")
            reason       = result.get("evaluation_reason", "")[:50]
            print(f"  [{done_count:3d}/{len(all_tcs)}] {tc_id:<35} [{scenario:<25}] {auth_payload:<28} {status:<15} HTTP {http_code}  {reason}", flush=True)

    # Tally results
    passed         = sum(1 for r in results if r.get("execution_status") == "PASS")
    failed         = sum(1 for r in results if r.get("execution_status") == "FAIL")
    blocked        = sum(1 for r in results if r.get("execution_status") == "BLOCKED")
    na             = sum(1 for r in results if r.get("execution_status") == "NOT_APPLICABLE")
    silent_accept  = sum(1 for r in results if r.get("defect_tag") == "D-CARDS-1")
    sig_bypass     = sum(1 for r in results if r.get("defect_tag") == "D-CARDS-SIG-1")
    valid_rejected = sum(1 for r in results if r.get("defect_tag") == "D-CARDS-AUTH-REJECT")

    print(f"\n{'=' * 70}", flush=True)
    print(f"  RESULTS  {len(results)} TCs — PASS: {passed}  FAIL: {failed}  BLOCKED: {blocked}  N/A: {na}", flush=True)
    print(f"  D-CARDS-1          (silent_accept Bearer)   : {silent_accept} TCs", flush=True)
    print(f"  D-CARDS-SIG-1      (signature not enforced) : {sig_bypass} TCs", flush=True)
    print(f"  D-CARDS-AUTH-REJECT (valid creds rejected)  : {valid_rejected} TCs", flush=True)
    print(f"{'=' * 70}", flush=True)

    # Write report
    try:
        report_path = write_yaml_report(setup_log, results, session_vars, args, start_time)
        print(f"\n  Report → {report_path}", flush=True)
    except Exception as e:
        print(f"\n  WARN: Failed to write report: {e}", flush=True)
        traceback.print_exc()

    token_manager.stop()


if __name__ == "__main__":
    main()
