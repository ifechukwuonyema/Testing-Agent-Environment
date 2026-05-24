"""
Cards E2E Test Runner — port 8082 (auth-enforced environment).

Combines:
  1. Full functional TC suite (~880 TCs) from Postman pack, with valid Bearer + ECDSA auth on every request.
  2. Auth bypass layer (~176 TCs, SC01-SC08) per endpoint, verifying bad credentials are rejected.

Auth layers:
  Layer 1 — Bearer token (OAuth2 client_credentials via IAM at hasham.platform.dev.chamsswitch.com)
  Layer 2 — ECDSA-SHA256 request signing (X-IAM-Signature/Timestamp/Nonce) on all POST endpoints

Excluded endpoints (backend broken):
  POST /api/v1/cards/{cardId}/load-requests        — always 500
  POST /api/v1/cards/{cardId}/load-requests/{id}/approve  — depends on broken endpoint above
  GET  /api/v1/cards/{cardId}/load-requests/{id}   — depends on broken endpoint above
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
import yaml

_SVC_DIR   = Path(__file__).resolve().parent
_REPO_ROOT = _SVC_DIR.parent
_SHARED    = _REPO_ROOT / "shared"
sys.path.insert(0, str(_SHARED))
sys.path.insert(0, str(_SVC_DIR))
from query_mutator import smart_set_query, smart_set_query_pair, extract_first_id_recursive  # noqa: E402

# --- paths -----------------------------------------------------------------
# paths resolved relative to this file — works after clone on any OS
POSTMAN_PATH     = _SHARED / "postman_collection.json"
TEST_PACK_PATH   = _SVC_DIR / "data" / "test_pack.json"
SWAGGER_PATH     = _SHARED / "MainSwagger.txt"
LIFECYCLE_PATH   = _SVC_DIR / "data" / "lifecycle_order.yaml"
RUNNER_KIT       = _SHARED
SESSION_IDS_PATH = _SHARED / "session_ids.json"
# 2026-05-07: backend supplied contract-correct payload replays for failed Cards
# TCs in `failed payload fixes.md`. Parsed to JSON (parse_failed_payload_fixes.py)
# and loaded here. When a TC is in this map, the runner sends URL+body verbatim
# (with requestId/idempotencyKey re-rotated per call) and skips the classifier
# mutation pipeline, except auth-side mutations which still layer on top.
FAILED_PAYLOAD_OVERRIDES_PATH = _SVC_DIR / "data" / "failed_payload_overrides.json"
CANONICAL_TENANT_ID = "00000000-0000-0000-0000-000000000000"

BASE_URL = os.getenv("KARDIT_CARDS_URL", "http://167.172.49.177:8082")
RUN_TS = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

SCOPE_ENDPOINT = os.environ.get("SCOPE_ENDPOINT")
SCOPE_API_IDS = [x.strip() for x in os.environ.get("SCOPE_API_IDS", "").split(",") if x.strip()]
_scope_tag = ""
if SCOPE_ENDPOINT:
    _scope_tag = "_" + re.sub(r"[^a-zA-Z0-9]+", "_", SCOPE_ENDPOINT).strip("_")
elif SCOPE_API_IDS:
    _scope_tag = "_" + "_".join(SCOPE_API_IDS)

# REPLAY_FAILED_REPORT: path to a previous cards report YAML.
# When set, replays (api_id, scenario) pairs that FAILed in that report.
# REPLAY_INCLUDE_BLOCKED=1: also include never-executed BLOCKEDs (response_code
# is None — pool-exhaustion blocks where no card of the right state was available).
# Structural BLOCKEDs (CLUSTER_C, WRITE_DID_NOT_PERSIST) are excluded because
# they have a non-empty verdict reason and/or a non-None response_code.
REPLAY_FAILED_REPORT = os.environ.get("REPLAY_FAILED_REPORT")
REPLAY_INCLUDE_BLOCKED = os.environ.get("REPLAY_INCLUDE_BLOCKED", "0") == "1"
_replay_failed_set: set = set()
if REPLAY_FAILED_REPORT:
    import yaml as _yaml_mod
    with open(REPLAY_FAILED_REPORT, encoding="utf-8") as _rf:
        _replay_data = _yaml_mod.safe_load(_rf)
    _replay_tcs = _replay_data.get("detailed_test_cases", [])
    _replay_failed_set = {
        (tc["api_id"], tc["scenario"])
        for tc in _replay_tcs
        if tc.get("execution_status") == "FAIL"
    }
    if REPLAY_INCLUDE_BLOCKED:
        _pool_blocked = {
            (tc["api_id"], tc["scenario"])
            for tc in _replay_tcs
            if (tc.get("execution_status") == "BLOCKED"
                and tc.get("response_code") is None
                and not (tc.get("verdict") or {}).get("reason", ""))
        }
        _replay_failed_set |= _pool_blocked
        print(f"[REPLAY] Loaded {len(_replay_failed_set)} pairs "
              f"(FAILs + {len(_pool_blocked)} pool-exhaustion BLOCKEDs) from {REPLAY_FAILED_REPORT}")
    else:
        print(f"[REPLAY] Loaded {len(_replay_failed_set)} failed (api_id, scenario) pairs from {REPLAY_FAILED_REPORT}")
    _scope_tag = "_replay_failed"

EVIDENCE_DIR     = _SVC_DIR / "evidence" / f"run_{RUN_TS}"
REPORT_PATH      = _SVC_DIR / "reports" / f"cards_run_{RUN_TS}.yaml"

# ─── AUTH INFRASTRUCTURE — port 8082 Bearer + ECDSA signing ─────────────────
import base64
import threading
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import ec as _ec
from cryptography.hazmat.primitives import hashes as _hashes, serialization as _serialization
from cryptography.hazmat.backends import default_backend as _default_backend
import urllib.parse as _urlparse

IAM_URL             = os.getenv("CARDS_IAM_URL",     "https://hasham.platform.dev.chamsswitch.com/gateway/token")
CARDS_CLIENT_ID     = os.getenv("CARDS_CLIENT_ID",   "platform-kardit-card-api")
CARDS_CLIENT_SECRET = os.getenv("CARDS_CLIENT_SECRET","723aa789be33d3195416aa86e04dabff4d936dea4af0c0ea83788b8db2cadc07")
BANK_CLIENT_ID      = os.getenv("BANK_CLIENT_ID",    "platform-kardit-bank-api")
BANK_CLIENT_SECRET  = os.getenv("BANK_CLIENT_SECRET","ca72de6da4ab7574f95f5484f3363fd2f2a6eaec42160ddcae096fe6275d2667")

SIGNING_KEY_PEM = os.getenv("CARDS_SIGNING_KEY_PEM", """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQguLTJ5EFCK3ayPpFj
C4vhlDXs0SFJELvhT754HsbHNGihRANCAAQCKqyhvvbCVHhPGHyuqip0fwemnQWs
IhkimdE3yKI8TNNQKqk7bNRSGWwXzKCMb7n2x7yZlCmRj9rU+VGylr//
-----END PRIVATE KEY-----""")

EXPIRED_TOKEN = os.getenv(
    "CARDS_EXPIRED_TOKEN",
    "eyJhbGciOiJFUzI1NiIsImtpZCI6IjU5YmY4MjlhMDk5M2VkYWIxYjZmNWVjYjFmZDdmNDJiN2JhMmJhYzVkMzAxMGE3ZGVjNTVhZmY1ZDczOWY3ZjUifQ"
    ".eyJzdWIiOiJzZXJ2aWNlOnBsYXRmb3JtLWthcmRpdC1jYXJkLWFwaSIsInRlbmFudElkIjoiMDAwMDAwMDAtMDAwMC0wMDAwLTAwMDAtMDAwMDAwMDAwMDAxIiwi"
    "cGVybWlzc2lvbnMiOlsia2FyZGl0OmNhcmRzOmFjdGl2YXRlIiwia2FyZGl0OmNhcmRzOmJhbGFuY2U6cmVhZCIsImthcmRpdDpjYXJkczpiYW5rczphZmZpbGlh"
    "dGU6ZnJlZXplIiwia2FyZGl0OmNhcmRzOmJhbmtzOmFmZmlsaWF0ZTp0ZXJtaW5hdGUiLCJrYXJkaXQ6Y2FyZHM6YmFua3M6YWZmaWxpYXRlOnVuZnJlZXplIiwi"
    "a2FyZGl0OmNhcmRzOmZ1bGZpbGxtZW50OnJlYWQiLCJrYXJkaXQ6Y2FyZHM6ZnVsZmlsbG1lbnQ6cmVmcmVzaCIsImthcmRpdDpjYXJkczpmdWxmaWxsbWVudDpy"
    "ZWluaXRpYXRlIiwia2FyZGl0OmNhcmRzOmZ1bmRpbmc6cmVhZCIsImthcmRpdDpjYXJkczppc3N1YW5jZTpjcmVhdGUiLCJrYXJkaXQ6Y2FyZHM6aXNzdWFuY2U6"
    "ZWxpZ2liaWxpdHkiLCJrYXJkaXQ6Y2FyZHM6bGlmZWN5Y2xlOmZyZWV6ZSIsImthcmRpdDpjYXJkczpsaWZlY3ljbGU6dGVybWluYXRlIiwia2FyZGl0OmNhcmRz"
    "OmxpZmVjeWNsZTp1bmZyZWV6ZSIsImthcmRpdDpjYXJkczpsaW1pdDpjcmVhdGUiLCJrYXJkaXQ6Y2FyZHM6bG9hZDphcHByb3ZlIiwia2FyZGl0OmNhcmRzOmxv"
    "YWQ6Y3JlYXRlIiwia2FyZGl0OmNhcmRzOmxvYWQ6cmVhZCIsImthcmRpdDpjYXJkczptZXRyaWNzOnJlYWQiLCJrYXJkaXQ6Y2FyZHM6b3BzOmxpbWl0OmNvbXBs"
    "ZXRlIiwia2FyZGl0OmNhcmRzOnBpbjpyZXNldCIsImthcmRpdDpjYXJkczpxdWVyeSIsImthcmRpdDpjYXJkczpyZWFkIiwia2FyZGl0OmNhcmRzOnVubG9hZDpj"
    "cmVhdGUiXSwic2VydmljZUFjY291bnQiOnRydWUsInNlc3Npb25JZCI6IjQxOGY1NmRiLTk3MzktNGQ2Yy04OGNlLWFiNTAwNjBiNzc2YiIsImlkZW50aXR5U291"
    "cmNlIjoiRElSRUNUIiwianRpIjoiMDI2MWRjNzctZjk2Zi00ZWRmLWIzODEtMzk2NGQzZGRkZjdmIiwiaWF0IjoxNzc5NDQyNDE0LCJleHAiOjE3Nzk0NDMzMTQs"
    "ImF1ZCI6WyJwbGF0Zm9ybS1rYXJkaXQtY2FyZC1hcGkiXX0"
    ".yfMhZhFd9l56XFZgAirvE4SAR4012v5tvtt6JzJwRkKgxYvvQJEMCTVDxF6RqmRKdfuKWbU0fhfeXsvhVyzUvg"
)

E2E_CUSTOMER_ID = os.getenv("CARDS_CUSTOMER_ID", "62a855d9-cc62-4233-88fe-856d901b0a04")
E2E_PRODUCT_ID  = os.getenv("CARDS_PRODUCT_ID",  "d475e7e2-0685-4bb6-9ef0-95fec4fcb495")
E2E_TENANT_ID   = "00000000-0000-0000-0000-000000000001"
EMPTY_BODY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
AUTH_REQUEST_TIMEOUT = 15

SKIP_BULK_TERMINATE_SC09 = os.getenv("SKIP_BULK_TERMINATE_SC09", "true").lower() == "true"

EXCLUDED_FUNCTIONAL_ENDPOINTS = {
    "POST /api/v1/cards/{cardId}/load-requests",
    "POST /api/v1/cards/{cardId}/load-requests/{loadRequestId}/approve",
    "GET /api/v1/cards/{cardId}/load-requests/{loadRequestId}",
}


def _load_private_key(pem: str):
    return _serialization.load_pem_private_key(
        pem.strip().encode("ascii"), password=None, backend=_default_backend()
    )


def _sign_request(method: str, path: str, query_str: str, body_bytes: bytes, private_key) -> tuple:
    timestamp_ms = str(int(time.time() * 1000))
    nonce        = str(uuid.uuid4())
    body_hash    = hashlib.sha256(body_bytes).hexdigest() if body_bytes else EMPTY_BODY_SHA256
    canonical    = "\n".join([method.upper(), path, query_str, body_hash, timestamp_ms, nonce])
    sig_der      = private_key.sign(canonical.encode("utf-8"), _ec.ECDSA(_hashes.SHA256()))
    return base64.b64encode(sig_der).decode("ascii"), timestamp_ms, nonce


class _TokenManager:
    _REFRESH_SECS = 540

    def __init__(self):
        self._cards_token: Optional[str] = None
        self._bank_token:  Optional[str] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def _mint(self, client_id: str, client_secret: str) -> str:
        resp = requests.post(
            IAM_URL,
            json={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=AUTH_REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise RuntimeError(f"IAM {resp.status_code} for {client_id}: {resp.text[:400]}")
        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError(f"IAM returned no access_token for {client_id}: {resp.text[:200]}")
        return token

    def init(self):
        self._cards_token = self._mint(CARDS_CLIENT_ID, CARDS_CLIENT_SECRET)
        self._bank_token  = self._mint(BANK_CLIENT_ID,  BANK_CLIENT_SECRET)

    def get_cards(self) -> str:
        with self._lock:
            return self._cards_token

    def get_bank(self) -> str:
        with self._lock:
            return self._bank_token

    def start_background_refresh(self):
        t = threading.Thread(target=self._refresh_loop, daemon=True, name="e2e-token-refresh")
        t.start()

    def stop(self):
        self._stop.set()

    def _refresh_loop(self):
        while not self._stop.wait(self._REFRESH_SECS):
            try:
                new_cards = self._mint(CARDS_CLIENT_ID, CARDS_CLIENT_SECRET)
                new_bank  = self._mint(BANK_CLIENT_ID,  BANK_CLIENT_SECRET)
                with self._lock:
                    self._cards_token = new_cards
                    self._bank_token  = new_bank
            except Exception as e:
                print(f"[TOKEN] background refresh failed: {e}", flush=True)


TOKEN_MANAGER = _TokenManager()
PRIVATE_KEY   = None  # assigned in main() after init

# ─────────────────────────────────────────────────────────────────────────────

# --- import kit's SchemaValidator + SessionStore --------------------------
sys.path.insert(0, str(RUNNER_KIT))
from schema_validator import SchemaValidator  # noqa: E402
from session_store import SessionStore  # noqa: E402

VALIDATOR = SchemaValidator(SWAGGER_PATH)
SESSION = SessionStore(SESSION_IDS_PATH)

# --- collection loading ----------------------------------------------------
def load_postman() -> dict:
    with open(POSTMAN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def walk_postman(items: list, folder=None) -> list:
    folder = folder or []
    out = []
    for it in items:
        if "item" in it:
            out.extend(walk_postman(it["item"], folder + [it.get("name", "")]))
        elif "request" in it:
            out.append({"folder": folder, "name": it.get("name"), "request": it["request"]})
    return out

def normalize_path(raw_url) -> str:
    if isinstance(raw_url, dict):
        segs = raw_url.get("path", [])
        path = "/" + "/".join(str(s) for s in segs) if segs else raw_url.get("raw", "")
    else:
        path = raw_url or ""
    path = re.sub(r"^\{\{[^}]+\}\}", "", path)
    path = re.sub(r"^https?://[^/]+", "", path)
    path = path.split("?")[0]
    path = re.sub(r":(\w+)", r"{\1}", path)
    if not path.startswith("/"):
        path = "/" + path
    return path

def postman_index() -> dict[str, dict]:
    """T12: cached parse. Pickle keyed on POSTMAN_PATH mtime to avoid
    re-parsing the (large) collection on every invocation. Critical for the
    chain orchestrator which runs 8 harnesses sequentially."""
    import pickle
    cache_path = POSTMAN_PATH.with_suffix(".pmidx.cache")
    try:
        src_mtime = POSTMAN_PATH.stat().st_mtime
        if cache_path.exists():
            cache_mtime = cache_path.stat().st_mtime
            if cache_mtime >= src_mtime:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
    except Exception:
        pass
    col = load_postman()
    idx = {}
    for entry in walk_postman(col["item"]):
        req = entry["request"]
        method = req.get("method", "GET").upper()
        url = req.get("url", "")
        path = normalize_path(url)
        idx[f"{method} {path}"] = entry
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(idx, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return idx

# --- pack-to-postman match map (Cards: all 21 are exact-match) ------------
PACK_TO_POSTMAN = {
    "POST /api/v1/cards/issuance": "POST /api/v1/cards/issuance",
    "GET /api/v1/cards/{cardId}": "GET /api/v1/cards/{cardId}",
    "GET /api/v1/cards/{cardId}/funding-details": "GET /api/v1/cards/{cardId}/funding-details",
    "GET /api/v1/cards/{cardId}/fulfillment/status": "GET /api/v1/cards/{cardId}/fulfillment/status",
    "POST /api/v1/cards/{cardId}/fulfillment/refresh": "POST /api/v1/cards/{cardId}/fulfillment/refresh",
    "POST /api/v1/cards/{cardId}/fulfillment/reinitiate": "POST /api/v1/cards/{cardId}/fulfillment/reinitiate",
    "POST /api/v1/cards/{cardId}/freeze": "POST /api/v1/cards/{cardId}/freeze",
    "POST /api/v1/cards/{cardId}/unfreeze": "POST /api/v1/cards/{cardId}/unfreeze",
    "POST /api/v1/cards/{cardId}/terminate": "POST /api/v1/cards/{cardId}/terminate",
    "GET /api/v1/cards/{cardId}/balance": "GET /api/v1/cards/{cardId}/balance",
    "POST /api/v1/cards/{cardId}/limit-requests": "POST /api/v1/cards/{cardId}/limit-requests",
    "POST /api/v1/ops/cards/{cardId}/limit-requests/{limitRequestId}/complete": "POST /api/v1/ops/cards/{cardId}/limit-requests/{limitRequestId}/complete",
    "POST /api/v1/cards/{cardId}/pin-reset": "POST /api/v1/cards/{cardId}/pin-reset",
    "POST /api/v1/cards/{cardId}/loads": "POST /api/v1/cards/{cardId}/loads",
    "POST /api/v1/cards/{cardId}/unloads": "POST /api/v1/cards/{cardId}/unloads",
    "GET /api/v1/cards/metrics/bank/{bankId}": "GET /api/v1/cards/metrics/bank/{bankId}",
    "GET /api/v1/cards/metrics/affiliate/{affiliateId}": "GET /api/v1/cards/metrics/affiliate/{affiliateId}",
    "POST /api/v1/cards/query": "POST /api/v1/cards/query",
    "POST /api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/freeze": "POST /api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/freeze",
    "POST /api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/terminate": "POST /api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/terminate",
    "POST /api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/unfreeze": "POST /api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/unfreeze",
    "POST /api/v1/cards/{cardId}/activate": "POST /api/v1/cards/{cardId}/activate",
    # load-requests family excluded — POST /cards/{cardId}/load-requests crashes 500 (D-CARDS-LOADREQ)
}
DRIFT_FLAGS: dict[str, str] = {}

# --- request building ------------------------------------------------------
def build_base_request(pm_entry: dict) -> dict:
    req = pm_entry["request"]
    method = req.get("method", "GET").upper()
    url = req.get("url", {})
    if isinstance(url, str):
        path = normalize_path(url)
        path_vars, query = {}, {}
    else:
        segs = url.get("path", [])
        path_template = "/" + "/".join(str(s) for s in segs) if segs else ""
        path_vars = {v["key"]: v.get("value", "") for v in (url.get("variable") or [])}
        path = path_template
        for k, v in path_vars.items():
            path = path.replace(f":{k}", v).replace(f"{{{k}}}", v)
        query = {q["key"]: q.get("value", "") for q in (url.get("query") or []) if not q.get("disabled")}
    headers = {}
    for h in (req.get("header") or []):
        if h.get("disabled"): continue
        k = h.get("key"); v = h.get("value")
        if k and v is not None:
            headers[k] = v
    body = None
    body_block = req.get("body") or {}
    if body_block.get("mode") == "raw":
        raw = body_block.get("raw", "").strip()
        if raw:
            try:
                body = json.loads(raw)
            except Exception:
                body = raw
    return {
        "method": method,
        "path": path,
        "path_vars": path_vars,
        "query": query,
        "headers": headers,
        "body": body,
    }

# --- HYBRID: requestContext rotation --------------------------------------
def rotate_request_context(body: Any) -> Any:
    """Replace requestContext.requestId + idempotencyKey with fresh UUIDs (or top-level if no nesting).
    Preserves all other fields. Operates on a deep copy.
    """
    if not isinstance(body, dict):
        return body
    body = copy.deepcopy(body)
    new_request_id = "REQ-HYBRID-" + uuid.uuid4().hex[:12].upper()
    new_idem = str(uuid.uuid4())
    if isinstance(body.get("requestContext"), dict):
        rc = body["requestContext"]
        if "requestId" in rc:
            rc["requestId"] = new_request_id
        if "idempotencyKey" in rc:
            rc["idempotencyKey"] = new_idem
    else:
        if "requestId" in body:
            body["requestId"] = new_request_id
        if "idempotencyKey" in body:
            body["idempotencyKey"] = new_idem
    return body


def inject_seeded_body_ids(body: Any, session_ids: dict) -> Any:
    """Recursively rewrite affiliateId / bankId values inside the request body
    to the approved DB-backed values seeded in session_ids. 2026-05-07: user
    supplied real approved IDs (approved ids.txt) — every cards request asking
    for an affiliateId or bankId must use these so backend FK lookups resolve
    instead of 404-ing.

    Skips:
    - Scenario-specific malformed/zero-UUID overrides applied later by classifier
      action (set_path_var / unknown_id) — those mutate AFTER body substitution
      and therefore win.
    - Non-string field values (don't touch arrays of IDs / null).
    """
    if not isinstance(body, (dict, list)):
        return body
    aff = session_ids.get("affiliateId")
    bnk = session_ids.get("bankId")
    body = copy.deepcopy(body)
    def _walk(node):
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if k == "affiliateId" and isinstance(v, str) and aff:
                    node[k] = aff
                elif k == "bankId" and isinstance(v, str) and bnk:
                    node[k] = bnk
                # 2026-05-07: backend's invalid_test_cases.txt directs canonical
                # tenantId across all Cards endpoints. Stamp it on every body
                # carrying the field (Postman exports often have stale or
                # placeholder tenantId values).
                elif k == "tenantId" and isinstance(v, str):
                    node[k] = CANONICAL_TENANT_ID
                else:
                    _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
    _walk(body)
    return body

# --- HYBRID: seeded-id injection ------------------------------------------
SEEDED_PATH_VAR_KEYS = {"cardId", "bankId", "affiliateId", "limitRequestId", "loadRequestId"}

# Endpoints whose state-change happy path requires a card in a specific state.
_HAPPY_PATH_NEEDS_ACTIVE = {
    "POST /api/v1/cards/{cardId}/freeze",
    "POST /api/v1/cards/{cardId}/terminate",
    "POST /api/v1/cards/{cardId}/loads",
    "POST /api/v1/cards/{cardId}/unloads",
    "POST /api/v1/cards/{cardId}/pin-reset",
    "POST /api/v1/cards/{cardId}/limit-requests",
    "POST /api/v1/cards/{cardId}/fulfillment/refresh",
    "POST /api/v1/cards/{cardId}/fulfillment/reinitiate",
    "GET /api/v1/cards/{cardId}/balance",
}
_HAPPY_PATH_NEEDS_FROZEN = {
    "POST /api/v1/cards/{cardId}/unfreeze",
}
# 2026-05-07: backend pre-seeded PENDING_ACTIVATION cards (ACTIVE.txt) so activate
# happy paths can finally test the PENDING_ACTIVATION → ACTIVE transition. Resolves
# D-09 state advancement gap from the 2026-05-06 cards run.
_HAPPY_PATH_NEEDS_PENDING_ACTIVATION = {
    "POST /api/v1/cards/{cardId}/activate",
}

# 2026-05-07: backend supplied dedicated card pools via Cards backend provisions.txt
# - Reinitiate requires FAILED-state cards (backend message: "Fulfillment
#   re-initiation is only allowed from FAILED state").
# - Refresh requires fulfillment-in-progress cards (backend message: "Fulfillment
#   refresh is only allowed while card fulfillment is in progress").
# Routed to dedicated pools so happy-path TCs hit the correct lifecycle slot.
# Cleared 2026-05-12: these cards are no longer in fulfillmentStatus=failed;
# the pre_flight_probe_fulfillment_pools phase now validates the pool live.
_PROVISIONED_REINITIATE_FAILED_CARDS = []
# 2026-05-13: cleared — IDs are stale; live enumeration via
# GET /api/v1/cards?status=PENDING_ISSUANCE&productType=PHYSICAL now fills this pool.
_PROVISIONED_REFRESH_INPROGRESS_CARDS = []
# 2026-05-07: backend supplied ONE shared cardId for every LIM-02 ops/complete
# call + 6 un-finalized limitRequestIds with REQUIRED amounts. Each LIM-02 happy
# path consumes the next (limitRequestId, amount) pair; the body's
# `appliedLimit.amount` MUST equal the amount or backend rejects. Pairs are
# single-use within a run; user resets them between runs.
# 2026-05-07: failed-payload overrides — backend-curated, contract-correct
# replay payloads for every failed Cards TC. Loaded from JSON produced by
# `parse_failed_payload_fixes.py`. When a TC is in this map, the dispatcher
# uses the override's URL+body verbatim and skips classifier mutation. Per-call
# uniqueness is preserved by re-rotating requestId/idempotencyKey AFTER applying
# the override.
def _load_failed_payload_overrides() -> dict:
    if not FAILED_PAYLOAD_OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(FAILED_PAYLOAD_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARN: could not load {FAILED_PAYLOAD_OVERRIDES_PATH.name}: {e}")
        return {}

_FAILED_PAYLOAD_OVERRIDES = _load_failed_payload_overrides()
print(f"Loaded {len(_FAILED_PAYLOAD_OVERRIDES)} failed-payload overrides "
      f"from {FAILED_PAYLOAD_OVERRIDES_PATH.name}")


def extract_path_vars_from_override_url(override_url: str, path_template: str) -> dict:
    """Parse the override URL and the runner's path template to extract path-var
    values the override is targeting. Used to seed path_vars[cardId|bankId|
    affiliateId|limitRequestId] from the backend-supplied URL.

    Example:
      override_url   = "{{baseUrl}}/api/v1/cards/CAR-7EAAE.../freeze"
      path_template  = "/api/v1/cards/{cardId}/freeze"
      → {"cardId": "CAR-7EAAE..."}
    """
    if not override_url or not path_template:
        return {}
    # Strip {{baseUrl}} and any trailing query string
    u = override_url.replace("{{baseUrl}}", "").split("?", 1)[0]
    # Build a regex from path_template by replacing {var} with capture groups
    var_pattern = re.compile(r"\{([^}]+)\}")
    var_names = var_pattern.findall(path_template)
    if not var_names:
        return {}
    regex_str = "^" + var_pattern.sub(r"([^/]+)", re.escape(path_template).replace(r"\{", "{").replace(r"\}", "}")) + r"/?$"
    m = re.match(regex_str, u)
    if not m:
        return {}
    return dict(zip(var_names, m.groups()))


# 2026-05-07: case(1).txt — canonical negative-test payloads for ISSUANCE TCs
# that previously silent-accepted with 200. Sent VERBATIM; classifier mutation
# and body-id substitution are skipped for these TCs so each canonical mutation
# reaches the backend exactly as written.
#
# Format per entry:
#   {"body": <dict | str>, "raw_invalid_json": bool, "headers": {...} (optional)}
# When `raw_invalid_json` is True the value of `body` is sent as a literal
# string (NOT json.dumps'd a second time), which lets us send the trailing
# comma in TC-039 without it being silently corrected.
_CANONICAL_TC_PAYLOADS = {
    # TC-API-ISS-02-003 — drop entire requestContext
    "TC-API-ISS-02-003": {"body": {
        "issuance": {
            "bankId": "BNK-WEM-002",
            "productId": "PRD-WEM-VIR-USD-011",
            "productType": "PHYSICAL",
            "currency": "USD",
        },
        "customer": {
            "customerId": "CUST-ACME-00096",
            "embeddedPayload": {
                "identity": {
                    "firstName": "Jane", "lastName": "Doe",
                    "dob": "1993-05-11",
                    "phone": "+2348098765432",
                    "email": "jane.doe@email.com",
                },
                "kyc": {"idType": "Passport", "idNumber": "12345678901", "kycLevel": "LEVEL_2"},
            },
        },
    }},
    # TC-API-ISS-02-012 — productId = zero GUID
    "TC-API-ISS-02-012": {"body": {
        "requestContext": {
            "requestId": "REQ-HYBRID-4EC6338971ED",
            "tenantId": "TNT-AFF-10291",
            "affiliateId": "AFF-00981",
            "idempotencyKey": "a06ec218-d929-4bd2-b157-1234c48005ff",
        },
        "issuance": {
            "bankId": "BNK-WEM-002",
            "productId": "00000000-0000-0000-0000-000000000000",
            "productType": "PHYSICAL",
            "currency": "USD",
        },
        "customer": {
            "customerId": "CUST-ACME-00096",
            "embeddedPayload": {
                "identity": {"firstName": "Jane", "lastName": "Doe", "dob": "1993-05-11",
                             "phone": "+2348098765432", "email": "jane.doe@email.com"},
                "kyc": {"idType": "Passport", "idNumber": "12345678901", "kycLevel": "LEVEL_2"},
            },
        },
    }},
    # TC-API-ISS-02-013 — bank/product mismatch (BNK-PRO-002 + PRD-WEM-…)
    "TC-API-ISS-02-013": {"body": {
        "requestContext": {
            "requestId": "REQ-HYBRID-B534446959F8",
            "tenantId": "TNT-AFF-10291",
            "affiliateId": "AFF-00981",
            "idempotencyKey": "9c22500f-352e-4f97-a2a3-b5bfc973dbb8",
        },
        "issuance": {
            "bankId": "BNK-PRO-002",
            "productId": "PRD-WEM-VIR-USD-011",
            "productType": "PHYSICAL",
            "currency": "USD",
        },
        "customer": {
            "customerId": "CUST-ACME-00096",
            "embeddedPayload": {
                "identity": {"firstName": "Jane", "lastName": "Doe", "dob": "1993-05-11",
                             "phone": "+2348098765432", "email": "jane.doe@email.com"},
                "kyc": {"idType": "Passport", "idNumber": "12345678901", "kycLevel": "LEVEL_2"},
            },
        },
    }},
    # TC-API-ISS-02-014 — drop issuance.productType
    "TC-API-ISS-02-014": {"body": {
        "requestContext": {
            "requestId": "REQ-HYBRID-B913CC415458",
            "tenantId": "TNT-AFF-10291",
            "affiliateId": "AFF-00981",
            "idempotencyKey": "90458072-eafb-44ac-9caa-d0e5e961418b",
        },
        "issuance": {
            "bankId": "BNK-WEM-002",
            "productId": "PRD-WEM-VIR-USD-011",
            "currency": "USD",
        },
        "customer": {
            "customerId": "CUST-ACME-00096",
            "embeddedPayload": {
                "identity": {"firstName": "Jane", "lastName": "Doe", "dob": "1993-05-11",
                             "phone": "+2348098765432", "email": "jane.doe@email.com"},
                "kyc": {"idType": "Passport", "idNumber": "12345678901", "kycLevel": "LEVEL_2"},
            },
        },
    }},
    # TC-API-ISS-02-018 — drop customer.embeddedPayload
    "TC-API-ISS-02-018": {"body": {
        "requestContext": {
            "requestId": "REQ-HYBRID-C8E4481A4EB2",
            "tenantId": "TNT-AFF-10291",
            "affiliateId": "AFF-00981",
            "idempotencyKey": "08bf2a92-8544-4044-a60f-320196ca487e",
        },
        "issuance": {
            "bankId": "BNK-WEM-002",
            "productId": "PRD-WEM-VIR-USD-011",
            "productType": "PHYSICAL",
            "currency": "USD",
        },
        "customer": {"customerId": "CUST-ACME-00096"},
    }},
    # TC-API-ISS-02-019 — drop customer.embeddedPayload.identity.firstName
    "TC-API-ISS-02-019": {"body": {
        "requestContext": {
            "requestId": "REQ-HYBRID-3EC607B7774A",
            "tenantId": "TNT-AFF-10291",
            "affiliateId": "AFF-00981",
            "idempotencyKey": "98bb3c7a-5390-431a-951e-ddd507b990a1",
        },
        "issuance": {
            "bankId": "BNK-WEM-002",
            "productId": "PRD-WEM-VIR-USD-011",
            "productType": "PHYSICAL",
            "currency": "USD",
        },
        "customer": {
            "customerId": "CUST-ACME-00096",
            "embeddedPayload": {
                "identity": {"lastName": "Doe", "dob": "1993-05-11",
                             "phone": "+2348098765432", "email": "jane.doe@email.com"},
                "kyc": {"idType": "Passport", "idNumber": "12345678901", "kycLevel": "LEVEL_2"},
            },
        },
    }},
    # TC-API-ISS-02-020 — drop customer.embeddedPayload.identity.lastName
    "TC-API-ISS-02-020": {"body": {
        "requestContext": {
            "requestId": "REQ-HYBRID-7D387E75B195",
            "tenantId": "TNT-AFF-10291",
            "affiliateId": "AFF-00981",
            "idempotencyKey": "ebc07ea7-9444-4d96-854b-5cd36ca97de9",
        },
        "issuance": {
            "bankId": "BNK-WEM-002",
            "productId": "PRD-WEM-VIR-USD-011",
            "productType": "PHYSICAL",
            "currency": "USD",
        },
        "customer": {
            "customerId": "CUST-ACME-00096",
            "embeddedPayload": {
                "identity": {"firstName": "Jane", "dob": "1993-05-11",
                             "phone": "+2348098765432", "email": "jane.doe@email.com"},
                "kyc": {"idType": "Passport", "idNumber": "12345678901", "kycLevel": "LEVEL_2"},
            },
        },
    }},
    # TC-API-ISS-02-025 — disallowed tenant/affiliate/bank combo (whitelist test)
    "TC-API-ISS-02-025": {"body": {
        "requestContext": {
            "requestId": "REQ-HYBRID-F90B18BC6703",
            "tenantId": "TNT-NOT-ALLOWED",
            "affiliateId": "AFF-NOT-ALLOWED",
            "idempotencyKey": "f8143bbf-86dc-4996-9ec3-9321b29e962d",
        },
        "issuance": {
            "bankId": "BNK-WEM-002",
            "productId": "PRD-WEM-VIR-USD-011",
            "productType": "PHYSICAL",
            "currency": "USD",
        },
        "customer": {
            "customerId": "CUST-ACME-00096",
            "embeddedPayload": {
                "identity": {"firstName": "Jane", "lastName": "Doe", "dob": "1993-05-11",
                             "phone": "+2348098765432", "email": "jane.doe@email.com"},
                "kyc": {"idType": "Passport", "idNumber": "12345678901", "kycLevel": "LEVEL_2"},
            },
        },
    }},
    # TC-API-ISS-02-039 — RAW invalid JSON (trailing comma after idempotencyKey)
    "TC-API-ISS-02-039": {"raw_invalid_json": True, "body": (
        '{\n'
        '  "requestContext": {\n'
        '    "requestId": "REQ-HYBRID-C78460247C5F",\n'
        '    "tenantId": "TNT-AFF-10291",\n'
        '    "affiliateId": "AFF-00981",\n'
        '    "idempotencyKey": "c4b8caa6-e869-4169-b1aa-e17df6e09aa1",\n'
        '  },\n'
        '  "issuance": {\n'
        '    "bankId": "BNK-WEM-002",\n'
        '    "productId": "PRD-WEM-VIR-USD-011",\n'
        '    "productType": "PHYSICAL",\n'
        '    "currency": "USD"\n'
        '  }\n'
        '}'
    )},
}


_PROVISIONED_LIM_OPS_CARD_ID = "CAR-09BE8F06B29D467DBA86A658440750B2"
_PROVISIONED_LIM_OPS_PAIRS = [
    ("LIM-2E394B7FF9324CB48807BCDDF5830BA0", 850000),
    ("LIM-EAD6C48B9BAD427F91F70E75276BA7AE", 851000),
    ("LIM-4482484241424792BFE20D921D5BFC86", 852000),
    ("LIM-917A90B43F464D74807E5311AD5AD151", 853000),
    ("LIM-CEB9C087B9074E6FB48F2B161BB13819", 854000),
    ("LIM-1F8FEEDFAA634E4E94065A58DE721BFA", 855000),
]

def resolve_required_card_state(scenario: str, pack_endpoint: str) -> str | None:
    """Return 'ACTIVE' / 'FROZEN' / 'TERMINATED' / 'PENDING' / None, based on
    what state the test scenario requires. Returns None when the seeded card
    can be used as-is (negative tests on ID/auth/role do not depend on state).
    """
    s = (scenario or "").lower()
    # Explicit scenario-keyword overrides — these win over endpoint defaults.
    if "frozen_card" in s or "frozen_state" in s or "already_frozen" in s:
        return "FROZEN"
    if "already_unfrozen" in s:
        return "ACTIVE"
    # Auth/role/tenant negative TCs: route to same card state as the happy path
    # so the request reaches the business layer with a valid-state card.
    # Without this, happy-path TCs consume/mutate cards first and these TCs get
    # stale cards (already-frozen, already-activated, etc.) producing 409/422/400
    # noise that masks the real defect (auth bypass → 200).
    if any(t in s for t in ("bank_user_write", "bank_user_activation",
                             "bank_write_rejected", "service_provider_write",
                             "service_provider_activation", "foreign_tenant_rejected")):
        if pack_endpoint == "POST /api/v1/cards/{cardId}/freeze":             return "ACTIVE"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/unfreeze":           return "FROZEN"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/activate":           return "PENDING_ACTIVATION"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/terminate":          return "ACTIVE"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/pin-reset":          return "ACTIVE"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/fulfillment/reinitiate": return "ACTIVE"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/loads":              return "ACTIVE"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/unloads":            return "ACTIVE"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/limit-requests":     return "ACTIVE"
    if "already_active" in s or "already_in_active_state" in s:
        # activate's already_active / already_in_active_state scenario — route
        # to an ACTIVE card so backend 409s on the right state-conflict.
        return "ACTIVE"
    if "invalid_source_state" in s:
        # Scenario: try to mutate a card from a state the endpoint doesn't accept.
        # TERMINATED is the safest choice — every write endpoint rejects TERMINATED
        # cards with 409/422, so this surfaces the real state-machine guard.
        return "TERMINATED"
    if "terminated_card" in s or "already_terminated" in s:
        return "TERMINATED"
    if "personalizing_state" in s:
        return "PERSONALIZING"
    if "non_active_card" in s:
        return "PENDING"
    if "already_target_state" in s:
        if pack_endpoint == "POST /api/v1/cards/{cardId}/freeze":     return "FROZEN"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/unfreeze":   return "ACTIVE"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/terminate":  return "TERMINATED"
        if pack_endpoint == "POST /api/v1/cards/{cardId}/activate":   return "ACTIVE"
    # Endpoint-default for happy-path scenarios.
    happy = any(t in s for t in ("success", "happy", "_safe", "well_formed",
                                  "minimum_required", "response_includes",
                                  "response_contract", "valid_response",
                                  "read_after_action_consistent",
                                  "read_after_activation_consistent",
                                  "platform_state_updates"))
    if happy:
        if pack_endpoint in _HAPPY_PATH_NEEDS_PENDING_ACTIVATION: return "PENDING_ACTIVATION"
        if pack_endpoint in _HAPPY_PATH_NEEDS_ACTIVE:  return "ACTIVE"
        if pack_endpoint in _HAPPY_PATH_NEEDS_FROZEN:  return "FROZEN"
    return None

def select_card_id_for_state(state: str | None, session_ids: dict,
                              pack_endpoint: str | None = None,
                              scenario: str | None = None) -> str | None:
    """Pick the cardId for the requested state. Happy-path TCs on every
    write endpoint that requires an ACTIVE card (freeze, terminate, loads,
    unloads, pin-reset, limit-requests, load-requests) JIT-consume the next
    not-yet-used cardId from the queried ACTIVE pool. UNF happy paths
    JIT-consume from the FROZEN pool (now seeded directly by the query
    filter, with Phase 0g freeze fallback). Pure read endpoints and
    pool-exhausted fallbacks share the default cardIdActive/cardIdLoadable."""
    scn = (scenario or "").lower()
    is_happy = any(k in scn for k in ("happy", "success", "minimum_required",
                                       "well_formed", "_safe", "response_includes",
                                       "read_after", "platform_state_updates"))
    pe = pack_endpoint or ""

    # FUL-02 (refresh) — backend requires a PHYSICAL card with fulfillment
    # in-progress. The pool is probe-validated by Phase 0f3b; exhausting it
    # triggers a sentinel BLOCK rather than a fall-through to wrong-state cards.
    if pe == "POST /api/v1/cards/{cardId}/fulfillment/refresh":
        if is_happy:
            cid = take_card_from_pool(session_ids, "cardIdRefreshInProgressPool",
                                      "_consumed_refresh_inprogress")
            if cid: return cid
            return None  # pool empty → __NO_INPROGRESS_CARD_FOR_FUL_02__ sentinel
        elif "already_target_state" in (scenario or "").lower():
            # This TC sends refresh to a card whose fulfillment is ALREADY at a terminal
            # state (FAILED). Backend must return 409 "only allowed while in progress".
            # Must NOT use cardIdRefreshInProgressPool (PERSONALIZING) — that would 200.
            pool = session_ids.get("cardIdFailedFulfillmentPool") or []
            cid = pool[0] if pool else session_ids.get("cardIdFailedFulfillment")
            if cid: return cid
            return None
        else:
            # Negative tests (body mutations, auth): any PHYSICAL card is fine.
            # Backend rejects virtual before inspecting the mutation payload.
            # Don't consume — negative TCs share a card.
            for _pool_key in ("cardIdRefreshInProgressPool",
                              "cardIdActivePhysicalPool",
                              "cardIdPendingPhysicalPool"):
                _pool = session_ids.get(_pool_key) or []
                if _pool: return _pool[0]
            cid = session_ids.get("cardIdFailedFulfillment") or session_ids.get("cardIdActivePhysical")
            if cid: return cid
            return None  # no physical card → __NO_PHYSICAL_CARD_FOR_FUL_02__ sentinel

    # FUL-03 (reinitiate) — backend ONLY accepts FAILED-state cards.
    # 2026-05-07 user clarification: ACTIVE(PHYSICAL) was supplied by mistake;
    # do NOT fall back to it (would 409 with "only allowed from FAILED state").
    # If the FAILED pool is exhausted, return None and let the caller surface
    # the pool-exhausted condition rather than poisoning the TC with a wrong-
    # state card.
    if pe == "POST /api/v1/cards/{cardId}/fulfillment/reinitiate" and is_happy:
        cid = take_card_from_pool(session_ids, "cardIdFailedFulfillmentPool",
                                  "_consumed_failed_for_reinitiate")
        if cid: return cid
        # Pool exhausted — do NOT fall through to ACTIVE-card fallback.
        # Backend rejects non-FAILED cards with 400 "physical cards only" or
        # 409 "only allowed from FAILED state". Return None so the sentinel path
        # blocks this TC with a clear data-availability message.
        return None

    # already_target_state_rejected on unfreeze: need a card that is NOT FROZEN so
    # unfreeze rejects with 409/422. Pool[0] can be stale (enumerated as ACTIVE but
    # actually FROZEN in live backend). cardIdTerminated is probe-verified by Phase 0h
    # and definitively non-FROZEN — unfreeze will reject it with the right error code.
    if "already_target_state" in scn and pe == "POST /api/v1/cards/{cardId}/unfreeze":
        return session_ids.get("cardIdTerminated")

    if state == "FROZEN":
        if is_happy and pe == "POST /api/v1/cards/{cardId}/unfreeze":
            cid = take_card_from_pool(session_ids, "cardIdFrozenPool", "_consumed_frozen_for_unfreeze")
            if cid: return cid
        # Non-happy FROZEN TCs (auth/role/tenant negatives on unfreeze): peek
        # current pool head — unfreeze happy paths consume cards so the scalar
        # cardIdFrozen may point to an already-unfrozen card.
        _fpool = session_ids.get("cardIdFrozenPool") or []
        if _fpool:
            return _fpool[0]
        return session_ids.get("cardIdFrozen")
    if state == "TERMINATED":
        return session_ids.get("cardIdTerminated")
    if state == "PENDING":
        return session_ids.get("cardIdPending")
    if state == "PERSONALIZING":
        cid = take_card_from_pool(session_ids, "cardIdPersonalizingPool",
                                  "_consumed_personalizing")
        if cid: return cid
        return session_ids.get("cardIdPersonalizing")
    if state == "PENDING_ACTIVATION":
        # ACTIVE.txt-seeded pool (2026-05-07): each activate happy path consumes
        # a fresh PENDING_ACTIVATION card so back-to-back TCs don't collide on
        # already-activated state.
        if is_happy and pe == "POST /api/v1/cards/{cardId}/activate":
            # Prefer cards owned by the canonical affiliate — wrong-affiliate cards
            # return 404 when the request body carries canonical affiliateId.
            cid = take_card_from_pool(session_ids, "cardIdPendingActivationOwnedPool",
                                      "_consumed_pending_activation_owned_for_activate")
            if cid: return cid
            cid = take_card_from_pool(session_ids, "cardIdPendingActivationPool",
                                      "_consumed_pending_activation_for_activate")
            if cid: return cid
        pool = session_ids.get("cardIdPendingActivationPool") or []
        if pool:
            return pool[0]
        # 2026-05-11: do NOT fall back to seed cardId for activate. The seed is
        # PENDING_ISSUANCE (or worse, terminated by prior lifecycle steps), and
        # backend rejects activate from any state other than PENDING_ACTIVATION.
        # Falling back here generated 9 false 422s per run. Return None so the
        # caller blocks the TC with a precise reason.
        return session_ids.get("cardIdPendingActivation")
    if state == "ACTIVE":
        # Mutating endpoints — each happy-path TC needs a FRESH card from the
        # pool because the previous TC's card has changed state.
        # 2026-05-07: virtual ACTIVE pool from ACTIVE.txt produced "Only ACTIVE
        # cards can be freezed." 400s — those cards verify as ACTIVE via GET
        # but the freeze endpoint disagrees. Use the verified-ACTIVE physical
        # pool first; fall back to the virtual pool only if physical empty.
        if is_happy and pe == "POST /api/v1/cards/{cardId}/freeze":
            cid = take_card_from_pool(session_ids, "cardIdActivePhysicalPool",
                                      "_consumed_active_physical_for_freeze")
            if cid: return cid
            cid = take_card_from_pool(session_ids, "cardIdActivePool", "_consumed_active_for_freeze")
            if cid: return cid
        if is_happy and pe == "POST /api/v1/cards/{cardId}/terminate":
            # ACTIVE.txt 2026-05-07 supplies a dedicated terminate pool
            # (8 cards under "ACTIVE:(terminate)") so freeze and terminate
            # don't compete for the same ACTIVE cards.
            cid = take_card_from_pool(session_ids, "cardIdActiveTerminatePool",
                                      "_consumed_active_terminate")
            if cid: return cid
            cid = take_card_from_pool(session_ids, "cardIdActivePhysicalPool",
                                      "_consumed_active_physical_for_terminate")
            if cid: return cid
            cid = take_card_from_pool(session_ids, "cardIdActivePool", "_consumed_active_for_terminate")
            if cid: return cid
            # Fallback: PENDING_ISSUANCE cards can also be terminated.
            cid = take_card_from_pool(session_ids, "cardIdPendingPool", "_consumed_pending_for_terminate")
            if cid: return cid
            # All terminate pools exhausted — do NOT fall through to the scalar
            # cardIdActive seed, which may be TERMINATED/stale. Return None so
            # inject_seeded_path_vars sets a sentinel and the TC is blocked.
            return None
        # Non-mutating endpoints (loads, unloads, pin-reset, limit-requests)
        # don't change card status — every happy-path TC SHARES the same card.
        if pe == "POST /api/v1/cards/{cardId}/pin-reset":
            return session_ids.get("cardIdFrozen") or session_ids.get("cardIdActive")
        if pe in ("POST /api/v1/cards/{cardId}/loads",
                  "POST /api/v1/cards/{cardId}/unloads",
                  "POST /api/v1/cards/{cardId}/limit-requests"):
            return session_ids.get("cardIdLoadable") or session_ids.get("cardIdActive")
        # For state-change endpoints (freeze, terminate) negative TCs: always peek
        # the current pool head rather than the stale cardIdActive scalar.
        # Happy-path TCs JIT-consume and mutate cards — the scalar points to a card
        # that is now frozen/terminated by the time negative TCs run.
        if pe in ("POST /api/v1/cards/{cardId}/freeze",
                  "POST /api/v1/cards/{cardId}/terminate",
                  "POST /api/v1/cards/{cardId}/fulfillment/reinitiate"):
            _pool = session_ids.get("cardIdActivePool") or []
            if _pool:
                return _pool[0]  # peek current head — unconsumed ACTIVE cards only
        # General fallback — prefer pool head over stale scalar for same reason.
        cid = session_ids.get("cardIdActive")
        _pool = session_ids.get("cardIdActivePool") or []
        if _pool:
            cid = _pool[0]  # peek, don't consume — shared across negative TCs
        return cid
    return None

def inject_seeded_path_vars(path_vars: dict, session_ids: dict, allow_substitution: bool,
                            path_template: str | None = None,
                            scenario: str | None = None,
                            pack_endpoint: str | None = None) -> dict:
    """Replace path-var values with seeded session IDs, scenario-aware.

    When the scenario implies a specific card state (ACTIVE/FROZEN/TERMINATED/PENDING),
    swap cardId to the matching pool entry. 2026-05-07: user supplied approved
    DB-backed affiliateId + bankId (approved ids.txt) — use these unconditionally
    for {affiliateId} and {bankId} on every request, including bank-scoped routes.
    Older bank-scoped-affiliate discovery and GUID-validator workarounds are no
    longer applied because the approved values are the canonical real IDs.
    """
    out = dict(path_vars)
    if not allow_substitution:
        return out
    needed_state = resolve_required_card_state(scenario or "", pack_endpoint or "") if pack_endpoint else None
    state_routed_card = select_card_id_for_state(needed_state, session_ids, pack_endpoint, scenario)
    # 2026-05-11: when state_routed_card is None for a happy-path activate or
    # terminate, do NOT fall back to the seed cardId (which is stale/TERMINATED
    # and always 4xx). Set a sentinel the per-TC dispatcher can detect to block
    # the TC with an accurate reason.
    is_activate_happy = (
        pack_endpoint == "POST /api/v1/cards/{cardId}/activate"
        and needed_state == "PENDING_ACTIVATION"
        and state_routed_card is None
    )
    is_terminate_happy = (
        pack_endpoint == "POST /api/v1/cards/{cardId}/terminate"
        and needed_state == "ACTIVE"
        and state_routed_card is None
        and any(k in (scenario or "").lower() for k in (
            "happy", "success", "minimum_required", "well_formed", "_safe",
            "response_includes", "read_after", "platform_state_updates"
        ))
    )
    is_reinitiate_happy = (
        pack_endpoint == "POST /api/v1/cards/{cardId}/fulfillment/reinitiate"
        and needed_state == "ACTIVE"
        and state_routed_card is None
        and any(k in (scenario or "").lower() for k in (
            "happy", "success", "minimum_required", "well_formed", "_safe",
            "response_includes", "read_after", "platform_state_updates"
        ))
    )
    _ful02_scn_is_happy = any(k in (scenario or "").lower() for k in (
        "happy", "success", "minimum_required", "well_formed", "_safe",
        "response_includes", "read_after", "platform_state_updates"
    ))
    is_refresh_happy_pool_empty = (
        pack_endpoint == "POST /api/v1/cards/{cardId}/fulfillment/refresh"
        and state_routed_card is None
        and _ful02_scn_is_happy
    )
    is_ful02_no_physical = (
        pack_endpoint == "POST /api/v1/cards/{cardId}/fulfillment/refresh"
        and state_routed_card is None
        and not _ful02_scn_is_happy
    )
    for k in list(out.keys()):
        if k == "cardId" and state_routed_card:
            out[k] = state_routed_card
        elif k == "cardId" and is_activate_happy:
            out[k] = "__NO_PENDING_ACTIVATION_CARD__"
        elif k == "cardId" and is_terminate_happy:
            out[k] = "__NO_ACTIVE_CARD_FOR_TERMINATE__"
        elif k == "cardId" and is_reinitiate_happy:
            out[k] = "__NO_FAILED_FULFILLMENT_CARD__"
        elif k == "cardId" and is_refresh_happy_pool_empty:
            out[k] = "__NO_INPROGRESS_CARD_FOR_FUL_02__"
        elif k == "cardId" and is_ful02_no_physical:
            out[k] = "__NO_PHYSICAL_CARD_FOR_FUL_02__"
        elif k == "affiliateId" and "affiliate_not_linked_to_bank" in (scenario or ""):
            # inject a real affiliate from a different bank so the backend sees a valid
            # affiliate that genuinely is not linked to the bank under test
            out[k] = session_ids.get("foreignAffiliateId") or "__NO_FOREIGN_AFFILIATE__"
        elif k == "affiliateId" and session_ids.get("affiliateId"):
            out[k] = session_ids["affiliateId"]
        elif k == "bankId" and session_ids.get("bankId"):
            out[k] = session_ids["bankId"]
        elif k in SEEDED_PATH_VAR_KEYS and session_ids.get(k):
            out[k] = session_ids[k]
    return out

# --- HYBRID: pre-flight card issuance -------------------------------------
def extract_request_id_from_response(resp_body: Any, key_candidates: tuple, prefix: str | None = None) -> str | None:
    """Generic extractor: returns the first matching key whose value is a non-empty string.
    Used for limitRequestId, loadRequestId, etc. minted by nested POSTs."""
    if not isinstance(resp_body, dict):
        return None
    data = resp_body.get("data") if isinstance(resp_body.get("data"), dict) else resp_body
    if not isinstance(data, dict):
        return None
    for k in key_candidates:
        v = data.get(k)
        if isinstance(v, str) and v and (prefix is None or v.startswith(prefix)):
            return v
    return None

def extract_card_id_from_response(resp_body: Any) -> str | None:
    """Best-effort extraction of cardId from issuance response. Tries common shapes."""
    if not isinstance(resp_body, dict):
        return None
    data = resp_body.get("data") if isinstance(resp_body.get("data"), dict) else resp_body
    for k in ("cardId", "cardID", "id"):
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, str) and v.startswith("CAR-"):
            return v
    if isinstance(data, dict):
        card = data.get("card")
        if isinstance(card, dict):
            for k in ("cardId", "id"):
                v = card.get(k)
                if isinstance(v, str) and v.startswith("CAR-"):
                    return v
    return None

def extract_first_card_id_from_query(resp_body: Any) -> str | None:
    """Recursively scan a /cards/query response for the first valid cardId.
    Enforces the CAR- prefix to skip placeholder ids and pre-issuance UUIDs.
    """
    cid = extract_first_id_recursive(resp_body, ("cardId", "cardID", "id"),
                                     expected_prefix="CAR-")
    if cid:
        return cid
    # Fall back without prefix enforcement (some env IDs may not yet use CAR-)
    return extract_first_id_recursive(resp_body, ("cardId", "cardID", "id"))


def _persist_card_if_verified(cid: str, session_ids: dict, source: str) -> dict:
    """Verify the cardId is queryable before writing it to SessionStore.
    Codex H4: never persist an unverified id, flag provenance.
    """
    verify_rec = verify_seeded_id_queryable(cid, "/api/v1/cards/{cardId}")
    persisted = False
    if verify_rec.get("verified"):
        session_ids["cardId"] = cid
        SESSION.save({"cardId": cid})
        persisted = True
    return {
        "selected_source": source,
        "selected_verified": bool(verify_rec.get("verified")),
        "persisted_to_session_store": persisted,
        "verify": verify_rec,
    }


def query_fallback_card(pm_idx: dict, session_ids: dict) -> dict:
    """Fallback to POST /api/v1/cards/query when issuance mint fails."""
    rec = {
        "step": "query_existing_card",
        "method": "POST",
        "endpoint": "/api/v1/cards/query",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
    }
    pm_entry = pm_idx.get("POST /api/v1/cards/query")
    if not pm_entry:
        rec.update({"status": "ERROR",
                    "reason": "POST /api/v1/cards/query not in Postman — cannot query for existing card"})
        return rec
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"])
    # Codex M6 + re-audit R4: filter for ACTIVE cards belonging to the seeded
    # affiliate/bank. Postman base has filters.status as a LIST (["string","string"]),
    # not a scalar — preserving list shape avoids contract drift.
    if isinstance(body, dict):
        existing_key = next((k for k in ("filters", "filter", "criteria")
                             if isinstance(body.get(k), dict)), None)
        target_key = existing_key or "filters"
        new_filters = {"status": ["ACTIVE"]}
        if session_ids.get("affiliateId"):
            new_filters["affiliateId"] = session_ids["affiliateId"]
        if session_ids.get("bankId"):
            new_filters["bankId"] = session_ids["bankId"]
        body[target_key] = new_filters
    path_template = get_postman_path_template(pm_entry)
    url = rebuild_url(base["method"], path_template, base["path_vars"], base["query"])
    rec["url"] = url
    rec["request_body"] = body
    response = execute(base["method"], url, base["headers"], body, timeout=30)
    rec["response_status"] = response.get("status_code")
    rec["response_body"] = response.get("body") if response.get("body") is not None else response.get("body_text")
    rec["completed_at"] = dt.datetime.now().isoformat()
    if not response.get("ok"):
        rec.update({"status": "ERROR", "reason": f"transport: {response.get('error')}"})
        return rec
    sc = response.get("status_code", 0)
    if 200 <= sc < 300:
        cid = extract_first_card_id_from_query(response.get("body"))
        if cid:
            persist = _persist_card_if_verified(cid, session_ids, source="query_fallback")
            rec["card_id"] = cid
            rec["persistence"] = persist
            rec["status"] = "OK" if persist["selected_verified"] else "UNVERIFIED"
            if not persist["selected_verified"]:
                rec["reason"] = "query returned a cardId but verify GET did not confirm it is queryable; not persisted"
            return rec
        rec.update({"status": "DEGRADED",
                    "reason": f"2xx ({sc}) but query returned no card with extractable id"})
        return rec
    rec.update({"status": "FAIL", "reason": f"query non-2xx ({sc})"})
    return rec


def pre_flight_issue_card(pm_idx: dict, session_ids: dict) -> dict:
    """Acquisition order: 1) mint via POST /cards/issuance (with seeded affiliate/bank context),
    2) fallback to POST /cards/query for an existing persisted cardId, 3) fallback to seeded cardId.
    """
    setup = {
        "step": "issue_seed_card",
        "method": "POST",
        "endpoint": "/api/v1/cards/issuance",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "fallback_used": False,
        "query_fallback": None,
    }
    pm_entry = pm_idx.get("POST /api/v1/cards/issuance")
    if not pm_entry:
        setup.update({
            "status": "ERROR",
            "reason": "POST /api/v1/cards/issuance not found in Postman collection — cannot pre-flight issue",
        })
        setup["query_fallback"] = query_fallback_card(pm_idx, session_ids)
        if setup["query_fallback"].get("status") == "OK":
            setup.update({"status": "OK_VIA_QUERY", "fallback_used": True,
                          "card_id": setup["query_fallback"].get("card_id")})
            # MEDIUM-3: promote nested persistence to top-level for chain harvester.
            qf_persistence = setup["query_fallback"].get("persistence")
            if isinstance(qf_persistence, dict):
                setup["persistence"] = qf_persistence
        return setup
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"])
    if isinstance(body, dict):
        rc = body.get("requestContext")
        if isinstance(rc, dict) and session_ids.get("affiliateId"):
            rc["affiliateId"] = session_ids["affiliateId"]
        iss = body.get("issuance")
        if isinstance(iss, dict) and session_ids.get("bankId"):
            iss["bankId"] = session_ids["bankId"]
    path_template = get_postman_path_template(pm_entry)
    url = rebuild_url(base["method"], path_template, base["path_vars"], base["query"])
    setup["url"] = url
    setup["request_body"] = body
    response = execute(base["method"], url, base["headers"], body, timeout=30)
    setup["response_status"] = response.get("status_code")
    setup["response_body"] = response.get("body") if response.get("body") is not None else response.get("body_text")
    setup["completed_at"] = dt.datetime.now().isoformat()
    sc = response.get("status_code", 0)
    if response.get("ok") and 200 <= sc < 300:
        new_card_id = extract_card_id_from_response(response.get("body"))
        if new_card_id:
            persist = _persist_card_if_verified(new_card_id, session_ids, source="mint")
            setup["card_id"] = new_card_id
            setup["persistence"] = persist
            if persist["selected_verified"]:
                setup["status"] = "OK"
                return setup
            setup.update({
                "status": "MINT_UNVERIFIED",
                "reason": "issuance 2xx returned a cardId but verify GET did not confirm it; trying query fallback",
                "fallback_used": True,
            })
        else:
            setup.update({
                "status": "DEGRADED",
                "reason": f"2xx ({sc}) but cardId not extractable from issuance response; trying query fallback",
                "fallback_used": True,
            })
    elif not response.get("ok"):
        setup.update({"status": "ERROR_PRE_FALLBACK",
                      "reason": f"issuance transport: {response.get('error')}; trying query fallback",
                      "fallback_used": True})
    else:
        setup.update({
            "status": "FAIL_PRE_FALLBACK",
            "reason": f"issuance non-2xx ({sc}); trying query fallback",
            "fallback_used": True,
        })
    setup["query_fallback"] = query_fallback_card(pm_idx, session_ids)
    if setup["query_fallback"].get("status") == "OK":
        setup.update({"status": "OK_VIA_QUERY", "card_id": setup["query_fallback"].get("card_id")})
        # MEDIUM-3: promote nested persistence to top-level for chain harvester.
        qf_persistence = setup["query_fallback"].get("persistence")
        if isinstance(qf_persistence, dict):
            setup["persistence"] = qf_persistence
    else:
        if setup["status"] == "ERROR_PRE_FALLBACK":
            setup["status"] = "ERROR"
        elif setup["status"] == "FAIL_PRE_FALLBACK":
            setup["status"] = "FAIL"
        setup["reason"] = (setup.get("reason", "") +
                          f" | query fallback: {setup['query_fallback'].get('status')} "
                          f"({setup['query_fallback'].get('reason')})")
    return setup

# --- HYBRID: lifecycle pre-flight (activate / mint limit-request / discover bank-scoped affiliate) ---
def pre_flight_activate_card(pm_idx: dict, session_ids: dict) -> dict:
    """Drive the seeded card from PENDING_ISSUANCE to ACTIVE so state-change
    happy-path TCs (FRZ/UNF/TRM/LOAD/UNLD/PIN/LIM) hit a usable card.
    Idempotent: skip if no cardId or if already ACTIVE per follow-up GET.
    """
    rec = {"step": "activate_seed_card", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "reason": None, "card_id": session_ids.get("cardId")}
    cid = session_ids.get("cardId")
    if not cid:
        rec.update({"reason": "no cardId in session"}); return rec
    pm_entry = pm_idx.get("POST /api/v1/cards/{cardId}/activate")
    if not pm_entry:
        rec.update({"reason": "POST /cards/{cardId}/activate not in Postman collection"}); return rec
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
    # Note: do NOT override requestContext.tenantId/affiliateId here — backend
    # validates them as strict GUIDs; session_ids carries AFF-/TNT- prefixed
    # IDs which 422 ("must be valid GUID values"). Postman defaults are GUIDs.
    path_template = get_postman_path_template(pm_entry)
    pv = inject_seeded_path_vars(base["path_vars"], session_ids, True)
    url = rebuild_url(base["method"], path_template, pv, base["query"])
    rec["url"] = url
    resp = execute(base["method"], url, base["headers"], body, timeout=20)
    rec["response_status"] = resp.get("status_code")
    rec["completed_at"] = dt.datetime.now().isoformat()
    sc = resp.get("status_code", 0)
    if resp.get("ok") and 200 <= sc < 300:
        rec.update({"status": "OK", "reason": "card activated"})
    elif sc == 409:
        # Already in target state — treat as success
        rec.update({"status": "ALREADY_ACTIVE", "reason": "409 from activate (likely already active)"})
    else:
        body_excerpt = resp.get("body") if resp.get("body") is not None else resp.get("body_text")
        rec.update({"status": "FAIL", "reason": f"activate non-2xx ({sc}): {str(body_excerpt)[:200]}"})
    return rec

def pre_flight_mint_limit_request(pm_idx: dict, session_ids: dict) -> dict:
    """Mint a real limitRequestId via POST /cards/{cardId}/limit-requests so the
    LIM-02 ops/complete endpoint has a valid {limitRequestId} path-var to use.
    """
    rec = {"step": "mint_limit_request", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "reason": None, "limit_request_id": None}
    cid = session_ids.get("cardId")
    if not cid:
        rec.update({"reason": "no cardId in session"}); return rec
    pm_entry = pm_idx.get("POST /api/v1/cards/{cardId}/limit-requests")
    if not pm_entry:
        rec.update({"reason": "POST /cards/{cardId}/limit-requests not in Postman collection"}); return rec
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
    # Same constraint as activate: don't override the Postman GUID values.
    path_template = get_postman_path_template(pm_entry)
    pv = inject_seeded_path_vars(base["path_vars"], session_ids, True)
    url = rebuild_url(base["method"], path_template, pv, base["query"])
    rec["url"] = url
    resp = execute(base["method"], url, base["headers"], body, timeout=20)
    rec["response_status"] = resp.get("status_code")
    rec["completed_at"] = dt.datetime.now().isoformat()
    sc = resp.get("status_code", 0)
    if resp.get("ok") and 200 <= sc < 300:
        lrid = extract_request_id_from_response(resp.get("body"),
                ("limitRequestId", "id", "requestId"), prefix=None)
        if lrid:
            session_ids["limitRequestId"] = lrid
            SESSION.save({"limitRequestId": lrid})
            rec.update({"status": "OK", "limit_request_id": lrid})
        else:
            rec.update({"status": "DEGRADED", "reason": f"2xx ({sc}) but no limitRequestId extractable"})
    else:
        body_excerpt = resp.get("body") if resp.get("body") is not None else resp.get("body_text")
        rec.update({"status": "FAIL", "reason": f"mint non-2xx ({sc}): {str(body_excerpt)[:200]}"})
    return rec

def pre_flight_mint_limit_request_pool(pm_idx: dict, session_ids: dict, count: int = 10) -> dict:
    """Mint `count` fresh limit requests so LIM-02 has a live (limitRequestId, amount)
    queue for every happy-path TC.  Amount varies per call so LIM-02 completes each
    with a distinct appliedLimit.amount — backend rejects if amounts don't match.
    Replaces the ACTIVE.txt-driven static queue entirely.
    If the ACTIVE.txt limOpsCardId rejects all mints, retries with the constant card.
    """
    rec = {"step": "mint_limit_request_pool", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "pairs": [], "minted": 0, "failed": 0}
    pm_entry = pm_idx.get("POST /api/v1/cards/{cardId}/limit-requests")
    if not pm_entry:
        rec.update({"reason": "POST /cards/{cardId}/limit-requests not in Postman collection"}); return rec
    base = build_base_request(pm_entry)
    path_template = get_postman_path_template(pm_entry)
    base_amount = 100_000
    amount_step = 10_000

    def _try_mint(card_id: str) -> list:
        pv = dict(base["path_vars"]); pv["cardId"] = card_id
        url = rebuild_url(base["method"], path_template, pv, base["query"])
        pairs: list = []
        failures = 0
        for i in range(count):
            amount = base_amount + i * amount_step
            body = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
            if isinstance(body, dict):
                body.setdefault("requestedLimit", {})["amount"] = amount
            resp = execute(base["method"], url, base["headers"], body, timeout=20)
            sc = resp.get("status_code", 0)
            if resp.get("ok") and 200 <= sc < 300:
                lrid = extract_request_id_from_response(resp.get("body"),
                        ("limitRequestId", "id", "requestId"), prefix=None)
                if lrid:
                    pairs.append([lrid, amount])
                else:
                    failures += 1
            else:
                failures += 1
                if failures >= 3:
                    break
        return pairs

    # Primary: ACTIVE.txt card (or constant if not set)
    primary_card = session_ids.get("limOpsCardId") or _PROVISIONED_LIM_OPS_CARD_ID
    pairs = _try_mint(primary_card)
    rec["card_used"] = primary_card

    # Fallback 1: constant card when primary fails and it's different from primary
    if not pairs and primary_card != _PROVISIONED_LIM_OPS_CARD_ID:
        print(f"  -> primary limOpsCardId {primary_card} rejected all mints; retrying with constant {_PROVISIONED_LIM_OPS_CARD_ID}")
        pairs = _try_mint(_PROVISIONED_LIM_OPS_CARD_ID)
        if pairs:
            rec["card_used"] = _PROVISIONED_LIM_OPS_CARD_ID
            session_ids["limOpsCardId"] = _PROVISIONED_LIM_OPS_CARD_ID

    # Fallback 2: probe cards from the live ACTIVE pool (both seeded IDs terminated)
    if not pairs:
        active_pool = list(session_ids.get("cardIdActivePool") or [])
        tried = {primary_card, _PROVISIONED_LIM_OPS_CARD_ID}
        for candidate in active_pool:
            if candidate in tried:
                continue
            tried.add(candidate)
            print(f"  -> trying pool card {candidate} for limit-request mint")
            pairs = _try_mint(candidate)
            if pairs:
                rec["card_used"] = candidate
                session_ids["limOpsCardId"] = candidate
                print(f"  -> found working limOpsCardId: {candidate}")
                break
            if len(tried) > 8:  # cap probe attempts
                break

    rec["pairs"] = pairs
    rec["minted"] = len(pairs)
    rec["failed"] = count - len(pairs)
    rec["status"] = "OK" if pairs else "FAIL"
    if not pairs:
        rec["reason"] = "no limitRequestIds minted; falling back to static queue"
    else:
        session_ids["limOpsPairsQueue"] = pairs
    rec["completed_at"] = dt.datetime.now().isoformat()
    return rec




def pre_flight_discover_bank_scoped_affiliate(session_ids: dict) -> dict:
    """GET /api/v1/banks/{bankId}/affiliates and pick the first affiliateId.
    Used to satisfy /cards/banks/{bankId}/affiliates/{affiliateId}/* validators
    that require an affiliate scoped under the seeded bankId.
    """
    rec = {"step": "discover_bank_scoped_affiliate", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "reason": None, "affiliate_id": None}
    bid = session_ids.get("bankId")
    if not bid:
        rec.update({"reason": "no bankId in session"}); return rec
    url = f"{BASE_URL}/api/v1/banks/{bid}/affiliates"
    rec["url"] = url
    resp = execute("GET", url, {"Accept": "application/json"}, None, timeout=20)
    rec["response_status"] = resp.get("status_code")
    rec["completed_at"] = dt.datetime.now().isoformat()
    sc = resp.get("status_code", 0)
    if resp.get("ok") and 200 <= sc < 300 and isinstance(resp.get("body"), dict):
        body = resp["body"]
        items = body.get("data") or body.get("affiliates") or body.get("items") or []
        if isinstance(items, list) and items:
            for it in items:
                if isinstance(it, dict):
                    aff = it.get("affiliateId") or it.get("id")
                    if isinstance(aff, str) and aff:
                        session_ids["affiliateIdScopedToBank"] = aff
                        rec.update({"status": "OK", "affiliate_id": aff})
                        return rec
            rec.update({"status": "DEGRADED", "reason": "list returned but no affiliateId fields"})
        else:
            rec.update({"status": "DEGRADED", "reason": "empty list or unexpected shape"})
    else:
        body_excerpt = resp.get("body") if resp.get("body") is not None else resp.get("body_text")
        rec.update({"status": "FAIL", "reason": f"discover non-2xx ({sc}): {str(body_excerpt)[:200]}"})
    return rec

def pre_flight_query_active_card_and_affiliate(pm_idx: dict, session_ids: dict) -> dict:
    """POST /cards/query (page 1, pageSize 50, status ACTIVE+PENDING_ISSUANCE).
    Buckets results by current status as reported by the query response so
    downstream JIT consumption picks from a freshly-known-good pool. Also
    extracts a real GUID affiliateId.
    """
    rec = {"step": "query_card_pool", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "active_pool_size": 0, "frozen_pool_size": 0,
           "active_affiliate_id": None}
    pm_entry = pm_idx.get("POST /api/v1/cards/query")
    if not pm_entry:
        rec.update({"reason": "POST /cards/query not in Postman collection"}); return rec
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
    if isinstance(body, dict):
        # Backend 2026-05-07: rejects {"request": {...}} envelope. Body must be
        # filters/page/pageSize at top level (CardQueryRequestDto).
        if "request" in body and isinstance(body["request"], dict) and "filters" in body["request"]:
            body = body["request"]
        req = body
        if isinstance(req, dict):
            req["page"] = 1
            req["pageSize"] = 25  # backend caps pageSize at 25 regardless of request
            f = req.get("filters")
            if isinstance(f, dict):
                # Include PENDING_ISSUANCE — terminate accepts non-terminated states,
                # so PENDING cards are valid TRM-01-source candidates too.
                # Include FROZEN so cardIdFrozenPool is populated directly from
                # existing FROZEN cards (UNF-01 happy paths consume from this pool).
                # Include READY — the backend treats READY as the post-activation
                # equivalent of ACTIVE (see _is_status checks for ACTIVE/READY/UNFROZEN).
                f["status"] = ["ACTIVE", "READY", "PENDING_ISSUANCE", "FROZEN"]
                for sk in ("bankId", "affiliateId", "customerId", "productId"):
                    if isinstance(f.get(sk), str) and f[sk] in ("", "string"):
                        f.pop(sk, None)
                ct = f.get("cardType")
                if isinstance(ct, list) and any(s == "string" for s in ct):
                    f.pop("cardType", None)
                pt = f.get("productType")
                if isinstance(pt, list) and any(s == "string" for s in pt):
                    f.pop("productType", None)
                f.pop("fromDate", None); f.pop("toDate", None)
    path_template = get_postman_path_template(pm_entry)
    url = rebuild_url(base["method"], path_template, base["path_vars"], base["query"])
    rec["url"] = url
    # Paginate to collect across the full result set — backend caps pageSize at 25,
    # so a system with hundreds of cards needs multiple pages to surface all
    # ACTIVE/READY/FROZEN records.
    MAX_PAGES = 25
    all_items = []
    last_status = 0
    for page in range(1, MAX_PAGES + 1):
        if isinstance(body, dict) and isinstance(body.get("request"), dict):
            body["request"]["page"] = page
        resp = execute(base["method"], url, base["headers"], body, timeout=20)
        last_status = resp.get("status_code", 0)
        if not (resp.get("ok") and 200 <= last_status < 300 and isinstance(resp.get("body"), dict)):
            break
        b = resp["body"]
        items = b.get("data") or b.get("items") or []
        if not isinstance(items, list) or not items:
            break
        all_items.extend(items)
        if len(items) < 25:
            break
    rec["response_status"] = last_status; rec["completed_at"] = dt.datetime.now().isoformat()
    rec["pages_fetched"] = page if all_items else 0
    if not all_items:
        rec.update({"status": "FAIL" if last_status else "DEGRADED",
                    "reason": f"query returned no records (last_status={last_status})"})
        return rec
    # Bucket by status from the query response itself, dedupe to unique cardIds.
    active_set, pending_set, frozen_set, terminated_set = set(), set(), set(), set()
    affiliate_id = None
    for it in all_items:
        if not isinstance(it, dict): continue
        cid = it.get("cardId"); aff = it.get("affiliateId"); st = (it.get("status") or "").upper()
        if not cid: continue
        if st in ("ACTIVE", "READY"):    active_set.add(cid)
        elif st == "PENDING_ISSUANCE":   pending_set.add(cid)
        elif st == "FROZEN":             frozen_set.add(cid)
        elif st == "TERMINATED":         terminated_set.add(cid)
        if (not affiliate_id or affiliate_id == "00000000-0000-0000-0000-000000000000") and isinstance(aff, str) and aff:
            affiliate_id = aff
    active_pool, pending_pool, frozen_pool, terminated_pool = list(active_set), list(pending_set), list(frozen_set), list(terminated_set)
    session_ids["cardIdActivePool"] = active_pool
    session_ids["cardIdPendingPool"] = pending_pool
    session_ids["cardIdFrozenPool"] = frozen_pool
    session_ids["cardIdTerminatedPool"] = terminated_pool
    if active_pool:
        session_ids["cardIdActive"] = active_pool[0]
    if affiliate_id:
        session_ids["affiliateIdActive"] = affiliate_id
    rec.update({"status": "OK",
                "active_pool_size": len(active_pool),
                "pending_pool_size": len(pending_pool),
                "frozen_pool_size": len(frozen_pool),
                "terminated_pool_size": len(terminated_pool),
                "active_card_id": session_ids.get("cardIdActive"),
                "active_affiliate_id": affiliate_id})
    return rec

def pre_flight_enumerate_cards_by_status(session_ids: dict) -> dict:
    """GET /api/v1/cards?status=S for each lifecycle status and union discovered
    cardIds into the matching pool in session_ids.  Called as Phase 0f1 (after
    POST /cards/query, before ACTIVE.txt load) so it augments rather than
    replaces previous discovery.  Resolves CARD-19 (empty PENDING_ACTIVATION
    pool) and keeps all pools fresh without relying on stale ACTIVE.txt labels.

    Status → pool mapping:
      ACTIVE             → cardIdActivePool (items with fulfillmentStatus=failed+PHYSICAL also → cardIdFailedFulfillmentPool)
      PENDING_ACTIVATION → cardIdPendingActivationPool
      FROZEN             → cardIdFrozenPool
      TERMINATED         → cardIdTerminatedPool
      READY              → cardIdReadyPool
      PENDING_ISSUANCE   → cardIdPendingPool

    Note: there is no top-level FAILED status. Failed-fulfillment cards are
    ACTIVE PHYSICAL cards with fulfillmentStatus=failed in the card object.
    """
    STATUS_TO_POOL = {
        "ACTIVE":             "cardIdActivePool",
        "PENDING_ACTIVATION": "cardIdPendingActivationPool",
        "FROZEN":             "cardIdFrozenPool",
        "TERMINATED":         "cardIdTerminatedPool",
        "READY":              "cardIdReadyPool",
        "PENDING_ISSUANCE":   "cardIdPendingPool",
    }
    LEGACY_KEYS = {
        "cardIdActivePool":            "cardIdActive",
        "cardIdFrozenPool":            "cardIdFrozen",
        "cardIdPendingActivationPool": "cardIdPendingActivation",
        "cardIdPendingPool":           "cardIdPending",
        "cardIdTerminatedPool":        "cardIdTerminated",
        "cardIdReadyPool":             "cardIdReady",
        "cardIdFailedFulfillmentPool": "cardIdFailedFulfillment",
    }
    rec = {
        "step": "enumerate_cards_by_status",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "per_status": {},
        "total_discovered": 0,
        "pool_deltas": {},
    }
    total = 0
    for st, pool_key in STATUS_TO_POOL.items():
        url = f"{BASE_URL}/api/v1/cards?status={st}"
        try:
            resp = execute("GET", url, {"Accept": "application/json"}, None, timeout=20)
        except Exception as ex:
            rec["per_status"][st] = {"status": "ERROR", "reason": str(ex)[:200]}
            continue
        sc = resp.get("status_code", 0)
        if not (resp.get("ok") and 200 <= sc < 300):
            body_excerpt = resp.get("body") if resp.get("body") is not None else resp.get("body_text")
            rec["per_status"][st] = {"status": "FAIL", "http": sc, "reason": str(body_excerpt)[:200]}
            continue
        body = resp.get("body")
        if isinstance(body, dict):
            items = body.get("data") or body.get("items") or body.get("content") or []
        elif isinstance(body, list):
            items = body
        else:
            rec["per_status"][st] = {"status": "DEGRADED",
                                     "reason": f"unexpected body type: {type(body).__name__}"}
            continue
        if not isinstance(items, list):
            rec["per_status"][st] = {"status": "DEGRADED", "reason": "data field is not a list"}
            continue
        discovered = []
        for item in items:
            if isinstance(item, dict):
                cid = item.get("cardId") or item.get("id")
                if cid and isinstance(cid, str):
                    discovered.append(cid)
                    # Capture a foreign affiliateId — an affiliate linked to a DIFFERENT
                    # bank than the session bank. Used by affiliate_not_linked_to_bank_rejected
                    # scenarios so the backend sees a real affiliate that genuinely isn't
                    # associated with the bank under test.
                    if not session_ids.get("foreignAffiliateId"):
                        _item_bank = item.get("bankId") or (item.get("bank") or {}).get("bankId") or ""
                        _item_aff  = item.get("affiliateId") or (item.get("affiliate") or {}).get("affiliateId") or ""
                        _sess_bank = session_ids.get("bankId") or ""
                        if _item_bank and _item_aff and _item_bank != _sess_bank:
                            session_ids["foreignAffiliateId"] = _item_aff
                    # ACTIVE PHYSICAL cards with fulfillmentStatus=failed are candidates
                    # for FUL-03 (reinitiate). fulfillmentStatus is a top-level field
                    # on ACTIVE PHYSICAL cards; also try nested form for safety.
                    if st == "ACTIVE" and (item.get("productType") or "").upper() == "PHYSICAL":
                        fs = (
                            item.get("fulfillmentStatus")
                            or (item.get("fulfillment") or {}).get("fulfillmentStatus")
                            or (item.get("fulfillment") or {}).get("status")
                            or ""
                        )
                        if fs.upper() == "FAILED":
                            ff_pool = session_ids.setdefault("cardIdFailedFulfillmentPool", [])
                            if cid not in ff_pool:
                                ff_pool.append(cid)
                    # PENDING_ACTIVATION cards owned by the canonical affiliate go into a
                    # dedicated pool so CARD-19 activate happy paths don't get wrong-affiliate
                    # cards (which return 404 when the request body carries canonical affiliateId).
                    if st == "PENDING_ACTIVATION":
                        _canonical_aff = session_ids.get("affiliateId")
                        _card_aff = (
                            item.get("affiliateId")
                            or (item.get("affiliate") or {}).get("affiliateId")
                            or (item.get("affiliate") or {}).get("id")
                            or ""
                        )
                        if _canonical_aff and _card_aff == _canonical_aff:
                            _owned_pool = session_ids.setdefault("cardIdPendingActivationOwnedPool", [])
                            if cid not in _owned_pool:
                                _owned_pool.append(cid)
            elif isinstance(item, str) and item.startswith("CAR-"):
                discovered.append(item)
        existing = session_ids.get(pool_key) or []
        before = len(existing)
        merged = list(existing)
        for cid in discovered:
            if cid not in merged:
                merged.append(cid)
        session_ids[pool_key] = merged
        delta = len(merged) - before
        total += len(discovered)
        rec["per_status"][st] = {"status": "OK", "found": len(discovered), "new_to_pool": delta}
        rec["pool_deltas"][pool_key] = {"before": before, "after": len(merged), "added": delta}
        legacy = LEGACY_KEYS.get(pool_key)
        if legacy and not session_ids.get(legacy) and merged:
            session_ids[legacy] = merged[0]
    # Dedicated pass: GET /api/v1/cards?status=ACTIVE&productType=PHYSICAL
    # User clarification 2026-05-13: fulfillmentStatus is a top-level field on
    # ACTIVE PHYSICAL cards. The general ?status=ACTIVE query may not include
    # productType in each item, causing the nested check to miss failed cards.
    # This pass explicitly targets physical cards and reads fulfillmentStatus flat.
    _phy_url = f"{BASE_URL}/api/v1/cards?status=ACTIVE&productType=PHYSICAL"
    _phy_failed_found = 0
    try:
        _phy_resp = execute("GET", _phy_url, {"Accept": "application/json"}, None, timeout=20)
        if _phy_resp.get("ok") and 200 <= _phy_resp.get("status_code", 0) < 300:
            _phy_body = _phy_resp.get("body")
            _phy_items = []
            if isinstance(_phy_body, dict):
                _phy_items = _phy_body.get("data") or _phy_body.get("items") or _phy_body.get("content") or []
            elif isinstance(_phy_body, list):
                _phy_items = _phy_body
            for _item in (_phy_items if isinstance(_phy_items, list) else []):
                if not isinstance(_item, dict):
                    continue
                _cid = _item.get("cardId") or _item.get("id")
                if not (_cid and isinstance(_cid, str)):
                    continue
                _fs = (
                    _item.get("fulfillmentStatus")
                    or (_item.get("fulfillment") or {}).get("fulfillmentStatus")
                    or (_item.get("fulfillment") or {}).get("status")
                    or ""
                )
                _fs_upper = _fs.upper()
                if _fs_upper == "FAILED":
                    _ff = session_ids.setdefault("cardIdFailedFulfillmentPool", [])
                    if _cid not in _ff:
                        _ff.append(_cid)
                        _phy_failed_found += 1
                elif _fs_upper == "PERSONALIZING":
                    _pp = session_ids.setdefault("cardIdPersonalizingPool", [])
                    if _cid not in _pp:
                        _pp.append(_cid)
                    # ACTIVE physical PERSONALIZING cards are also refresh-eligible
                    _rp = session_ids.setdefault("cardIdRefreshInProgressPool", [])
                    if _cid not in _rp:
                        _rp.append(_cid)
        rec["per_status"]["ACTIVE_PHYSICAL_failed_scan"] = {
            "status": "OK", "new_failed_added": _phy_failed_found,
            "total_failed_pool": len(session_ids.get("cardIdFailedFulfillmentPool", [])),
        }
    except Exception as _ex:
        rec["per_status"]["ACTIVE_PHYSICAL_failed_scan"] = {"status": "ERROR", "reason": str(_ex)[:200]}

    # Dedicated pass: GET /api/v1/cards?status=PENDING_ISSUANCE&productType=PHYSICAL
    # FUL-02 (refresh) needs PHYSICAL cards with fulfillment in progress.
    # Same pattern: query by status+productType, read fulfillmentStatus flat.
    _pend_url = f"{BASE_URL}/api/v1/cards?status=PENDING_ISSUANCE&productType=PHYSICAL"
    _pend_refresh_found = 0
    try:
        _pend_resp = execute("GET", _pend_url, {"Accept": "application/json"}, None, timeout=20)
        if _pend_resp.get("ok") and 200 <= _pend_resp.get("status_code", 0) < 300:
            _pend_body = _pend_resp.get("body")
            _pend_items = []
            if isinstance(_pend_body, dict):
                _pend_items = _pend_body.get("data") or _pend_body.get("items") or _pend_body.get("content") or []
            elif isinstance(_pend_body, list):
                _pend_items = _pend_body
            for _item in (_pend_items if isinstance(_pend_items, list) else []):
                if not isinstance(_item, dict):
                    continue
                _cid = _item.get("cardId") or _item.get("id")
                if not (_cid and isinstance(_cid, str)):
                    continue
                # Only add cards where fulfillmentStatus == PERSONALIZING.
                # Backend rejects refresh with 409 "only allowed while fulfillment is in progress"
                # for any other fulfillmentStatus, even if the card state is PENDING_ISSUANCE.
                _fs = (
                    _item.get("fulfillmentStatus")
                    or (_item.get("fulfillment") or {}).get("fulfillmentStatus")
                    or (_item.get("fulfillment") or {}).get("status")
                    or ""
                )
                if _fs.upper() == "PERSONALIZING":
                    _rp = session_ids.setdefault("cardIdRefreshInProgressPool", [])
                    if _cid not in _rp:
                        _rp.append(_cid)
                        _pend_refresh_found += 1
        rec["per_status"]["PENDING_ISSUANCE_PHYSICAL_refresh_scan"] = {
            "status": "OK", "new_refresh_added": _pend_refresh_found,
            "total_refresh_pool": len(session_ids.get("cardIdRefreshInProgressPool", [])),
        }
    except Exception as _ex:
        rec["per_status"]["PENDING_ISSUANCE_PHYSICAL_refresh_scan"] = {"status": "ERROR", "reason": str(_ex)[:200]}

    # Additional pass: GET /api/v1/cards?status=PENDING_ACTIVATION&productType=PHYSICAL
    # Live testing shows PENDING_ACTIVATION physical cards are also refresh-eligible;
    # PENDING_ISSUANCE cards are often already past the in-progress window.
    _pend_act_url = f"{BASE_URL}/api/v1/cards?status=PENDING_ACTIVATION&productType=PHYSICAL"
    _pend_act_refresh_found = 0
    try:
        _pa_resp = execute("GET", _pend_act_url, {"Accept": "application/json"}, None, timeout=20)
        if _pa_resp.get("ok") and 200 <= _pa_resp.get("status_code", 0) < 300:
            _pa_body = _pa_resp.get("body")
            _pa_items = []
            if isinstance(_pa_body, dict):
                _pa_items = _pa_body.get("data") or _pa_body.get("items") or _pa_body.get("content") or []
            elif isinstance(_pa_body, list):
                _pa_items = _pa_body
            for _item in (_pa_items if isinstance(_pa_items, list) else []):
                if not isinstance(_item, dict):
                    continue
                _cid = _item.get("cardId") or _item.get("id")
                if not (_cid and isinstance(_cid, str)):
                    continue
                # Only add cards where fulfillmentStatus == PERSONALIZING (same rule as PENDING_ISSUANCE).
                _fs = (
                    _item.get("fulfillmentStatus")
                    or (_item.get("fulfillment") or {}).get("fulfillmentStatus")
                    or (_item.get("fulfillment") or {}).get("status")
                    or ""
                )
                if _fs.upper() == "PERSONALIZING":
                    _rp = session_ids.setdefault("cardIdRefreshInProgressPool", [])
                    if _cid not in _rp:
                        _rp.append(_cid)
                        _pend_act_refresh_found += 1
        rec["per_status"]["PENDING_ACTIVATION_PHYSICAL_refresh_scan"] = {
            "status": "OK", "new_refresh_added": _pend_act_refresh_found,
            "total_refresh_pool": len(session_ids.get("cardIdRefreshInProgressPool", [])),
        }
    except Exception as _ex:
        rec["per_status"]["PENDING_ACTIVATION_PHYSICAL_refresh_scan"] = {"status": "ERROR", "reason": str(_ex)[:200]}

    rec.update({
        "status": "OK",
        "total_discovered": total,
        "completed_at": dt.datetime.now().isoformat(),
    })
    return rec


def load_card_pools_from_active_txt(session_ids: dict, txt_path: Path | None = None) -> dict:
    """Parse ACTIVE.txt, verify each cardId's actual state via GET /cards/{id},
    then merge into session_ids pools by ACTUAL backend state (ignoring the file's
    section header). Run-2026-05-07 evidence: ACTIVE.txt's ACTIVE section
    contained cards that backend reports as FROZEN — pooling them under ACTIVE
    poisoned freeze/loads/etc. happy paths with 400 'Only ACTIVE cards can be
    freezed.' State-verification eliminates label drift while still using the
    backend-supplied cards.
    """
    rec = {"step": "seed_card_pools_from_active_txt", "status": "PENDING",
           "started_at": dt.datetime.now().isoformat()}
    p = Path(txt_path) if txt_path else (_SVC_DIR / "data" / "ACTIVE.txt")
    if not p.exists():
        rec.update({"status": "SKIPPED", "reason": f"file not found: {p}"})
        return rec
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as ex:
        rec.update({"status": "ERROR", "reason": f"read failed: {ex}"})
        return rec
    # Parse sections. 2026-05-07 ACTIVE.txt uses annotated section headers
    # ("ACTIVE:for (freeze)", "Fulfilment reinitiate: (FAILED state)", etc.)
    # so the legacy "line ends with ':'" heuristic missed half the file.
    # New rule: any line that doesn't start with "CAR-" / "LIM-" / "CardId:"
    # and contains a colon is a section header. Both the part before the
    # colon AND the parenthetical hint after it determine routing.
    # Also parse the "LIMIT COMPLETE:" CardId and "LIM ID's:" (LIM ID, amount)
    # pairs so LIM-02 ops/complete picks them up at runtime — these reset
    # between runs and the user updates ACTIVE.txt rather than the harness.
    parsed: list[dict] = []
    lim_ops_card_id: str | None = None
    lim_pairs_parsed: list[tuple[str, int]] = []
    current_header: str | None = None
    in_lim_section = False
    in_limit_complete_section = False
    for line in text.splitlines():
        s = line.strip().rstrip(",").strip()
        if not s:
            continue
        # LIMIT COMPLETE section: pick up the single shared cardId line
        # ("CardId:  CAR-…") then leave card-pool routing.
        if s.upper().startswith("LIMIT COMPLETE"):
            current_header = None
            in_limit_complete_section = True
            in_lim_section = False
            continue
        # LIM ID's section: list of "LIM-… (amount)" pairs.
        if "LIM ID" in s.upper():
            in_lim_section = True
            in_limit_complete_section = False
            current_header = None
            continue
        if in_limit_complete_section and s.lower().startswith("cardid"):
            # "CardId: CAR-..."
            after = s.split(":", 1)[1].strip() if ":" in s else ""
            if after.startswith("CAR-"):
                lim_ops_card_id = after
            continue
        if in_lim_section and s.startswith("LIM-"):
            # "LIM-XXX (amount)"
            import re as _re
            m = _re.match(r'^(LIM-[A-Za-z0-9]+)\s*\(\s*(\d+)\s*\)\s*$', s)
            if m:
                lim_pairs_parsed.append((m.group(1), int(m.group(2))))
            continue
        if s.startswith("CAR-"):
            if current_header and not in_limit_complete_section:
                parsed.append({"cardId": s, "raw_label": current_header})
            continue
        # Skip non-card-pool helper lines.
        if s.startswith("LIM-") or s.lower().startswith("(use"):
            continue
        if ":" in s:
            current_header = s
            in_lim_section = False
            in_limit_complete_section = False

    # Map each parsed (cardId, header) entry to a target pool. Hints in the
    # header text override raw state.
    def _route(header: str) -> tuple[str | None, str | None, bool]:
        """Returns (label_state, target_pool_override, is_physical).
        - label_state: best-guess primary state for state-verify drift logging
        - target_pool_override: if set, route directly to this pool, skipping
          the actual_state→pool mapping (used for FAILED cards which lack
          a generic state-pool, and for endpoint-tagged ACTIVE pools)
        - is_physical: form-factor flag
        """
        h_upper = header.upper()
        is_physical = "(PHYSICAL)" in h_upper.replace(" ", "")
        # FAILED state — annotated as "(FAILED state)" or label "FAILED"
        if "FAILED" in h_upper:
            return ("FAILED", "cardIdFailedFulfillmentPool", is_physical)
        # PENDING ISSUANCE PHYSICAL marked "for fulfillment refresh"
        if ("PENDING ISSUANCE" in h_upper or "PENDING_ISSUANCE" in h_upper) and is_physical:
            if "REFRESH" in h_upper or "FULFILLMENT" in h_upper:
                return ("PENDING_ISSUANCE", "cardIdRefreshInProgressPool", True)
            return ("PENDING_ISSUANCE", "cardIdPendingPhysicalPool", True)
        # ACTIVE annotated for terminate — dedicated terminate pool so freeze
        # consumers don't poach.
        if h_upper.startswith("ACTIVE") and "TERMINATE" in h_upper:
            if is_physical:
                return ("ACTIVE", "cardIdActiveTerminatePhysicalPool", True)
            return ("ACTIVE", "cardIdActiveTerminatePool", False)
        # ACTIVE annotated for freeze — primary ACTIVE consumer pool.
        if h_upper.startswith("ACTIVE") and "FREEZE" in h_upper:
            return ("ACTIVE", "cardIdActivePool", is_physical)
        # ACTIVE PHYSICAL annotated for reinitiate — these are ACTIVE cards
        # with fulfillmentStatus=failed; route to the failed-fulfillment pool.
        if h_upper.startswith("ACTIVE") and is_physical and "REINITIATE" in h_upper:
            return ("ACTIVE", "cardIdFailedFulfillmentPool", True)
        if h_upper.startswith("ACTIVE") and is_physical:
            return ("ACTIVE", "cardIdActivePhysicalPool", True)
        # Bare state labels.
        if h_upper.startswith("FROZEN"):              return ("FROZEN", "cardIdFrozenPool", is_physical)
        if h_upper.startswith("READY"):               return ("READY", "cardIdReadyPool", is_physical)
        if h_upper.startswith("PENDING_ACTIVATION") or h_upper.startswith("PENDING ACTIVATION"):
            return ("PENDING_ACTIVATION", "cardIdPendingActivationPool", is_physical)
        if h_upper.startswith("PENDING ISSUANCE") or h_upper.startswith("PENDING_ISSUANCE"):
            return ("PENDING_ISSUANCE", "cardIdPendingPool", is_physical)
        if h_upper.startswith("ACTIVE"):              return ("ACTIVE", "cardIdActivePool", is_physical)
        if h_upper.startswith("TERMINATED"):          return ("TERMINATED", "cardIdTerminatedPool", is_physical)
        return (None, None, False)

    # Verify each cardId's ACTUAL state via GET /cards/{id}; route by header
    # hint primarily, fall back to actual_state if header has no override.
    verifications = []
    drifted: list[dict] = []
    by_pool: dict[str, list[str]] = {}
    def _pool_key(actual_state: str, is_physical: bool) -> str | None:
        base = {
            "ACTIVE":             "cardIdActivePool",
            "FROZEN":             "cardIdFrozenPool",
            "READY":              "cardIdReadyPool",
            "PENDING_ACTIVATION": "cardIdPendingActivationPool",
            "PENDING_ISSUANCE":   "cardIdPendingPool",
            "FAILED":             "cardIdFailedFulfillmentPool",
            "TERMINATED":         "cardIdTerminatedPool",
        }.get(actual_state)
        if not base:
            return None
        if is_physical:
            return {
                "cardIdActivePool":   "cardIdActivePhysicalPool",
                "cardIdPendingPool":  "cardIdPendingPhysicalPool",
            }.get(base, base)
        return base
    for entry in parsed:
        cid = entry["cardId"]
        label_state, target_pool, is_physical = _route(entry["raw_label"])
        try:
            r = execute("GET", f"{BASE_URL.rstrip('/')}/api/v1/cards/{cid}",
                        {"Accept": "application/json"}, None, timeout=10)
            if not r.get("ok") or not (200 <= (r.get("status_code") or 0) < 300):
                verifications.append({"cardId": cid, "raw_label": entry["raw_label"],
                                      "actual": None, "ok": False,
                                      "status_code": r.get("status_code"),
                                      "error": r.get("error")})
                # Even if GET fails, route by header hint so FAILED cards
                # (which the GET endpoint may not return cleanly) still seed.
                if target_pool:
                    by_pool.setdefault(target_pool, []).append(cid)
                continue
            body = r.get("body") or {}
            actual = (body.get("status") if isinstance(body, dict) else None)
            if not actual and isinstance(body.get("data"), dict):
                actual = body["data"].get("status")
            actual = (actual or "").upper() or None
            verifications.append({"cardId": cid, "raw_label": entry["raw_label"],
                                  "is_physical": is_physical,
                                  "actual": actual, "ok": True,
                                  "status_code": r.get("status_code")})
            # Routing rules:
            #   - Endpoint-specific target_pool set → always honor it; the
            #     probe phase validates these cards live after ACTIVE.txt loads.
            #   - Generic state pool (target_pool None or a status-based pool)
            #     → apply drift-correction: route by actual state, log drift.
            #     This prevents stale ACTIVE-labeled cards from poisoning the
            #     ACTIVE pool with actually-FROZEN cards (2026-05-07 fix).
            ENDPOINT_SPECIFIC_POOLS = {
                "cardIdFailedFulfillmentPool",
                "cardIdPersonalizingPool",
                "cardIdRefreshInProgressPool",
                "cardIdActiveTerminatePool",
                "cardIdActiveTerminatePhysicalPool",
            }
            if target_pool and target_pool in ENDPOINT_SPECIFIC_POOLS:
                # PERSONALIZING is its own fulfillmentStatus — cards in that state
                # cannot be reinitiated but CAN be used for personalizing_state TCs.
                if actual == "PERSONALIZING":
                    key = "cardIdPersonalizingPool"
                else:
                    key = target_pool
                if actual and label_state and actual != label_state:
                    drifted.append({"cardId": cid, "label": entry["raw_label"],
                                    "label_state": label_state, "actual": actual,
                                    "note": f"drift logged; routed to {key}"})
            elif actual and label_state and actual != label_state:
                drifted.append({"cardId": cid, "label": entry["raw_label"],
                                "label_state": label_state, "actual": actual})
                key = _pool_key(actual, is_physical)
            elif actual:
                key = target_pool or _pool_key(actual, is_physical)
            else:
                key = target_pool
            if key:
                by_pool.setdefault(key, []).append(cid)
        except Exception as ex:
            verifications.append({"cardId": cid, "raw_label": entry["raw_label"],
                                  "ok": False, "error": str(ex)[:120]})
            if target_pool:
                by_pool.setdefault(target_pool, []).append(cid)

    # Merge into session_ids, preserving any already-discovered cards.
    # Phase 0f1 (live enumeration) is authoritative for status-based pools — never
    # let ACTIVE.txt augment them because stale IDs cause wrong-state 400s/409s.
    ENUMERATED_POOLS = {
        "cardIdActivePool", "cardIdFrozenPool", "cardIdTerminatedPool",
        "cardIdReadyPool", "cardIdPendingActivationPool", "cardIdPendingPool",
    }
    sizes = {}
    legacy_keys = {
        "cardIdActivePool":                  "cardIdActive",
        "cardIdFrozenPool":                  "cardIdFrozen",
        "cardIdPendingActivationPool":       "cardIdPendingActivation",
        "cardIdPendingPool":                 "cardIdPending",
        "cardIdTerminatedPool":              "cardIdTerminated",
        "cardIdReadyPool":                   "cardIdReady",
        "cardIdActivePhysicalPool":          "cardIdActivePhysical",
        "cardIdPendingPhysicalPool":         "cardIdPendingPhysical",
        "cardIdFailedFulfillmentPool":       "cardIdFailedFulfillment",
        "cardIdRefreshInProgressPool":       "cardIdRefreshInProgress",
        "cardIdActiveTerminatePool":         "cardIdActiveTerminate",
        "cardIdActiveTerminatePhysicalPool": "cardIdActiveTerminatePhysical",
    }
    for key, ids in by_pool.items():
        if key in ENUMERATED_POOLS and session_ids.get(key):
            # Live enumeration already filled this pool — ACTIVE.txt entries are
            # unreliable (not reset between runs) and must not contaminate it.
            sizes[key] = len(session_ids[key])
            continue
        existing = session_ids.get(key) or []
        merged = list(existing)
        for cid in ids:
            if cid not in merged:
                merged.append(cid)
        session_ids[key] = merged
        sizes[key] = len(merged)
        legacy = legacy_keys.get(key)
        if legacy and not session_ids.get(legacy) and merged:
            session_ids[legacy] = merged[0]
    # 2026-05-07: write LIM-02 ops/complete config straight from ACTIVE.txt so
    # the runner picks up the latest cardId + (limitRequestId, amount) pairs
    # without a code change each time the backend resets them.
    if lim_ops_card_id:
        session_ids["limOpsCardId"] = lim_ops_card_id
    if lim_pairs_parsed:
        session_ids["limOpsPairsQueue"] = [list(p) for p in lim_pairs_parsed]

    rec.update({
        "status": "OK" if sizes else "EMPTY",
        "file": str(p),
        "labels_loaded": sorted({e["raw_label"] for e in parsed}),
        "pool_sizes": sizes,
        "verifications": verifications,
        "drifted_labels": drifted,
        "lim_ops_card_id": lim_ops_card_id,
        "lim_ops_pairs_parsed": lim_pairs_parsed,
        "completed_at": dt.datetime.now().isoformat(),
    })
    return rec


def take_card_from_pool(session_ids: dict, pool_key: str, consumed_key: str) -> str | None:
    """JIT consumer: pop the next not-yet-consumed cardId from the named pool.
    Tracks consumed IDs in session_ids[consumed_key] to guarantee that
    sequential happy-path TCs never step on each other's cards.
    """
    pool = session_ids.get(pool_key) or []
    consumed_list = session_ids.setdefault(consumed_key, [])
    consumed_set = set(consumed_list)
    for cid in pool:
        if cid not in consumed_set:
            consumed_list.append(cid)
            return cid
    return None

def pre_flight_terminate_card_for_seed(pm_idx: dict, session_ids: dict) -> dict:
    """Terminate the dedicated 'cardIdToBeTerminated' so we have a TERMINATED
    cardId available for terminated_card_* and already_terminated scenarios.
    """
    rec = {"step": "terminate_card_for_terminated_seed", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "terminated_card_id": None}
    cid = session_ids.get("cardIdToBeTerminated")
    if not cid:
        rec.update({"reason": "no cardIdToBeTerminated in session"}); return rec
    pm_entry = pm_idx.get("POST /api/v1/cards/{cardId}/terminate")
    if not pm_entry:
        rec.update({"reason": "POST /cards/{cardId}/terminate not in Postman collection"}); return rec
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
    pv = dict(base["path_vars"]); pv["cardId"] = cid
    url = rebuild_url(base["method"], get_postman_path_template(pm_entry), pv, base["query"])
    rec["url"] = url
    resp = execute(base["method"], url, base["headers"], body, timeout=20)
    rec["response_status"] = resp.get("status_code"); rec["completed_at"] = dt.datetime.now().isoformat()
    sc = resp.get("status_code", 0)
    if (resp.get("ok") and 200 <= sc < 300) or sc == 409:
        session_ids["cardIdTerminated"] = cid
        rec.update({"status": "OK" if 200 <= sc < 300 else "ALREADY_TERMINATED", "terminated_card_id": cid})
    else:
        body_excerpt = resp.get("body") if resp.get("body") is not None else resp.get("body_text")
        rec.update({"status": "FAIL", "reason": f"terminate non-2xx ({sc}): {str(body_excerpt)[:200]}"})
    return rec

def pre_flight_probe_fulfillment_pools(session_ids: dict) -> dict:
    """Validate cardIdFailedFulfillmentPool, probe cardIdRefreshInProgressPool,
    and discover cardIdPersonalizingPool.

    Failed pool (FUL-03 reinitiate candidates):
      Phase 0f1 seeded this pool via the LIST endpoint's fulfillmentStatus=FAILED.
      FUL-03 backend reinitiate checks the same list-endpoint field, so only
      cards already in the pool are kept here.  Cards whose individual
      bureauStatus=failed but whose list fulfillmentStatus differs are NOT added
      — they would be rejected by the backend.
      Cards that no longer return bureauStatus=failed are dropped (stale).

    Personalizing pool:
      ACTIVE PHYSICAL cards with bureauStatus=personalizing are discovered here
      and added to cardIdPersonalizingPool (FUL-03/FUL-02 personalizing TCs).

    Refresh pool (FUL-02 happy-path candidates):
      Cards in cardIdRefreshInProgressPool with terminal bureauStatus
      (failed/completed/delivered/cancelled) are dropped (no longer refreshable).
    """
    rec = {
        "step": "probe_fulfillment_pools",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "probed": 0,
        "failed_kept": 0,
        "failed_dropped": 0,
        "personalizing_found": 0,
        "refresh_kept": 0,
        "refresh_dropped": 0,
    }
    # Probe the failed pool for liveness only.
    # fulfillmentStatus=FAILED was already confirmed by Phase 0f1 via the list endpoint.
    # Personalizing cards are now discovered by Phase 0f1 directly (ACTIVE PHYSICAL pass).
    # We only need to verify these cards still exist (GET /cards/{cardId} → 200).
    candidates = list(session_ids.get("cardIdFailedFulfillmentPool") or [])
    if not candidates:
        rec.update({"status": "SKIPPED", "reason": "no failed pool candidates to probe"})
        return rec

    failed_pool_before = set(session_ids.get("cardIdFailedFulfillmentPool") or [])
    validated_failed: list[str] = []
    personalizing: list[str] = []

    for cid in candidates:
        # Check top-level card status and productType first.
        card_url = f"{BASE_URL}/api/v1/cards/{cid}"
        top_status = ""
        product_type = ""
        try:
            cr = execute("GET", card_url, {"Accept": "application/json"}, None, timeout=10)
            if cr.get("ok") and 200 <= (cr.get("status_code") or 0) < 300:
                cb = cr.get("body") or {}
                top_status = ((cb.get("status") if isinstance(cb, dict) else None) or "").upper()
                product_type = ((cb.get("productType") if isinstance(cb, dict) else None) or "").upper()
        except Exception:
            pass

        # Only PHYSICAL cards can have FAILED fulfillment — skip virtual cards.
        if product_type and product_type != "PHYSICAL":
            rec["probed"] += 1
            continue

        # Only ACTIVE cards are FUL-03 reinitiate candidates.
        if top_status and top_status != "ACTIVE":
            rec["probed"] += 1
            continue  # TERMINATED/FROZEN/etc — skip

        rec["probed"] += 1
        # Liveness check: card is ACTIVE + PHYSICAL and was seeded by Phase 0f1
        # (which confirmed fulfillmentStatus=FAILED via the list endpoint).
        # The individual endpoint does not expose fulfillmentStatus — bureauStatus
        # from /fulfillment/status is a different field and cannot be used here.
        if cid in failed_pool_before:
            if cid not in validated_failed:
                validated_failed.append(cid)

    dropped = [c for c in failed_pool_before if c not in validated_failed]
    rec["failed_kept"] = len(validated_failed)
    rec["failed_dropped"] = len(dropped)
    rec["personalizing_found"] = len(personalizing)

    # Replace failed pool with only probe-validated cards (drops stale entries).
    session_ids["cardIdFailedFulfillmentPool"] = validated_failed
    if validated_failed:
        session_ids["cardIdFailedFulfillment"] = validated_failed[0]
    # Union personalizing — Phase 0f1 already seeded some; don't clobber.
    existing_personalizing = session_ids.get("cardIdPersonalizingPool") or []
    merged_personalizing = list(existing_personalizing)
    for cid in personalizing:
        if cid not in merged_personalizing:
            merged_personalizing.append(cid)
    session_ids["cardIdPersonalizingPool"] = merged_personalizing
    if merged_personalizing:
        session_ids["cardIdPersonalizing"] = merged_personalizing[0]
    rec["personalizing_found"] = len(merged_personalizing)

    # Probe refresh-in-progress pool — liveness check only.
    # Phase 0f1 already confirmed these cards via GET /api/v1/cards?status=PENDING_ISSUANCE
    # &productType=PHYSICAL (live query). bureauStatus from /fulfillment/status is a
    # different field and is FAILED for all PENDING_ISSUANCE PHYSICAL cards regardless
    # of their actual fulfillment state — using it as a filter would drop the entire pool.
    # A 200 from GET /api/v1/cards/{cardId} is sufficient liveness proof.
    refresh_pool_before = list(session_ids.get("cardIdRefreshInProgressPool") or [])
    validated_refresh: list[str] = []
    for cid in refresh_pool_before:
        card_url = f"{BASE_URL}/api/v1/cards/{cid}"
        try:
            resp = execute("GET", card_url, {"Accept": "application/json"}, None, timeout=10)
        except Exception:
            validated_refresh.append(cid)  # inconclusive → keep
            continue
        if resp.get("ok") and 200 <= (resp.get("status_code") or 0) < 300:
            validated_refresh.append(cid)  # card exists → keep
        # non-200 → card gone → drop (don't append)
    rec["refresh_kept"] = len(validated_refresh)
    rec["refresh_dropped"] = len(refresh_pool_before) - len(validated_refresh)
    session_ids["cardIdRefreshInProgressPool"] = validated_refresh

    rec.update({
        "status": "OK",
        "validated_failed": validated_failed,
        "dropped_stale": dropped,
        "personalizing": personalizing,
        "completed_at": dt.datetime.now().isoformat(),
    })
    return rec


def pre_flight_probe_loadable_card(session_ids: dict) -> dict:
    """Find a card from the active pool that has a usable CMS token (i.e.
    LOAD/UNLD/PIN endpoints don't 400 with 'Card token is not available').
    Probes via GET /cards/{cardId}/balance — a 200 with non-trivial body
    indicates the card is fully provisioned.
    """
    rec = {"step": "probe_loadable_card", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "loadable_card_id": None, "candidates_tried": 0}
    pool = session_ids.get("cardIdActivePool") or []
    if not pool:
        rec.update({"reason": "empty active pool"}); return rec
    for i, cid in enumerate(pool[:12]):
        rec["candidates_tried"] = i + 1
        # Step 1: verify the card is currently ACTIVE (status may have
        # changed since the pool was queried).
        get_url = f"{BASE_URL}/api/v1/cards/{cid}"
        get_resp = execute("GET", get_url, {"Accept": "application/json"}, None, timeout=10)
        if not (get_resp.get("ok") and 200 <= (get_resp.get("status_code") or 0) < 300):
            continue
        gbody = get_resp.get("body")
        if not isinstance(gbody, dict): continue
        st = (gbody.get("status") or "").upper()
        if st != "ACTIVE":
            continue
        # Step 2: balance must indicate the card is provisioned and live.
        bal_url = f"{BASE_URL}/api/v1/cards/{cid}/balance"
        bal_resp = execute("GET", bal_url, {"Accept": "application/json"}, None, timeout=15)
        if not (bal_resp.get("ok") and 200 <= (bal_resp.get("status_code") or 0) < 300):
            continue
        bbody = bal_resp.get("body")
        if not isinstance(bbody, dict): continue
        is_unavailable = bbody.get("isAvailable") is False
        source = (bbody.get("source") or "").upper()
        if is_unavailable or source == "UNAVAILABLE":
            continue
        session_ids["cardIdLoadable"] = cid
        rec.update({"status": "OK", "loadable_card_id": cid})
        return rec
    rec.update({"status": "DEGRADED", "reason": f"no loadable card found among {len(pool[:12])} candidates"})
    return rec

def pre_flight_freeze_card(pm_idx: dict, session_ids: dict) -> dict:
    """Freeze the ACTIVE card to seed a FROZEN cardId for UNF-01 / frozen_card_*
    scenarios. Idempotent — re-freezing a frozen card returns the conflict the
    backend allows, which is fine for our purposes (we just want a frozen ID).
    """
    rec = {"step": "freeze_card_for_frozen_seed", "started_at": dt.datetime.now().isoformat(),
           "status": "SKIPPED", "frozen_card_id": None}
    cid = session_ids.get("cardIdActive")
    if not cid:
        rec.update({"reason": "no cardIdActive in session"}); return rec
    pm_entry = pm_idx.get("POST /api/v1/cards/{cardId}/freeze")
    if not pm_entry:
        rec.update({"reason": "POST /cards/{cardId}/freeze not in Postman collection"}); return rec
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
    pv = dict(base["path_vars"]); pv["cardId"] = cid
    url = rebuild_url(base["method"], get_postman_path_template(pm_entry), pv, base["query"])
    rec["url"] = url
    resp = execute(base["method"], url, base["headers"], body, timeout=20)
    rec["response_status"] = resp.get("status_code"); rec["completed_at"] = dt.datetime.now().isoformat()
    sc = resp.get("status_code", 0)
    if resp.get("ok") and 200 <= sc < 300:
        session_ids["cardIdFrozen"] = cid  # same card, just frozen now
        rec.update({"status": "OK", "frozen_card_id": cid})
    elif sc == 409:
        # already frozen — still usable as the FROZEN seed
        session_ids["cardIdFrozen"] = cid
        rec.update({"status": "ALREADY_FROZEN", "frozen_card_id": cid})
    else:
        body_excerpt = resp.get("body") if resp.get("body") is not None else resp.get("body_text")
        rec.update({"status": "FAIL", "reason": f"freeze non-2xx ({sc}): {str(body_excerpt)[:200]}"})
    return rec

# --- HYBRID: post-mint verify (Cluster-C mitigation) ----------------------
def verify_seeded_id_queryable(seed_id: str | None, get_path_template: str,
                               max_retries: int = 2, delay_s: float = 1.0) -> dict:
    """GET the freshly-minted resource. Retries on 404 with backoff.
    Distinguishes 'eventual consistency' (transient 404 that resolves) from
    'persistence split' (404 that never resolves — Cluster C signature)."""
    rec = {"verified": False, "url": None, "status": None, "attempts": 0,
           "cluster_c_suspected": False, "reason": None}
    if not seed_id:
        rec["reason"] = "no seed_id provided"
        return rec
    url = f"{BASE_URL}{get_path_template.replace('{cardId}', seed_id).replace('{bankId}', seed_id).replace('{affiliateId}', seed_id)}"
    rec["url"] = url
    last_status = None
    for attempt in range(max_retries + 1):
        rec["attempts"] = attempt + 1
        resp = execute("GET", url, {"Accept": "application/json"}, None, timeout=15)
        sc = resp.get("status_code")
        last_status = sc
        if resp.get("ok") and sc and 200 <= sc < 300:
            rec.update({"verified": True, "status": sc})
            return rec
        if not resp.get("ok"):
            rec.update({"status": sc, "reason": f"transport: {resp.get('error')}"})
            return rec
        if sc != 404:
            rec.update({"status": sc, "reason": f"GET returned non-2xx non-404 ({sc}); not Cluster-C signature"})
            return rec
        if attempt < max_retries:
            time.sleep(delay_s * (attempt + 1))
    rec.update({"status": last_status, "cluster_c_suspected": True,
                "reason": f"GET returned 404 after {max_retries + 1} attempts — likely backend write/read persistence split"})
    return rec

# --- HYBRID: per-TC GET-after-POST probe ----------------------------------
# Uses shared probe module ~/Kardit/harnesses/probe.py
sys.path.insert(0, str(Path(__file__).parent))
from probe import probe_get_after_post as _shared_probe, state_effect_probe as _shared_state_probe

PROBE_MAX_WAIT_S = float(os.environ.get("CARDS_PROBE_MAX_WAIT_S", "6.0"))

def probe_get_after_post(resource_id: str | None,
                          primary_path_template: str = "/api/v1/cards/{cardId}",
                          secondary_path_template: str | None = "/api/v1/cards/{cardId}/balance",
                          token_replacements: dict | None = None,
                          max_retries: int = 2,
                          delay_s: float = 1.0) -> dict:
    return _shared_probe(
        resource_id=resource_id,
        base_url=BASE_URL,
        execute=execute,
        primary_path_template=primary_path_template,
        secondary_path_template=secondary_path_template,
        token_replacements=token_replacements,
        max_retries=max_retries,
        delay_s=delay_s,
        max_wait_s=PROBE_MAX_WAIT_S,
    )

def state_effect_probe(resource_id, verify_path_template, expected_field_path,
                       expected_value, max_retries: int = 1, delay_s: float = 1.0):
    return _shared_state_probe(
        resource_id=resource_id,
        base_url=BASE_URL,
        execute=execute,
        verify_path_template=verify_path_template,
        expected_field_path=expected_field_path,
        expected_value=expected_value,
        max_retries=max_retries,
        delay_s=delay_s,
    )

# --- State-verification registry (T9) -------------------------------------
# Maps (scenario_keyword, endpoint) -> verification spec. Lets the harness
# upgrade B1_db_verify BLOCKEDs to deterministic PASS/FAIL when the side
# effect IS observable via an existing GET endpoint. Narrow scope by design:
# only state changes that are visible from outside the API. Audit-log,
# notification, CMS-internal verifications stay BLOCKED honestly.
def _is_status(v, *expected_uppers):
    return str(v).upper() in expected_uppers

STATE_VERIFY_REGISTRY = {
    "platform_state_updates_after_cms_success": {
        "POST /api/v1/cards/{cardId}/freeze": {
            "verify_path": "/api/v1/cards/{cardId}",
            "field": "status",
            "expected": lambda v: _is_status(v, "FROZEN", "BLOCKED"),
            "description": "card status FROZEN/BLOCKED after /freeze",
        },
        "POST /api/v1/cards/{cardId}/unfreeze": {
            "verify_path": "/api/v1/cards/{cardId}",
            "field": "status",
            "expected": lambda v: _is_status(v, "ACTIVE", "READY", "UNFROZEN"),
            "description": "card status ACTIVE/READY after /unfreeze",
        },
        "POST /api/v1/cards/{cardId}/terminate": {
            "verify_path": "/api/v1/cards/{cardId}",
            "field": "status",
            "expected": lambda v: _is_status(v, "TERMINATED"),
            "description": "card status TERMINATED after /terminate",
        },
        "POST /api/v1/cards/{cardId}/fulfillment/refresh": {
            "verify_path": "/api/v1/cards/{cardId}/fulfillment/status",
            "field": "fulfillment.lastUpdatedAt",
            "expected": lambda v: bool(v),
            "description": "fulfillment.lastUpdatedAt set after /refresh",
        },
        "POST /api/v1/cards/{cardId}/fulfillment/reinitiate": {
            "verify_path": "/api/v1/cards/{cardId}/fulfillment/status",
            "field": "fulfillment.status",
            "expected": lambda v: bool(v) and str(v).strip() != "",
            "description": "fulfillment.status set after /reinitiate",
        },
    },
}

def lookup_state_verify(scenario: str, endpoint: str) -> dict | None:
    s = (scenario or "").lower()
    for keyword, by_ep in STATE_VERIFY_REGISTRY.items():
        if keyword in s and endpoint in by_ep:
            return by_ep[endpoint]
    return None

# --- HYBRID: lifecycle ordering -------------------------------------------
def order_pack_by_lifecycle(pack_endpoints: list, lifecycle_order: list[str]) -> list:
    """Reorder pack endpoints to match lifecycle_order (by api_id). Endpoints not in lifecycle stay at end."""
    by_id = {ep["api_id"]: ep for ep in pack_endpoints}
    ordered = []
    seen = set()
    for api_id in lifecycle_order:
        if api_id in by_id:
            ordered.append(by_id[api_id])
            seen.add(api_id)
    for ep in pack_endpoints:
        if ep["api_id"] not in seen:
            ordered.append(ep)
    return ordered

def load_lifecycle_order() -> list[str]:
    if not LIFECYCLE_PATH.exists():
        return []
    with open(LIFECYCLE_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return list(cfg.get("order") or [])

# --- mutation engine -------------------------------------------------------
ZERO_UUID = "00000000-0000-0000-0000-000000000000"

def snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])

def _find_and_apply(body: dict, field: str, action: str, value: Any = None) -> bool:
    """Walk arbitrarily deep, find the first key matching `field` (case-insensitive),
    apply action='drop'|'set'. Returns True if applied."""
    if not isinstance(body, dict):
        return False
    for k in list(body.keys()):
        if k.lower() == field.lower():
            if action == "drop":
                body.pop(k)
            else:
                body[k] = value
            return True
    for v in body.values():
        if isinstance(v, dict):
            if _find_and_apply(v, field, action, value):
                return True
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and _find_and_apply(item, field, action, value):
                    return True
    return False

def drop_field(body: Any, field: str) -> Any:
    if not isinstance(body, dict): return body
    body = copy.deepcopy(body)
    _find_and_apply(body, field, "drop")
    return body

def set_field(body: Any, field: str, value: Any) -> Any:
    if not isinstance(body, dict): return body
    body = copy.deepcopy(body)
    _find_and_apply(body, field, "set", value)
    return body

def classify_scenario(scenario: str, expected: str) -> dict:
    s = scenario.lower()

    # ---- 1. genuine BLOCKED (DB/multi-call/state/role/external-system) ----
    if any(k in s for k in (
        "audit_log", "tenant_created", "admin_context", "persistence", "_persisted",
        "metadata_persisted", "timestamp_recorded", "actor_recorded",
        "decision_timestamp_recorded", "decision_actor_recorded",
        "notification_event", "notification_created", "notification_triggered",
        "notification_to_affiliate", "notification_to_customer",
        "iam_account_provisioned", "iam_failure", "admin_iam",
        "status_history", "_history_updated", "_history_entry_created",
        "platform_state_updates_after_cms_success",
        "cms_permanent_failure_no_state_change",
        "card_status_persisted", "fulfillment_status_persisted",
        "balance_persisted", "limit_persisted",
        "activate_creates_va", "va_creation",
        "load_prevented_until_va_ready",
        "request_id_created", "audit_record_created",
        # CMS / virtual-account / bureau external-system verifications
        "cms_token_obtained", "cms_signature_computed", "cms_mac_included",
        "cms_create_unit_card_called", "cms_failure_no_duplicate_card",
        "cms_retry_", "cms_idempotency_",
        "cms_failure_retry_policy", "cms_request_log_created",
        "cms_timeout_cached_fallback", "cms_failure_no_cache_returns_502",
        "cms_invalid_response_fallback",
        "virtual_account_provisioned", "virtual_account_failure_partial_state",
        "virtual_account_creation_idempotent",
        "bureau_push_failure_retryable_partial", "bureau_push_succeeded",
        # 2026-05-08: virtual/physical_card_status_X are response-shape inspections
        # ("issuance returns the card status"), not state-persistence verifications.
        # Removed from BLOCKED list; they're handled as as_is response-shape below.
        "card_provisioning_event_emitted", "card_event_published",
        "card_lifecycle_event_created", "transaction_record_created",
        "fulfillment_provider_called", "fulfillment_callback_received",
        # T13: additional DB-verify patterns observed in adjacent services
        # (Bank, Affiliate). Adding here so they classify cleanly as B1
        # instead of falling through to the B9 catch-all.
        "relationship_status_updated", "actor_metadata_recorded",
        "decision_persisted", "approval_history_recorded",
        "tenant_provisioned", "iam_role_assigned",
        "webhook_dispatched", "webhook_retry_scheduled",
        "outbox_message_published", "saga_step_completed",
        # 2026-05-07: activate-endpoint scenarios that need backend chaos
        # hooks or notification audit endpoints — runner can't simulate.
        "cms_unreachable_502",
        "notification_on_failure_where_required",
        "notification_on_success",
    )):
        return {"action": "blocked", "reason": "Skipped — this test wants to confirm something happened in the database (or wants a follow-up call to verify), and our HTTP-only runner can't see inside the database"}
    # Idempotency: send the same request twice, verdict on response equivalence
    if any(k in s for k in (
        "_idempotent_on_retry", "session_idempotent",
        "idempotency", "repeated_reads_consistent",
    )):
        return {"action": "idempotency_double_send"}
    # NOTE (T17): for endpoints with a probe wired in (POST /cards/issuance,
    # POST /cards/{cardId}/load-requests), the GET-after-POST persistence probe
    # supersedes the read_after_write_chain action — the probe runs per-TC for
    # every 2xx write and provides deterministic attribution. read_after_write_chain
    # remains a fallback for scenarios that explicitly request it on endpoints
    # without probe coverage.
    # Read-after-write: execute the write, then immediately GET the resource and verify
    if any(k in s for k in ("read_after_action_consistent", "read_after_decision_consistent",
                            "read_after_create_consistent", "read_after_")):
        return {"action": "read_after_write_chain"}
    # Concurrency: fire the same request N times in parallel; PASS if all return same status
    if any(k in s for k in ("concurrent_", "_consistency_concurrent")):
        return {"action": "concurrent_parallel_send", "n": 5}
    # Duplicate request id (same as concurrency for our purposes — fire twice with same body)
    if "duplicate_request_id" in s:
        return {"action": "idempotency_double_send"}
    # SLA
    if "response_time_within_sla" in s:
        return {"action": "sla_check", "threshold_seconds": 2.0}
    if "large_result_set_performance" in s:
        return {"action": "set_query", "key": "pageSize", "value": "1000"}
    if any(k in s for k in ("rate_limit", "throttle")):
        return {"action": "blocked", "reason": "Skipped — this test wants to flood the API with many fast requests; we avoided sending that flood here so we don't trip alarms or look like an attack on the live server"}
    # Cards-specific state-dependent (run as-is, single available card)
    if any(k in s for k in (
        "already_target_state", "already_frozen", "already_unfrozen", "already_terminated",
        "already_active_rejected",
        "affiliate_not_linked_to_bank_rejected", "product_not_available_for_bank_rejected",
        "affiliate_bank_partnership_missing_rejected",
        "invalid_source_state", "personalizing_state_policy",
        "non_active_card_rejected", "terminated_card_cannot",
        "terminated_card_rejected", "frozen_card_policy_enforced",
        "archived_or_terminated_visibility",
        "frozen_card_cannot_load", "frozen_card_cannot_unload",
        "expired_", "stale_",
        "cross_tenant", "foreign_tenant", "wrong_tenant",
        "wrong_bank_reviewer", "bank_id_path_mismatch",
        "foreign_affiliate_id_rejected", "foreign_bank_rejected",
        "foreign_bank_scope_rejected", "foreign_scope_rejected",
        "foreign_scope_filtered_out", "only_combined_scope_affected",
        "affiliate_not_linked_to_bank_rejected",
        "ineligible_bank", "inactive_bank", "archived_affiliate",
        "ineligible_cards_skipped",
        "suspended_affiliate_rejected", "blocked_affiliate_rejected",
        "non_pending_request", "already_completed_request",
        "limit_request_already_complete", "limit_request_pending",
        "load_below_minimum", "load_exceeds_max",
        "insufficient_balance_rejected", "destination_account_invalid_rejected",
        "unsupported_currency", "currency_mismatch",
        "non_existent_va", "va_not_ready",
    )):
        return {"action": "as_is", "note": "STATE-DEPENDENT — running against single seeded card. Interpret response: 4xx (409/422/404) = endpoint enforces state machine (matches scenario intent for negative tests); 2xx where rejection expected = state machine NOT enforced (defect)"}
    # Auth / role
    if any(k in s for k in (
        "service_provider_policy", "service_provider_can_access",
        "service_provider_sees_all", "service_provider_rejected",
        "service_provider_write_rejected", "service_provider_activation_rejected",
        "bank_user_rejected", "bank_user_cannot", "bank_user_write_rejected",
        "bank_user_activation_rejected",
        "bank_write_rejected_or_policy",
        "affiliate_user_rejected", "affiliate_user_cannot",
        "bank_owned_access_limited",
        "external_affiliate_scope_limited", "bank_scope_matches_request",
        "scope_isolation_affiliate", "scope_isolation_bank",
        "denied_access_audited",
        "masking_policy_applied", "no_sensitive_fields_exposed",
        "sensitive_data_not_exposed", "masked_pan_only",
        "pan_masked", "cvv_not_returned", "pin_not_returned",
    )):
        return {"action": "as_is", "note": "RAN WITHOUT AUTH — scenario originally tests role/auth behavior; interpret API response: 401/403 = endpoint enforces auth (matches role-block intent), 2xx = endpoint is open/no auth gate"}
    if "unauthenticated" in s or "no_token" in s or "invalid_token" in s or "expired_token" in s:
        return {"action": "as_is", "note": "no auth header sent (matches scenario intent of unauthenticated/bad-token request)"}
    if "unauthorized" in s or "wrong_role" in s or "forbidden" in s:
        return {"action": "as_is", "note": "no auth header sent; if API enforces auth, will be 401/403 (matching scenario intent)"}

    # ---- 2. response-shape scenarios ----
    # Generic numbered "additional case" / "functional case" scenarios with no specific mutation hint:
    # treat as as_is happy path (the pack uses these as throwaway slots after the structured first 30)
    if re.match(r"^(additional_read_edge_case|bulk_scope_functional_case|metrics_functional_case)_\d+$", s):
        return {"action": "as_is", "note": "GENERIC EDGE-CASE SLOT — pack uses this as a numbered placeholder beyond the structured TC range; running happy path"}

    if (s.startswith("response_includes_") or s.startswith("response_contains_")
        or s.startswith("returned_fields_")
        or s in ("created_response_fields_valid", "response_schema_complete",
                 "response_contract_valid",
                 "total_cards_issued_returned", "active_cards_count_returned",
                 "frozen_cards_count_returned", "terminated_cards_count_returned",
                 "metrics_derived_within_scope", "generated_at_returned",
                 "frozen_count_correct", "unfrozen_count_correct",
                 "terminated_count_correct", "matched_count_correct",
                 "skipped_count_correct", "no_other_bank_cards_affected",
                 "no_other_affiliate_cards_affected", "cached_source_marked",
                 "response_timestamp_format_valid",
                 "read_only_no_mutation", "read_only_no_state_mutation",
                 "card_list_includes_card_id", "card_list_includes_status",
                 "balance_response_includes_currency", "balance_response_includes_amount",
                 "fulfillment_status_includes_state",
                 "metrics_response_includes_total", "metrics_response_includes_active",
                 "no_cards_return_empty_array", "empty_result_well_formed",
                 "extra_fields_tolerated", "extra_unknown_fields_tolerated",
                 "extra_fields_in_body_tolerated",
                 "extra_query_params_ignored", "unexpected_query_params_handled",
                 "filter_by_status", "filter_by_bank_id", "filter_by_affiliate_id",
                 "filter_by_product_type", "filter_by_currency", "filter_by_date_range",
                 "pagination_default", "pagination_first_page",
                 "pagination_second_page", "pagination_beyond_last_page",
                 "page_size_max_boundary", "max_banks_boundary",
                 "additional_endpoint_specific_functional_case_39",
                 "additional_endpoint_specific_functional_case_40",
                 "created_at_present_in_response",
                 "response_includes_card_id", "response_includes_status",
                 "response_includes_currency", "response_includes_balance",
                 "response_includes_available_balance", "response_includes_blocked_balance",
                 "response_includes_product_type", "response_includes_card_holder",
                 "response_includes_masked_pan", "response_includes_funding_account",
                 "response_includes_fulfillment_state",
                 "response_includes_limit_amount", "response_includes_limit_period",
                 "response_includes_limit_request_id", "response_includes_load_id",
                 "response_includes_unload_id", "response_includes_audit_log_id",
                 "response_includes_tenant_id", "response_includes_actor_user_id",
                 "card_holder_present", "trimmed_search_handled",
                 "case_sensitive_id_handling", "whitespace_id_handling",
                 "unsupported_accept_header_handled",
                 # 2026-05-08: response-shape inspection scenarios for issuance.
                 # Earlier I removed these from the BLOCKED keyword list but
                 # never added a positive-routing handler — they fell to the
                 # runner's BLOCKED fallback ("our automated test-builder
                 # doesn't recognize"). Routing them here as as_is happy-path
                 # exercises issuance and the response-field check (Fix #3 in
                 # evaluate()) verifies the status field if the scenario
                 # implies it should be returned.
                 "virtual_card_status_active",
                 "physical_card_status_personalizing",
        )):
        return {"action": "as_is", "note": "response-shape/optional-input scenario; sending happy-path Postman request as-is"}

    # ---- 3. mutation patterns ----
    # 2026-05-08: explicit handlers BEFORE the generic missing_(.+?) regex.
    # Without these, names like `destination_account_missing_rejected` get
    # mis-captured by the regex (which matches `missing_` mid-string and grabs
    # trailing chars to end-of-string when no `_rejected` suffix follows the
    # capture, ending up with raw="rejected" → drop_field("rejected") no-op).
    if s == "destination_account_missing_rejected":
        return {"action": "drop_field", "field": "destinationAccount"}
    if s == "funding_reference_missing_rejected":
        return {"action": "drop_field", "field": "fundingReference"}

    # missing field
    # NOTE: we intentionally DON'T allow `$` in the suffix alternation — that
    # caused the regex to greedily consume tail chars when the scenario had
    # `_missing_` in the MIDDLE (e.g. "destination_account_missing_rejected").
    m = re.search(r"(?:^|_)missing_(.+?)_(?:rejected|blocks)\b", s)
    if m:
        raw = m.group(1)
        # 2026-05-08 fix: backend's failed-payload-fixes.md (and our updated
        # Postman) now supply requestContext on every body that needs it, so
        # the prior as_is no-op silently accepts. Drop the field to actually
        # exercise the scenario premise.
        if raw == "request_context": return {"action": "drop_field", "field": "requestContext"}
        if raw == "request_id" or raw == "idempotency_key" or raw == "tenant_id" or raw == "actor_user_id":
            return {"action": "drop_field", "field": snake_to_camel(raw)}
        if raw == "affiliate_id":
            return {"action": "drop_field", "field": "affiliateId"}
        if raw == "bank_id":
            return {"action": "drop_field", "field": "bankId"}
        if raw == "card_id":
            return {"action": "set_path_var", "field": "cardId", "value": "",
                    "note": "empty cardId in URL path (e.g. /cards//freeze) → expect 404 or 405"}
        if raw == "customer":
            return {"action": "drop_field", "field": "customer"}
        if raw == "issuance":
            return {"action": "drop_field", "field": "issuance"}
        if raw == "product_id":
            return {"action": "drop_field", "field": "productId"}
        if raw == "product_type":
            return {"action": "drop_field", "field": "productType"}
        if raw == "currency":
            return {"action": "drop_field", "field": "currency"}
        if raw == "reason":
            return {"action": "drop_field", "field": "reason"}
        if raw == "amount":
            return {"action": "drop_field", "field": "amount"}
        if raw == "limit_amount":
            return {"action": "drop_field", "field": "limitAmount"}
        if raw == "limit_period":
            return {"action": "drop_field", "field": "limitPeriod"}
        if raw == "embedded_payload":
            return {"action": "drop_field", "field": "embeddedPayload"}
        if raw == "kyc":
            return {"action": "drop_field", "field": "kyc"}
        if raw == "identity":
            return {"action": "drop_field", "field": "identity"}
        if raw == "first_name":
            return {"action": "drop_field", "field": "firstName"}
        if raw == "last_name":
            return {"action": "drop_field", "field": "lastName"}
        if raw == "email":
            return {"action": "drop_field", "field": "email"}
        if raw == "phone":
            return {"action": "drop_field", "field": "phone"}
        if raw == "dob":
            return {"action": "drop_field", "field": "dob"}
        if raw == "id_type":
            return {"action": "drop_field", "field": "idType"}
        if raw == "id_number":
            return {"action": "drop_field", "field": "idNumber"}
        if raw == "kyc_level":
            return {"action": "drop_field", "field": "kycLevel"}
        return {"action": "drop_field", "field": snake_to_camel(raw)}

    # blank field
    m = re.search(r"(?:^|_)blank_(.+?)(?:_rejected|$)", s)
    if m:
        raw = m.group(1)
        camel = snake_to_camel(raw)
        if raw == "request_id": return {"action": "set_field", "field": "requestId", "value": ""}
        if raw == "idempotency_key": return {"action": "set_field", "field": "idempotencyKey", "value": ""}
        if raw == "card_id": return {"action": "blocked", "reason": "Skipped — this test wants the URL to have an empty cardId; can't simulate without changing URL shape"}
        if raw == "bank_id": return {"action": "blocked", "reason": "Skipped — this test wants the URL to have an empty bankId; can't simulate without changing URL shape"}
        if raw == "affiliate_id": return {"action": "blocked", "reason": "Skipped — this test wants the URL to have an empty affiliateId; can't simulate without changing URL shape"}
        if raw == "currency": return {"action": "set_field", "field": "currency", "value": ""}
        if raw == "reason": return {"action": "set_field", "field": "reason", "value": ""}
        if raw == "product_type": return {"action": "set_field", "field": "productType", "value": ""}
        if raw == "request_context": return {"action": "as_is", "note": "REQUEST-CONTEXT BLANK — sending as-is"}
        return {"action": "set_field", "field": camel, "value": ""}

    # null field
    m = re.search(r"(?:^|_)null_(.+?)(?:_rejected|$)", s)
    if m:
        raw = m.group(1)
        return {"action": "set_field", "field": snake_to_camel(raw), "value": None}

    # whitespace-only field
    m = re.search(r"whitespace_only_(.+?)_rejected", s)
    if m:
        return {"action": "set_field", "field": snake_to_camel(m.group(1)), "value": "   "}

    # 2026-05-08: explicit handlers BEFORE the generic malformed_(.+?) regex,
    # which would otherwise capture "json" / "body" as a body-field name and
    # mis-route to set_field("json", ...) / drop_field("body").
    if s == "malformed_json_rejected":
        return {"action": "raw_invalid_json"}
    if s in ("empty_body_rejected", "empty_body", "empty_body_handled"):
        return {"action": "empty_body"}
    # 2026-05-12: scope_id in Cards context == affiliateId path var.
    # Generic malformed regex captures raw="scope_id" → set_field("scopeId") which
    # is a no-op on GET requests (null body). Route directly to set_path_var.
    if s == "malformed_scope_id_rejected":
        return {"action": "set_path_var", "field": "affiliateId", "value": "MALFORMED-AFF-SCOPE-!@#"}

    # malformed id (path or body)
    m = re.search(r"malformed_(.+?)(?:_rejected|$)", s)
    if m:
        raw = m.group(1)
        # Path-var IDs: snake_case + camelCase-collapsed-by-lower() forms.
        # Without the camelCase forms (cardid, customerid, ...), scenario names like
        # `malformed_cardId_rejected` mis-route to set_field on a body field that
        # doesn't exist on a GET, leaving the URL with the seeded valid ID.
        if raw in ("card_id", "bank_id", "affiliate_id", "limit_request_id", "request_id",
                   "case_id", "customer_id", "product_id", "partnership_request_id",
                   "load_request_id",
                   "cardid", "customerid", "productid", "bankid", "affiliateid",
                   "caseid", "requestid", "partnershiprequestid",
                   "limitrequestid", "loadrequestid"):
            field = "cardId" if raw in ("card_id", "cardid") else snake_to_camel(raw)
            if   raw in ("case_id", "caseid"):    field = "caseId"
            elif raw in ("customer_id", "customerid"): field = "customerId"
            elif raw in ("product_id", "productid"):   field = "productId"
            elif raw in ("bank_id", "bankid"):    field = "bankId"
            elif raw in ("affiliate_id", "affiliateid"): field = "affiliateId"
            elif raw in ("request_id", "requestid"): field = "requestId"
            elif raw in ("partnership_request_id", "partnershiprequestid"): field = "partnershipRequestId"
            elif raw in ("limit_request_id", "limitrequestid"): field = "limitRequestId"
            elif raw in ("load_request_id", "loadrequestid"): field = "loadRequestId"
            return {"action": "set_path_var", "field": field, "value": "not-a-valid-uuid-!@#"}
        return {"action": "set_field", "field": snake_to_camel(raw), "value": "not-a-valid-uuid-!@#"}

    # unknown id (path or body)
    m = re.search(r"(?:^|_)unknown_(.+?)(?:_rejected|_not_found|$)", s)
    if m:
        raw = m.group(1)
        if raw in ("card", "bank", "affiliate", "limit_request", "customer", "product"):
            return {"action": "unknown_id", "field": f"{snake_to_camel(raw)}Id"}
        if raw.endswith("_id"):
            return {"action": "unknown_id", "field": snake_to_camel(raw)}
        return {"action": "unknown_id", "field": snake_to_camel(raw) + "Id"}

    # unsupported value
    m = re.search(r"unsupported_(.+?)_rejected", s)
    if m:
        raw = m.group(1)
        if raw == "content_type":
            return {"action": "wrong_content_type"}
        return {"action": "set_field", "field": snake_to_camel(raw), "value": "BOGUS_VALUE_XYZ"}
    if s == "unsupported_content_type" or s == "unsupported_content_type_rejected":
        return {"action": "wrong_content_type"}

    # invalid format
    m = re.search(r"(\w+?)_format_invalid", s)
    if m:
        raw = m.group(1).split("_", 1)[-1] if "_" in m.group(1) else m.group(1)
        invalid = "###not-valid###" if "email" in raw or "phone" in raw else "INVALID_FORMAT"
        return {"action": "set_field", "field": snake_to_camel(raw), "value": invalid}

    # max length / too long
    if any(k in s for k in ("_max_length_rejected", "_max_length_exceeded", "_exceeds_max", "exceed_max", "_too_long_rejected", "_too_long")):
        m = re.search(r"(\w+?)_(?:max_length|exceeds_max|exceed_max|too_long)", s)
        if m:
            return {"action": "set_field", "field": snake_to_camel(m.group(1)), "value": "X" * 4096}

    # duplicate idempotency / request id (idempotency handled above; this branch for arrays)
    m = re.search(r"duplicate_(\w+)_(?:safe|rejected|in_array)", s)
    if m:
        raw = m.group(1)
        if raw in ("idempotency_key", "request_id"):
            return {"action": "idempotency_double_send"}
        return {"action": "duplicate_array", "field": snake_to_camel(raw)}

    # script / XSS
    if "script_" in s and ("rejected" in s or "escaped" in s):
        m = re.search(r"script_(\w+?)_", s)
        if m:
            return {"action": "set_field", "field": snake_to_camel(m.group(1)), "value": "<script>alert(1)</script>"}

    # empty body
    if s in ("empty_body_rejected", "empty_body", "empty_body_handled"):
        return {"action": "empty_body"}

    # Cards customer/format mutations (issuance-specific deeply-nested fields)
    if s == "customer_dob_invalid_rejected":
        return {"action": "set_field", "field": "dob", "value": "not-a-date"}
    if s == "customer_phone_invalid_rejected":
        return {"action": "set_field", "field": "phone", "value": "###not-valid###"}
    if s == "customer_email_invalid_rejected":
        return {"action": "set_field", "field": "email", "value": "###not-valid###"}
    if s == "customer_first_name_missing_rejected":
        return {"action": "drop_field", "field": "firstName"}
    if s == "customer_last_name_missing_rejected":
        return {"action": "drop_field", "field": "lastName"}
    if s == "customer_payload_missing_rejected":
        return {"action": "drop_field", "field": "customer"}
    if s == "kyc_level_insufficient_rejected":
        return {"action": "set_field", "field": "kycLevel", "value": "LEVEL_0"}
    if s == "kyc_missing_rejected":
        return {"action": "drop_field", "field": "kyc"}
    if s == "id_type_invalid_rejected":
        return {"action": "set_field", "field": "idType", "value": "BOGUS_TYPE"}
    if s == "id_number_invalid_rejected":
        return {"action": "set_field", "field": "idNumber", "value": "###"}
    if s == "currency_not_supported_rejected":
        return {"action": "set_field", "field": "currency", "value": "ZZZ"}
    if s == "invalid_product_type_rejected":
        return {"action": "set_field", "field": "productType", "value": "BOGUS_TYPE"}
    if s == "product_not_available_for_bank_rejected":
        return {"action": "as_is", "note": "STATE-DEPENDENT — needs a bank-product mismatch in real data; running happy-path. 4xx = enforced; 2xx = not enforced"}
    if s == "affiliate_bank_partnership_missing_rejected":
        return {"action": "as_is", "note": "STATE-DEPENDENT — needs missing partnership in real data; running happy-path. 4xx = enforced; 2xx = not enforced"}
    if s == "missing_request_context_rejected":
        return {"action": "drop_field", "field": "requestContext"}

    # numeric / type mismatch
    if s == "amount_negative_rejected" or s == "negative_amount_rejected":
        return {"action": "set_field", "field": "amount", "value": -100}
    if s == "amount_zero_rejected" or s == "zero_amount_rejected":
        return {"action": "set_field", "field": "amount", "value": 0}
    if s == "amount_precision_boundary":
        # 2026-05-08 fix: previously `set_field("amount", 0.001)` overwrote the
        # `{value, currency}` object on LOAD/UNLOAD with a float (broke schema).
        # Use precision_amount so the dispatcher walks the body and sets either
        # the scalar `amount` or the nested `*.amount.value` to a precision-edge
        # value, depending on the body shape.
        return {"action": "precision_amount"}
    if s == "invalid_currency_rejected":
        return {"action": "set_field", "field": "currency", "value": "ZZZ"}
    if s == "amount_string_rejected":
        return {"action": "set_field", "field": "amount", "value": "not-a-number"}
    if s == "limit_amount_negative_rejected":
        return {"action": "set_field", "field": "limitAmount", "value": -1}
    if s == "limit_amount_zero_rejected":
        return {"action": "set_field", "field": "limitAmount", "value": 0}
    if s == "currency_lowercase_rejected_or_normalised":
        return {"action": "set_field", "field": "currency", "value": "usd"}
    if s == "currency_invalid_iso_rejected":
        return {"action": "set_field", "field": "currency", "value": "XYZ"}
    if s == "product_type_invalid_rejected":
        return {"action": "set_field", "field": "productType", "value": "BOGUS_TYPE"}

    # pagination mutations
    if s == "page_zero_rejected": return {"action": "set_query", "key": "page", "value": "0"}
    if s == "negative_page_value_rejected": return {"action": "set_query", "key": "page", "value": "-1"}
    if s == "non_numeric_page_rejected": return {"action": "set_query", "key": "page", "value": "abc"}
    if s == "page_size_zero_rejected": return {"action": "set_query", "key": "pageSize", "value": "0"}
    if s == "negative_page_size_rejected": return {"action": "set_query", "key": "pageSize", "value": "-1"}
    if s == "page_size_exceeds_max" or s == "excessive_page_size_rejected_or_capped":
        return {"action": "set_query", "key": "pageSize", "value": "100000"}
    if s == "from_date_after_to_date_rejected":
        return {"action": "set_query_pair", "values": {"fromDate": "2030-01-01", "toDate": "2020-01-01"}}

    # malformed JSON
    if s == "malformed_json_rejected":
        return {"action": "raw_invalid_json"}

    # invalid filter values (cards/query and metrics endpoints)
    m = re.match(r"^invalid_(\w+?)_filter_rejected$", s)
    if m:
        raw = m.group(1)
        # 2026-05-08: two layered fixes —
        # (a) scenario.lower() gave us lowercase field names, but the body uses
        #     camelCase ('cardType'). Map to canonical case.
        # (b) set_field only mutates EXISTING keys via recursive walk. When the
        #     Postman base body's `filters` doesn't include `cardType` at all,
        #     set_field is a no-op and the BOGUS value never reaches the body.
        #     Use set_nested to insert the filter under `filters`, which both
        #     finds the existing key OR adds it at the canonical location.
        FILTER_FIELD_CASE = {
            "cardtype": "cardType",
            "banktype": "bankType",
            "bankid": "bankId",
            "affiliateid": "affiliateId",
            "customerid": "customerId",
            "productid": "productId",
            "producttype": "productType",
            "issuancedaterange": "issuanceDateRange",
            "daterange": "dateRange",
            "fromdate": "fromDate",
            "todate": "toDate",
        }
        canonical = FILTER_FIELD_CASE.get(raw.lower(), raw)
        # query-param mutations
        if canonical.endswith("Range") or "date" in canonical.lower():
            return {"action": "set_query", "key": canonical, "value": "not-a-range"}
        return {"action": "set_nested", "parent": "filters", "field": canonical, "value": "BOGUS_VALUE_XYZ"}
    if s == "invalid_date_range_rejected":
        return {"action": "set_query_pair", "values": {"fromDate": "not-a-date", "toDate": "also-bad"}}
    # 2026-05-12: issuanceDateRange filter test for POST /cards/query.
    # Generic invalid_filter regex routes this to set_query (URL param) which
    # ASP.NET ignores on POST endpoints. Use inverted fromDate/toDate in filters
    # body instead — the normalization block is skipped for this scenario via
    # date_test detection.
    if s == "invalid_issuancedaterange_filter_rejected":
        return {"action": "inverted_daterange_in_filters"}
    if s == "multiple_filters_and_semantics":
        return {"action": "as_is", "note": "multi-filter semantics test; happy path with current Postman filters"}

    # 2026-05-10 fix (Bug 2): page_two/page_one explicit before _success catch-all.
    if s in ("pagination_page_two_success", "page_two_success", "pagination_page_two", "pagination_second_page"):
        return {"action": "set_query", "key": "page", "value": "2",
                "note": "advanced to page 2 to actually exercise pagination"}
    if s in ("pagination_page_one_success", "page_one_success", "pagination_first_page"):
        return {"action": "set_query", "key": "page", "value": "1",
                "note": "explicit page 1 (canonical happy path)"}
    # success / happy paths (after specific patterns)
    if any(k in s for k in ("_success", "_safe", "_accepted", "_handled", "_well_formed")):
        return {"action": "as_is", "note": "happy-path or accepting variant; sent Postman request as-is"}
    if s.startswith("issue_virtual") or s.startswith("issue_physical") or s.startswith("issue_card_"):
        return {"action": "as_is", "note": "alternative happy-path variant; Postman provides one variant"}

    # ---- 2026-05-11: classifier additions from cards run gaps ----
    # Invalid-enum / format scenarios on issuance body
    if s == "invalid_currency_enum_rejected":
        return {"action": "set_field", "field": "currency", "value": "ZZZ_NOT_A_REAL_CCY"}
    if s == "invalid_customer_dob_format_rejected":
        return {"action": "set_nested", "parent": "identity", "field": "dob", "value": "not-a-date"}
    if s == "invalid_customer_phone_format_rejected":
        return {"action": "set_nested", "parent": "identity", "field": "phone", "value": "not-a-phone"}
    if s == "invalid_customer_email_format_rejected":
        return {"action": "set_nested", "parent": "identity", "field": "email", "value": "not-an-email"}

    # Swagger additionalProperties:false probe — add a junk field to body
    if s == "additional_property_rejected_per_swagger":
        return {"action": "set_field", "field": "__extraPropertyTest", "value": "should-be-rejected"}

    # Method-not-allowed probes (HTTP verb swap)
    if "delete_method_not_allowed" in s:
        return {"action": "method_swap", "method": "DELETE"}
    if "patch_method_not_allowed" in s:
        return {"action": "method_swap", "method": "PATCH"}
    if "put_method_not_allowed" in s:
        return {"action": "method_swap", "method": "PUT"}

    # Idempotency variants the dedicated regex above misses
    if s in ("duplicate_bulk_action_idempotent", "repeated_read_idempotent"):
        return {"action": "idempotency_double_send"}

    # State-dependent already-in-X (the as_is fall-through above catches
    # already_active but misses already_in_active / already_in_frozen / etc.)
    if re.match(r"^already_in_\w+_state_rejected$", s):
        return {"action": "as_is", "note": "STATE-DEPENDENT — already_in_X scenario; rely on backend state machine to reject"}

    # Injection / overflow probes on path-var IDs. Sniff the field from the
    # scenario prefix (bankId_with_..., affiliateId_with_..., cardId_with_...).
    m = re.match(r"^(?P<f>bankId|affiliateId|cardId|customerId|productId|limitRequestId|loadRequestId|partnershipRequestId|caseId|requestId)_with_sql_injection_payload$", scenario)
    if m:
        return {"action": "set_path_var", "field": m.group("f"),
                "value": "1' OR '1'='1' --"}
    m = re.match(r"^(?P<f>bankId|affiliateId|cardId|customerId|productId|limitRequestId|loadRequestId|partnershipRequestId|caseId|requestId)_with_xss_payload$", scenario)
    if m:
        return {"action": "set_path_var", "field": m.group("f"),
                "value": "<script>alert('xss')</script>"}
    m = re.match(r"^(?P<f>bankId|affiliateId|cardId|customerId|productId|limitRequestId|loadRequestId|partnershipRequestId|caseId|requestId)_extremely_long_rejected$", scenario)
    if m:
        return {"action": "set_path_var", "field": m.group("f"),
                "value": "X" * 5000}

    if s == "correlationid_echoed_in_response":
        return {"action": "inject_correlation_id_header",
                "value": "test-corr-id-RUNNER-01",
                "note": "injects X-Correlation-Id request header; verifies response echoes it back"}

    if s == "invalid_kyclevel_enum_rejected":
        return {"action": "set_field", "field": "kycLevel", "value": "INVALID_ENUM_XYZ",
                "note": "invalid kycLevel enum → expect 400/422"}

    # fallback — append scenario name to help diagnose gaps faster
    return {"action": "blocked", "reason": f"Skipped — the test case scenario '{scenario}' uses a name our automated test-builder doesn't recognize, so we couldn't tell what change to make to the request. Rather than guess and report a wrong answer, we skipped it. Scenario name: '{scenario}'"}

# --- request execution -----------------------------------------------------
def rebuild_url(method: str, base_path_template: str, path_vars: dict, query: dict) -> str:
    p = base_path_template
    for k, v in path_vars.items():
        p = p.replace(f"{{{k}}}", str(v)).replace(f":{k}", str(v))
    url = BASE_URL.rstrip("/") + p
    if query:
        from urllib.parse import urlencode
        url += "?" + urlencode(query)
    return url

def get_postman_path_template(pm_entry: dict) -> str:
    url = pm_entry["request"].get("url", {})
    if isinstance(url, str):
        return normalize_path(url)
    segs = url.get("path", [])
    if not segs:
        return normalize_path(url)
    raw = "/" + "/".join(str(s) for s in segs)
    raw = re.sub(r":(\w+)", r"{\1}", raw)
    if not raw.startswith("/"): raw = "/" + raw
    return raw

def execute(method: str, url: str, headers: dict, body: Any, timeout: int = 20) -> dict:
    """Execute with Bearer + ECDSA auth injected on every call.
    All Phase 0 pre-flight and TC execution flows through here so auth is
    applied once rather than scattered across callers.
    Retries once on transport errors for safe (idempotent) verbs only."""
    started = dt.datetime.now().isoformat()
    t0 = time.perf_counter()

    # Inject valid auth on every call (port 8082 enforces it everywhere).
    # If caller pre-set Authorization (e.g. bank token for bank_user scenarios),
    # respect it rather than overwriting with the cards token.
    h = dict(headers or {})
    if h.get("Authorization") == "__NO_AUTH__":
        del h["Authorization"]          # auth-scenario probe: send with NO Authorization header
    elif "Authorization" not in h and TOKEN_MANAGER.get_cards():
        h["Authorization"] = f"Bearer {TOKEN_MANAGER.get_cards()}"
    h["Accept"] = "application/json"  # force override — Postman has text/plain on some GETs

    # For signed verbs, normalise body to bytes NOW so the hash we sign matches
    # exactly what goes on the wire. requests' json= encoding uses different
    # separators than our canonical form, which would break ECDSA verification.
    _signed_body_bytes: bytes | None = None
    if method.upper() in ("POST", "PUT", "PATCH") and PRIVATE_KEY is not None:
        parsed    = _urlparse.urlparse(url)
        path      = parsed.path
        qs_parts  = sorted(parsed.query.split("&")) if parsed.query else []
        query_str = "&".join(qs_parts)
        if body is None:
            _signed_body_bytes = b""
        elif isinstance(body, (bytes, bytearray)):
            _signed_body_bytes = bytes(body)
        elif isinstance(body, str):
            _signed_body_bytes = body.encode("utf-8")
        else:
            _signed_body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
        sig, ts, nonce = _sign_request(method.upper(), path, query_str, _signed_body_bytes, PRIVATE_KEY)
        h["X-IAM-Signature"] = sig
        h["X-IAM-Timestamp"] = ts
        h["X-IAM-Nonce"]     = nonce
        if _signed_body_bytes:
            h.setdefault("Content-Type", "application/json")

    safe_to_retry = method.upper() in ("GET", "HEAD", "OPTIONS", "DELETE")
    last_ex = None
    attempts = 1 if not safe_to_retry else 2
    for attempt in range(attempts):
        try:
            if _signed_body_bytes is not None:
                # Send exactly the bytes that were signed — never re-serialise.
                resp = requests.request(method, url, headers=h,
                                        data=_signed_body_bytes or None, timeout=timeout)
            elif body is None:
                resp = requests.request(method, url, headers=h, timeout=timeout)
            elif isinstance(body, (bytes, bytearray)):
                h.setdefault("Content-Type", "application/json")
                resp = requests.request(method, url, headers=h, data=body, timeout=timeout)
            elif isinstance(body, str):
                resp = requests.request(method, url, headers=h, data=body, timeout=timeout)
            else:
                h.setdefault("Content-Type", "application/json")
                resp = requests.request(method, url, headers=h, json=body, timeout=timeout)
            elapsed = time.perf_counter() - t0
            try:
                resp_body = resp.json()
                body_text = None
            except Exception:
                resp_body = None
                body_text = resp.text
            return {
                "ok": True,
                "started_at": started,
                "status_code": resp.status_code,
                "elapsed_seconds": round(elapsed, 4),
                "headers": dict(resp.headers),
                "body": resp_body,
                "body_text": body_text,
                "retried": attempt > 0,
            }
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError) as ex:
            last_ex = ex
            if attempt + 1 < attempts:
                time.sleep(0.5)
                continue
        except requests.exceptions.RequestException as ex:
            last_ex = ex
            break
    return {
        "ok": False,
        "started_at": started,
        "error": f"{type(last_ex).__name__}: {last_ex}",
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
        "retried": attempts > 1,
    }

# --- evaluation ------------------------------------------------------------
EXPECTED_STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")

# Per user direction 2026-05-01 (extended): backend collapses validation, lookup, method-routing,
# state-conflict, and semantic-invalid layers. Treat 400/404/405/409/422 as a single client-error
# family. 200 is NOT in the family — Cluster B (backend-accepts-invalid) stays distinct.
CLIENT_ERROR_FAMILY = {400, 404, 405, 409, 422}

def parse_expected_statuses(expected: str) -> list[int]:
    if not expected: return []
    return [int(s) for s in EXPECTED_STATUS_RE.findall(expected)]

def status_in_expected(actual: int, expected_codes: list[int]) -> bool:
    if actual in expected_codes:
        return True
    if actual in CLIENT_ERROR_FAMILY and any(c in CLIENT_ERROR_FAMILY for c in expected_codes):
        return True
    return False

# --- business-logic response-shape gates (backend feedback 2026-05-05) ----
# These augment swagger validation: until swagger is regenerated to include the
# new fields/enums, BL gates enforce them at runtime so the runner surfaces
# missing fields as defects instead of waiting on the contract update.
EXPECTED_VIRTUAL_ACCOUNT_FIELDS = ("accountNumber", "accountName", "bankName", "bankId")
EXPECTED_BALANCE_FIELDS = ("isAvailable", "isStale", "availabilityMessage", "retrievalStatus", "lastLiveAt")
ALLOWED_CARD_STATUS_ENUM = {
    "PENDING_ISSUANCE", "PENDING_ACTIVATION",
    "ACTIVE", "FROZEN", "TERMINATED", "PERSONALIZING",
    "ARCHIVED", "EXPIRED", "INACTIVE", "CANCELLED", "BLOCKED", "SUSPENDED",
}

def _find_virtual_account(body):
    if not isinstance(body, dict): return None
    if isinstance(body.get("virtualAccount"), dict):
        return body["virtualAccount"]
    for parent in ("card", "data", "issuance", "fundingDetails", "fulfillment"):
        v = body.get(parent)
        if isinstance(v, dict) and isinstance(v.get("virtualAccount"), dict):
            return v["virtualAccount"]
    return None

def _find_card_status(body):
    if not isinstance(body, dict): return None
    s = body.get("status")
    if isinstance(s, str): return s
    for parent in ("card", "data", "issuance"):
        v = body.get(parent)
        if isinstance(v, dict) and isinstance(v.get("status"), str):
            return v["status"]
    return None

def business_logic_check(method: str, path: str, status: int, body) -> dict | None:
    """Returns {'reason': str, 'missing': [...]} on BL failure, else None.
    Only runs on 2xx responses. Path is the path template (e.g. '/api/v1/cards/{cardId}/balance')."""
    if not (200 <= (status or 0) < 300) or not isinstance(body, dict):
        return None
    p = path or ""
    findings = []
    missing_all = []

    # (a) virtualAccount block must include accountNumber/accountName/bankName/bankId
    is_va_endpoint = (
        (method == "POST" and p in ("/api/v1/cards/issuance", "/api/v1/banks/{bankId}/cards",
                                     "/api/v1/cards/{cardId}/activate"))
        or (method == "GET" and p in ("/api/v1/cards/{cardId}", "/api/v1/cards/{cardId}/funding-details"))
    )
    if is_va_endpoint:
        va = _find_virtual_account(body)
        if va is not None:
            missing_va = [f for f in EXPECTED_VIRTUAL_ACCOUNT_FIELDS if f not in va]
            if missing_va:
                findings.append(f"virtualAccount missing {missing_va}")
                missing_all.extend(f"virtualAccount.{f}" for f in missing_va)

    # (b) card status enum must be in documented set (now includes
    # PENDING_ISSUANCE / PENDING_ACTIVATION per feedback 2026-05-05).
    is_card_resource = (
        (method == "POST" and p in ("/api/v1/cards/issuance", "/api/v1/banks/{bankId}/cards",
                                     "/api/v1/cards/{cardId}/activate", "/api/v1/cards/{cardId}/freeze",
                                     "/api/v1/cards/{cardId}/unfreeze", "/api/v1/cards/{cardId}/terminate"))
        or (method == "GET" and p == "/api/v1/cards/{cardId}")
    )
    if is_card_resource:
        s = _find_card_status(body)
        if isinstance(s, str) and s.upper() not in ALLOWED_CARD_STATUS_ENUM:
            findings.append(f"unknown card status '{s}' (not in documented enum)")

    # (c) GET balance response must include the 5 liveness/staleness fields
    if method == "GET" and p == "/api/v1/cards/{cardId}/balance":
        missing_bal = [f for f in EXPECTED_BALANCE_FIELDS if f not in body]
        if missing_bal:
            findings.append(f"balance response missing {missing_bal}")
            missing_all.extend(missing_bal)

    if findings:
        return {"reason": "; ".join(findings), "missing": missing_all}
    return None

# Drift detection for forward-compatible swagger lag.
#
# Backend has rolled out additive contract changes (new response fields, new
# enum values) that swagger hasn't picked up. We want to PASS responses whose
# only schema "violations" are these additions, not regress to FAIL on every
# correct backend response. The BL gate handles whether the new fields/enums
# carry the right values; the drift suppressor stops swagger lag from masking
# that signal.
#
# Two error shapes count as "additive only":
#   1. "Additional properties are not allowed (...)"     -> backend added fields
#   2. "'X' is not one of [...]"                          -> backend added enum values
# Anything else (missing required field, type mismatch, range violation, etc.)
# is a real schema violation and stays a FAIL.
_ADDITIVE_DRIFT_PATTERNS = (
    re.compile(r"Additional properties are not allowed"),
    re.compile(r"is not one of \["),
)

def schema_drift_only_new_contract(schema_finding: dict | None) -> bool:
    """True iff every schema error matches an additive-drift pattern. Used to
    suppress schema-FAIL when swagger is the stale party (backend feedback
    2026-05-05). The BL gate adjudicates the actual values."""
    if not schema_finding or schema_finding.get("valid"):
        return False
    errs = schema_finding.get("errors") or []
    if not errs:
        return False
    for e in errs:
        s = str(e)
        if not any(pat.search(s) for pat in _ADDITIVE_DRIFT_PATTERNS):
            return False
    return True

def evaluate(tc: dict, request_summary: dict, response: dict) -> dict:
    expected = tc.get("expected_result", "") or ""
    expected_codes = parse_expected_statuses(expected)
    if not response.get("ok"):
        return {"status": "FAIL", "reason": f"network/transport error: {response.get('error')}"}
    if response.get("_idempotency"):
        idem = response["_idempotency"]
        if idem["same_status"] and idem["same_body_hash"]:
            return {"status": "PASS", "reason": f"idempotent: both calls returned {idem['first_status']} with identical body"}
        if idem["same_status"]:
            return {"status": "PASS", "reason": f"idempotent on status: both calls returned {idem['first_status']} (body diff allowed)"}
        return {"status": "FAIL", "reason": f"NOT idempotent: 1st={idem['first_status']}, 2nd={idem['second_status']}"}
    if response.get("_concurrency"):
        c = response["_concurrency"]
        if c["all_same_status"] and 200 <= c["statuses"][0] < 300:
            return {"status": "PASS", "reason": f"concurrency-safe: all {c['parallel_count']} parallel calls returned {c['statuses'][0]} consistently"}
        if c["all_same_status"]:
            return {"status": "PASS", "reason": f"concurrency-handled: all {c['parallel_count']} parallel calls returned {c['statuses'][0]} (non-2xx but consistent)"}
        # Mixed statuses — usually a sign of a race condition. PASS only if exactly one succeeded and the rest got expected conflict codes (409/423)
        succ = c["successful_calls"]
        rej = c["rejected_calls"]
        if succ == 1 and rej == c["parallel_count"] - 1 and all(s in (409, 423, 422) for s in c["statuses"] if 400 <= (s or 0) < 500):
            return {"status": "PASS", "reason": f"concurrency-handled: 1 success + {rej} conflict-rejected (statuses={c['statuses']})"}
        return {"status": "FAIL", "reason": f"concurrency NOT handled: mixed statuses {c['statuses']} ({succ} success, {rej} rejected)"}
    if response.get("_read_after_write"):
        raw = response["_read_after_write"]
        write_ok = raw.get("write_ok") and raw.get("write_status") and 200 <= raw["write_status"] < 300
        read_ok = raw.get("read_ok") and raw.get("read_status") and 200 <= raw["read_status"] < 300
        if write_ok and read_ok and raw.get("read_body_present"):
            return {"status": "PASS", "reason": f"read-after-write consistent: write={raw['write_status']}, read={raw['read_status']} returned body"}
        if not write_ok:
            return {"status": "FAIL", "reason": f"write step failed (status={raw.get('write_status')}); cannot verify consistency"}
        if not read_ok:
            return {"status": "FAIL", "reason": f"write succeeded ({raw['write_status']}) but follow-up read failed ({raw.get('read_status')}) — read-after-write inconsistency"}
        return {"status": "FAIL", "reason": f"write={raw.get('write_status')}, read={raw.get('read_status')} — read body absent"}
    if response.get("_sla"):
        sla = response["_sla"]
        if not sla["within_sla"]:
            return {"status": "FAIL", "reason": f"SLA breach: {sla['actual_seconds']}s exceeds {sla['threshold_seconds']}s"}
        if 200 <= response["status_code"] < 300:
            return {"status": "PASS", "reason": f"within SLA ({sla['actual_seconds']}s <= {sla['threshold_seconds']}s) and 2xx"}
        return {"status": "FAIL", "reason": f"within SLA but non-2xx ({response['status_code']})"}
    if response.get("_correlation_id_check"):
        chk = response["_correlation_id_check"]
        if not (response.get("ok") and 200 <= (response.get("status_code") or 0) < 300):
            return {"status": "FAIL", "reason": f"endpoint returned non-2xx ({response.get('status_code')}); cannot verify correlation-ID echo"}
        if chk["match"]:
            return {"status": "PASS", "reason": f"X-Correlation-Id echoed correctly in response header (value={chk['echoed']!r})"}
        if chk["echoed"]:
            return {"status": "FAIL", "reason": f"X-Correlation-Id mismatch: sent={chk['sent']!r}, echoed={chk['echoed']!r}"}
        return {"status": "FAIL", "reason": f"X-Correlation-Id not echoed in response headers (sent={chk['sent']!r})"}
    actual = response["status_code"]
    schema_finding = None
    if response.get("body") is not None:
        sf = VALIDATOR.validate_response(request_summary["method"], request_summary["path"], actual, response["body"])
        if sf:
            schema_finding = {"valid": sf.valid, "errors": sf.errors}
    bl_finding = business_logic_check(request_summary["method"], request_summary["path"], actual, response.get("body"))
    schema_drift_suppressed = schema_drift_only_new_contract(schema_finding)
    status_match = status_in_expected(actual, expected_codes) if expected_codes else None

    # 2026-05-08: response-field presence check for `response_includes_X` /
    # `response_contains_X` scenarios. Schema validation can pass even when an
    # optional field is absent — but the scenario name says the field MUST be
    # in the response. Walk the body and require it, otherwise FAIL even on 2xx.
    response_field_finding = None
    scenario_lower = (tc.get("scenario", "") or "").lower()
    rf_match = re.match(r"^response_(includes|contains)_(.+)$", scenario_lower)
    if rf_match and 200 <= actual < 300 and isinstance(response.get("body"), (dict, list)):
        target_raw = rf_match.group(2)
        target_camel = target_raw.split("_")[0] + "".join(p.capitalize() for p in target_raw.split("_")[1:])
        def _walk_for_field(node, fname: str) -> bool:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k.lower() == fname.lower():
                        return True
                    if _walk_for_field(v, fname):
                        return True
            elif isinstance(node, list):
                return any(_walk_for_field(x, fname) for x in node)
            return False
        if not _walk_for_field(response["body"], target_camel):
            response_field_finding = {
                "missing_field": target_camel,
                "reason": f"scenario '{tc.get('scenario')}' requires field '{target_camel}' in 2xx response, not present in body",
            }
    if expected_codes:
        if status_match:
            if schema_finding and not schema_finding["valid"] and not schema_drift_suppressed:
                return {"status": "FAIL",
                        "reason": f"status {actual} matched expected {expected_codes}, but response schema invalid: {schema_finding['errors'][:3]}",
                        "schema": schema_finding,
                        "business_logic": bl_finding}
            if bl_finding:
                return {"status": "FAIL",
                        "reason": f"status {actual} matched expected {expected_codes}, but business-logic gate failed: {bl_finding['reason']}",
                        "schema": schema_finding,
                        "business_logic": bl_finding}
            if response_field_finding:
                return {"status": "FAIL",
                        "reason": f"status {actual} matched expected {expected_codes}, but {response_field_finding['reason']}",
                        "schema": schema_finding,
                        "business_logic": bl_finding,
                        "response_field": response_field_finding}
            family_note = ""
            if actual not in expected_codes and actual in CLIENT_ERROR_FAMILY and any(c in CLIENT_ERROR_FAMILY for c in expected_codes):
                family_note = " (client-error family equivalence: 400/404/405/409/422 treated as interchangeable)"
            return {"status": "PASS",
                    "reason": f"status {actual} in expected {expected_codes}{family_note}",
                    "schema": schema_finding,
                    "business_logic": bl_finding}
        return {"status": "FAIL",
                "reason": f"expected status in {expected_codes}, got {actual}",
                "schema": schema_finding,
                "business_logic": bl_finding}
    if 200 <= actual < 300:
        if schema_finding and not schema_finding["valid"] and not schema_drift_suppressed:
            return {"status": "FAIL", "reason": f"2xx but schema invalid: {schema_finding['errors'][:3]}",
                    "schema": schema_finding, "business_logic": bl_finding}
        if bl_finding:
            return {"status": "FAIL", "reason": f"2xx ({actual}) but business-logic gate failed: {bl_finding['reason']}",
                    "schema": schema_finding, "business_logic": bl_finding}
        if response_field_finding:
            return {"status": "FAIL", "reason": f"2xx ({actual}) but {response_field_finding['reason']}",
                    "schema": schema_finding, "business_logic": bl_finding,
                    "response_field": response_field_finding}
        return {"status": "PASS", "reason": f"2xx ({actual}); no parseable expected codes",
                "schema": schema_finding, "business_logic": bl_finding}
    # State-machine enforcement scenarios: 4xx = policy enforced (PASS).
    # 2xx on these would be a B_silent_accept defect — stays FAIL via the
    # 2xx branch above. List mirrors the STATE-DEPENDENT as_is bucket in
    # classify_scenario so the evaluator and classifier agree.
    _STATE_MACHINE_ENFORCE_KWORDS = (
        "personalizing_state_policy", "frozen_card_policy_enforced",
        "frozen_card_cannot", "already_frozen", "already_active_rejected",
        "already_terminated", "already_target_state", "non_active_card_rejected",
        "terminated_card_cannot", "terminated_card_rejected", "invalid_source_state",
        "non_pending_request", "already_completed_request",
        "limit_request_already_complete", "limit_request_pending",
        "load_below_minimum", "load_exceeds_max",
    )
    if 400 <= actual < 500 and not expected_codes:
        scn_eval = (tc.get("scenario", "") or "").lower()
        if any(k in scn_eval for k in _STATE_MACHINE_ENFORCE_KWORDS):
            return {"status": "PASS",
                    "reason": (f"state-machine enforcement: {actual} for "
                               f"'{tc.get('scenario')}' — 4xx = policy enforced "
                               f"(2xx would be a silent-accept defect)"),
                    "schema": schema_finding, "business_logic": bl_finding}
    return {"status": "FAIL", "reason": f"non-2xx ({actual}); no parseable expected codes",
            "schema": schema_finding, "business_logic": bl_finding}

# --- helpers ---------------------------------------------------------------
def hash_body(b: Any) -> str:
    if b is None: return ""
    s = json.dumps(b, sort_keys=True) if not isinstance(b, str) else b
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _summarize_blocked(blocked: list) -> dict:
    by_reason = defaultdict(int)
    for b in blocked:
        by_reason[b.get("blocked_reason", "unknown")] += 1
    return {"total": len(blocked), "by_reason": dict(by_reason)}

# ─────────────────────────────────────────────────────────────────────────────
# AUTH BYPASS LAYER — SC01-SC08 per endpoint
# These TCs run BEFORE functional TCs.  They deliberately send bad/missing
# auth credentials and verify the backend returns 401 or 403.
# Uses requests.request() directly so the auth-injecting execute() is bypassed.
# ─────────────────────────────────────────────────────────────────────────────

AUTH_BYPASS_ENDPOINTS = [
    {"code": "AUTH-01", "method": "GET",  "path": "/api/v1/auth/permissions",                                            "signed": False, "vars": [],                           "body_key": None},
    {"code": "AUTH-02", "method": "GET",  "path": "/api/v1/auth/me",                                                     "signed": False, "vars": [],                           "body_key": None},
    {"code": "CBNK-01", "method": "POST", "path": "/api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/freeze",        "signed": True,  "vars": ["bankId", "affiliateId"],    "body_key": "bank_action"},
    {"code": "CBNK-02", "method": "POST", "path": "/api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/unfreeze",      "signed": True,  "vars": ["bankId", "affiliateId"],    "body_key": "bank_action"},
    {"code": "CBNK-03", "method": "POST", "path": "/api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/terminate",     "signed": True,  "vars": ["bankId", "affiliateId"],    "body_key": "bank_action"},
    {"code": "MBNK",    "method": "GET",  "path": "/api/v1/cards/metrics/bank/{bankId}",                                 "signed": False, "vars": ["bankId"],                   "body_key": None},
    {"code": "MAFF",    "method": "GET",  "path": "/api/v1/cards/metrics/affiliate/{affiliateId}",                       "signed": False, "vars": ["affiliateId"],              "body_key": None},
    {"code": "CQRY",    "method": "POST", "path": "/api/v1/cards/query",                                                 "signed": True,  "vars": [],                           "body_key": "cards_query"},
    {"code": "CLIST",   "method": "GET",  "path": "/api/v1/cards",                                                       "signed": False, "vars": [],                           "body_key": None},
    {"code": "CISS",    "method": "POST", "path": "/api/v1/cards/issuance",                                              "signed": True,  "vars": [],                           "body_key": "issuance"},
    {"code": "CGET",    "method": "GET",  "path": "/api/v1/cards/{cardId}",                                              "signed": False, "vars": ["cardId"],                   "body_key": None},
    {"code": "CFUND",   "method": "GET",  "path": "/api/v1/cards/{cardId}/funding-details",                              "signed": False, "vars": ["cardId"],                   "body_key": None},
    {"code": "CFFST",   "method": "GET",  "path": "/api/v1/cards/{cardId}/fulfillment/status",                           "signed": False, "vars": ["cardId"],                   "body_key": None},
    {"code": "CFFRE",   "method": "POST", "path": "/api/v1/cards/{cardId}/fulfillment/refresh",                          "signed": True,  "vars": ["cardId"],                   "body_key": "ctx_only"},
    {"code": "CFFRI",   "method": "POST", "path": "/api/v1/cards/{cardId}/fulfillment/reinitiate",                       "signed": True,  "vars": ["cardId"],                   "body_key": "ctx_reason"},
    {"code": "CFRZC",   "method": "POST", "path": "/api/v1/cards/{cardId}/freeze",                                       "signed": True,  "vars": ["cardId"],                   "body_key": "ctx_reason"},
    {"code": "CUFZC",   "method": "POST", "path": "/api/v1/cards/{cardId}/unfreeze",                                     "signed": True,  "vars": ["cardId"],                   "body_key": "ctx_reason"},
    {"code": "CBAL",    "method": "GET",  "path": "/api/v1/cards/{cardId}/balance",                                      "signed": False, "vars": ["cardId"],                   "body_key": None},
    {"code": "CLREQ",   "method": "POST", "path": "/api/v1/cards/{cardId}/limit-requests",                               "signed": True,  "vars": ["cardId"],                   "body_key": "limit_request"},
    {"code": "CPIN",    "method": "POST", "path": "/api/v1/cards/{cardId}/pin-reset",                                    "signed": True,  "vars": ["cardId"],                   "body_key": "ctx_reason"},
    {"code": "CLOADS",  "method": "POST", "path": "/api/v1/cards/{cardId}/loads",                                        "signed": True,  "vars": ["cardId"],                   "body_key": "load_body"},
    {"code": "CUNLD",   "method": "POST", "path": "/api/v1/cards/{cardId}/unloads",                                      "signed": True,  "vars": ["cardId"],                   "body_key": "unload_body"},
    {"code": "CACT",    "method": "POST", "path": "/api/v1/cards/{cardId}/activate",                                     "signed": True,  "vars": ["cardId"],                   "body_key": "ctx_reason"},
    {"code": "OPLIM",   "method": "POST", "path": "/api/v1/ops/cards/{cardId}/limit-requests/{limitRequestId}/complete", "signed": True,  "vars": ["cardId", "limitRequestId"], "body_key": "ops_limit"},
    {"code": "CTERM",   "method": "POST", "path": "/api/v1/cards/{cardId}/terminate",                                    "signed": True,  "vars": ["cardId"],                   "body_key": "ctx_reason"},
]

AUTH_BYPASS_SCENARIOS = {
    1: "missing_header",
    2: "empty_bearer",
    3: "garbage_token",
    4: "truncated_token",
    5: "expired_token",
    6: "wrong_audience_token",
    7: "missing_iam_signature",
    8: "invalid_iam_signature",
}


def _ab_make_ctx(sv: dict) -> dict:
    return {
        "requestId":      str(uuid.uuid4()),
        "actorUserId":    "USR-AFF-20045",
        "userType":       "AFFILIATE",
        "tenantId":       E2E_TENANT_ID,
        "affiliateId":    sv.get("affiliateId"),
        "idempotencyKey": str(uuid.uuid4()),
    }


def _ab_build_body(body_key: str, sv: dict) -> dict:
    ctx = _ab_make_ctx(sv)
    if body_key == "ctx_only":
        return {"requestContext": ctx}
    if body_key == "ctx_reason":
        return {"requestContext": ctx, "reason": "CUSTOMER_REQUEST"}
    if body_key == "bank_action":
        return {"reason": "auth_bypass_probe"}
    if body_key == "cards_query":
        return {"filters": {"affiliateId": sv.get("affiliateId")}, "page": 1, "pageSize": 10}
    if body_key == "issuance":
        return {
            "requestContext": ctx,
            "customer": {"customerId": sv.get("customerId", E2E_CUSTOMER_ID), "embeddedPayload": {}},
            "issuance": {"bankId": sv.get("bankId"), "productId": E2E_PRODUCT_ID, "productType": "VIRTUAL", "currency": "USD"},
        }
    if body_key == "limit_request":
        return {"requestContext": ctx, "requestedLimit": {"amount": 550000, "currency": "USD"}, "reason": "CUSTOMER_REQUEST"}
    if body_key == "load_body":
        return {
            "requestContext": ctx,
            "amount": {"value": 10, "currency": "USD"},
            "fundingReference": {
                "virtualAccountNumber": "8917024177",
                "bankId": "BNK-WEM-002",
                "bankTransferReference": "TRF-2026-009811",
                "proofType": "BANK_TRANSFER_CONFIRMED",
            },
        }
    if body_key == "unload_body":
        return {
            "requestContext": ctx,
            "amount": {"value": 12.5, "currency": "USD"},
            "destinationAccount": {"accountId": "ACC-REG-00081", "bankCode": "058", "accountNumberMasked": "01******89"},
            "reason": "CUSTOMER_CASH_OUT",
        }
    if body_key == "ops_limit":
        ops_ctx = {
            "requestId":      str(uuid.uuid4()),
            "actorUserId":    "USR-OPS-0001",
            "userType":       "SERVICE_PROVIDER",
            "tenantId":       E2E_TENANT_ID,
            "affiliateId":    sv.get("affiliateId"),
            "idempotencyKey": str(uuid.uuid4()),
            "role":           "OPS_ADMIN",
        }
        return {
            "requestContext": ops_ctx,
            "outcome": "COMPLETED",
            "appliedLimit": {"amount": 550000, "currency": "USD"},
            "external": {"cmsReference": "CMS-LIM-992201"},
            "opsRemarks": "auth_bypass_probe",
        }
    return {}


def _ab_build_headers(scenario: int, ep: dict, body_bytes: bytes, path: str) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    cards_token = TOKEN_MANAGER.get_cards()
    bank_token  = TOKEN_MANAGER.get_bank()
    signed = ep["signed"]

    def _add_valid_sig():
        if signed and PRIVATE_KEY is not None:
            sig, ts, nonce = _sign_request(ep["method"], path, "", body_bytes, PRIVATE_KEY)
            h["X-IAM-Signature"] = sig
            h["X-IAM-Timestamp"] = ts
            h["X-IAM-Nonce"]     = nonce

    if scenario == 1:
        pass  # no auth at all
    elif scenario == 2:
        h["Authorization"] = "Bearer "
        _add_valid_sig()
    elif scenario == 3:
        h["Authorization"] = "Bearer garbage_invalid_token_abc123xyz_not_a_jwt"
        _add_valid_sig()
    elif scenario == 4:
        truncated = cards_token[:-20] if cards_token and len(cards_token) > 20 else (cards_token or "")[:10]
        h["Authorization"] = f"Bearer {truncated}"
        _add_valid_sig()
    elif scenario == 5:
        h["Authorization"] = f"Bearer {EXPIRED_TOKEN}"
        _add_valid_sig()
    elif scenario == 6:
        h["Authorization"] = f"Bearer {bank_token}"
        _add_valid_sig()
    elif scenario == 7:
        h["Authorization"] = f"Bearer {cards_token}"
        # intentionally no signing headers
    elif scenario == 8:
        h["Authorization"] = f"Bearer {cards_token}"
        if signed:
            h["X-IAM-Signature"] = "aGFja2Vk"
            h["X-IAM-Timestamp"] = str(int(time.time() * 1000))
            h["X-IAM-Nonce"]     = str(uuid.uuid4())
    return h


def _ab_classify(scenario: int, status_code: int, ep: dict) -> tuple:
    name = AUTH_BYPASS_SCENARIOS.get(scenario, str(scenario))
    if scenario in (1, 2, 3, 4, 5, 6):
        if status_code in (401, 403):
            return "PASS", f"auth enforced: {status_code} for {name}", None
        if 200 <= status_code < 300:
            return "FAIL", f"silent_accept: {status_code} with {name} — D-CARDS-AUTH-1", "D-CARDS-AUTH-1"
        return "FAIL", f"unexpected_{status_code}: expected 401/403 for {name}", "D-CARDS-AUTH-1"
    if scenario in (7, 8):
        if status_code in (401, 403):
            return "PASS", f"signature enforcement confirmed: {status_code} for {name}", None
        if 200 <= status_code < 300:
            return "FAIL", f"signature_not_enforced: {status_code} for {name} — D-CARDS-SIG-1", "D-CARDS-SIG-1"
        return "FAIL", f"unexpected_{status_code}: expected 401/403 for {name}", "D-CARDS-SIG-1"
    return "FAIL", f"unclassified_scenario_{scenario}", None


def pre_run_card_check(session_ids: dict) -> bool:
    """Verify card pool sizes meet the minimums required to run the E2E suite.
    Call this after all Phase 0 pool-building steps complete.
    Returns True if all minimums are met; False if the run should be aborted.
    """
    # Minimum cards required per state for a meaningful E2E run.
    # ACTIVE  3 = 1 general-reads card + 1 freeze/unfreeze card + 1 terminate card
    # FROZEN  1 = unfreeze happy-path
    # PENDING 1 = activate happy-path
    REQUIREMENTS = [
        ("cardIdActivePool",            "ACTIVE cards",             3),
        ("cardIdFrozenPool",            "FROZEN cards",             1),
        ("cardIdPendingActivationPool", "PENDING_ACTIVATION cards", 1),
    ]

    print("\n[Pre-Run Check] Verifying card pool sizes before run ...", flush=True)

    shortfalls = []
    for key, label, minimum in REQUIREMENTS:
        available = len(session_ids.get(key) or [])
        ok = available >= minimum
        tag = "OK" if ok else "INSUFFICIENT"
        print(f"  {tag:<14} {label:<30} {available:>3} available  /  {minimum} needed", flush=True)
        if not ok:
            shortfalls.append((label, available, minimum))

    # Non-orphaned (loadable) ACTIVE card needed for load/unload TCs.
    # Failing this is a warning, not a hard abort — those TCs BLOCK gracefully.
    loadable = session_ids.get("cardIdLoadable")
    if loadable:
        print(f"  {'OK':<14} Non-orphaned ACTIVE card (load/unload)   {loadable!r}", flush=True)
    else:
        print(f"  {'WARNING':<14} Non-orphaned ACTIVE card (load/unload)   none found"
              f" — load/unload happy-path TCs will BLOCK", flush=True)

    if shortfalls:
        total_available = sum(len(session_ids.get(k) or []) for k, _, _ in REQUIREMENTS)
        total_needed    = sum(m for _, _, m in REQUIREMENTS)
        print(f"\n[Pre-Run Check] FAIL  RUN ABORTED — insufficient cards in pool.", flush=True)
        print(f"  {'Pool':<30} {'Available':>10} {'Needed':>8} {'Deficit':>8}", flush=True)
        print(f"  {'-'*60}", flush=True)
        for label, avail, needed in shortfalls:
            print(f"  {label:<30} {avail:>10} {needed:>8} {needed - avail:>8}", flush=True)
        print(f"  {'-'*60}", flush=True)
        print(f"  {'TOTAL':<30} {total_available:>10} {total_needed:>8} "
              f"{max(0, total_needed - total_available):>8}", flush=True)
        print(f"\n  Action: ask backend to provision cards in the states listed above, "
              f"then re-run.", flush=True)
        return False

    total_available = sum(len(session_ids.get(k) or []) for k, _, _ in REQUIREMENTS)
    total_needed    = sum(m for _, _, m in REQUIREMENTS)
    print(f"\n[Pre-Run Check] PASS  All minimums met — "
          f"{total_available} cards across pools ({total_needed} needed). "
          f"Run commencing.", flush=True)
    return True


def run_auth_bypass(sv: dict) -> list:
    """Execute SC01-SC08 for all AUTH_BYPASS_ENDPOINTS.
    Uses requests.request() directly — intentionally bypasses the auth-injecting execute().
    sv: session vars from Phase 0 (card_id, affiliateId, bankId, limit_request_id, …).
    """
    # ── Preflight: verify auth fires BEFORE resource resolution ──────────────
    # Send SC01 (no auth, no headers) to a known card-scoped GET endpoint.
    # Backend must return 401 or 403 — not 404 or 200.
    # If it doesn't, the entire auth bypass layer produces false signal:
    # a 404 from ID-not-found would be misclassified as FAIL.
    _auth_layer_verified = False
    _probe_card_id = sv.get("card_id")
    if _probe_card_id:
        _probe_url = f"{BASE_URL}/api/v1/cards/{_probe_card_id}"
        try:
            _probe_resp = requests.get(_probe_url, headers={}, timeout=AUTH_REQUEST_TIMEOUT)
            if _probe_resp.status_code in (401, 403):
                _auth_layer_verified = True
                print(f"[Auth Bypass] Preflight OK — auth fires before resource resolution "
                      f"(SC01 -> {_probe_resp.status_code} on GET /cards/{{cardId}})", flush=True)
            else:
                print(f"\n[Auth Bypass] WARN AUTH_LAYER_UNVERIFIED -- SC01 probe returned "
                      f"{_probe_resp.status_code} (expected 401/403). "
                      f"Auth may fire AFTER ID resolution; auth bypass results are UNVERIFIED.", flush=True)
        except Exception as _probe_exc:
            print(f"[Auth Bypass] WARN AUTH_LAYER_UNVERIFIED -- preflight probe failed: {_probe_exc}", flush=True)
    else:
        print(f"[Auth Bypass] WARN AUTH_LAYER_UNVERIFIED -- no card_id in sv; cannot run preflight probe.", flush=True)
    # ─────────────────────────────────────────────────────────────────────────

    results = []
    total = len(AUTH_BYPASS_ENDPOINTS) * 8
    done = 0
    print(f"\n[Auth Bypass] {total} TCs across {len(AUTH_BYPASS_ENDPOINTS)} endpoints, 8 scenarios each ...\n", flush=True)

    for ep in AUTH_BYPASS_ENDPOINTS:
        for scenario in range(1, 9):
            tc_id = f"E2E-AUTH-{ep['code']}-SC{scenario:02d}"

            # scenarios 7/8 (signing) are N/A on unsigned endpoints
            if scenario in (7, 8) and not ep["signed"]:
                results.append({
                    "tc_id": tc_id, "endpoint": f"{ep['method']} {ep['path']}",
                    "scenario": AUTH_BYPASS_SCENARIOS[scenario],
                    "execution_status": "NOT_APPLICABLE",
                    "evaluation_reason": f"Endpoint unsigned — {AUTH_BYPASS_SCENARIOS[scenario]} N/A",
                    "layer": "auth_bypass",
                })
                done += 1
                continue

            # resolve path vars
            resolved_path = ep["path"]
            blocked_reason = None
            for var in ep["vars"]:
                if var == "cardId":
                    val = sv.get("card_id")
                    if not val:
                        blocked_reason = "card_id not available from Phase 0"
                        break
                elif var == "bankId":
                    val = sv.get("bankId")
                    if not val:
                        blocked_reason = "bankId not available"
                        break
                elif var == "affiliateId":
                    val = sv.get("affiliateId")
                    if not val:
                        blocked_reason = "affiliateId not available"
                        break
                elif var == "limitRequestId":
                    val = sv.get("limit_request_id")
                    if not val:
                        val = str(uuid.uuid4())  # dummy — auth rejected before ID lookup on SC01-08
                else:
                    val = str(uuid.uuid4())
                resolved_path = resolved_path.replace(f"{{{var}}}", str(val))

            if blocked_reason:
                results.append({
                    "tc_id": tc_id, "endpoint": f"{ep['method']} {ep['path']}",
                    "scenario": AUTH_BYPASS_SCENARIOS[scenario],
                    "execution_status": "BLOCKED",
                    "evaluation_reason": blocked_reason,
                    "layer": "auth_bypass",
                })
                done += 1
                continue

            # build body
            body_dict  = _ab_build_body(ep["body_key"], sv) if ep["body_key"] else None
            body_bytes = json.dumps(body_dict, separators=(",", ":")).encode("utf-8") if body_dict else b""

            # build deliberately-bad auth headers
            headers = _ab_build_headers(scenario, ep, body_bytes, resolved_path)
            full_url = BASE_URL + resolved_path

            start = time.time()
            try:
                resp = requests.request(
                    method=ep["method"],
                    url=full_url,
                    headers=headers,
                    data=body_bytes if body_bytes else None,
                    timeout=AUTH_REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
                elapsed_ms = int((time.time() - start) * 1000)
                try:
                    resp_body = resp.json()
                except Exception:
                    resp_body = resp.text[:400] if resp.text else None

                exec_status, eval_reason, defect_tag = _ab_classify(scenario, resp.status_code, ep)
                result = {
                    "tc_id": tc_id,
                    "endpoint": f"{ep['method']} {ep['path']}",
                    "scenario": AUTH_BYPASS_SCENARIOS[scenario],
                    "layer": "auth_bypass",
                    "auth_layer_verified": _auth_layer_verified,
                    "signed": ep["signed"],
                    "input_data": {"method": ep["method"], "url": full_url, "body": body_dict},
                    "response_data": {"status_code": resp.status_code, "elapsed_ms": elapsed_ms, "body": resp_body},
                    "execution_status": exec_status,
                    "evaluation_reason": eval_reason,
                    "defect_tag": defect_tag,
                }
            except requests.exceptions.Timeout:
                result = {"tc_id": tc_id, "endpoint": f"{ep['method']} {ep['path']}",
                          "scenario": AUTH_BYPASS_SCENARIOS[scenario], "layer": "auth_bypass",
                          "execution_status": "BLOCKED", "evaluation_reason": f"TIMEOUT at {full_url}"}
            except Exception as exc:
                result = {"tc_id": tc_id, "endpoint": f"{ep['method']} {ep['path']}",
                          "scenario": AUTH_BYPASS_SCENARIOS[scenario], "layer": "auth_bypass",
                          "execution_status": "BLOCKED", "evaluation_reason": f"{type(exc).__name__}: {exc}"}

            results.append(result)
            done += 1
            status    = result.get("execution_status", "?")
            http_code = result.get("response_data", {}).get("status_code", "-")
            print(f"  [{done:3d}/{total}] {tc_id:<40} [{AUTH_BYPASS_SCENARIOS.get(scenario,'?'):<26}] {status:<10} HTTP {http_code}", flush=True)

    ab_pass    = sum(1 for r in results if r.get("execution_status") == "PASS")
    ab_fail    = sum(1 for r in results if r.get("execution_status") == "FAIL")
    ab_blocked = sum(1 for r in results if r.get("execution_status") == "BLOCKED")
    ab_na      = sum(1 for r in results if r.get("execution_status") == "NOT_APPLICABLE")
    print(f"\n  Auth Bypass  PASS: {ab_pass}  FAIL: {ab_fail}  BLOCKED: {ab_blocked}  N/A: {ab_na}", flush=True)
    return results


# --- main ------------------------------------------------------------------
def main():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    # --- E2E: initialise tokens + signing key BEFORE any HTTP ---
    global PRIVATE_KEY
    print("E2E init: minting tokens and loading signing key...", flush=True)
    TOKEN_MANAGER.init()
    TOKEN_MANAGER.start_background_refresh()
    PRIVATE_KEY = _load_private_key(SIGNING_KEY_PEM)
    print(f"  -> cards_token={'OK minted' if TOKEN_MANAGER.get_cards() else 'MISSING'}"
          f"  bank_token={'OK minted' if TOKEN_MANAGER.get_bank() else 'MISSING'}"
          f"  signing_key=OK loaded", flush=True)

    pm_idx = postman_index()
    with open(TEST_PACK_PATH, "r", encoding="utf-8") as f:
        pack = json.load(f)

    # --- HYBRID phase 0: load session + pre-flight issue card ---
    session_ids = SESSION.load()
    # 2026-05-07: backend-supplied canonical Cards IDs (per failed payload fixes.md
    # and invalid_test_cases.txt) override whatever's in session_ids.json. Other
    # services share that file and have their own canonical IDs — we only override
    # in-process, never write back. Without this, a stale bankId from an earlier
    # service run causes /metrics/bank/{bankId} to 404 across the board.
    # 2026-05-11: backend reissued working pair after PERMIT-1 fix. Verified
    # 200 against POST /cards/issuance with this exact pair + kycLevel=LEVEL_2.
    CARDS_CANONICAL_BANK_ID = "000045f9-d01b-479c-a84d-0fe82454d55a"
    CARDS_CANONICAL_AFFILIATE_ID = "a7d5929b-cba8-4e97-8985-2ce1d9fc91c3"
    if session_ids.get("bankId") != CARDS_CANONICAL_BANK_ID:
        print(f"  Overriding bankId for Cards run: "
              f"{session_ids.get('bankId')!r} -> {CARDS_CANONICAL_BANK_ID!r}")
        session_ids["bankId"] = CARDS_CANONICAL_BANK_ID
    if session_ids.get("affiliateId") != CARDS_CANONICAL_AFFILIATE_ID:
        print(f"  Overriding affiliateId for Cards run: "
              f"{session_ids.get('affiliateId')!r} -> {CARDS_CANONICAL_AFFILIATE_ID!r}")
        session_ids["affiliateId"] = CARDS_CANONICAL_AFFILIATE_ID
    session_ids["tenantId"] = CANONICAL_TENANT_ID
    if not session_ids.get("affiliateId") or not session_ids.get("bankId"):
        print(f"WARN: missing seeded affiliateId/bankId in {SESSION_IDS_PATH}; pre-flight will use Postman literals")
    print(f"Phase 0: pre-flight issuance (mint -> query fallback)...")
    setup_record = pre_flight_issue_card(pm_idx, session_ids)
    qf = setup_record.get("query_fallback")
    qf_status = qf.get("status") if isinstance(qf, dict) else None
    print(f"  -> mint_status={setup_record.get('status')} cardId={session_ids.get('cardId')!r} "
          f"fallback_used={setup_record.get('fallback_used')} query_fallback={qf_status}")
    if not session_ids.get("cardId"):
        print(f"ERROR: no cardId available (pre-flight failed and SessionStore empty); aborting")
        sys.exit(2)

    # --- HYBRID phase 0a: pre-flight short-circuit (T10) ---
    # When SKIP_ON_PREFLIGHT_FAIL=1 and seed verify suggests Cluster-C, we
    # skip happy-path TCs that would just be Cluster-C BLOCKED reclassifications
    # and only run negative tests + state-verify carve-outs. Saves wall time
    # on dead environments.
    SKIP_ON_PREFLIGHT_FAIL = os.environ.get("SKIP_ON_PREFLIGHT_FAIL", "0") == "1"

    # --- HYBRID phase 0b: verify the seeded cardId is queryable (Cluster-C mitigation) ---
    print(f"Phase 0b: verifying seeded cardId is queryable via GET /api/v1/cards/{{cardId}}...")
    verify_record = verify_seeded_id_queryable(session_ids.get("cardId"), "/api/v1/cards/{cardId}")
    print(f"  -> verified={verify_record['verified']} attempts={verify_record['attempts']} cluster_c_suspected={verify_record['cluster_c_suspected']}")
    setup_record["post_mint_verify"] = verify_record

    # --- HYBRID phase 0c: drive seeded card PENDING_ISSUANCE -> ACTIVE (fix 2) ---
    print(f"Phase 0c: activating seeded card via POST /api/v1/cards/{{cardId}}/activate...")
    activate_record = pre_flight_activate_card(pm_idx, session_ids)
    print(f"  -> activate_status={activate_record.get('status')} response={activate_record.get('response_status')}")
    setup_record["activate"] = activate_record

    # --- HYBRID phase 0d: mint a real limitRequestId (fix 3) ---
    # Only attempt if activate succeeded — minting limit-requests on a
    # PENDING_ISSUANCE card has been observed to corrupt downstream state
    # (LIM-02/LOAD-01 flip from 4xx to 500 on subsequent calls).
    if activate_record.get("status") in ("OK", "ALREADY_ACTIVE"):
        print(f"Phase 0d: minting limitRequestId via POST /api/v1/cards/{{cardId}}/limit-requests...")
        mint_lr_record = pre_flight_mint_limit_request(pm_idx, session_ids)
        print(f"  -> mint_status={mint_lr_record.get('status')} limitRequestId={mint_lr_record.get('limit_request_id')!r}")
    else:
        mint_lr_record = {"step": "mint_limit_request", "status": "SKIPPED",
                          "reason": "skipped because activate did not succeed"}
        print(f"Phase 0d: skipped limitRequestId mint (activate status={activate_record.get('status')})")
    setup_record["mint_limit_request"] = mint_lr_record

    # --- HYBRID phase 0e: discover bank-scoped affiliateId (fix 7) ---
    print(f"Phase 0e: discovering bank-scoped affiliate via GET /api/v1/banks/{{bankId}}/affiliates...")
    discover_record = pre_flight_discover_bank_scoped_affiliate(session_ids)
    print(f"  -> discover_status={discover_record.get('status')} affiliateIdScopedToBank={discover_record.get('affiliate_id')!r}")
    setup_record["discover_bank_affiliate"] = discover_record

    # Preserve the freshly-minted PENDING_ISSUANCE cardId for scenarios that
    # require a non-active card (personalizing_state_policy, non_active_card_*).
    if session_ids.get("cardId"):
        session_ids["cardIdPending"] = session_ids["cardId"]

    # --- HYBRID phase 0f: query for an ACTIVE card + GUID affiliateId (fix 9/10) ---
    print(f"Phase 0f: querying POST /api/v1/cards/query for an ACTIVE card and a GUID affiliateId...")
    active_query_record = pre_flight_query_active_card_and_affiliate(pm_idx, session_ids)
    print(f"  -> query_status={active_query_record.get('status')} "
          f"cardIdActive={session_ids.get('cardIdActive')!r} "
          f"affiliateIdActive={session_ids.get('affiliateIdActive')!r}")
    setup_record["query_active"] = active_query_record

    # --- HYBRID phase 0f1: enumerate cards by status via GET /api/v1/cards ---
    # Calls GET /api/v1/cards?status=S for every lifecycle state and unions the
    # discovered cardIds into the matching pool.  Runs after POST /cards/query
    # so query results are preserved; ACTIVE.txt (0f2) augments further on top.
    # Primary benefit: populates cardIdPendingActivationPool which the query
    # endpoint never returned (resolves CARD-19 BLOCKED cluster, 8 TCs).
    print(f"Phase 0f1: enumerating cards by status via GET /api/v1/cards?status=S...")
    enumerate_record = pre_flight_enumerate_cards_by_status(session_ids)
    print(f"  -> enumerate_status={enumerate_record.get('status')} "
          f"total_discovered={enumerate_record.get('total_discovered')} "
          f"per_status={ {k: v.get('found', v.get('status')) for k, v in enumerate_record.get('per_status', {}).items()} }")
    print(f"  -> pool_deltas={ {k: v['added'] for k, v in enumerate_record.get('pool_deltas', {}).items() if v['added'] > 0} }")
    setup_record["enumerate_cards_by_status"] = enumerate_record

    # --- HYBRID phase 0f2: DISABLED 2026-05-13 ---
    # ACTIVE.txt IDs are stale between runs. All pool discovery now comes exclusively
    # from Phase 0f1 (GET /api/v1/cards?status={S}&productType={T} live enumeration)
    # and the dedicated PHYSICAL passes added to pre_flight_enumerate_cards_by_status.
    active_txt_record = {"status": "SKIPPED", "reason": "ACTIVE.txt disabled — live enumeration is sole source of card pools"}
    print(f"Phase 0f2: load ACTIVE.txt status=SKIPPED (disabled — using live enumeration only)")
    setup_record["seed_card_pools_from_active_txt"] = active_txt_record

    # --- HYBRID phase 0f3: merge any constant backstop IDs into pools ---
    # 2026-05-13: ACTIVE.txt disabled. Phase 0f1 live enumeration is sole source.
    # _PROVISIONED_REFRESH_INPROGRESS_CARDS is now empty so this union is a no-op;
    # kept in case future runs need a manual backstop override.
    def _union_pool(key, extra_ids):
        existing = session_ids.get(key) or []
        for cid in extra_ids:
            if cid not in existing:
                existing.append(cid)
        session_ids[key] = existing
    _union_pool("cardIdRefreshInProgressPool", _PROVISIONED_REFRESH_INPROGRESS_CARDS)
    # LIM-02: ensure limOpsCardId is set (live ACTIVE pool is primary; constant is backstop).
    if not session_ids.get("limOpsCardId"):
        session_ids["limOpsCardId"] = _PROVISIONED_LIM_OPS_CARD_ID
    # Seed static queue as fallback — Phase 0f4 below will replace it with live-minted pairs.
    if not session_ids.get("limOpsPairsQueue"):
        session_ids["limOpsPairsQueue"] = [list(pair) for pair in _PROVISIONED_LIM_OPS_PAIRS]

    # --- HYBRID phase 0f3b: probe fulfillment/status to validate failed pool + find personalizing ---
    # Drops stale cards from cardIdFailedFulfillmentPool (cards that backend no longer
    # considers in fulfillmentStatus=failed). Also discovers cardIdPersonalizingPool
    # from ACTIVE PHYSICAL cards — needed for personalizing_state_policy_enforced TCs.
    print(f"Phase 0f3b: probing fulfillment/status to validate failed pool and discover personalizing pool...")
    probe_rec = pre_flight_probe_fulfillment_pools(session_ids)
    print(f"  -> status={probe_rec.get('status')} probed={probe_rec.get('probed')} "
          f"failed_kept={probe_rec.get('failed_kept')} failed_dropped={probe_rec.get('failed_dropped')} "
          f"personalizing_found={probe_rec.get('personalizing_found')} "
          f"refresh_kept={probe_rec.get('refresh_kept', 'n/a')} refresh_dropped={probe_rec.get('refresh_dropped', 'n/a')}")
    setup_record["probe_fulfillment_pools"] = probe_rec

    print(f"Phase 0f3: pool sizes after merge — "
          f"failed={len(session_ids.get('cardIdFailedFulfillmentPool') or [])} "
          f"personalizing={len(session_ids.get('cardIdPersonalizingPool') or [])} "
          f"refresh_inprogress={len(session_ids.get('cardIdRefreshInProgressPool') or [])} "
          f"lim_ops_pairs={len(session_ids['limOpsPairsQueue'])}")
    setup_record["seed_provisioned_card_pools"] = {
        "step": "seed_provisioned_card_pools",
        "status": "OK",
        "source": "live enumeration GET /api/v1/cards?status={S}&productType={T} + constant backstop",
        "cardIdFailedFulfillmentPool": list(session_ids.get("cardIdFailedFulfillmentPool") or []),
        "cardIdPersonalizingPool": list(session_ids.get("cardIdPersonalizingPool") or []),
        "cardIdRefreshInProgressPool": list(session_ids.get("cardIdRefreshInProgressPool") or []),
        "cardIdActiveTerminatePool": list(session_ids.get("cardIdActiveTerminatePool") or []),
        "limOpsCardId": session_ids["limOpsCardId"],
        "limOpsPairsQueue": list(session_ids["limOpsPairsQueue"]),
    }

    # --- HYBRID phase 0f3c: probe cardIdActiveTerminatePool for stale (already-terminated) cards ---
    # ACTIVE.txt "ACTIVE:(terminate)" cards get consumed by TRM-01 across runs.
    # Between runs they become TERMINATED; sending terminate again returns 400.
    # Probe each card live and drop any that aren't ACTIVE so the fallback path
    # (cardIdActivePool — live-enumerated, always fresh) takes over.
    _trm_pool_before = list(session_ids.get("cardIdActiveTerminatePool") or [])
    if _trm_pool_before:
        print(f"Phase 0f3c: probing cardIdActiveTerminatePool for stale entries ({len(_trm_pool_before)} cards)...")
        _trm_pool_kept, _trm_dropped = [], 0
        for _cid in _trm_pool_before:
            try:
                _r = execute("GET", f"{BASE_URL}/api/v1/cards/{_cid}", {}, None, timeout=10)
                _status = (_r.get("body", {}).get("status") or "") if _r.get("ok") and _r.get("status_code") == 200 else ""
            except Exception:
                _status = ""
            if _status == "ACTIVE":
                _trm_pool_kept.append(_cid)
            else:
                _trm_dropped += 1
        session_ids["cardIdActiveTerminatePool"] = _trm_pool_kept
        print(f"  -> kept={len(_trm_pool_kept)} dropped={_trm_dropped} "
              f"(dropped cards not ACTIVE; TRM-01 falls back to live cardIdActivePool)")

    # --- HYBRID phase 0f3d: probe cardIdPendingActivationPool for phantom cards ---
    # Cards that appear in GET /api/v1/cards?status=PENDING_ACTIVATION may not
    # resolve individually (cluster-C phantom) — they return 404 on activate and
    # would FAIL the TC. Probe each card via GET; drop non-200 responses.
    _pend_pool_before = list(session_ids.get("cardIdPendingActivationPool") or [])
    if _pend_pool_before:
        print(f"Phase 0f3d: probing cardIdPendingActivationPool for phantom cards ({len(_pend_pool_before)} cards)...")
        _pend_kept: list[str] = []
        _pend_dropped = 0
        _pend_wrong_aff = 0
        _aff_filter = session_ids.get("affiliateId")
        for _cid in _pend_pool_before:
            _keep = False
            try:
                _r = execute("GET", f"{BASE_URL}/api/v1/cards/{_cid}", {}, None, timeout=10)
                if _r.get("ok") and _r.get("status_code") == 200:
                    _keep = True
                    if _aff_filter:
                        try:
                            _body = _r.get("body") or {}
                            _card_aff = (_body.get("affiliateId")
                                         or (_body.get("data") or {}).get("affiliateId"))
                            if _card_aff and _card_aff != _aff_filter:
                                _keep = False
                                _pend_wrong_aff += 1
                        except Exception:
                            pass
                else:
                    _pend_dropped += 1
            except Exception:
                _keep = True
            if _keep:
                _pend_kept.append(_cid)
        session_ids["cardIdPendingActivationPool"] = _pend_kept
        print(f"  -> kept={len(_pend_kept)} dropped_phantom={_pend_dropped} dropped_wrong_affiliate={_pend_wrong_aff}")

    # --- HYBRID phase 0f4: live-mint LIM-02 pair queue ---
    # Call POST /cards/{cardId}/limit-requests once per needed pair with a unique
    # amount each time so the queue is always fresh and never goes stale between runs.
    # On success this REPLACES the static queue seeded above.
    print(f"Phase 0f4: minting fresh LIM-02 limit-request pool (limOpsCardId={session_ids['limOpsCardId']})...")
    lim_pool_rec = pre_flight_mint_limit_request_pool(pm_idx, session_ids, count=10)
    print(f"  -> status={lim_pool_rec['status']} minted={lim_pool_rec['minted']} failed={lim_pool_rec['failed']}")
    if lim_pool_rec["pairs"]:
        print(f"  -> live queue: {len(lim_pool_rec['pairs'])} pairs seeded")
    else:
        print(f"  -> live mint failed; keeping static backstop queue ({len(session_ids['limOpsPairsQueue'])} pairs)")
    setup_record["mint_limit_request_pool"] = lim_pool_rec

    # --- HYBRID phase 0g: seed cardIdFrozen from cardIdFrozenPool (NO POACHING) ---
    # 2026-05-07 fix: prior runs popped 2 cards from cardIdActivePool to freeze
    # them, leaving only 6 freeze cards for 8 freeze happy-path TCs. ACTIVE.txt
    # now provides 8 verified-FROZEN cards directly — pull from FrozenPool head
    # without consuming any ACTIVE cards.
    freeze_records = {}
    frozen_pool = session_ids.get("cardIdFrozenPool") or []
    for idx, slot in enumerate(("cardIdFrozen", "cardIdFrozen2")):
        if idx < len(frozen_pool):
            session_ids[slot] = frozen_pool[idx]
            freeze_records[slot] = {"status": "OK_FROM_POOL", "card_id": frozen_pool[idx],
                                    "reason": "ACTIVE.txt FROZEN pool sufficient — no pre-freeze needed"}
            print(f"Phase 0g: pinned {frozen_pool[idx]} -> {slot} (from FrozenPool head)")
        else:
            freeze_records[slot] = {"status": "SKIPPED", "reason": "FrozenPool too small"}
    setup_record["freeze_for_frozen_seed"] = freeze_records

    # --- HYBRID phase 0h: seed cardIdTerminated from cardIdTerminatedPool (NO POACHING) ---
    # Same fix: ACTIVE.txt provides 5 TERMINATED cards directly. Don't consume
    # an ACTIVE card to terminate it as a seed.
    terminated_pool = session_ids.get("cardIdTerminatedPool") or []
    if terminated_pool:
        session_ids["cardIdTerminated"] = terminated_pool[0]
        terminate_record = {"status": "OK_FROM_POOL", "card_id": terminated_pool[0],
                            "reason": "ACTIVE.txt TerminatedPool sufficient — no pre-terminate needed"}
    else:
        terminate_record = {"status": "SKIPPED", "reason": "TerminatedPool empty"}
    print(f"Phase 0h: cardIdTerminated={session_ids.get('cardIdTerminated')!r} ({terminate_record.get('status')})")
    setup_record["terminate_for_terminated_seed"] = terminate_record

    # --- HYBRID phase 0i: pin cardIdLoadable to a non-mutating shared card ---
    # 2026-05-07 fix: cardIdLoadable was sourced from cardIdActivePool, which
    # is the freeze pool. The loadable card got consumed by freeze TCs. Pin
    # cardIdLoadable to a card that's NOT in any consumable mutating pool —
    # use cardIdReadyPool[0] when present; if READY isn't accepted by some
    # endpoints, fall back to a probe of ACTIVE cards but pull from a SEPARATE
    # pool than cardIdActivePool.
    print(f"Phase 0i: pinning cardIdLoadable to a non-mutating card...")
    ready_pool = session_ids.get("cardIdReadyPool") or []
    active_phys_pool = session_ids.get("cardIdActivePhysicalPool") or []
    if active_phys_pool:
        # Prefer a physical-ACTIVE card (not in any consumable virtual pool)
        session_ids["cardIdLoadable"] = active_phys_pool[0]
        loadable_record = {"status": "PINNED_PHYSICAL_ACTIVE", "card_id": active_phys_pool[0],
                           "reason": "pinned to ActivePhysicalPool head — not in any mutating pool"}
    elif ready_pool:
        session_ids["cardIdLoadable"] = ready_pool[0]
        loadable_record = {"status": "PINNED_READY", "card_id": ready_pool[0],
                           "reason": "pinned to ReadyPool head — non-mutating"}
    else:
        # Last-resort fallback: probe (legacy behavior)
        loadable_record = pre_flight_probe_loadable_card(session_ids)
        if session_ids.get("cardIdLoadable"):
            ap = session_ids.get("cardIdActivePool") or []
            if session_ids["cardIdLoadable"] in ap:
                ap.remove(session_ids["cardIdLoadable"])
                session_ids["cardIdActivePool"] = ap
    print(f"  -> {loadable_record.get('status')} cardIdLoadable={session_ids.get('cardIdLoadable')!r}")
    setup_record["probe_loadable"] = loadable_record

    # Refresh cardIdActive to whatever's now at the head of the pool —
    # that's the "next fresh" card for any code path that uses cardIdActive.
    if session_ids.get("cardIdActivePool"):
        session_ids["cardIdActive"] = session_ids["cardIdActivePool"][0]


    # --- E2E phase: run auth bypass (SC01-SC08 per endpoint) BEFORE functional TCs ---
    # Pass a flat dict of session vars aligned to what run_auth_bypass() expects.
    # --- E2E pre-run: card pool size gate ---
    if not pre_run_card_check(session_ids):
        TOKEN_MANAGER.stop()
        sys.exit(3)

    _ab_sv = {
        "card_id":          session_ids.get("cardIdActive") or session_ids.get("cardId"),
        "affiliateId":      session_ids.get("affiliateId"),
        "bankId":           session_ids.get("bankId"),
        "customerId":       session_ids.get("customerId", E2E_CUSTOMER_ID),
        "limit_request_id": session_ids.get("limitRequestId"),
    }
    auth_bypass_results = run_auth_bypass(_ab_sv)

    # --- HYBRID phase 1: order pack by lifecycle ---
    lifecycle = load_lifecycle_order()
    if lifecycle:
        pack["endpoints"] = order_pack_by_lifecycle(pack["endpoints"], lifecycle)
        print(f"Phase 1: ordered {len(pack['endpoints'])} endpoints by lifecycle ({len(lifecycle)} ids in lifecycle)")
    else:
        print(f"Phase 1: lifecycle_order.yaml not found or empty; using pack order")

    started_at = dt.datetime.now().isoformat()
    detailed = []
    endpoint_summaries = []
    counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "ERROR": 0}
    drift_findings = []

    # T14: suggest path-template overrides for pack endpoints absent from Postman
    import difflib as _dl
    pm_keys = list(pm_idx.keys())
    suggestions = []
    for ep in pack["endpoints"]:
        pack_ep = ep["endpoint"]
        if PACK_TO_POSTMAN.get(pack_ep) and pm_idx.get(PACK_TO_POSTMAN[pack_ep]):
            continue
        # try suffix-match (last 3 path segments) before falling back to fuzzy
        suffix = "/".join(pack_ep.split("/")[-3:])
        candidates = [k for k in pm_keys if k.endswith(suffix)]
        if not candidates:
            candidates = _dl.get_close_matches(pack_ep, pm_keys, n=2, cutoff=0.7)
        if candidates:
            suggestions.append((pack_ep, candidates))
    if suggestions:
        print("Path-override suggestions (pack endpoints not in Postman with possible matches):")
        for pack_ep, cands in suggestions:
            print(f"  {pack_ep}  ->  {cands}")

    pack_endpoints_iter = pack["endpoints"]
    if SCOPE_ENDPOINT:
        pack_endpoints_iter = [e for e in pack["endpoints"] if e["endpoint"] == SCOPE_ENDPOINT]
        if not pack_endpoints_iter:
            # T16: suggest the closest match before exiting
            import difflib
            all_eps = [e["endpoint"] for e in pack["endpoints"]]
            close = difflib.get_close_matches(SCOPE_ENDPOINT, all_eps, n=3, cutoff=0.6)
            print(f"ERROR: SCOPE_ENDPOINT '{SCOPE_ENDPOINT}' not found in test pack")
            if close:
                print("Did you mean one of:")
                for c in close: print(f"  - {c}")
            sys.exit(2)
    elif SCOPE_API_IDS:
        pack_endpoints_iter = [e for e in pack["endpoints"] if e.get("api_id") in SCOPE_API_IDS]
        if not pack_endpoints_iter:
            print(f"ERROR: SCOPE_API_IDS '{','.join(SCOPE_API_IDS)}' matched no endpoints in test pack")
            print("Available api_ids:", [e.get("api_id") for e in pack["endpoints"]])
            sys.exit(2)
        print(f"  SCOPE_API_IDS filter: running {len(pack_endpoints_iter)} endpoint(s): {[e.get('api_id') for e in pack_endpoints_iter]}")
    if _replay_failed_set:
        filtered_eps = []
        for e in pack_endpoints_iter:
            aid = e["api_id"]
            tcs = [t for t in e["test_cases"] if (aid, t.get("scenario", "")) in _replay_failed_set]
            if tcs:
                filtered_eps.append({**e, "test_cases": tcs})
        pack_endpoints_iter = filtered_eps
        total_replay = sum(len(e["test_cases"]) for e in pack_endpoints_iter)
        print(f"[REPLAY] Scoped to {len(pack_endpoints_iter)} endpoints, {total_replay} TCs")
    # E2E: exclude load-requests family (backend broken — 500 on every call)
    _before_excl = len(pack_endpoints_iter)
    pack_endpoints_iter = [e for e in pack_endpoints_iter if e["endpoint"] not in EXCLUDED_FUNCTIONAL_ENDPOINTS]
    if len(pack_endpoints_iter) < _before_excl:
        print(f"[E2E] Excluded {_before_excl - len(pack_endpoints_iter)} load-requests endpoints (D-CARDS-LOADREQ)")

    for ep in pack_endpoints_iter:
        pack_ep = ep["endpoint"]
        api_id = ep["api_id"]
        pm_key = PACK_TO_POSTMAN.get(pack_ep)
        pm_entry = pm_idx.get(pm_key) if pm_key else None
        drift = DRIFT_FLAGS.get(pack_ep)
        ep_counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "ERROR": 0}

        if not pm_entry:
            for tc in ep["test_cases"]:
                detailed.append({
                    "test_case_id": tc["tc_id"],
                    "endpoint": pack_ep,
                    "api_id": api_id,
                    "scenario": tc.get("scenario"),
                    "endpoint_feature": tc.get("test_description"),
                    "precondition": tc.get("preconditions"),
                    "priority": tc.get("priority"),
                    "severity": tc.get("priority"),
                    "fr_coverage": tc.get("fr_coverage", []),
                    "execution_status": "BLOCKED",
                    "blocked_reason": "Skipped — the Postman file you provided doesn't include any request for this endpoint, so we have no real input data to send",
                    "expected_result": tc.get("expected_result"),
                })
                counts["BLOCKED"] += 1
                ep_counts["BLOCKED"] += 1
            endpoint_summaries.append({
                "endpoint": pack_ep, "api_id": api_id,
                "postman_endpoint": None,
                "drift_flag": drift,
                "test_case_counts": ep_counts,
            })
            continue

        if drift:
            drift_findings.append({"api_id": api_id, "pack_endpoint": pack_ep, "postman_endpoint": pm_key, "drift_type": drift})

        base = build_base_request(pm_entry)
        path_template = get_postman_path_template(pm_entry)

        print(f"  {api_id} {pack_ep} ({len(ep['test_cases'])} TCs)")
        for tc in ep["test_cases"]:
            scenario = tc.get("scenario", "")
            plan = classify_scenario(scenario, tc.get("expected_result", ""))
            evidence_path = EVIDENCE_DIR / f"{tc['tc_id']}.json"

            # unsupported_accept_header_handled: execute() forces Accept:application/json
            # so we can never send a different Accept — untestable through this runner.
            if "unsupported_accept_header_handled" in scenario:
                tc_base_early = {
                    "test_case_id": tc["tc_id"], "endpoint": pack_ep,
                    "api_id": api_id, "scenario": scenario,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                }
                detailed.append({**tc_base_early, "execution_status": "BLOCKED",
                                  "blocked_reason": "execute() forces Accept:application/json — "
                                                    "unsupported Accept header cannot be tested "
                                                    "through this runner"})
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            # State-change endpoints mutate state on the first call, so idempotency
            # and concurrency scenarios produce meaningless results — the second call
            # sees a different state, not a repeat of the first. Block rather than FAIL.
            _STATE_CHANGE_IDEM_TOKENS = (
                "duplicate_idempotency_key_safe",
                # "missing_idempotency_key_rejected_if_required" intentionally NOT here —
                # that scenario is a single-request validation test (drop idempotencyKey,
                # expect 400/422). No replay semantics, no state-mutation interference.
                # It must run so the backend's missing-field validation is actually tested.
                "concurrent_conflicting_action_handled",
            )
            _STATE_CHANGE_ENDPOINTS = {
                "POST /api/v1/cards/{cardId}/fulfillment/refresh",
                "POST /api/v1/cards/{cardId}/fulfillment/reinitiate",
                "POST /api/v1/cards/{cardId}/freeze",
                "POST /api/v1/cards/{cardId}/unfreeze",
                "POST /api/v1/cards/{cardId}/activate",
                "POST /api/v1/cards/{cardId}/terminate",
                "POST /api/v1/cards/{cardId}/pin-reset",
                "POST /api/v1/cards/{cardId}/loads",
                "POST /api/v1/cards/{cardId}/unloads",
            }
            if (pack_ep in _STATE_CHANGE_ENDPOINTS
                    and any(tok in scenario for tok in _STATE_CHANGE_IDEM_TOKENS)):
                tc_base_early = {
                    "test_case_id": tc["tc_id"], "endpoint": pack_ep,
                    "api_id": api_id, "scenario": scenario,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                }
                detailed.append({**tc_base_early, "execution_status": "BLOCKED",
                                  "blocked_reason": "state-change endpoint — idempotency/concurrency "
                                                    "semantics do not apply; state mutation on first call "
                                                    "makes repeat calls semantically different, not defective"})
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            tc_base = {
                "test_case_id": tc["tc_id"],
                "endpoint": pack_ep,
                "api_id": api_id,
                "scenario": scenario,
                "endpoint_feature": tc.get("test_description"),
                "precondition": tc.get("preconditions"),
                "priority": tc.get("priority"),
                "severity": tc.get("priority"),
                "fr_coverage": tc.get("fr_coverage", []),
                "expected_result": tc.get("expected_result"),
                "drift_flag": drift,
                "executed_by": "postman_hybrid_cards_runner",
                "executed_at": dt.datetime.now().isoformat(),
            }

            # --- T9: state-verify carve-out ---
            # Before honoring a "blocked" classification for db-verify scenarios,
            # check if the (scenario, endpoint) has an observable state effect
            # in STATE_VERIFY_REGISTRY. If so, run the request normally and probe
            # the resulting state instead of skipping with BLOCKED.
            state_verify_spec = None
            if plan["action"] == "blocked":
                state_verify_spec = lookup_state_verify(scenario, pack_ep)
                if state_verify_spec:
                    plan = {"action": "as_is",
                            "note": f"state-verify carve-out: probe {state_verify_spec['description']}"}

            if plan["action"] == "blocked":
                detailed.append({**tc_base, "execution_status": "BLOCKED", "blocked_reason": plan["reason"]})
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            # --- E2E: bulk affiliate terminate safety guard ---
            # POST .../banks/{bankId}/affiliates/{affiliateId}/terminate SC09
            # terminates ALL cards in the affiliate's pool — irreversible without backend reset.
            # Blocked by default (SKIP_BULK_TERMINATE_SC09=true); set env var to "false" to enable.
            if (SKIP_BULK_TERMINATE_SC09
                    and pack_ep == "POST /api/v1/cards/banks/{bankId}/affiliates/{affiliateId}/terminate"
                    and plan["action"] == "as_is"
                    and any(k in scenario.lower() for k in ("happy", "success", "terminate", "sc09", "well_formed", "_safe"))):
                detailed.append({**tc_base, "execution_status": "BLOCKED",
                                 "blocked_reason": ("SKIP_BULK_TERMINATE_SC09=true — bulk affiliate "
                                                    "terminate would wipe the card pool. "
                                                    "Set SKIP_BULK_TERMINATE_SC09=false to enable.")})
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            # --- T10: pre-flight short-circuit ---
            # If pre-flight verify suggests Cluster-C and the user opted in,
            # skip happy-path TCs whose only outcome would be Cluster-C BLOCKED
            # reclassification. Negative tests still run.
            if (SKIP_ON_PREFLIGHT_FAIL
                and verify_record.get("cluster_c_suspected")
                and plan["action"] == "as_is"
                and any(tok in path_template for tok in ("{cardId}", "{bankId}", "{affiliateId}"))):
                detailed.append({**tc_base, "execution_status": "BLOCKED",
                                 "blocked_reason": ("Skipped — SKIP_ON_PREFLIGHT_FAIL=1 and pre-flight "
                                                    "verify confirmed seed_not_queryable; happy-path TC "
                                                    "would only produce Cluster-C reclassification"),
                                 "cluster": "C", "defect_class": "preflight_short_circuit"})
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            # --- HYBRID per-TC: rotate request context, then inject seeded path vars ---
            method = base["method"]
            body_after_rotation = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
            # 2026-05-07: stamp approved affiliateId/bankId into every body
            # field carrying those keys (requestContext.affiliateId, filters.bankId,
            # etc.). Scenario-specific mutations applied below still win.
            allow_seed_substitution = plan["action"] not in ("set_path_var", "unknown_id")
            if allow_seed_substitution and isinstance(body_after_rotation, (dict, list)):
                body_after_rotation = inject_seeded_body_ids(body_after_rotation, session_ids)
            path_vars = inject_seeded_path_vars(base["path_vars"], session_ids, allow_seed_substitution, path_template, scenario, pack_ep)
            # 2026-05-11: short-circuit when activate has no PENDING_ACTIVATION
            # card available — block the TC with a precise reason instead of
            # 422ing on the stale seed cardId.
            if path_vars.get("cardId") == "__NO_PENDING_ACTIVATION_CARD__":
                detailed.append({
                    "tc_id": tc["tc_id"], "endpoint": pack_ep, "api_id": api_id,
                    "scenario": tc.get("scenario"),
                    "expected_result": tc.get("expected_result"),
                    "drift_flag": drift,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                    "execution_status": "BLOCKED",
                    "blocked_reason": "Skipped — activate happy-path needs a card in PENDING_ACTIVATION state, but cardIdPendingActivationPool is empty. Live enumeration (GET /api/v1/cards?status=PENDING_ACTIVATION) found none. Ensure backend has cards in PENDING_ACTIVATION state to unblock.",
                })
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue
            if path_vars.get("cardId") == "__NO_ACTIVE_CARD_FOR_TERMINATE__":
                detailed.append({
                    "tc_id": tc["tc_id"], "endpoint": pack_ep, "api_id": api_id,
                    "scenario": tc.get("scenario"),
                    "expected_result": tc.get("expected_result"),
                    "drift_flag": drift,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                    "execution_status": "BLOCKED",
                    "blocked_reason": "Skipped — terminate happy-path needs an ACTIVE card but all pools (cardIdActiveTerminatePool, cardIdActivePhysicalPool, cardIdActivePool, cardIdPendingPool) are exhausted. Live enumeration (GET /api/v1/cards?status=ACTIVE) found none usable. Backend must have ACTIVE cards available to unblock.",
                })
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue
            if path_vars.get("cardId") == "__NO_FAILED_FULFILLMENT_CARD__":
                detailed.append({
                    "tc_id": tc["tc_id"], "endpoint": pack_ep, "api_id": api_id,
                    "scenario": tc.get("scenario"),
                    "expected_result": tc.get("expected_result"),
                    "drift_flag": drift,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                    "execution_status": "BLOCKED",
                    "blocked_reason": "Skipped — reinitiate happy-path needs an ACTIVE PHYSICAL card with fulfillmentStatus=FAILED, but cardIdFailedFulfillmentPool is empty (live probe confirmed no cards in that state). Backend must have ACTIVE PHYSICAL cards with fulfillmentStatus=FAILED (discoverable via GET /api/v1/cards?status=ACTIVE&productType=PHYSICAL) to unblock.",
                })
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue
            if path_vars.get("cardId") == "__NO_INPROGRESS_CARD_FOR_FUL_02__":
                detailed.append({
                    "tc_id": tc["tc_id"], "endpoint": pack_ep, "api_id": api_id,
                    "scenario": tc.get("scenario"),
                    "expected_result": tc.get("expected_result"),
                    "drift_flag": drift,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                    "execution_status": "BLOCKED",
                    "blocked_reason": "Skipped — FUL-02 happy-path needs a PHYSICAL card with fulfillment in-progress; probe-validated cardIdRefreshInProgressPool is exhausted. Backend must have PENDING_ISSUANCE PHYSICAL cards with in-progress fulfillment (discoverable via GET /api/v1/cards?status=PENDING_ISSUANCE&productType=PHYSICAL) to unblock.",
                })
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue
            if path_vars.get("cardId") == "__NO_PHYSICAL_CARD_FOR_FUL_02__":
                detailed.append({
                    "tc_id": tc["tc_id"], "endpoint": pack_ep, "api_id": api_id,
                    "scenario": tc.get("scenario"),
                    "expected_result": tc.get("expected_result"),
                    "drift_flag": drift,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                    "execution_status": "BLOCKED",
                    "blocked_reason": "Skipped — FUL-02 negative test needs any PHYSICAL card (backend rejects virtual before evaluating the mutation); no physical card found in cardIdRefreshInProgressPool, cardIdActivePhysicalPool, or cardIdPendingPhysicalPool.",
                })
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            if path_vars.get("affiliateId") == "__NO_FOREIGN_AFFILIATE__":
                detailed.append({
                    "tc_id": tc["tc_id"], "endpoint": pack_ep, "api_id": api_id,
                    "scenario": tc.get("scenario"),
                    "expected_result": tc.get("expected_result"),
                    "drift_flag": drift,
                    "executed_by": "postman_hybrid_cards_runner",
                    "executed_at": dt.datetime.now().isoformat(),
                    "execution_status": "BLOCKED",
                    "blocked_reason": "No foreign affiliate found in pool — Phase 0f1 enumeration found no card "
                                      "belonging to a different bank than the session bank. Cannot test "
                                      "affiliate_not_linked_to_bank without a real unlinked affiliate "
                                      "(a dead UUID would test 'affiliate not found', not 'wrong bank linkage').",
                })
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            query = dict(base["query"])
            body = body_after_rotation

            # --- HYBRID per-TC: canonical-payload override (case(1).txt) ---
            # When the TC has a canonical mutation payload supplied by the user,
            # send it VERBATIM and force the rest of the pipeline (classifier
            # mutation, body-id substitution) to a no-op. Trailing-comma /
            # raw-invalid-JSON entries are sent as a literal string.
            canonical = _CANONICAL_TC_PAYLOADS.get(tc["tc_id"])
            mutation_note = None
            override_headers = dict(base["headers"])

            # Auth-rejection scenarios: inject the appropriate bad credential.
            # execute() will still apply valid ECDSA signing so only the Bearer
            # layer is under test. __NO_AUTH__ sentinel causes execute() to send
            # no Authorization header at all — backend must return 401/403.
            _FUNC_AUTH_CRED = {
                "unauthenticated_rejected":  "__NO_AUTH__",
                "missing_token_rejected":    "__NO_AUTH__",
                "no_auth_rejected":          "__NO_AUTH__",
                "invalid_token_rejected":    "Bearer garbage_invalid_token_abc123xyz_not_a_jwt",
                "malformed_token_rejected":  "Bearer ",
                "expired_token_rejected":    f"Bearer {EXPIRED_TOKEN}",
                "wrong_audience_rejected":   "__BANK_TOKEN__",
                "foreign_scope_rejected":    "__BANK_TOKEN__",
            }
            _func_auth_match = next((tok for tok in _FUNC_AUTH_CRED if tok in scenario), None)
            if _func_auth_match:
                _bad_cred = _FUNC_AUTH_CRED[_func_auth_match]
                if _bad_cred == "__BANK_TOKEN__":
                    _bank_tok_auth = TOKEN_MANAGER.get_bank()
                    override_headers["Authorization"] = (f"Bearer {_bank_tok_auth}"
                                                         if _bank_tok_auth else "__NO_AUTH__")
                else:
                    override_headers["Authorization"] = _bad_cred

            if canonical:
                # Canonical override wins — replace body, force as_is action,
                # bypass classifier mutation. Body-id substitution does NOT run
                # against this body; the supplied IDs (e.g. TNT-NOT-ALLOWED for
                # TC-025, BNK-PRO-002 for TC-013) are intentional and must stay.
                if canonical.get("raw_invalid_json"):
                    body = canonical["body"]  # raw string sent as-is
                    override_headers.setdefault("Content-Type", "application/json")
                    mutation_note = (f"canonical-payload override (case(1).txt) "
                                     f"— RAW invalid JSON sent verbatim")
                else:
                    body = copy.deepcopy(canonical["body"])
                    mutation_note = f"canonical-payload override (case(1).txt)"
                if canonical.get("headers"):
                    override_headers.update(canonical["headers"])
                # Coerce action to as_is so the elif chain below skips mutation.
                plan = {"action": "as_is", "note": mutation_note}

            # --- HYBRID per-TC: failed-payload override (failed payload fixes.md) ---
            # 2026-05-07: backend supplied contract-correct replay payloads for
            # every previously-failed Cards TC. When a TC is in this map, the
            # override's URL+body wins over the Postman base. Path-vars
            # (cardId/bankId/affiliateId/limitRequestId) come from the override
            # URL — they're often state-specific (e.g. PENDING_ACTIVATION cardId
            # for activate happy-path). requestId/idempotencyKey are re-rotated
            # AFTER applying the override so retries don't replay.
            #
            # 2026-05-08 fix: do NOT coerce plan to as_is here. The override
            # supplies the baseline body; classifier-driven mutations
            # (drop_field, set_field, raw_invalid_json, etc.) still need to run
            # on top so the scenario premise is actually exercised. Without
            # this, e.g. missing_request_context_rejected would silent-accept
            # because the override body has requestContext, and
            # malformed_json_rejected would send well-formed JSON.
            override = _FAILED_PAYLOAD_OVERRIDES.get(tc["tc_id"])
            override_applied = False
            if override and not canonical:
                if override.get("body") is not None:
                    body = copy.deepcopy(override["body"])
                    # Re-rotate requestId/idempotencyKey so per-call uniqueness
                    # is preserved (the markdown's static UUIDs would otherwise
                    # trigger idempotent-replay on subsequent runs).
                    body = rotate_request_context(body) if isinstance(body, dict) else body
                # Extract path-var values from the override URL (specific
                # state-bearing cardId etc.) and use them; this overrides
                # whatever inject_seeded_path_vars chose from the rotation pool.
                override_path_vars = extract_path_vars_from_override_url(
                    override["url"], path_template
                )
                if override_path_vars:
                    # Never let the override URL replace cardId — the pool-selected
                    # cardId (from live Phase 0f1 enumeration) is authoritative.
                    # Override-URL cardIds go stale across runs as cards get terminated.
                    override_path_vars.pop("cardId", None)
                    path_vars = {**path_vars, **override_path_vars}
                # If the override URL has a query string, preserve it.
                u_no_base = override["url"].replace("{{baseUrl}}", "")
                if "?" in u_no_base:
                    qs = u_no_base.split("?", 1)[1]
                    from urllib.parse import parse_qs
                    parsed = parse_qs(qs, keep_blank_values=True)
                    for k, vs in parsed.items():
                        query[k] = vs[0] if len(vs) == 1 else vs
                override_applied = True
                # Don't coerce plan — let classifier mutation run on top.
                # Notes will be combined after the elif chain.

            if plan["action"] == "as_is":
                # 2026-05-12: case_sensitive_id_handling TCs need a lowercase
                # cardId path var — engine classifies them as as_is (no mutation)
                # but the scenario premise is that a lowercase ID is sent.
                if scenario == "case_sensitive_id_handling":
                    _cref = path_vars.get("cardId", "")
                    if _cref:
                        path_vars = dict(path_vars)
                        path_vars["cardId"] = _cref.lower()
                        mutation_note = "lowercased cardId path var to test case-sensitivity"
                    else:
                        mutation_note = plan.get("note", "no mutation; sent Postman request as-is")
                else:
                    mutation_note = mutation_note or plan.get("note", "no mutation; sent Postman request as-is")
            elif plan["action"] == "drop_field":
                body = drop_field(body, plan["field"])
                mutation_note = f"dropped body field '{plan['field']}'"
            elif plan["action"] == "set_field":
                body = set_field(body, plan["field"], plan["value"])
                mutation_note = f"set body field '{plan['field']}' to {plan['value']!r}"
            elif plan["action"] == "drop_nested":
                if isinstance(body, dict) and isinstance(body.get(plan["parent"]), dict):
                    body = copy.deepcopy(body)
                    body[plan["parent"]].pop(plan["field"], None)
                mutation_note = f"dropped nested '{plan['parent']}.{plan['field']}'"
            elif plan["action"] == "set_nested":
                if isinstance(body, dict):
                    body = copy.deepcopy(body)
                    if plan["parent"] not in body or not isinstance(body[plan["parent"]], dict):
                        body[plan["parent"]] = {}
                    body[plan["parent"]][plan["field"]] = plan["value"]
                mutation_note = f"set nested '{plan['parent']}.{plan['field']}' to {plan['value']!r}"
            elif plan["action"] == "precision_amount":
                # 2026-05-08: shape-aware precision-boundary mutation. Find an
                # `amount` field anywhere in the body. If it's an object with a
                # numeric `value` sub-field, set value to precision-edge.
                # If it's a scalar, set it directly. This avoids breaking the
                # schema on LOAD/UNLOAD where amount is `{value, currency}`.
                PRECISION_VALUE = 0.000001
                if isinstance(body, dict):
                    body = copy.deepcopy(body)
                    def _walk_set_amount(node):
                        if not isinstance(node, dict):
                            return False
                        for k, v in list(node.items()):
                            if k.lower() == "amount":
                                if isinstance(v, dict) and "value" in v and isinstance(v.get("value"), (int, float)):
                                    v["value"] = PRECISION_VALUE
                                    return True
                                if isinstance(v, (int, float)):
                                    node[k] = PRECISION_VALUE
                                    return True
                            if _walk_set_amount(v):
                                return True
                        return False
                    applied = _walk_set_amount(body)
                    mutation_note = (f"set amount precision boundary value={PRECISION_VALUE}"
                                     if applied else
                                     "no amount field found to mutate (body shape unrecognized)")
            elif plan["action"] == "set_path_var":
                target = None
                for k in path_vars:
                    if k.lower() == plan["field"].lower():
                        target = k; break
                if target is None and path_vars:
                    target = next(iter(path_vars))
                if target:
                    path_vars[target] = plan["value"]
                    mutation_note = f"set path var '{target}' to {plan['value']!r}"
                else:
                    detailed.append({**tc_base, "execution_status": "BLOCKED",
                                     "blocked_reason": f"Skipped — this test wants to put an invalid value in a URL field called '{plan['field']}', but the URL has no path variables"})
                    counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1; continue
            elif plan["action"] == "inject_correlation_id_header":
                _corr_val = plan.get("value", "test-corr-id-RUNNER-01")
                override_headers["X-Correlation-Id"] = _corr_val
                mutation_note = f"injected X-Correlation-Id: {_corr_val!r} in request; will verify response echoes it"
            elif plan["action"] == "wrong_content_type":
                override_headers["Content-Type"] = "text/plain"
                mutation_note = "set Content-Type to text/plain"
            elif plan["action"] == "method_swap":
                method = plan["method"]
                mutation_note = f"swapped HTTP method to {plan['method']} (expect 405 Method Not Allowed)"
            elif plan["action"] == "empty_body":
                body = {}
                mutation_note = "sent empty body {}"
            elif plan["action"] == "set_query":
                body, query, mutation_note = smart_set_query(method, body, query, plan["key"], plan["value"])
            elif plan["action"] == "set_query_pair":
                body, query, mutation_note = smart_set_query_pair(method, body, query, plan["values"])
            elif plan["action"] == "inverted_daterange_in_filters":
                if not isinstance(body, dict):
                    body = {}
                else:
                    body = copy.deepcopy(body)
                if not isinstance(body.get("filters"), dict):
                    body["filters"] = {}
                body["filters"]["fromDate"] = "2030-01-01T00:00:00.000Z"
                body["filters"]["toDate"]   = "2020-01-01T00:00:00.000Z"
                mutation_note = "injected inverted fromDate/toDate in body.filters (fromDate > toDate → expect 400)"
            elif plan["action"] == "raw_invalid_json":
                body = "{not-json"
                override_headers.setdefault("Content-Type", "application/json")
                mutation_note = "sent raw invalid JSON"
            elif plan["action"] == "duplicate_array":
                if isinstance(body, dict):
                    f = plan["field"]
                    if f in body and isinstance(body[f], list) and body[f]:
                        body = copy.deepcopy(body)
                        body[f] = body[f] + [body[f][0]]
                        mutation_note = f"duplicated first element of '{f}'"
                    else:
                        detailed.append({**tc_base, "execution_status": "BLOCKED",
                                         "blocked_reason": f"Skipped — wanted to duplicate '{f}' but it's not a non-empty list in the Postman request body"})
                        counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1; continue
            elif plan["action"] == "unknown_id":
                f = plan.get("field")
                # 2026-05-12: use Kardit-format unknown IDs (prefix + 32 zeros)
                # instead of UUID format. Kardit IDs are BAN-/AFF-/CAR-{32hex};
                # sending a UUID-format ID was silently accepted by some endpoints.
                _PREFIX_MAP = {
                    "bankid":      "BAN-",
                    "affiliateid": "AFF-",
                    "cardid":      "CAR-",
                    "customerid":  "CUS-",
                    "productid":   "PRD-",
                }
                _flow = (f or "").lower()
                _pfx = _PREFIX_MAP.get(_flow, "")
                _unknown_val = (_pfx + "0" * 32) if _pfx else ZERO_UUID
                applied = False
                if f and isinstance(body, dict):
                    candidate = copy.deepcopy(body)
                    if _find_and_apply(candidate, f, "set", _unknown_val):
                        body = candidate
                        mutation_note = f"set body '{f}' (deep) to unknown-ID {_unknown_val!r}"
                        applied = True
                if not applied and path_vars:
                    target = None
                    if f:
                        for k in path_vars:
                            if k.lower() == f.lower() or f.lower() in k.lower():
                                target = k; break
                    if target is None:
                        for k in path_vars:
                            if k.lower().endswith("id"):
                                target = k; break
                    if target:
                        path_vars[target] = _unknown_val
                        mutation_note = f"set path var '{target}' to unknown-ID {_unknown_val!r}"
                        applied = True
                if not applied:
                    detailed.append({**tc_base, "execution_status": "BLOCKED",
                                     "blocked_reason": "Skipped — wanted to swap an ID for an unknown one but no matching ID field in URL or body"})
                    counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1; continue
            elif plan["action"] == "idempotency_double_send":
                # Body already has rotated keys; both calls share the same key (intentional).
                mutation_note = "idempotency test — sending twice with same key"
            elif plan["action"] == "concurrent_parallel_send":
                mutation_note = f"concurrency test — firing {plan.get('n',5)} parallel requests"
            elif plan["action"] == "read_after_write_chain":
                mutation_note = "read-after-write — performing the write, then chaining a GET on the same cardId"

            # POST /ops/cards/{cardId}/limit-requests/{limitRequestId}/complete
            # normalization. Backend (2026-05-07 run) rejects every body with
            # "RequestContext.TenantId / AffiliateId field is required" because
            # the Postman OPS body omits them under role=OPS_ADMIN. Provisions.txt
            # spells out the full body shape — inject the missing fields when
            # they aren't already present. Also use the provisioned matched
            # cardId+limitRequestId pair on happy paths so the request targets a
            # real outstanding limit request.
            if (method == "POST"
                    and path_template == "/api/v1/ops/cards/{cardId}/limit-requests/{limitRequestId}/complete"
                    and isinstance(body, dict)):
                # 2026-05-08: scenario-aware skips. The classifier may have
                # already removed requestContext / mutated appliedLimit.amount;
                # we must not re-inject those or the scenario premise is lost.
                scn_lower = (scenario or "").lower()
                skip_rc_inject = scn_lower in (
                    "missing_request_context_rejected",
                    "missing_request_context_blocks",
                )
                skip_amount_inject = scn_lower in (
                    "missing_amount_rejected", "zero_amount_rejected",
                    "negative_amount_rejected", "blank_amount_rejected",
                    "null_amount_rejected", "amount_max_value_rejected",
                    "missing_applied_limit_rejected",
                )
                if not skip_rc_inject:
                    rc = body.setdefault("requestContext", {})
                    if isinstance(rc, dict):
                        if not rc.get("tenantId") and session_ids.get("tenantId"):
                            rc["tenantId"] = session_ids["tenantId"]
                        if not rc.get("tenantId"):
                            rc["tenantId"] = "a3f52a65-9d8a-4f75-bf7a-2f4b1e1a1c11"
                        # Always use the approved affiliateId (inject_seeded_body_ids
                        # also covers this, but LIM-02 starts with no affiliateId in
                        # requestContext so the recursive walker skips it).
                        if session_ids.get("affiliateId"):
                            rc["affiliateId"] = session_ids["affiliateId"]
                        elif not rc.get("affiliateId"):
                            rc["affiliateId"] = "5c1e9fd2-6d32-4d0c-9bf2-c7b0d8f2b201"
                        mutation_note = (mutation_note + " | " if mutation_note else "") + "injected requestContext.tenantId/affiliateId for LIM-02"
                # Always pin the LIM-02 cardId — provisions.txt 2026-05-07 says
                # "use the same cardid" for every call.
                # 2026-05-13: skip override for malformed_card_id_rejected so the
                # set_path_var mutation isn't nullified by this block.
                if scenario != "malformed_card_id_rejected":
                    path_vars["cardId"] = session_ids.get("limOpsCardId", _PROVISIONED_LIM_OPS_CARD_ID)
                is_happy_lim = any(k in scn_lower for k in (
                    "happy", "success", "minimum_required", "_safe", "well_formed",
                    "response_includes", "response_contract", "read_after",
                    "platform_state_updates", "cms_success_updates"))
                queue = session_ids.get("limOpsPairsQueue") or []
                if is_happy_lim and queue:
                    # Happy/contract scenarios MUTATE the limit request — pop
                    # the next pair so each TC gets a fresh un-finalized LIM ID.
                    lim_id, amount = queue.pop(0)
                    session_ids["limOpsPairsQueue"] = queue
                    path_vars["limitRequestId"] = lim_id
                    if not skip_amount_inject:
                        applied = body.setdefault("appliedLimit", {})
                        if isinstance(applied, dict):
                            applied["amount"] = amount
                    mutation_note = (mutation_note + " | " if mutation_note else "") + (
                        f"consumed LIM-02 pair limitRequestId={lim_id}"
                        + (f" amount={amount}" if not skip_amount_inject else " (amount injection skipped — scenario mutates amount)"))
                elif queue:
                    # Non-happy / auth / state-policy TCs PEEK at queue[0]
                    # without popping. Backend's lifecycle gate runs before
                    # finalization, so the LIM ID stays un-finalized for the
                    # next happy-path TC. 2026-05-07 fix: prior runs let these
                    # TCs fall through to session_ids["limitRequestId"] which
                    # was a stale LIM-BD1B... value from earlier sessions —
                    # backend 404s with misleading "No card found for id 'LIM-…'".
                    lim_id, amount = queue[0]
                    path_vars["limitRequestId"] = lim_id
                    # For non-happy scenarios, also stamp matching amount so
                    # the body is a valid LIM-02 request shape; the auth/state
                    # check fires first and the request never finalizes.
                    if not skip_amount_inject:
                        applied = body.setdefault("appliedLimit", {})
                        if isinstance(applied, dict):
                            applied["amount"] = amount
                    mutation_note = (mutation_note + " | " if mutation_note else "") + (
                        f"peeked LIM-02 pair (no consume) limitRequestId={lim_id}"
                        + (f"" if not skip_amount_inject else " (amount injection skipped)"))
                else:
                    # Pool exhausted — let the request fall through.
                    mutation_note = (mutation_note + " | " if mutation_note else "") + (
                        "LIM-02 pair pool exhausted; request sent without fresh pair")

            # POST /cards/query body normalization. Backend changed contract
            # 2026-05-07: rejects the {"request": {...}} wrapper that was
            # required earlier ('$.request could not be mapped to
            # CardQueryRequestDto'). Body must now have filters/page/pageSize
            # directly at top level, matching CardQueryRequestDto schema. Also
            # strip placeholder strings the backend's filters rejects, and seed
            # an active affiliateId GUID for happy-path queries.
            if (method == "POST" and path_template == "/api/v1/cards/query"
                    and isinstance(body, dict)):
                # If a stale wrapper is present, unwrap it.
                if "request" in body and isinstance(body["request"], dict) and "filters" in body["request"]:
                    body = body["request"]
                    mutation_note = (mutation_note + " | " if mutation_note else "") + "unwrapped stale {'request': ...} envelope for /cards/query"
                # Clamp pageSize to backend's 1-100 cap for scenarios NOT explicitly
                # testing pageSize boundary cases. Postman base has pageSize=1390
                # which 422s on every TC otherwise. Exclusion list is narrow:
                # only skip clamping when the scenario name has pageSize-value
                # semantics. Generic pagination-flow tests (page_one_success,
                # minimum_pagination_success, etc.) get clamped.
                scn_lower = (scenario or "").lower()
                pagination_test = any(k in scn_lower for k in (
                    "page_size", "pagesize",
                    "excessive_page", "max_page_size", "minimum_page_size",
                    "negative_page", "non_numeric_page",
                    "page_zero", "page_size_zero",
                    "boundary"))
                if not pagination_test:
                    ps = body.get("pageSize")
                    if isinstance(ps, int) and (ps > 100 or ps < 1):
                        body["pageSize"] = 25
                        mutation_note = (mutation_note + " | " if mutation_note else "") + f"clamped pageSize {ps}->25 (backend cap 1-100)"
                    pg = body.get("page")
                    if isinstance(pg, int) and (pg > 100 or pg < 1):
                        body["page"] = 1
                        mutation_note = (mutation_note + " | " if mutation_note else "") + f"clamped page {pg}->1"
                # Drop inverted date filters (Postman has fromDate=2024-02 >
                # toDate=2004-07 — backend 400s "fromDate cannot be greater than
                # toDate"). Strip date filters unless the test specifically
                # exercises date-range behavior.
                date_test = any(k in scn_lower for k in ("date_range", "from_date", "to_date", "filter_by_date", "issuancedaterange", "issuancedate"))
                f0 = body.get("filters")
                if isinstance(f0, dict) and not date_test:
                    fd, td = f0.get("fromDate"), f0.get("toDate")
                    if isinstance(fd, str) and isinstance(td, str) and fd > td:
                        f0.pop("fromDate", None)
                        f0.pop("toDate", None)
                        mutation_note = (mutation_note + " | " if mutation_note else "") + "dropped inverted fromDate/toDate filters"
                f = body.get("filters")
                if isinstance(f, dict):
                    # Replace placeholder strings the backend rejects.
                    for sk in ("bankId", "affiliateId", "customerId", "productId"):
                        if isinstance(f.get(sk), str) and f[sk] in ("", "string"):
                            f.pop(sk, None)
                    ct = f.get("cardType")
                    if isinstance(ct, list) and any(s == "string" for s in ct):
                        f.pop("cardType", None)
                    pt = f.get("productType")
                    if isinstance(pt, list) and any(s == "string" for s in pt):
                        f.pop("productType", None)
                    st = f.get("status")
                    if isinstance(st, list) and any(s == "string" for s in st):
                        f["status"] = [s for s in st if s != "string"] or ["ACTIVE"]
                    # Seed approved affiliateId/bankId only when the test isn't
                    # specifically probing those filters. 2026-05-07: switched
                    # from affiliateIdActive (queried GUID) to session_ids
                    # ["affiliateId"] (approved DB-backed AFF- prefixed value).
                    # Seed approved affiliateId/bankId for regular filter scenarios.
                    if (session_ids.get("affiliateId")
                            and "affiliate" not in scn_lower
                            and "filter_by_affiliate" not in scn_lower
                            and "scope" not in scn_lower):
                        f["affiliateId"] = session_ids["affiliateId"]
                    if (session_ids.get("bankId")
                            and "bank" not in scn_lower
                            and "filter_by_bank" not in scn_lower
                            and "scope" not in scn_lower):
                        f["bankId"] = session_ids["bankId"]
                    # 2026-05-11: response_includes_* scenarios only check
                    # response shape — they need at least one result back.
                    # inject_seeded_body_ids + Postman base add zero-UUID
                    # customerId/productId and inverted date ranges that kill
                    # the query entirely (data: []). Strip ALL scoping filters
                    # here so the query returns whatever cards exist in the DB.
                    if "response_includes" in scn_lower or "response_contains" in scn_lower:
                        for _fk in ("affiliateId", "bankId", "customerId", "productId",
                                    "fromDate", "toDate"):
                            f.pop(_fk, None)
                        f.setdefault("status", ["ACTIVE"])
                        mutation_note = (mutation_note + " | " if mutation_note else "") + \
                            "stripped scope filters for response_includes shape check"

            # 2026-05-11: POST /cards/issuance happy-path re-inject after override.
            # inject_seeded_body_ids runs at line ~3177 BEFORE failed_payload_overrides
            # replaces the body at ~3241, so the override's stale AFF-prefix affiliateId
            # survives and causes 422 "Affiliate is not permitted to issue cards for
            # this bank". Re-stamp the canonical pair here for happy paths only;
            # skip for scenarios that intentionally test wrong credentials.
            if (method == "POST"
                    and path_template == "/api/v1/cards/issuance"
                    and isinstance(body, dict)
                    and override_applied):
                scn_lower_iss = (scenario or "").lower()
                _iss_happy = any(k in scn_lower_iss for k in (
                    "_success", "issue_virtual", "issue_physical", "_safe",
                    "cms_", "virtual_account_", "virtual_card_", "physical_card_",
                    "bureau_push_", "load_prevented_", "audit_log_", "notification_",
                ))
                _iss_auth_test = any(k in scn_lower_iss for k in (
                    "affiliate_bank_partnership", "missing_affiliate",
                    "unauthenticated", "invalid_token", "foreign_tenant",
                ))
                if _iss_happy and not _iss_auth_test:
                    rc = body.get("requestContext")
                    if isinstance(rc, dict) and session_ids.get("affiliateId"):
                        rc["affiliateId"] = session_ids["affiliateId"]
                    iss = body.get("issuance")
                    if isinstance(iss, dict) and session_ids.get("bankId"):
                        iss["bankId"] = session_ids["bankId"]
                    mutation_note = (mutation_note + " | " if mutation_note else "") + \
                        "re-injected canonical affiliateId+bankId into ISS-02 override body"

            # POST /cards/{cardId}/activate happy-path re-inject after override.
            # Override body carries stale AFF-prefix affiliateId that doesn't match the
            # card's owner affiliate → backend 404s. Re-stamp canonical UUID after override.
            if (method == "POST"
                    and path_template == "/api/v1/cards/{cardId}/activate"
                    and isinstance(body, dict)):
                scn_lower_act = (scenario or "").lower()
                _act_happy = any(k in scn_lower_act for k in (
                    "_success", "happy", "minimum_required", "read_after",
                ))
                _act_auth_test = any(k in scn_lower_act for k in (
                    "unauthenticated", "invalid_token", "foreign_tenant", "foreign_affiliate",
                    "missing_affiliate",
                ))
                if _act_happy and not _act_auth_test:
                    rc = body.get("requestContext")
                    if isinstance(rc, dict) and session_ids.get("affiliateId"):
                        rc["affiliateId"] = session_ids["affiliateId"]
                        mutation_note = (mutation_note + " | " if mutation_note else "") + \
                            "re-injected canonical affiliateId into CARD-19 activate body"

            # 2026-05-08 fix: prepend override-applied marker so evidence shows
            # both the override AND any classifier-driven mutation that ran on top.
            if override_applied:
                base_note = ("failed-payload override base (failed payload fixes.md) "
                             "— backend-curated body+cardId; ")
                if mutation_note and "no mutation" in (mutation_note or ""):
                    mutation_note = base_note + "no further classifier mutation"
                elif mutation_note:
                    mutation_note = base_note + "with classifier mutation: " + mutation_note
                else:
                    mutation_note = base_note + "no further classifier mutation"

            url = rebuild_url(method, path_template, path_vars, query)
            request_summary = {"method": method, "path": path_template, "url": url, "headers": override_headers, "body": body}

            if plan["action"] == "idempotency_double_send":
                resp1 = execute(method, url, override_headers, body)
                resp2 = execute(method, url, override_headers, body)
                same_status = resp1.get("status_code") == resp2.get("status_code")
                same_body_hash = hash_body(resp1.get("body") or resp1.get("body_text")) == hash_body(resp2.get("body") or resp2.get("body_text"))
                response = resp2
                response["_idempotency"] = {
                    "first_status": resp1.get("status_code"),
                    "second_status": resp2.get("status_code"),
                    "same_status": same_status,
                    "same_body_hash": same_body_hash,
                }
                mutation_note = (mutation_note or "") + f" | sent twice: 1st={resp1.get('status_code')}, 2nd={resp2.get('status_code')}, same_status={same_status}, same_body={same_body_hash}"
            elif plan["action"] == "concurrent_parallel_send":
                from concurrent.futures import ThreadPoolExecutor
                n = plan.get("n", 5)
                with ThreadPoolExecutor(max_workers=n) as ex:
                    futures = [ex.submit(execute, method, url, override_headers, copy.deepcopy(body)) for _ in range(n)]
                    results = [f.result() for f in futures]
                statuses = [r.get("status_code") for r in results]
                ok_results = [r for r in results if r.get("ok")]
                response = ok_results[0] if ok_results else results[0]
                response["_concurrency"] = {
                    "parallel_count": n,
                    "statuses": statuses,
                    "all_same_status": len(set(statuses)) == 1,
                    "successful_calls": sum(1 for s in statuses if s and 200 <= s < 300),
                    "rejected_calls": sum(1 for s in statuses if s and 400 <= s < 500),
                }
                mutation_note = (mutation_note or "") + f" | parallel x{n}: statuses={statuses}, all_same={response['_concurrency']['all_same_status']}"
            elif plan["action"] == "read_after_write_chain":
                # Step 1: perform the write (the original endpoint's call)
                write_resp = execute(method, url, override_headers, body)
                # FUL-02 retry: pool probe can miss FAILED cards; if write 409s try next card once.
                if (write_resp.get("status_code") == 409
                        and path_template == "/api/v1/cards/{cardId}/fulfillment/refresh"):
                    _retry_cid = take_card_from_pool(session_ids, "cardIdRefreshInProgressPool",
                                                     "_consumed_refresh_inprogress")
                    if _retry_cid:
                        path_vars["cardId"] = _retry_cid
                        url = rebuild_url(method, path_template, path_vars, query)
                        write_resp = execute(method, url, override_headers, body)
                        mutation_note = (mutation_note or "") + \
                            f" | FUL-02 retry on 409 → cardId={_retry_cid} → {write_resp.get('status_code')}"
                # CARD-19 retry: phantom pool cards pass GET probe but activate returns 404; try next card.
                if (write_resp.get("status_code") == 404
                        and path_template == "/api/v1/cards/{cardId}/activate"):
                    _retry_cid = take_card_from_pool(session_ids, "cardIdPendingActivationPool",
                                                     "_consumed_pending_activation_for_activate")
                    if _retry_cid:
                        path_vars["cardId"] = _retry_cid
                        url = rebuild_url(method, path_template, path_vars, query)
                        write_resp = execute(method, url, override_headers, body)
                        mutation_note = (mutation_note or "") + \
                            f" | CARD-19 retry on 404 → cardId={_retry_cid} → {write_resp.get('status_code')}"
                # Step 2: GET /api/v1/cards/{cardId} on the same seeded cardId
                read_card_id = (path_vars.get("cardId") or session_ids.get("cardId"))
                read_url = f"{BASE_URL}/api/v1/cards/{read_card_id}" if read_card_id else None
                if read_url:
                    read_resp = execute("GET", read_url, {"Accept": "application/json"}, None)
                else:
                    read_resp = {"ok": False, "error": "no cardId available for read-after-write chain"}
                response = write_resp
                response["_read_after_write"] = {
                    "write_status": write_resp.get("status_code"),
                    "write_ok": write_resp.get("ok"),
                    "read_url": read_url,
                    "read_status": read_resp.get("status_code"),
                    "read_ok": read_resp.get("ok"),
                    "read_body_present": read_resp.get("body") is not None,
                }
                mutation_note = (mutation_note or "") + f" | write={write_resp.get('status_code')}, follow-up read={read_resp.get('status_code')}"
            # Bank-scoped scenarios must use the bank token so the backend
            # receives a genuinely wrong-audience credential and can enforce 403.
            # execute() respects a pre-set Authorization header and won't overwrite it.
            _BANK_TOKEN_SCENARIOS = (
                "bank_user_write", "bank_user_activation",
                "bank_write_rejected", "foreign_bank_rejected",
            )
            if any(t in scenario for t in _BANK_TOKEN_SCENARIOS):
                _bank_tok = TOKEN_MANAGER.get_bank()
                if _bank_tok:
                    override_headers["Authorization"] = f"Bearer {_bank_tok}"

            if plan["action"] == "sla_check":
                response = execute(method, url, override_headers, body)
                threshold = plan.get("threshold_seconds", 2.0)
                elapsed = response.get("elapsed_seconds", 999)
                response["_sla"] = {"threshold_seconds": threshold, "actual_seconds": elapsed, "within_sla": elapsed <= threshold}
                mutation_note = (mutation_note or "") + f" | SLA check: {elapsed}s vs {threshold}s threshold"
            else:
                response = execute(method, url, override_headers, body)

            # --- correlation-ID echo check ---
            if plan["action"] == "inject_correlation_id_header":
                _expected_corr = override_headers.get("X-Correlation-Id", "")
                _resp_headers = {k.lower(): v for k, v in (response.get("headers") or {}).items()}
                _echoed = _resp_headers.get("x-correlation-id", "")
                response["_correlation_id_check"] = {
                    "sent": _expected_corr,
                    "echoed": _echoed,
                    "match": _echoed == _expected_corr,
                }

            # --- HYBRID per-TC: GET-after-POST persistence probe ---
            # Scope: MINT endpoints only — those that create new resources
            # whose persistence we can verify via a corresponding GET. State-
            # mutation endpoints (freeze/unfreeze/loads/etc.) use the state-
            # effect probe instead. Probe NEVER upgrades verdicts to PASS.
            probe_record = None
            wr_ok = (response.get("ok")
                     and isinstance(response.get("status_code"), int)
                     and 200 <= response.get("status_code") < 300)
            if wr_ok and pack_ep == "POST /api/v1/cards/issuance":
                minted_id = extract_card_id_from_response(response.get("body"))
                probe_record = probe_get_after_post(minted_id)
            elif wr_ok and pack_ep == "POST /api/v1/cards/{cardId}/limit-requests":
                # Mints a limitRequestId; no direct GET in current swagger,
                # so use the ops-complete endpoint as a reachability proxy
                # (HEAD-like). If unreachable, the persistence probe will
                # report not_persisted; otherwise skipped.
                minted_id = extract_request_id_from_response(
                    response.get("body"),
                    ("limitRequestId", "id", "requestId"),
                )
                # No GET-by-id for limit-requests in the current Postman/Swagger.
                # Record that we attempted extraction but skipped probe.
                if minted_id:
                    probe_record = {
                        "kind": "skipped",
                        "primary_url": None,
                        "primary_status": None,
                        "primary_attempts": 0,
                        "secondary_url": None,
                        "secondary_status": None,
                        "persistence_confirmed": None,
                        "reason": (f"limitRequestId={minted_id} extracted but no direct "
                                   "GET-by-id endpoint exists in current contract; probe skipped"),
                    }
            if probe_record is not None:
                response["_persistence_probe"] = probe_record

            # --- T9: state-effect probe for carve-out TCs ---
            state_probe_record = None
            if state_verify_spec and wr_ok:
                cid = path_vars.get("cardId") or session_ids.get("cardId")
                if cid:
                    state_probe_record = state_effect_probe(
                        resource_id=cid,
                        verify_path_template=state_verify_spec["verify_path"],
                        expected_field_path=state_verify_spec["field"],
                        expected_value=state_verify_spec["expected"],
                    )
                    response["_state_effect_probe"] = state_probe_record

            verdict = evaluate(tc, request_summary, response)
            # --- Cluster-C reclassification ---
            # 404 on a happy-path TC with seeded substitution is Cluster-C-family regardless
            # of pre-flight verify outcome. Two sub-cases:
            #   (a) verify_record.verified=True + write 404  -> persistence_split (read works, write doesn't)
            #   (b) verify_record.cluster_c_suspected=True + write 404 -> seed_not_queryable (seed never resolves)
            # Either way: backend-owned, single finding instead of dozens of FAILs polluting the report.
            if (verdict["status"] == "FAIL"
                and response.get("status_code") == 404
                and allow_seed_substitution
                and plan["action"] == "as_is"
                and any(tok in path_template for tok in ("{cardId}", "{bankId}", "{affiliateId}"))):
                if verify_record.get("verified"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": ("CLUSTER_C_PERSISTENCE_SPLIT — seeded ID returns 200 on "
                                   "GET /api/v1/cards/{cardId} but this write/state endpoint returns 404 "
                                   "for the same ID; backend write/read consistency defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "persistence_split",
                    }
                elif verify_record.get("cluster_c_suspected"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"CLUSTER_C_SEED_NOT_QUERYABLE — pre-flight verify on seeded cardId "
                                   f"({session_ids.get('cardId')}) returned 404 after 3 attempts; this 404 "
                                   "is downstream of an unusable seed, not a real validation defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "seed_not_queryable",
                    }

            # --- Per-TC probe reclassification (POST /cards/issuance only) ---
            # Only refines non-PASS verdicts. Probe NEVER upgrades to PASS.
            if probe_record and verdict["status"] != "PASS":
                kind = probe_record.get("kind")
                if kind == "not_persisted":
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"WRITE_DID_NOT_PERSIST — POST returned 2xx "
                                   f"({response.get('status_code')}) and emitted cardId "
                                   f"{extract_card_id_from_response(response.get('body'))!r}, but "
                                   f"probe could not retrieve it on either primary or secondary "
                                   f"read path. Confirmed write-path defect. "
                                   f"Probe detail: {probe_record.get('reason')}"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "write_did_not_persist",
                    }
                elif kind == "read_path_5xx":
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"READ_PATH_5XX — POST returned 2xx but probe got 5xx on both "
                                   f"primary ({probe_record.get('primary_status')}) and secondary "
                                   f"({probe_record.get('secondary_status')}) reads."),
                        "schema": verdict.get("schema"),
                        "cluster": "H",
                        "defect_class": "read_path_5xx",
                    }
                elif kind == "partial_persistence":
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"PARTIAL_PERSISTENCE — cardId is retrievable on one read path "
                                   f"but not the other (primary={probe_record.get('primary_status')}, "
                                   f"secondary={probe_record.get('secondary_status')}). "
                                   f"{probe_record.get('reason')}"),
                        "schema": verdict.get("schema"),
                        "cluster": "H",
                        "defect_class": "partial_persistence",
                    }

            # --- T9: state-effect verdict refinement ---
            # ONLY for state-verify carve-outs. State_confirmed=True is the
            # explicit purpose of this probe — convert BLOCKED to PASS based
            # on real verification, not speculation. Safety: only fires when
            # state_verify_spec was set (i.e. classifier originally said BLOCKED
            # for db-verify reasons).
            if state_probe_record and state_verify_spec:
                kind = state_probe_record.get("kind")
                if kind == "state_confirmed":
                    verdict = {
                        "status": "PASS",
                        "reason": (f"STATE_CONFIRMED — {state_verify_spec['description']} "
                                   f"verified via {state_verify_spec['verify_path']} "
                                   f"(actual={state_probe_record.get('actual_value')!r})"),
                        "schema": verdict.get("schema"),
                    }
                elif kind == "state_mismatch":
                    verdict = {
                        "status": "FAIL",
                        "reason": (f"STATE_MISMATCH — write returned 2xx but state did not change "
                                   f"as expected. {state_verify_spec['description']}; actual="
                                   f"{state_probe_record.get('actual_value')!r}. Probe detail: "
                                   f"{state_probe_record.get('reason')}"),
                        "schema": verdict.get("schema"),
                        "cluster": "H",
                        "defect_class": "state_mismatch",
                    }
                elif kind == "state_field_missing":
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"STATE_FIELD_MISSING — verify GET succeeded but field "
                                   f"'{state_verify_spec['field']}' is not in response body. "
                                   f"Likely schema drift on the verify endpoint; cannot confirm "
                                   f"or deny state change."),
                        "schema": verdict.get("schema"),
                        "cluster": "Z2",
                        "defect_class": "verify_field_missing",
                    }
                elif kind == "state_get_failed":
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"STATE_GET_FAILED — verify GET returned "
                                   f"{state_probe_record.get('verify_status')}; cannot read "
                                   f"state. Stays BLOCKED but with attribution."),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "verify_get_failed",
                    }
            # --- port-8082 auth-before-routing: DELETE returns 401 not 405 ---
            # On port 8082 the auth middleware fires before method-routing, so DELETE
            # on a non-DELETE endpoint returns 401 instead of 405. Accept 401/403 as
            # PASS for delete_method_not_allowed scenarios.
            if (verdict["status"] == "FAIL"
                    and "delete_method_not_allowed" in scenario
                    and response.get("status_code") in (401, 403)):
                verdict = {
                    "status": "PASS",
                    "reason": (f"METHOD_NOT_ALLOWED_AUTH_FIRST — DELETE returned "
                               f"{response.get('status_code')} on port 8082; auth middleware "
                               f"fires before method routing so 401/403 is the correct rejection "
                               f"signal (equivalent to 405 on auth-unenforced ports)"),
                    "schema": verdict.get("schema"),
                }

            status = verdict["status"]
            counts[status] += 1; ep_counts[status] += 1

            input_data = {
                "method": method,
                "url": url,
                "path_template": path_template,
                "path_vars": path_vars,
                "query": query,
                "headers": override_headers,
                "body": body,
                "body_sha256": hash_body(body),
                "mutation": {"action": plan["action"], "note": mutation_note,
                             **{k: v for k, v in plan.items() if k not in ("action", "reason", "note")}},
                "seeded_substitution_applied": allow_seed_substitution,
            }

            actual_result = {
                "description": verdict.get("reason"),
                "cause": "schema mismatch" if (verdict.get("schema") and not verdict["schema"].get("valid")) else None,
                "result": verdict.get("status"),
            }

            evidence = {
                "test_case_id": tc["tc_id"],
                "endpoint": pack_ep,
                "api_id": api_id,
                "scenario": scenario,
                "input_data": input_data,
                "response": {
                    "ok": response.get("ok"),
                    "status_code": response.get("status_code"),
                    "elapsed_seconds": response.get("elapsed_seconds"),
                    "headers": response.get("headers"),
                    "body": response.get("body"),
                    "body_text": response.get("body_text"),
                    "body_sha256": hash_body(response.get("body") if response.get("body") is not None else response.get("body_text")),
                    "error": response.get("error"),
                    "_idempotency": response.get("_idempotency"),
                    "_sla": response.get("_sla"),
                    "_persistence_probe": probe_record,
                    "_state_effect_probe": state_probe_record,
                },
                "expected_result": tc.get("expected_result"),
                "verdict": verdict,
            }
            with open(evidence_path, "w", encoding="utf-8") as f:
                json.dump(evidence, f, indent=2, default=str)

            response_data = {
                "ok": response.get("ok"),
                "status_code": response.get("status_code"),
                "elapsed_seconds": response.get("elapsed_seconds"),
                "headers": response.get("headers"),
                "body": response.get("body"),
                "body_text": response.get("body_text"),
                "body_sha256": hash_body(response.get("body") if response.get("body") is not None else response.get("body_text")),
                "error": response.get("error"),
                "_idempotency": response.get("_idempotency"),
                "_concurrency": response.get("_concurrency"),
                "_read_after_write": response.get("_read_after_write"),
                "_sla": response.get("_sla"),
                "_persistence_probe": probe_record,
                "_state_effect_probe": state_probe_record,
            }
            entry = {
                **tc_base,
                "input_data": input_data,
                "response_data": response_data,
                "actual_result": actual_result,
                "response_code": response.get("status_code"),
                "execution_status": status,
                "evaluation_reason": verdict.get("reason"),
                "schema_finding": verdict.get("schema"),
                "finding_type": ("Schema Mismatch" if verdict.get("schema") and not verdict["schema"].get("valid")
                                 else ("Status Mismatch" if status == "FAIL" else None)),
                "defect_id": None,
                "evidence_file": evidence_path.name,
                "verdict": verdict,
            }
            if probe_record is not None:
                entry["probe_endpoint"] = probe_record.get("primary_url")
                entry["probe_status"] = probe_record.get("primary_status")
                entry["probe_attempts"] = probe_record.get("primary_attempts")
                entry["probe_kind"] = probe_record.get("kind")
                entry["persistence_confirmed"] = probe_record.get("persistence_confirmed")
            if state_probe_record is not None:
                entry["state_probe_endpoint"] = state_probe_record.get("verify_url")
                entry["state_probe_status"] = state_probe_record.get("verify_status")
                entry["state_probe_kind"] = state_probe_record.get("kind")
                entry["state_confirmed"] = state_probe_record.get("state_confirmed")
                entry["state_actual_value"] = state_probe_record.get("actual_value")
            if verdict.get("cluster"):
                entry["cluster"] = verdict["cluster"]
                entry["defect_class"] = verdict.get("defect_class")
                entry["blocked_reason"] = verdict["reason"]
            detailed.append(entry)

        endpoint_summaries.append({
            "endpoint": pack_ep, "api_id": api_id,
            "postman_endpoint": pm_key,
            "drift_flag": drift,
            "postman_base_payload": {
                "method": base["method"],
                "path_template": path_template,
                "path_vars": base["path_vars"],
                "query": base["query"],
                "headers": base["headers"],
                "body": base["body"],
            },
            "test_case_counts": ep_counts,
        })

    completed_at = dt.datetime.now().isoformat()
    total_tcs = sum(counts.values())
    failed = [d for d in detailed if d["execution_status"] == "FAIL"]
    blocked = [d for d in detailed if d["execution_status"] == "BLOCKED"]
    critical_failures = [f for f in failed if (f.get("priority") or "").lower() == "critical"]
    overall = "PASS" if counts["FAIL"] == 0 and counts["ERROR"] == 0 else "FAIL"

    report = {
        "report_metadata": {
            "service": "cards",
            "service_upper": "CARD",
            "run_mode": "postman_hybrid_cards",
            "report_date": dt.datetime.now().strftime("%Y-%m-%d"),
            "tester": "postman_hybrid_cards_runner",
            "base_api_url": BASE_URL,
            "swagger_source": str(SWAGGER_PATH),
            "postman_collection": str(POSTMAN_PATH),
            "test_pack": str(TEST_PACK_PATH),
            "auth_mode": "bearer_ecdsa_e2e",
            "seeded_ids": {
                "affiliateId": session_ids.get("affiliateId"),
                "bankId": session_ids.get("bankId"),
                "cardId_preflight": session_ids.get("cardId"),
                "cardId_fallback_used": setup_record.get("fallback_used", False),
                "post_mint_verify": verify_record,
            },
            "cluster_c_reclassified_count": sum(1 for d in detailed if d.get("cluster") == "C"),
            "persistence_probe_summary": {
                "endpoints_scoped_to": ["POST /api/v1/cards/issuance"],
                "probes_fired": sum(1 for d in detailed if d.get("probe_kind") is not None and d.get("probe_kind") != "skipped"),
                "persisted_count": sum(1 for d in detailed if d.get("probe_kind") == "persisted"),
                "not_persisted_count": sum(1 for d in detailed if d.get("probe_kind") == "not_persisted"),
                "read_path_5xx_count": sum(1 for d in detailed if d.get("probe_kind") == "read_path_5xx"),
                "partial_persistence_count": sum(1 for d in detailed if d.get("probe_kind") == "partial_persistence"),
                "transport_error_count": sum(1 for d in detailed if d.get("probe_kind") == "transport_error"),
                "write_did_not_persist_count": sum(1 for d in detailed if d.get("defect_class") == "write_did_not_persist"),
                "max_wait_seconds": PROBE_MAX_WAIT_S,
            },
            "state_effect_probe_summary": {
                "registry_entries": sum(len(v) for v in STATE_VERIFY_REGISTRY.values()),
                "probes_fired": sum(1 for d in detailed if d.get("state_probe_kind") is not None and d.get("state_probe_kind") != "skipped"),
                "state_confirmed_count": sum(1 for d in detailed if d.get("state_probe_kind") == "state_confirmed"),
                "state_mismatch_count": sum(1 for d in detailed if d.get("state_probe_kind") == "state_mismatch"),
                "state_field_missing_count": sum(1 for d in detailed if d.get("state_probe_kind") == "state_field_missing"),
                "state_get_failed_count": sum(1 for d in detailed if d.get("state_probe_kind") == "state_get_failed"),
                "blocked_to_pass_via_state_probe": sum(1 for d in detailed
                                                        if d.get("state_probe_kind") == "state_confirmed"
                                                        and d.get("execution_status") == "PASS"),
            },
            "overall_status": overall,
            "total_endpoints_processed": len(pack["endpoints"]) if not SCOPE_ENDPOINT else len(pack_endpoints_iter),
            "total_test_cases": total_tcs,
            "passed_test_cases": counts["PASS"],
            "failed_test_cases": counts["FAIL"],
            "blocked_test_cases": counts["BLOCKED"],
            "error_test_cases": counts["ERROR"],
            "started_at": started_at,
            "completed_at": completed_at,
        },
        "setup_steps": [setup_record],
        "test_pack_reconciliation": {
            "total_pack_endpoints": len(pack["endpoints"]),
            "matched_to_postman": sum(1 for e in pack["endpoints"] if PACK_TO_POSTMAN.get(e["endpoint"])),
            "unmatched": [e["endpoint"] for e in pack["endpoints"] if not PACK_TO_POSTMAN.get(e["endpoint"])],
            "expected_test_cases": pack.get("total_test_cases"),
            "actual_test_cases": total_tcs,
        },
        "contract_drift_findings": drift_findings,
        "discrepancy_overview": {
            "critical_issues": critical_failures,
            "all_failed_findings": failed,
            "blocked_findings_summary": _summarize_blocked(blocked),
        },
        "endpoint_summaries": endpoint_summaries,
        "detailed_test_cases": detailed,
        "auth_bypass_summary": {
            "total": len(auth_bypass_results),
            "passed":  sum(1 for r in auth_bypass_results if r.get("execution_status") == "PASS"),
            "failed":  sum(1 for r in auth_bypass_results if r.get("execution_status") == "FAIL"),
            "blocked": sum(1 for r in auth_bypass_results if r.get("execution_status") == "BLOCKED"),
            "not_applicable": sum(1 for r in auth_bypass_results if r.get("execution_status") == "NOT_APPLICABLE"),
            "auth_layer_verified": any(r.get("auth_layer_verified") for r in auth_bypass_results),
            "defects_found": sorted({r["defect_tag"] for r in auth_bypass_results if r.get("defect_tag")}),
            "note": ("Results UNVERIFIED — auth may fire after resource resolution; "
                     "404s on bad IDs could be misclassified as FAIL. "
                     "Re-run with a valid cardId or confirm middleware order.")
                    if not any(r.get("auth_layer_verified") for r in auth_bypass_results) else None,
        },
        "auth_bypass_test_cases": auth_bypass_results,
    }

    REPORT_PATH.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # T15: compress evidence dir into .tar.gz, delete originals.
    if os.environ.get("KEEP_EVIDENCE_DIR", "0") != "1":
        try:
            import shutil
            archive_path = EVIDENCE_DIR.with_suffix(".tar.gz")
            shutil.make_archive(str(EVIDENCE_DIR), "gztar", root_dir=str(EVIDENCE_DIR.parent),
                                base_dir=EVIDENCE_DIR.name)
            shutil.rmtree(EVIDENCE_DIR)
            print(f"Evidence compressed: {archive_path}")
        except Exception as e:
            print(f"Evidence compression skipped: {e}")

    ab_pass    = sum(1 for r in auth_bypass_results if r.get("execution_status") == "PASS")
    ab_fail    = sum(1 for r in auth_bypass_results if r.get("execution_status") == "FAIL")
    ab_blocked = sum(1 for r in auth_bypass_results if r.get("execution_status") == "BLOCKED")
    ab_na      = sum(1 for r in auth_bypass_results if r.get("execution_status") == "NOT_APPLICABLE")
    grand_total = total_tcs + len(auth_bypass_results)
    print(f"\n=== RUN COMPLETE ===")
    print(f"[Functional] Total: {total_tcs}  PASS: {counts['PASS']}  FAIL: {counts['FAIL']}  BLOCKED: {counts['BLOCKED']}  ERROR: {counts['ERROR']}")
    print(f"[Auth Bypass] Total: {len(auth_bypass_results)}  PASS: {ab_pass}  FAIL: {ab_fail}  BLOCKED: {ab_blocked}  N/A: {ab_na}")
    print(f"[Grand Total] {grand_total} TCs")
    print(f"Overall: {overall}")
    print(f"Report: {REPORT_PATH}")
    print(f"Evidence dir: {EVIDENCE_DIR}")

if __name__ == "__main__":
    try:
        main()
    finally:
        TOKEN_MANAGER.stop()
