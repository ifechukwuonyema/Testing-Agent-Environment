"""
Postman-driven HYBRID Bank API test harness.

Hybrid model (Bank variant):
  - Default: Postman base + scenario-driven mutation
  - Pre-flight: live POST /api/v1/admin/banks to mint a fresh bankId; on failure, fallback to POST /api/v1/banks/query for an existing persisted bankId; persisted to SessionStore
  - Per-TC: requestContext.requestId + idempotencyKey rotated to fresh UUIDs (except *_idempotent_on_retry)
  - Per-TC: {bankId}/{affiliateId} path vars substituted with seeded values
            (skipped for unknown_id/malformed_id scenarios)
  - Pack order iteration (no lifecycle_order.yaml for Bank)

Per-TC payload inline in YAML's detailed_test_cases[].input_data per the canonical schema.
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

BASE_URL = os.getenv("KARDIT_BASE_URL", "http://167.172.49.177:8080")
RUN_TS = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

# Backend-canonical IDs (Bankbackend.docx feedback, 2026-05-07).
# Backend identified these as the seeded test fixtures for the bank harness.
# When CANONICAL_BANK_SEED has a bankId, pre-flight skips POST /admin/banks mint
# and uses the canonical id directly (still verified via Phase 0b).
# Per-endpoint affiliate overrides apply at request-build time so CTRL-01 and
# CTRL-02 each get their dedicated affiliate fixture.
CANONICAL_BANK_SEED = {
    "bankId": "000045f9-d01b-479c-a84d-0fe82454d55a",   # 80 ACTIVE affiliates; UUID requestIds confirmed (probed 2026-05-14)
}
# Same bank as CANONICAL_BANK_SEED — UUID requestIds only resolvable on this bank.
APPROVE_REJECT_BANK_ID = "000045f9-d01b-479c-a84d-0fe82454d55a"

CANONICAL_AFFILIATE_BY_ENDPOINT: dict = {}
# Stale hardcoded seeds removed 2026-05-14 — AFF-B64CCDBF / AFF-CB5CF16C already
# suspended/blocked from prior runs; rotating pools from bank_fixtures_v2.json used instead.

# --- Rotating fixture pools (one fresh resource per TC) -------------------
# bank_fixtures_v2.json layout:
#   suspend_block_pool:  [{bankId, affiliateId}]  — canonical bank affiliates
#   approve_reject_pool: [{bankCode, bankId, affiliateId, partnershipRequestId}]
from collections import deque as _deque
def _load_fixture_pools():
    _fp = _SVC_DIR / "data" / "bank_fixtures_v2.json"
    if not _fp.exists():
        return _deque(), _deque(), _deque(), _deque(), _deque(), _deque(), _deque()
    try:
        with open(_fp, encoding="utf-8") as _f:
            _fx = json.load(_f)
    except Exception:
        return _deque(), _deque(), _deque(), _deque(), _deque(), _deque(), _deque()
    # Dedicated suspend/block pools — non-overlapping by design (different affiliateId sets).
    # Fall back to legacy suspend_block_pool (split in half) if new keys absent.
    _legacy_sb = _fx.get("suspend_block_pool", [])
    _legacy_sb_pairs = [(x["bankId"], x["affiliateId"]) for x in _legacy_sb if x.get("bankId") and x.get("affiliateId")]
    _legacy_mid = len(_legacy_sb_pairs) // 2
    _susp_raw = _fx.get("suspend_pool") or _legacy_sb_pairs[:_legacy_mid]
    _blk_raw  = _fx.get("block_pool")   or _legacy_sb_pairs[_legacy_mid:]
    def _pairs(lst):
        if lst and isinstance(lst[0], dict):
            return [(x["bankId"], x["affiliateId"]) for x in lst if x.get("bankId") and x.get("affiliateId")]
        return lst  # already tuples (legacy path)
    _suspend_pairs = _pairs(_susp_raw)
    _block_pairs   = _pairs(_blk_raw)
    # Approve/reject pools — non-overlapping by design (different requestId sets).
    _ap = _fx.get("approve_pool") or _fx.get("approve_reject_pool", [])
    _rp = _fx.get("reject_pool")  or _fx.get("approve_reject_pool", [])
    _p1 = _fx.get("part01_pool")  or _ap or _fx.get("approve_reject_pool", [])
    _ap_reqs = [x["partnershipRequestId"] for x in _ap if x.get("partnershipRequestId")]
    _rp_reqs = [x["partnershipRequestId"] for x in _rp if x.get("partnershipRequestId")]
    _p1_reqs = [x["partnershipRequestId"] for x in _p1 if x.get("partnershipRequestId")]
    # Bonus pools for duplicate-decision TCs.
    _aa = _fx.get("already_approved_pool", [])
    _ar = _fx.get("already_rejected_pool", [])
    _aa_reqs = [x["partnershipRequestId"] for x in _aa if x.get("partnershipRequestId")]
    _ar_reqs = [x["partnershipRequestId"] for x in _ar if x.get("partnershipRequestId")]
    return (_deque(_suspend_pairs), _deque(_block_pairs),
            _deque(_ap_reqs), _deque(_rp_reqs), _deque(_p1_reqs),
            _deque(_aa_reqs), _deque(_ar_reqs))

(SUSPEND_POOL, BLOCK_POOL,
 APPROVE_POOL, REJECT_POOL, PART01_POOL,
 ALREADY_APPROVED_POOL, ALREADY_REJECTED_POOL) = _load_fixture_pools()
# suspend_pool: 40 AFF-SUS-xxx (exclusively for CTRL-01 suspend, DB-confirmed 2026-05-14).
# block_pool:   40 AFF-BLK-xxx (exclusively for CTRL-02 block, non-overlapping).
# approve_pool: 40 REQ-APP-xxx PENDING requestIds (bank-internal, for PART-02).
# reject_pool:  40 REQ-REJ-xxx PENDING requestIds (non-overlapping, for PART-03).
# part01_pool:  80 requestIds (read-only GET, no state consumed).
# already_approved_pool: 1 already-APPROVED requestId (for duplicate_decision TCs on approve).
# already_rejected_pool: 1 already-REJECTED requestId (for duplicate_decision TCs on reject).
# Phase 0d/0e refresh these at runtime; _load_fixture_pools is a cold-start fallback.
FIXTURE_POOL_BY_ENDPOINT: dict = {}
REQUEST_POOL_BY_ENDPOINT = {
    "GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}": PART01_POOL,
    "POST /api/v1/banks/partnerships/{requestId}/approve": APPROVE_POOL,
    "POST /api/v1/banks/partnerships/{requestId}/reject":  REJECT_POOL,
}

# Strict per-endpoint pool registry.
# Each endpoint maps to exactly one pool. No cross-endpoint borrowing — ever.
# CTRL endpoints: pool contains (bankId, affiliateId) tuples.
# PART endpoints: pool contains requestId strings.
# Populated at startup; Phase 0d/0e mutate the deques in-place so these refs stay live.
ENDPOINT_POOL_REGISTRY: dict[str, Any] = {
    "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend": SUSPEND_POOL,
    "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/block":   BLOCK_POOL,
    "GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}": PART01_POOL,
    "POST /api/v1/banks/partnerships/{requestId}/approve": APPROVE_POOL,
    "POST /api/v1/banks/partnerships/{requestId}/reject":  REJECT_POOL,
}
# Already-settled pools for non_pending / duplicate_decision scenarios.
# Only approve/reject endpoints have these — CTRL and PART-01 have no settled pool.
ENDPOINT_SETTLED_POOL_REGISTRY: dict[str, Any] = {
    "POST /api/v1/banks/partnerships/{requestId}/approve": ALREADY_APPROVED_POOL,
    "POST /api/v1/banks/partnerships/{requestId}/reject":  ALREADY_REJECTED_POOL,
}

# Per-TC requestId overrides — bypasses pool rotation and pins a specific PENDING
# requestId directly to a named TC. Used when pool IDs are consumed and we need
# a guaranteed-fresh ID for a specific scenario without rebuilding the fixture.
CANONICAL_BANK_ID = "000045f9-d01b-479c-a84d-0fe82454d55a"
# Per-TC seed override — maps tc_id to either a requestId string (PART endpoints)
# or a (bankId, affiliateId) tuple (CTRL endpoints). Bypasses pool rotation entirely.
TC_REQUEST_ID_OVERRIDE: dict[str, Any] = {
    # CTRL-01: ACTIVE affiliates for suspend state-guard TCs
    "TC-API-BNK-CTRL-01-014": (CANONICAL_BANK_ID, "AFF-SUS-411"),
    "TC-API-BNK-CTRL-01-015": (CANONICAL_BANK_ID, "AFF-SUS-410"),
    # CTRL-02: ACTIVE affiliates for block state-guard TCs
    "TC-API-BNK-CTRL-02-014": (CANONICAL_BANK_ID, "AFF-BLK-514"),
    "TC-API-BNK-CTRL-02-015": (CANONICAL_BANK_ID, "AFF-BLK-510"),
    # PART-02: PENDING requestIds for approve TCs
    "TC-API-BNK-PART-02-001": "REQ-PENDING-904",
    "TC-API-BNK-PART-02-021": "REQ-PENDING-905",
    "TC-API-BNK-PART-02-022": "REQ-PENDING-906",
    "TC-API-BNK-PART-02-026": "REQ-PENDING-907",
    "TC-API-BNK-PART-02-037": "REQ-TEST-NEW-001",
    # PART-03: PENDING requestIds for reject TCs
    "TC-API-BNK-PART-03-001": "REQ-PENDING-908",
    "TC-API-BNK-PART-03-022": "REQ-PENDING-909",
    "TC-API-BNK-PART-03-025": "REQ-PENDING-982",
    "TC-API-BNK-PART-03-026": "REQ-PENDING-983",
}

# Backend requires fields on requestContext that the swagger marks optional and
# the Postman base body omits. Per 2026-05-07 run, every CTRL-01 happy path
# 400'd with `RequestContext.AffiliateId is required` and CTRL-02 also wanted
# `RequestContext.TenantId`. Inject these from path_vars / DEFAULT_TENANT_ID
# AFTER rotate_request_context but BEFORE the mutation engine, so missing_X
# tests can still drop the field and exercise the negative path.
CANONICAL_REQUEST_CONTEXT_INJECTION = {
    "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend": ("affiliateId", "tenantId", "top_level_idem"),
    "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/block":   ("affiliateId", "tenantId"),
}
DEFAULT_TENANT_ID = "TNT-AFF-10291"

# Postman has POST /api/v1/banks/query mistakenly registered as GET. Pack and
# swagger declare it as POST. Without this override every BNK-06 TC blocks with
# "Postman doesn't include any request for this endpoint". The override remaps
# the lookup to the actual Postman key; method gets force-corrected at request
# time using the pack endpoint's declared verb. Body defaults to a swagger-valid
# empty filter when the Postman entry has no body.
POSTMAN_KEY_OVERRIDE = {
    "POST /api/v1/banks/query": "GET /api/v1/banks/query",
}
POSTMAN_BODY_DEFAULT = {
    "POST /api/v1/banks/query": {
        "filters": {},
        "pagination": {"page": 1, "pageSize": 20},
    },
}

SCOPE_ENDPOINT = os.environ.get("SCOPE_ENDPOINT")
_env_api_ids = [x.strip() for x in os.environ.get("SCOPE_API_IDS", "").split(",") if x.strip()]
# Restrict run to specific api_ids. Env var overrides; empty = run all.
SCOPE_API_IDS: set[str] = set(_env_api_ids)
SCOPE_TC_IDS: set[str] = {t.strip() for t in os.environ.get("SCOPE_TC_IDS", "").split(",") if t.strip()}
_scope_tag = ""
if SCOPE_ENDPOINT:
    _scope_tag = "_" + re.sub(r"[^a-zA-Z0-9]+", "_", SCOPE_ENDPOINT).strip("_")
elif SCOPE_TC_IDS:
    _scope_tag = "_tc"

# REPLAY_FAILED_REPORT: path to a previous bank report YAML.
# When set, only (api_id, scenario) pairs that FAILed in that report are run.
# Useful for re-testing failed TCs after a fix without re-running the full pack.
REPLAY_FAILED_REPORT = os.environ.get("REPLAY_FAILED_REPORT")
_replay_failed_set: set = set()  # set of (api_id, scenario) tuples
if REPLAY_FAILED_REPORT:
    import yaml as _yaml_mod
    with open(REPLAY_FAILED_REPORT, encoding="utf-8") as _rf:
        _replay_data = _yaml_mod.safe_load(_rf)
    _replay_tcs = _replay_data.get("detailed_test_cases", [])
    _replay_failed_set = {
        (tc["api_id"], tc["scenario"])
        for tc in _replay_tcs
        if tc.get("execution_status") in ("FAIL", "BLOCKED")
    }
    _scope_tag = "_replay_failed"
    print(f"[REPLAY] Loaded {len(_replay_failed_set)} FAIL+BLOCKED (api_id, scenario) pairs from {REPLAY_FAILED_REPORT}")

EVIDENCE_DIR     = _SVC_DIR / "evidence" / f"run_{RUN_TS}"
REPORT_PATH      = _SVC_DIR / "reports" / f"bank_run_{RUN_TS}.yaml"

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
    col = load_postman()
    idx = {}
    for entry in walk_postman(col["item"]):
        req = entry["request"]
        method = req.get("method", "GET").upper()
        url = req.get("url", "")
        path = normalize_path(url)
        idx[f"{method} {path}"] = entry
    return idx

# --- pack-to-postman match map (Bank, after 2026-05-01 path remap) --------
PACK_TO_POSTMAN = {
    "POST /api/v1/admin/banks": "POST /api/v1/admin/banks",
    "GET /api/v1/banks/{bankId}/affiliates": "GET /api/v1/banks/{bankId}/affiliates",
    "POST /api/v1/banks/{bankId}/audit-logs": "POST /api/v1/banks/{bankId}/audit-logs",
    "POST /api/v1/banks/{bankId}/reports": "POST /api/v1/banks/{bankId}/reports",
    "POST /api/v1/banks/query": "POST /api/v1/banks/query",
    "GET /api/v1/banks/query": "GET /api/v1/banks/query",
    "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend": "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend",
    "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/block": "POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/block",
    "GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}": "GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}",
    "POST /api/v1/banks/partnerships/{requestId}/approve": "POST /api/v1/partnerships/{requestId}/approve",
    "POST /api/v1/banks/partnerships/{requestId}/reject": "POST /api/v1/partnerships/{requestId}/reject",
    "POST /api/v1/banks/{bankId}/cards": "POST /api/v1/banks/{bankId}/cards",
}
# Pack endpoints whose actual path differs from the Postman entry's path. Reserved for future
# pack-vs-Postman drift; currently empty since dashboard reconciled at v2 in both.
PATH_TEMPLATE_OVERRIDE = {
    # PART-01 Postman entry has a literal concrete URL (no path variables). Override with
    # the parameterised template so rebuild_url can substitute bankId + requestId from the pool.
    "GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}":
        "/api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}",
    # PART-02/03 Postman entries use /partnerships/... (no /banks/ prefix).
    # Override to use the swagger-correct /banks/partnerships/... path at runtime.
    "POST /api/v1/banks/partnerships/{requestId}/approve":
        "/api/v1/banks/partnerships/{requestId}/approve",
    "POST /api/v1/banks/partnerships/{requestId}/reject":
        "/api/v1/banks/partnerships/{requestId}/reject",
}
DRIFT_FLAGS = {
    "GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}": "pack_path_remapped_2026-05-01_was_partnership_requests_list",
}

# Pack endpoints that require body-level scope injection because the new endpoint dropped a
# path-var the pack still expects. Maps pack endpoint -> the body filter the seeded id goes
# into. Applied per-TC after mutations, before URL build. Only fires when allow_substitution
# is True (so foreign-bank/scope negative tests still get the input the mutator picked).
BODY_SCOPE_INJECTION = {}

# Pack endpoints whose Postman base body needs sanitization for happy-path runs because the
# Postman literal carries "string" placeholders, inverted date ranges, or out-of-range
# page/pageSize that the backend rejects with 400. The harness still sends a real, valid
# body to exercise the endpoint; per-TC mutations override these defaults.
BODY_SANITIZATION = {}

_STRING_SENTINELS = ("", "string", "null", None)


def _sanitize_filters_dict(filters: dict) -> dict:
    """Replace 'string' sentinel scalars with None, and arrays of 'string' sentinels with []."""
    out = {}
    for k, v in filters.items():
        if isinstance(v, str) and v in _STRING_SENTINELS:
            out[k] = None
        elif isinstance(v, list) and all(isinstance(x, str) and x in _STRING_SENTINELS for x in v):
            out[k] = []
        else:
            out[k] = v
    return out


def inject_body_scope(pack_ep: str, body: Any, session_ids: dict,
                       allow_substitution: bool) -> Any:
    """For pack endpoints that lost a path-scope, inject the seeded id into the
    matching body filter and sanitize the Postman placeholder body. Replaces only
    Postman-literal sentinels ('string', '', null) so explicit per-TC mutations
    are preserved."""
    if not allow_substitution or not isinstance(body, dict):
        return body
    out = copy.deepcopy(body)

    # Body sanitization (happy-path placeholder cleanup) — runs before scope injection.
    san = BODY_SANITIZATION.get(pack_ep)
    if san:
        if san.get("filters_clear_sentinels") and isinstance(out.get("filters"), dict):
            out["filters"] = _sanitize_filters_dict(out["filters"])
        if san.get("drop_inverted_dates") and isinstance(out.get("filters"), dict):
            f = out["filters"]
            fd, td = f.get("fromDate"), f.get("toDate")
            if isinstance(fd, str) and isinstance(td, str) and fd > td:
                f["fromDate"] = None
                f["toDate"] = None
        if "page_default" in san:
            page = out.get("page")
            if not isinstance(page, int) or page < 1 or page > 100000:
                out["page"] = san["page_default"]
        if "page_size_default" in san:
            ps = out.get("pageSize")
            if not isinstance(ps, int) or ps < 1 or ps > 1000:
                out["pageSize"] = san["page_size_default"]

    # Scope injection (replace "string" with seeded id where rules apply)
    rules = BODY_SCOPE_INJECTION.get(pack_ep) or []
    for parent, field, session_key in rules:
        seed = session_ids.get(session_key)
        if not seed:
            continue
        container = out.setdefault(parent, {})
        if not isinstance(container, dict):
            continue
        existing = container.get(field)
        if existing in _STRING_SENTINELS:
            container[field] = seed
    return out

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
            if k.lower() in ("authorization", "x-api-key"): continue
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
    """Replace requestContext.requestId + idempotencyKey with fresh UUIDs, and
    also rotate any top-level requestId/idempotencyKey. The 2026-05-11 Postman
    has /block with idempotencyKey at the TOP LEVEL while /suspend has it
    nested in requestContext — both must rotate per TC or the second TC hits
    a stale idempotencyKey and 409s on idempotency replay.
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
    # Always rotate top-level too — body may carry both (e.g. /block) and we
    # don't want stale top-level overriding fresh nested ones (or vice versa).
    if "requestId" in body:
        body["requestId"] = new_request_id
    if "idempotencyKey" in body:
        body["idempotencyKey"] = new_idem
    return body

# --- HYBRID: seeded-id injection ------------------------------------------
SEEDED_PATH_VAR_KEYS = {"cardId", "bankId", "affiliateId", "requestId"}

def inject_seeded_path_vars(path_vars: dict, session_ids: dict, allow_substitution: bool) -> dict:
    """Replace path-var values with seeded session IDs, where applicable.
    `allow_substitution=False` skips the swap (e.g. for unknown_id / malformed_id mutations
    that intentionally want a fake value).
    """
    out = dict(path_vars)
    if not allow_substitution:
        return out
    for k in list(out.keys()):
        if k in SEEDED_PATH_VAR_KEYS and session_ids.get(k):
            out[k] = session_ids[k]
    return out

# --- HYBRID: pre-flight bank provision ------------------------------------
def extract_bank_id_from_response(resp_body: Any) -> str | None:
    """Best-effort extraction of bankId from POST /admin/banks response. Tries common shapes."""
    if not isinstance(resp_body, dict):
        return None
    data = resp_body.get("data") if isinstance(resp_body.get("data"), dict) else resp_body
    for k in ("bankId", "id", "bankID"):
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, str) and v:
            return v
    if isinstance(data, dict):
        bank = data.get("bank")
        if isinstance(bank, dict):
            for k in ("bankId", "id"):
                v = bank.get(k)
                if isinstance(v, str) and v:
                    return v
    return None

def extract_first_bank_id_from_query(resp_body: Any) -> str | None:
    """Recursively scan a /banks/query response for the first valid bankId.
    Handles arbitrary envelopes (data[], data.data[], items[], banks[], etc.).
    """
    return extract_first_id_recursive(resp_body, ("bankId", "bankID", "id"))


def _persist_bank_if_verified(bid: str, session_ids: dict, source: str) -> dict:
    """Verify the bankId is queryable before writing it to SessionStore.
    Codex H4: never persist an unverified id, never silently fall back to a
    stale stored id without flagging provenance.
    Returns a record with verified bool, source label, and the verify outcome.
    """
    verify_rec = verify_seeded_id_queryable(bid, "/api/v1/banks/{bankId}/affiliates")
    persisted = False
    if verify_rec.get("verified"):
        session_ids["bankId"] = bid
        SESSION.save({"bankId": bid})
        persisted = True
    return {
        "selected_source": source,
        "selected_verified": bool(verify_rec.get("verified")),
        "persisted_to_session_store": persisted,
        "verify": verify_rec,
    }


def query_fallback_bank(pm_idx: dict, session_ids: dict) -> dict:
    """Fallback to POST /api/v1/banks/query when mint fails. Returns a sub-record."""
    rec = {
        "step": "query_existing_bank",
        "method": "POST",
        "endpoint": "/api/v1/banks/query",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
    }
    pm_entry = pm_idx.get("POST /api/v1/banks/query")
    if not pm_entry:
        rec.update({"status": "ERROR",
                    "reason": "POST /api/v1/banks/query not in Postman — cannot query for existing bank"})
        return rec
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"])
    # Codex M6: filter for ACTIVE banks only — picking the first SUSPENDED/BLOCKED
    # bank from a broadened query would propagate an unusable id downstream.
    if isinstance(body, dict):
        for criteria_key in ("criteria", "filter", "filters"):
            sub = body.get(criteria_key)
            if isinstance(sub, dict):
                # Preserve container shape; replace filter contents with status=ACTIVE.
                body[criteria_key] = {"status": ["ACTIVE"]}
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
        bid = extract_first_bank_id_from_query(response.get("body"))
        if bid:
            persist = _persist_bank_if_verified(bid, session_ids, source="query_fallback")
            rec["bank_id"] = bid
            rec["persistence"] = persist
            rec["status"] = "OK" if persist["selected_verified"] else "UNVERIFIED"
            if not persist["selected_verified"]:
                rec["reason"] = "query returned a bankId but verify GET did not confirm it is queryable; not persisted"
            return rec
        rec.update({"status": "DEGRADED",
                    "reason": f"2xx ({sc}) but query returned no bank with extractable id"})
        return rec
    rec.update({"status": "FAIL", "reason": f"query non-2xx ({sc})"})
    return rec


def pre_flight_provision_bank(pm_idx: dict, session_ids: dict) -> dict:
    """Acquisition order: 0) honor CANONICAL_BANK_SEED if set (skip mint, verify only),
    1) mint via POST /admin/banks, 2) fallback to POST /banks/query for an existing
    persisted bankId, 3) fallback to whatever's in SessionStore."""
    setup = {
        "step": "provision_seed_bank",
        "method": "POST",
        "endpoint": "/api/v1/admin/banks",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "fallback_used": False,
        "query_fallback": None,
    }
    # Phase 0a: use backend-canonical seed if provided (Bankbackend.docx 2026-05-07).
    canonical_bid = CANONICAL_BANK_SEED.get("bankId")
    if canonical_bid:
        setup["step"] = "use_canonical_bank_seed"
        setup["endpoint"] = "<canonical>"
        setup["bank_id"] = canonical_bid
        persist = _persist_bank_if_verified(canonical_bid, session_ids, source="canonical_seed")
        setup["persistence"] = persist
        if persist["selected_verified"]:
            setup["status"] = "OK_VIA_CANONICAL"
            setup["completed_at"] = dt.datetime.now().isoformat()
            return setup
        setup.update({
            "status": "CANONICAL_UNVERIFIED",
            "reason": (f"Canonical bankId {canonical_bid} did not verify via GET "
                       f"/api/v1/banks/{{bankId}}/affiliates; falling back to mint+query"),
            "fallback_used": True,
        })
    pm_entry = pm_idx.get("POST /api/v1/admin/banks")
    if not pm_entry:
        setup.update({
            "status": "ERROR",
            "reason": "POST /api/v1/admin/banks not found in Postman collection — cannot pre-flight provision",
        })
        # Even with mint unavailable, still try the query fallback before giving up.
        setup["query_fallback"] = query_fallback_bank(pm_idx, session_ids)
        if setup["query_fallback"].get("status") == "OK":
            setup.update({"status": "OK_VIA_QUERY", "fallback_used": True,
                          "bank_id": setup["query_fallback"].get("bank_id")})
            # Codex re-audit MEDIUM-3: promote the verified persistence record
            # so the chain harvester (R1 verified-gate) sees this id as harvestable.
            qf_persistence = setup["query_fallback"].get("persistence")
            if isinstance(qf_persistence, dict):
                setup["persistence"] = qf_persistence
        return setup
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"])
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
        new_bank_id = extract_bank_id_from_response(response.get("body"))
        if new_bank_id:
            persist = _persist_bank_if_verified(new_bank_id, session_ids, source="mint")
            setup["bank_id"] = new_bank_id
            setup["persistence"] = persist
            if persist["selected_verified"]:
                setup["status"] = "OK"
                return setup
            # mint produced a bankId but verify failed — try query fallback.
            setup.update({
                "status": "MINT_UNVERIFIED",
                "reason": "mint 2xx returned a bankId but verify GET did not confirm it; trying query fallback",
                "fallback_used": True,
            })
        else:
            # 2xx but no extractable bankId — try query fallback before giving up.
            setup.update({
                "status": "DEGRADED",
                "reason": f"2xx ({sc}) but bankId not extractable from mint response; trying query fallback",
                "fallback_used": True,
            })
    elif not response.get("ok"):
        setup.update({"status": "ERROR_PRE_FALLBACK",
                      "reason": f"mint transport: {response.get('error')}; trying query fallback",
                      "fallback_used": True})
    else:
        setup.update({
            "status": "FAIL_PRE_FALLBACK",
            "reason": f"mint non-2xx ({sc}); trying query fallback",
            "fallback_used": True,
        })
    setup["query_fallback"] = query_fallback_bank(pm_idx, session_ids)
    if setup["query_fallback"].get("status") == "OK":
        setup.update({"status": "OK_VIA_QUERY", "bank_id": setup["query_fallback"].get("bank_id")})
        # MEDIUM-3: promote nested persistence to top-level for chain harvester.
        qf_persistence = setup["query_fallback"].get("persistence")
        if isinstance(qf_persistence, dict):
            setup["persistence"] = qf_persistence
    else:
        # Map back to a terminal status so callers see the original failure mode preserved.
        if setup["status"] == "ERROR_PRE_FALLBACK":
            setup["status"] = "ERROR"
        elif setup["status"] == "FAIL_PRE_FALLBACK":
            setup["status"] = "FAIL"
        setup["reason"] = (setup.get("reason", "") +
                          f" | query fallback: {setup['query_fallback'].get('status')} "
                          f"({setup['query_fallback'].get('reason')})")
    return setup

# --- HYBRID: partnership-request acquisition (mint -> query fallback) -----
# Bank approve/reject endpoints need a fresh PENDING requestId per run because
# any reused requestId returns 409 once it has been settled. Pre-flight mints
# one against the seeded affiliateId+bankId, falls back to querying for an
# existing PENDING request if mint fails.

def extract_first_request_id_recursive(resp_body: Any) -> str | None:
    return extract_first_id_recursive(
        resp_body,
        ("requestId", "partnershipRequestId", "request_id", "id"),
    )


def _is_pending_request(record: dict) -> bool:
    if not isinstance(record, dict):
        return False
    status = record.get("status") or record.get("requestStatus") or record.get("state")
    if not isinstance(status, str):
        return True  # if no status field, accept (let verify decide)
    return status.upper() == "PENDING"


def extract_pending_request_id_from_query(resp_body: Any) -> str | None:
    """Walk a /partnership-requests/query response for a request whose status is PENDING.
    Falls back to the first request-like id if none is explicitly PENDING."""
    if not isinstance(resp_body, dict):
        return None
    for container in ("data", "items", "results", "requests", "partnershipRequests"):
        items = resp_body.get(container)
        if isinstance(items, list):
            for item in items:
                if _is_pending_request(item):
                    for k in ("requestId", "partnershipRequestId", "id"):
                        v = item.get(k) if isinstance(item, dict) else None
                        if isinstance(v, str) and v:
                            return v
    return extract_first_request_id_recursive(resp_body)


def verify_partnership_request_queryable(request_id: str | None, bank_id: str | None,
                                          max_retries: int = 2, delay_s: float = 1.0) -> dict:
    """GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId} to confirm
    the request is recognized by the read pipeline."""
    rec = {"verified": False, "url": None, "status": None, "attempts": 0,
           "cluster_c_suspected": False, "reason": None}
    if not request_id or not bank_id:
        rec["reason"] = "no request_id or bank_id provided"
        return rec
    url = (f"{BASE_URL}/api/v1/banks/{bank_id}"
           f"/affiliate-partnership-requests/{request_id}")
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
            rec.update({"status": sc, "reason": f"GET non-2xx non-404 ({sc}); not Cluster-C signature"})
            return rec
        if attempt < max_retries:
            time.sleep(delay_s * (attempt + 1))
    rec.update({"status": last_status, "cluster_c_suspected": True,
                "reason": f"GET returned 404 after {max_retries + 1} attempts — partnership-request not visible to bank read scope"})
    return rec


def _persist_request_if_verified(request_id: str, bank_id: str, session_ids: dict,
                                  source: str) -> dict:
    verify_rec = verify_partnership_request_queryable(request_id, bank_id)
    persisted = False
    if verify_rec.get("verified"):
        session_ids["requestId"] = request_id
        SESSION.save({"requestId": request_id})
        persisted = True
    return {
        "selected_source": source,
        "selected_verified": bool(verify_rec.get("verified")),
        "persisted_to_session_store": persisted,
        "verify": verify_rec,
    }


def query_fallback_partnership_request(pm_idx: dict, session_ids: dict,
                                        bank_id: str) -> dict:
    rec = {
        "step": "query_existing_partnership_request",
        "method": "POST",
        "endpoint": "/api/v1/affiliates/partnership-requests/query",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
    }
    pm_entry = pm_idx.get("POST /api/v1/affiliates/partnership-requests/query")
    if not pm_entry:
        rec.update({"status": "ERROR",
                    "reason": "POST /api/v1/affiliates/partnership-requests/query not in Postman"})
        return rec
    base = build_base_request(pm_entry)
    # Override Postman base body with bank-scoped, status-filtered query so the
    # fallback returns PENDING requests belonging to the canonical bank instead
    # of an unscoped page-1 dump that hits requests in other banks. Body shape
    # per swagger: top-level `filters`, top-level `page`/`pageSize` (NOT nested
    # under `pagination` — that triggers a $.pagination unmappable + payload-
    # required cascade error against QueryPartnershipRequestsDTO).
    path_template = get_postman_path_template(pm_entry)
    url = rebuild_url(base["method"], path_template, base["path_vars"], base["query"])
    rec["url"] = url
    # Try PENDING_BANK_APPROVAL first; fall back to any-status so a valid requestId
    # can still seed the GET endpoint even when all requests have been processed.
    query_attempts = [
        {"filters": {"bankId": bank_id, "status": ["PENDING_BANK_APPROVAL"]}, "page": 1, "pageSize": 50},
        {"filters": {"bankId": bank_id}, "page": 1, "pageSize": 50},
    ]
    for attempt_body in query_attempts:
        rec["request_body"] = attempt_body
        response = execute(base["method"], url, base["headers"], attempt_body, timeout=30)
        rec["response_status"] = response.get("status_code")
        rec["response_body"] = response.get("body") if response.get("body") is not None else response.get("body_text")
        rec["completed_at"] = dt.datetime.now().isoformat()
        if not response.get("ok"):
            rec.update({"status": "ERROR", "reason": f"transport: {response.get('error')}"})
            return rec
        sc = response.get("status_code", 0)
        if 200 <= sc < 300:
            rid = extract_pending_request_id_from_query(response.get("body"))
            if rid:
                persist = _persist_request_if_verified(rid, bank_id, session_ids,
                                                        source="query_fallback")
                rec["request_id"] = rid
                rec["persistence"] = persist
                rec["status"] = "OK" if persist["selected_verified"] else "UNVERIFIED"
                if not persist["selected_verified"]:
                    rec["reason"] = "query returned a requestId but verify GET did not confirm it; not persisted"
                return rec
        else:
            rec.update({"status": "FAIL", "reason": f"query non-2xx ({sc})"})
            return rec
    rec.update({"status": "DEGRADED",
                "reason": "2xx but no partnership-request found under any status filter"})
    return rec


def _list_bank_linked_affiliate_ids(bank_id: str) -> set[str]:
    """Return the set of affiliateIds already linked to the bank."""
    if not bank_id:
        return set()
    url = f"{BASE_URL}/api/v1/banks/{bank_id}/affiliates"
    resp = execute("GET", url, {"Accept": "application/json"}, None, timeout=15)
    out: set[str] = set()
    if resp.get("ok") and resp.get("status_code") == 200:
        body = resp.get("body") or {}
        affiliates = body.get("affiliates") if isinstance(body, dict) else None
        if isinstance(affiliates, list):
            for item in affiliates:
                aid = item.get("affiliateId") if isinstance(item, dict) else None
                if isinstance(aid, str) and aid:
                    out.add(aid)
    return out


def discover_approved_affiliate_for_bank(bank_id: str) -> str | None:
    """Pull an approved affiliateId from GET /banks/{bankId}/affiliates.
    Bank-linked affiliates are by definition approved. Used by reads that
    need a guaranteed-in-scope affiliate.
    """
    if not bank_id:
        return None
    linked = _list_bank_linked_affiliate_ids(bank_id)
    if linked:
        return next(iter(linked))
    # Fallback: any ACTIVE affiliate via POST /affiliates/query
    qurl = f"{BASE_URL}/api/v1/affiliates/query"
    qbody = {"page": 1, "pageSize": 50, "filters": {}}
    qresp = execute("POST", qurl, {"Content-Type": "application/json"}, qbody, timeout=20)
    if qresp.get("ok") and qresp.get("status_code") == 200:
        body = qresp.get("body") or {}
        items = body.get("data") or body.get("items") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                status = (item.get("status") or "").upper()
                aid = item.get("affiliateId")
                if isinstance(aid, str) and aid and status in ("ACTIVE", "APPROVED"):
                    return aid
    return None


def discover_unlinked_affiliate_for_bank(bank_id: str) -> str | None:
    """Find an ACTIVE/APPROVED affiliate that is NOT yet linked to the bank.
    Used by partnership-request mint: minting against an already-linked
    affiliate returns 409 'Partnership request already exists', which then
    cascades into PART-02/03 hitting an already-settled requestId. Picking
    an unlinked affiliate produces a fresh PENDING the canonical bank can
    own. Falls back to None if every active affiliate is already linked.
    """
    if not bank_id:
        return None
    linked = _list_bank_linked_affiliate_ids(bank_id)
    qurl = f"{BASE_URL}/api/v1/affiliates/query"
    qbody = {"page": 1, "pageSize": 100, "filters": {}}
    qresp = execute("POST", qurl, {"Content-Type": "application/json"}, qbody, timeout=20)
    if qresp.get("ok") and qresp.get("status_code") == 200:
        body = qresp.get("body") or {}
        items = body.get("data") or body.get("items") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                status = (item.get("status") or "").upper()
                aid = item.get("affiliateId")
                if (isinstance(aid, str) and aid and aid not in linked
                        and status in ("ACTIVE", "APPROVED")):
                    return aid
    return None


def pre_flight_acquire_partnership_request(pm_idx: dict, session_ids: dict) -> dict:
    """Acquisition order:
      1) Discover an approved affiliateId from /banks/{bankId}/affiliates (bank-linked
         affiliates are approved by construction). Override seeded affiliateId only if
         the discovered one differs and the seeded one fails.
      2) Mint via POST /affiliates/{affiliateId}/bank-partnership-requests.
      3) Fallback to POST /affiliates/partnership-requests/query for an existing PENDING.
    """
    setup = {
        "step": "acquire_seed_partnership_request",
        "method": "POST",
        "endpoint": "/api/v1/affiliates/{affiliateId}/bank-partnership-requests",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "fallback_used": False,
        "query_fallback": None,
    }
    bank_id = session_ids.get("bankId")
    affiliate_id = session_ids.get("affiliateId")
    if not bank_id:
        setup.update({"status": "ERROR",
                      "reason": "no seeded bankId; partnership-request mint requires a bank scope"})
        return setup
    # For mint we need an affiliate NOT already linked to this bank — minting
    # against a linked affiliate returns 409 'Partnership request already
    # exists'. Fall through to bank-linked discovery only if no unlinked
    # candidate exists (mint will then 409 but we still record provenance).
    discovered = discover_unlinked_affiliate_for_bank(bank_id)
    if discovered:
        setup["discovered_unlinked_affiliate_id"] = discovered
        affiliate_id = discovered
    else:
        setup["unlinked_affiliate_search"] = "none_found_all_active_affiliates_already_linked"
        linked_fallback = discover_approved_affiliate_for_bank(bank_id)
        if linked_fallback:
            setup["discovered_affiliate_id"] = linked_fallback
            affiliate_id = linked_fallback
    if affiliate_id and session_ids.get("affiliateId") and session_ids.get("affiliateId") != affiliate_id:
        setup["seeded_affiliate_id_overridden_by_discovery"] = {
            "seeded": session_ids.get("affiliateId"), "used": affiliate_id}
    if not affiliate_id:
        setup.update({"status": "ERROR",
                      "reason": "no approved affiliateId discoverable from bank scope and none seeded"})
        return setup
    pm_entry = pm_idx.get("POST /api/v1/affiliates/{affiliateId}/bank-partnership-requests")
    if not pm_entry:
        setup.update({"status": "ERROR",
                      "reason": "mint endpoint not in Postman; trying query fallback"})
        setup["query_fallback"] = query_fallback_partnership_request(pm_idx, session_ids, bank_id)
        if setup["query_fallback"].get("status") == "OK":
            setup.update({"status": "OK_VIA_QUERY", "fallback_used": True,
                          "request_id": setup["query_fallback"].get("request_id")})
            qf_persist = setup["query_fallback"].get("persistence")
            if isinstance(qf_persist, dict):
                setup["persistence"] = qf_persist
        return setup
    base = build_base_request(pm_entry)
    body = rotate_request_context(base["body"])
    if isinstance(body, dict):
        body["bankId"] = bank_id
        body.setdefault("note", "pre-flight partnership-request seed for bank harness run")
    path_template = get_postman_path_template(pm_entry)
    pv = dict(base["path_vars"])
    pv["affiliateId"] = affiliate_id
    url = rebuild_url(base["method"], path_template, pv, base["query"])
    setup["url"] = url
    setup["request_body"] = body
    response = execute(base["method"], url, base["headers"], body, timeout=30)
    setup["response_status"] = response.get("status_code")
    setup["response_body"] = response.get("body") if response.get("body") is not None else response.get("body_text")
    setup["completed_at"] = dt.datetime.now().isoformat()
    sc = response.get("status_code", 0)
    if response.get("ok") and 200 <= sc < 300:
        rid = extract_first_request_id_recursive(response.get("body"))
        if rid:
            persist = _persist_request_if_verified(rid, bank_id, session_ids, source="mint")
            setup["request_id"] = rid
            setup["persistence"] = persist
            if persist["selected_verified"]:
                setup["status"] = "OK"
                return setup
            setup.update({"status": "MINT_UNVERIFIED",
                          "reason": "mint 2xx returned a requestId but verify GET did not confirm it; trying query fallback",
                          "fallback_used": True})
        else:
            setup.update({"status": "DEGRADED",
                          "reason": f"2xx ({sc}) but requestId not extractable; trying query fallback",
                          "fallback_used": True})
    elif not response.get("ok"):
        setup.update({"status": "ERROR_PRE_FALLBACK",
                      "reason": f"mint transport: {response.get('error')}; trying query fallback",
                      "fallback_used": True})
    else:
        setup.update({"status": "FAIL_PRE_FALLBACK",
                      "reason": f"mint non-2xx ({sc}); trying query fallback",
                      "fallback_used": True})
    setup["query_fallback"] = query_fallback_partnership_request(pm_idx, session_ids, bank_id)
    if setup["query_fallback"].get("status") == "OK":
        setup.update({"status": "OK_VIA_QUERY",
                      "request_id": setup["query_fallback"].get("request_id")})
        qf_persist = setup["query_fallback"].get("persistence")
        if isinstance(qf_persist, dict):
            setup["persistence"] = qf_persist
    else:
        if setup["status"] == "ERROR_PRE_FALLBACK":
            setup["status"] = "ERROR"
        elif setup["status"] == "FAIL_PRE_FALLBACK":
            setup["status"] = "FAIL"
        setup["reason"] = (setup.get("reason", "") +
                          f" | query fallback: {setup['query_fallback'].get('status')} "
                          f"({setup['query_fallback'].get('reason')})")
    return setup


# --- HYBRID: Phase 0d — live suspend/block affiliate pool -----------------
def pre_flight_build_suspend_block_pool(session_ids: dict, pool_size: int = 120) -> dict:
    """Query GET /banks/{bankId}/affiliates for ACTIVE-relationship affiliates.
    Repopulates SUSPEND_POOL and BLOCK_POOL and enables FIXTURE_POOL_BY_ENDPOINT
    routing so each non-mutation TC on suspend/block gets a distinct affiliate.
    Failure is non-fatal: pools stay empty and canonical IDs are used as fallback.
    """
    setup = {
        "step": "build_suspend_block_pool",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "pool_size": 0,
        "affiliate_ids": [],
    }
    # Fix 3: if fixture pools are pre-loaded from bank_fixtures_v2.json, skip the
    # live-probe override so the designated suspend/block split is preserved.
    if SUSPEND_POOL and BLOCK_POOL:
        FIXTURE_POOL_BY_ENDPOINT["POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend"] = SUSPEND_POOL
        FIXTURE_POOL_BY_ENDPOINT["POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/block"] = BLOCK_POOL
        setup.update({
            "status": "OK",
            "pool_size": len(SUSPEND_POOL) + len(BLOCK_POOL),
            "suspend_pool_size": len(SUSPEND_POOL),
            "block_pool_size": len(BLOCK_POOL),
            "source": "fixture_preload (bank_fixtures_v2.json suspend_pool/block_pool)",
            "completed_at": dt.datetime.now().isoformat(),
        })
        return setup
    bank_id = session_ids.get("bankId")
    if not bank_id:
        setup.update({"status": "ERROR", "reason": "no bankId in session"})
        return setup
    url = f"{BASE_URL}/api/v1/banks/{bank_id}/affiliates?pageSize=500"
    resp = execute("GET", url, {"Accept": "application/json"}, None, timeout=20)
    setup["response_status"] = resp.get("status_code")
    if not resp.get("ok") or resp.get("status_code") != 200:
        setup.update({"status": "FAIL",
                      "reason": f"GET /banks/{{bankId}}/affiliates returned {resp.get('status_code')}"})
        return setup
    body = resp.get("body") or {}
    if isinstance(body, list):
        raw_list = body
    elif isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            raw_list = data.get("affiliates") or data.get("items") or []
        elif isinstance(data, list):
            raw_list = data
        else:
            raw_list = body.get("affiliates") or body.get("items") or []
    else:
        raw_list = []
    active_ids: list[str] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        status = (item.get("relationshipStatus") or item.get("status")
                  or item.get("affiliateStatus") or item.get("partnershipStatus") or "").upper()
        # Accept ACTIVE, APPROVED, or missing status (assume active if endpoint returns it).
        if status and status not in ("ACTIVE", "APPROVED"):
            continue
        aid = item.get("affiliateId") or item.get("id")
        if isinstance(aid, str) and aid:
            active_ids.append(aid)
        if len(active_ids) >= pool_size:
            break
    if not active_ids:
        setup.update({"status": "FAIL", "reason": "no ACTIVE affiliates found in GET /banks/{bankId}/affiliates response"})
        return setup
    # Split pool 50/50 so suspend and block each get a non-overlapping set.
    # Sharing the same affiliates causes block to 409 on affiliates already
    # suspended by the suspend endpoint (which runs first).
    mid = len(active_ids) // 2
    suspend_ids = active_ids[:mid] if mid > 0 else active_ids
    block_ids   = active_ids[mid:] if mid < len(active_ids) else active_ids
    suspend_pairs = [(bank_id, aid) for aid in suspend_ids]
    block_pairs   = [(bank_id, aid) for aid in block_ids]
    SUSPEND_POOL.clear()
    SUSPEND_POOL.extend(suspend_pairs)
    BLOCK_POOL.clear()
    BLOCK_POOL.extend(block_pairs)
    FIXTURE_POOL_BY_ENDPOINT["POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/suspend"] = SUSPEND_POOL
    FIXTURE_POOL_BY_ENDPOINT["POST /api/v1/banks/{bankId}/affiliates/{affiliateId}/block"] = BLOCK_POOL
    setup.update({
        "status": "OK",
        "pool_size": len(active_ids),
        "suspend_pool_size": len(suspend_ids),
        "block_pool_size": len(block_ids),
        "affiliate_ids": active_ids,
        "completed_at": dt.datetime.now().isoformat(),
    })
    return setup


# --- HYBRID: Phase 0e — live approve/reject partnership-request pool ------
def pre_flight_build_approve_reject_pool(pm_idx: dict, session_ids: dict,
                                          pool_size: int = 100) -> dict:
    """Build approve/reject pool from PENDING requests on APPROVE_REJECT_BANK_ID.
    Primary path: query existing PENDING_BANK_APPROVAL requests directly (no mint needed).
    Fallback: mint fresh requests against unlinked affiliates on the canonical bank.
    APPROVE_REJECT_BANK_ID is used exclusively here — never mixed into the canonical bankId.
    """
    setup = {
        "step": "build_approve_reject_pool",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "pool_size": 0,
        "minted": [],
        "errors": [],
    }
    bank_id = session_ids.get("bankId")
    if not bank_id:
        setup.update({"status": "ERROR", "reason": "no bankId in session"})
        return setup

    # Phase 0d parity: if fixture pools are pre-loaded, skip the live query so the
    # designated approve/reject split is preserved and UUID IDs from stale Phase 0c
    # sessions can't override fresh bank-internal fixture IDs.
    if APPROVE_POOL and REJECT_POOL:
        setup.update({
            "status": "OK",
            "pool_size": len(APPROVE_POOL) + len(REJECT_POOL),
            "approve_pool_size": len(APPROVE_POOL),
            "reject_pool_size": len(REJECT_POOL),
            "source": "fixture_preload (bank_fixtures_v2.json approve_pool/reject_pool)",
            "completed_at": dt.datetime.now().isoformat(),
        })
        return setup

    # --- Primary: query PENDING requests from the dedicated PENDING bank -----
    # Bank approve/reject endpoints only accept UUID-format requestIds. The affiliate
    # query returns PARTNERSHIP{hex} / PRQC{hex} IDs — those give 404 on the bank side.
    # Filter to UUID format only; if none found, leave the pre-loaded fixture pool intact.
    _UUID_PAT = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
    )
    request_ids: list[str] = []
    if APPROVE_REJECT_BANK_ID:
        pq_url = f"{BASE_URL}/api/v1/affiliates/partnership-requests/query"
        pq_body = {
            "filters": {"bankId": APPROVE_REJECT_BANK_ID, "status": ["PENDING_BANK_APPROVAL"]},
            "page": 1,
            "pageSize": pool_size,
        }
        pq_resp = execute("POST", pq_url, {"Content-Type": "application/json"}, pq_body, timeout=20)
        if pq_resp.get("ok") and 200 <= (pq_resp.get("status_code") or 0) < 300:
            pq_data = pq_resp.get("body") or {}
            pq_items = pq_data.get("data") if isinstance(pq_data.get("data"), list) else []
            for item in pq_items:
                rid = item.get("partnershipRequestId") or item.get("requestId")
                if isinstance(rid, str) and rid and _UUID_PAT.match(rid):
                    request_ids.append(rid)
                if len(request_ids) >= pool_size:
                    break
        setup["pending_bank_query_count"] = len(request_ids)

    if request_ids:
        # All three pools get the full set and rotate. Approve and reject share the
        # same IDs — with few confirmed UUID requestIds, splitting would starve each pool.
        APPROVE_POOL.clear(); APPROVE_POOL.extend(request_ids)
        REJECT_POOL.clear();  REJECT_POOL.extend(request_ids)
        PART01_POOL.clear();  PART01_POOL.extend(request_ids)
        approve_ids = request_ids
        reject_ids  = request_ids
        setup.update({
            "status": "OK",
            "pool_size": len(request_ids),
            "approve_pool_size": len(approve_ids),
            "reject_pool_size": len(reject_ids),
            "source": f"APPROVE_REJECT_BANK_ID={APPROVE_REJECT_BANK_ID}",
            "completed_at": dt.datetime.now().isoformat(),
        })
        return setup

    # No bank-format requestIds from live query — keep the pre-loaded fixture pools.
    # approve_pool and reject_pool are already loaded from bank_fixtures_v2.json with
    # bank-internal APR-xxx / REQ-UBA-xxx IDs that the approve/reject endpoints accept.
    if APPROVE_POOL and REJECT_POOL:
        setup.update({
            "status": "OK",
            "pool_size": len(APPROVE_POOL) + len(REJECT_POOL),
            "approve_pool_size": len(APPROVE_POOL),
            "reject_pool_size": len(REJECT_POOL),
            "source": "fixture_preload (bank-internal IDs from bank_fixtures_v2.json)",
            "completed_at": dt.datetime.now().isoformat(),
        })
        return setup

    # --- Fallback: mint fresh requests against unlinked affiliates -----------
    # APPROVE_REJECT_BANK_ID == CANONICAL_BANK_SEED (33e3bc51); same bank handles
    # both suspend/block (ACTIVE affiliates) and approve/reject (PENDING requests).
    setup["errors"].append(f"PENDING query on {APPROVE_REJECT_BANK_ID} returned 0; falling back to mint")
    pm_entry = pm_idx.get("POST /api/v1/affiliates/{affiliateId}/bank-partnership-requests")
    if not pm_entry:
        setup.update({"status": "ERROR",
                      "reason": "POST /api/v1/affiliates/{affiliateId}/bank-partnership-requests not in Postman"})
        return setup
    mint_bank_id = APPROVE_REJECT_BANK_ID or bank_id
    linked = _list_bank_linked_affiliate_ids(mint_bank_id)
    qurl = f"{BASE_URL}/api/v1/affiliates/query"
    qbody = {"page": 1, "pageSize": 100, "filters": {}}
    qresp = execute("POST", qurl, {"Content-Type": "application/json"}, qbody, timeout=20)
    candidates: list[str] = []
    if qresp.get("ok") and qresp.get("status_code") == 200:
        items = (qresp.get("body") or {})
        items = items.get("data") or items.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = (item.get("status") or "").upper()
            aid = item.get("affiliateId")
            if isinstance(aid, str) and aid and aid not in linked and status in ("ACTIVE", "APPROVED"):
                candidates.append(aid)
    if not candidates:
        setup.update({"status": "FAIL",
                      "reason": "no unlinked ACTIVE affiliates available for partnership-request minting"})
        return setup
    request_ids: list[str] = []
    used: set[str] = set()
    for aff_id in candidates:
        if len(request_ids) >= pool_size:
            break
        if aff_id in used:
            continue
        used.add(aff_id)
        base = build_base_request(pm_entry)
        body = rotate_request_context(base["body"])
        if isinstance(body, dict):
            body["bankId"] = mint_bank_id
            body.setdefault("note", f"pre-flight approve/reject pool item {len(request_ids) + 1}")
        pv = dict(base["path_vars"])
        pv["affiliateId"] = aff_id
        path_template = get_postman_path_template(pm_entry)
        url = rebuild_url(base["method"], path_template, pv, base["query"])
        resp = execute(base["method"], url, base["headers"], body, timeout=30)
        sc = resp.get("status_code", 0)
        if resp.get("ok") and 200 <= sc < 300:
            rid = extract_first_request_id_recursive(resp.get("body"))
            if rid:
                request_ids.append(rid)
                setup["minted"].append({"affiliateId": aff_id, "requestId": rid})
            else:
                setup["errors"].append(f"mint for {aff_id} 2xx but no requestId extractable")
        else:
            setup["errors"].append(f"mint for {aff_id} -> {sc}")
    if not request_ids:
        # All mints failed (likely 409 — existing requests already present on
        # APPROVE_REJECT_BANK_ID). Query all statuses on that bank as last resort.
        # These may be ACTIVE/REJECTED (already processed), meaning happy-path TCs
        # will 409, but validation/mutation TCs will still fire and can pass.
        qurl = f"{BASE_URL}/api/v1/affiliates/partnership-requests/query"
        qbody = {"filters": {"bankId": mint_bank_id}, "page": 1, "pageSize": pool_size}
        qresp = execute("POST", qurl, {"Content-Type": "application/json"}, qbody, timeout=20)
        if qresp.get("ok") and 200 <= (qresp.get("status_code") or 0) < 300:
            qdata = qresp.get("body") or {}
            qitems = qdata.get("data") if isinstance(qdata.get("data"), list) else []
            for item in qitems:
                rid = item.get("partnershipRequestId") or item.get("requestId")
                if isinstance(rid, str) and rid:
                    request_ids.append(rid)
                if len(request_ids) >= pool_size:
                    break
        if not request_ids:
            setup.update({"status": "FAIL",
                          "reason": "no partnership requests successfully minted and query fallback found none",
                          "errors": setup["errors"]})
            return setup
        setup["fallback_note"] = (
            f"used {len(request_ids)} existing requests from {mint_bank_id} (status unknown); "
            "happy-path TCs will fail until backend resets requests to PENDING"
        )
    # Split pool 50/50 so approve and reject each get non-overlapping requestIds.
    # Sharing the same IDs causes reject to 409 on requests already approved
    # (approve endpoint runs first in pack order).
    mid = len(request_ids) // 2
    approve_ids = request_ids[:mid] if mid > 0 else request_ids
    reject_ids  = request_ids[mid:] if mid < len(request_ids) else request_ids
    APPROVE_POOL.clear()
    APPROVE_POOL.extend(approve_ids)
    REJECT_POOL.clear()
    REJECT_POOL.extend(reject_ids)
    setup.update({
        "status": "OK",
        "pool_size": len(request_ids),
        "approve_pool_size": len(approve_ids),
        "reject_pool_size": len(reject_ids),
        "completed_at": dt.datetime.now().isoformat(),
    })
    return setup


# --- HYBRID: post-mint verify (Cluster-C mitigation) ----------------------
def verify_seeded_id_queryable(seed_id: str | None, get_path_template: str,
                               max_retries: int = 2, delay_s: float = 1.0) -> dict:
    """GET on the freshly-minted resource. Retries on 404 with backoff.
    Distinguishes 'eventual consistency' (transient 404 that resolves) from
    'persistence split' (404 that never resolves — Cluster C signature).
    For Bank we use GET /api/v1/banks/{bankId}/affiliates as the cheapest read
    that proves the bankId is recognized by the read pipeline."""
    rec = {"verified": False, "url": None, "status": None, "attempts": 0,
           "cluster_c_suspected": False, "reason": None}
    if not seed_id:
        rec["reason"] = "no seed_id provided"
        return rec
    url = f"{BASE_URL}{get_path_template.replace('{bankId}', seed_id).replace('{affiliateId}', seed_id)}"
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
from probe import probe_get_after_post as _shared_probe

PROBE_MAX_WAIT_S = float(os.environ.get("BANK_PROBE_MAX_WAIT_S", "6.0"))

def probe_get_after_post(resource_id: str | None,
                          primary_path_template: str = "/api/v1/banks/{bankId}/affiliates",
                          secondary_path_template: str = "/api/v2/banks/{bankId}/dashboard",
                          max_retries: int = 2,
                          delay_s: float = 1.0) -> dict:
    return _shared_probe(
        resource_id=resource_id,
        base_url=BASE_URL,
        execute=execute,
        primary_path_template=primary_path_template,
        secondary_path_template=secondary_path_template,
        max_retries=max_retries,
        delay_s=delay_s,
        max_wait_s=PROBE_MAX_WAIT_S,
    )

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


def set_field_force(body: Any, field: str, value: Any) -> Any:
    """Like set_field but creates the field at top level if absent. Used for
    Cluster-D scenarios that exercise contract fields the current DTO does not
    declare (e.g. supportedCurrencies on /admin/banks) — the harness still sends
    the field so the verdict captures whether the backend silently ignores or
    properly rejects the unrecognized input."""
    if not isinstance(body, dict): return body
    body = copy.deepcopy(body)
    if not _find_and_apply(body, field, "set", value):
        body[field] = value
    return body

def classify_scenario(scenario: str, expected: str) -> dict:
    s = scenario.lower()

    # ---- Cluster-D admin/banks (2026-05-04): explicit routes for input-validation
    # and duplicate-detection scenarios that previously fell to BLOCKED. Placed BEFORE
    # the generic blocked-list so e.g. `audit_log_created` (admin/banks-specific
    # follow-up) doesn't get caught by the catch-all `audit_log` rule below.
    if s == "invalid_bank_code_format_rejected":
        return {"action": "set_field", "field": "bankCode", "value": "###BAD!CODE###"}
    if s == "invalid_country_code_rejected":
        return {"action": "set_field", "field": "country", "value": "ZZ"}
    if s == "empty_supported_currencies_rejected":
        return {"action": "set_field_force", "field": "supportedCurrencies", "value": []}
    if s == "invalid_currency_code_rejected":
        return {"action": "set_field_force", "field": "supportedCurrencies", "value": ["ZZZ"]}
    if s == "duplicate_currency_codes_safe":
        return {"action": "set_field_force", "field": "supportedCurrencies", "value": ["NGN", "NGN"]}
    if s == "duplicate_bank_code_rejected":
        return {"action": "as_is", "note": "Postman bankCode matches a previously-minted bank — duplicate-rejection naturally tested. Expected 4xx."}
    if s == "duplicate_institution_id_rejected":
        return {"action": "as_is", "note": "DTO has no separate institutionId; bankCode is the institution identifier in this contract — Postman bankCode duplicates seeded bank. Expected 4xx."}
    if s == "case_insensitive_duplicate_bank_code":
        return {"action": "mint_unique_then_resend_modified", "transform": "uppercase_bankcode"}
    if s == "trimmed_bank_code_duplicate":
        return {"action": "mint_unique_then_resend_modified", "transform": "whitespace_pad_bankcode"}
    if s == "bank_id_generated_unique":
        return {"action": "mint_twice_assert_unique"}
    if s == "audit_log_created":
        return {"action": "mint_then_check_audit_log"}
    if s == "actor_metadata_persisted":
        return {"action": "mint_then_check_audit_log", "assert_field": "actorUserId"}
    if s == "timestamp_metadata_persisted":
        return {"action": "mint_then_check_audit_log", "assert_field": "occurredAt"}
    if s == "partial_failure_no_orphan_bank":
        return {"action": "mint_invalid_then_check_no_orphan"}
    # ---- Bank CTRL/PART explicit branches (2026-05-10) ----
    if s == "invalid_reason_code_rejected":
        return {"action": "set_field", "field": "reasonCode", "value": "BOGUS_REASON_CODE"}
    if s == "case_insensitive_search":
        return {"action": "set_query", "key": "search", "value": "TEST"}
    if s == "duplicate_decision_safe":
        return {"action": "idempotency_double_send"}
    # 2026-05-10 fix (pagination): page_two_success must actually advance to page 2,
    # not as_is (which leaves page=1 and never tests page-2 navigation).
    if s == "page_two_success":
        return {"action": "set_query", "key": "page", "value": "2",
                "note": "advanced to page 2 to actually exercise pagination"}
    if s == "page_one_success":
        return {"action": "set_query", "key": "page", "value": "1",
                "note": "explicit page 1 (canonical happy path)"}

    # ---- Cluster-B audit-log side-effect verification (2026-05-04): generic
    # write-then-check-audit-log pattern. Replaces blanket BLOCKED for audit/
    # actor/timestamp scenarios with a real follow-up GET on the bank's
    # audit-logs endpoint. Works on any pack endpoint that operates within a
    # bank scope (path or session).
    if s in ("audit_log_created_where_required", "audit_log_created"):
        return {"action": "write_then_check_audit_log"}
    if s in ("actor_metadata_recorded", "actor_metadata_captured",
             "actor_recorded"):
        return {"action": "write_then_check_audit_log", "assert_field": "actorUserId"}
    if s in ("timestamp_recorded", "decision_timestamp_captured",
             "decision_timestamp_recorded"):
        return {"action": "write_then_check_audit_log", "assert_field": "occurredAt"}

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
        "physical_card_status_personalizing", "virtual_card_status_active",
        "card_provisioning_event_emitted", "card_event_published",
        "card_lifecycle_event_created", "transaction_record_created",
        "fulfillment_provider_called", "fulfillment_callback_received",
        # Bank suspend/block + partnerships DB-verify scenarios (added 2026-05-10)
        "completion_confirmed", "relationship_status_updated",
        "only_bank_scoped_cards_selected",
        "partial_cascade_failure_retried", "partial_cascade_result_reported",
        "bank_queue_updated", "affiliate_view_updated",
        "issuance_eligibility_enabled_on_approval",
        "issuance_eligibility_not_enabled_on_rejection",
        # Bare "status_updated" (PART-02/03) — DB-side check, distinct from "_history_*"
        "status_updated",
    )):
        return {"action": "blocked", "reason": "Skipped — this test wants to confirm something happened in the database (or wants a follow-up call to verify), and our HTTP-only runner can't see inside the database"}
    # Idempotency: send the same request twice, verdict on response equivalence
    if any(k in s for k in (
        "_idempotent_on_retry", "session_idempotent",
        "idempotency", "repeated_reads_consistent",
    )):
        return {"action": "idempotency_double_send"}
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
        # Bank PART-02/03 + CTRL state-dependent scenarios (added 2026-05-10)
        "request_outside_bank_scope_rejected",
        "inactive_affiliate_decision_rejected",
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
        "service_provider_write_rejected",
        "bank_user_rejected", "bank_user_cannot", "bank_user_write_rejected",
        "bank_write_rejected_or_policy",
        # Bank CTRL non-bank role scenarios (added 2026-05-10)
        "non_bank_role_rejected",
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
                 "read_only_no_mutation",
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
        )):
        return {"action": "as_is", "note": "response-shape/optional-input scenario; sending happy-path Postman request as-is"}

    # ---- 3. mutation patterns ----
    # missing field
    m = re.search(r"(?:^|_)missing_(.+?)(?:_rejected|_blocks|$)", s)
    if m:
        raw = m.group(1)
        if raw == "request_context": return {"action": "as_is", "note": "REQUEST-CONTEXT MISSING — Postman collection contains no request-context headers; sending as-is matches scenario intent. 4xx = enforced; 2xx = not enforced"}
        if raw == "request_id" or raw == "idempotency_key" or raw == "tenant_id" or raw == "actor_user_id":
            return {"action": "drop_field", "field": snake_to_camel(raw)}
        if raw == "affiliate_id":
            return {"action": "drop_field", "field": "affiliateId"}
        if raw == "bank_id":
            return {"action": "drop_field", "field": "bankId"}
        if raw == "card_id":
            return {"action": "blocked", "reason": "Skipped — this test wants the URL to be missing the cardId path piece; can't simulate without changing URL shape"}
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

    # malformed id (path or body)
    m = re.search(r"malformed_(.+?)(?:_rejected|$)", s)
    if m:
        raw = m.group(1)
        if raw == "json":
            return {"action": "raw_invalid_json"}
        if raw in ("card_id", "bank_id", "affiliate_id", "limit_request_id", "request_id"):
            return {"action": "set_path_var", "field": snake_to_camel(raw), "value": "not-a-valid-uuid-!@#"}
        return {"action": "set_field", "field": snake_to_camel(raw), "value": "not-a-valid-uuid-!@#"}

    # bogus path-var id (syntactically invalid, not merely unknown)
    if s == "bogus_request_id_rejected":
        return {"action": "set_path_var", "field": "requestId", "value": "BOGUS-MISSING-REQ-000"}

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
        return {"action": "set_field", "field": "amount", "value": 0.001}
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
    if s == "negative_page_value_rejected" or s == "negative_page_rejected": return {"action": "set_query", "key": "page", "value": "-1"}
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
    # 2026-05-10 fix (Bug A/D): match against `scenario` (original case) instead of
    # `s` (lowercased) so field names preserve camelCase. Without this, mutations
    # used lowercase keys like `daterange` which .NET rejects as case-sensitive
    # unknown query params, causing false silent-accept FAILs.
    m = re.match(r"^invalid_(\w+?)_filter_rejected$", scenario)
    if m:
        raw = m.group(1)  # camelCase preserved
        # query-param mutations
        if raw.endswith("Range") or "date" in raw.lower():
            return {"action": "set_query", "key": raw, "value": "not-a-range"}
        return {"action": "set_field", "field": raw, "value": "BOGUS_VALUE_XYZ"}
    if s == "invalid_date_range_rejected":
        return {"action": "set_query_pair", "values": {"fromDate": "not-a-date", "toDate": "also-bad"}}
    if s == "multiple_filters_and_semantics":
        return {"action": "as_is", "note": "multi-filter semantics test; happy path with current Postman filters"}

    # success / happy paths (after specific patterns)
    if any(k in s for k in ("_success", "_safe", "_accepted", "_handled", "_well_formed")):
        return {"action": "as_is", "note": "happy-path or accepting variant; sent Postman request as-is"}
    if s.startswith("issue_virtual") or s.startswith("issue_physical") or s.startswith("issue_card_"):
        return {"action": "as_is", "note": "alternative happy-path variant; Postman provides one variant"}

    # fallback
    return {"action": "blocked", "reason": f"Skipped — the test case scenario '{scenario}' uses a name our automated test-builder doesn't recognize, so we couldn't tell what change to make to the request. Rather than guess and report a wrong answer, we skipped it"}

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
    started = dt.datetime.now().isoformat()
    t0 = time.perf_counter()
    # HTTP-spec correctness: GET (and HEAD/DELETE) requests should not carry a body.
    # Backend complaints (2026-05-06) flagged GET endpoints receiving body fields like
    # "filterHandled" — strip body unconditionally on bodyless verbs to prevent
    # false-positive failures that test the request shape rather than business logic.
    if method.upper() in ("GET", "HEAD", "DELETE"):
        body = None
    try:
        if body is None:
            resp = requests.request(method, url, headers=headers, timeout=timeout)
        elif isinstance(body, str):
            resp = requests.request(method, url, headers=headers, data=body, timeout=timeout)
        else:
            h = dict(headers)
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
        }
    except requests.exceptions.RequestException as ex:
        return {
            "ok": False,
            "started_at": started,
            "error": f"{type(ex).__name__}: {ex}",
            "elapsed_seconds": round(time.perf_counter() - t0, 4),
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
    actual = response["status_code"]
    schema_finding = None
    if response.get("body") is not None:
        sf = VALIDATOR.validate_response(request_summary["method"], request_summary["path"], actual, response["body"])
        if sf:
            schema_finding = {"valid": sf.valid, "errors": sf.errors}
    status_match = status_in_expected(actual, expected_codes) if expected_codes else None
    if expected_codes:
        if status_match:
            if schema_finding and not schema_finding["valid"]:
                return {"status": "FAIL",
                        "reason": f"status {actual} matched expected {expected_codes}, but response schema invalid: {schema_finding['errors'][:3]}",
                        "schema": schema_finding}
            family_note = ""
            if actual not in expected_codes and actual in CLIENT_ERROR_FAMILY and any(c in CLIENT_ERROR_FAMILY for c in expected_codes):
                family_note = " (client-error family equivalence: 400/404/405/409/422 treated as interchangeable)"
            return {"status": "PASS",
                    "reason": f"status {actual} in expected {expected_codes}{family_note}",
                    "schema": schema_finding}
        return {"status": "FAIL",
                "reason": f"expected status in {expected_codes}, got {actual}",
                "schema": schema_finding}
    if 200 <= actual < 300:
        if schema_finding and not schema_finding["valid"]:
            return {"status": "FAIL", "reason": f"2xx but schema invalid: {schema_finding['errors'][:3]}", "schema": schema_finding}
        return {"status": "PASS", "reason": f"2xx ({actual}); no parseable expected codes", "schema": schema_finding}
    return {"status": "FAIL", "reason": f"non-2xx ({actual}); no parseable expected codes", "schema": schema_finding}

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

# --- main ------------------------------------------------------------------
def main():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    pm_idx = postman_index()
    with open(TEST_PACK_PATH, "r", encoding="utf-8") as f:
        pack = json.load(f)

    # --- HYBRID phase 0: load session + pre-flight provision bank ---
    session_ids = SESSION.load()
    print(f"Phase 0: pre-flight bank provision (mint -> query fallback)...")
    setup_record = pre_flight_provision_bank(pm_idx, session_ids)
    qf = setup_record.get("query_fallback")
    qf_status = qf.get("status") if isinstance(qf, dict) else None
    print(f"  -> mint_status={setup_record.get('status')} bankId={session_ids.get('bankId')!r} "
          f"fallback_used={setup_record.get('fallback_used')} query_fallback={qf_status}")
    if not session_ids.get("bankId"):
        print(f"ERROR: no bankId available (pre-flight failed and SessionStore empty); aborting")
        sys.exit(2)

    # --- HYBRID phase 0b: verify the seeded bankId is queryable (Cluster-C mitigation) ---
    print(f"Phase 0b: verifying seeded bankId is queryable via GET /api/v1/banks/{{bankId}}/affiliates...")
    verify_record = verify_seeded_id_queryable(session_ids.get("bankId"), "/api/v1/banks/{bankId}/affiliates")
    print(f"  -> verified={verify_record['verified']} attempts={verify_record['attempts']} cluster_c_suspected={verify_record['cluster_c_suspected']}")
    setup_record["post_mint_verify"] = verify_record

    # --- HYBRID phase 0c: acquire fresh partnership-request for approve/reject TCs ---
    # Reused requestIds return 409 once settled. Mint a PENDING request per run
    # (fallback to query for an existing PENDING) so partnership tests get a
    # fresh subject. Failure here is non-fatal — tests will fall back to the
    # Postman literal requestId and the Cluster-C/409 reclassification handles
    # downstream verdicts.
    print(f"Phase 0c: acquiring partnership-request seed (mint -> query fallback)...")
    request_setup = pre_flight_acquire_partnership_request(pm_idx, session_ids)
    qf_r = request_setup.get("query_fallback")
    qf_r_status = qf_r.get("status") if isinstance(qf_r, dict) else None
    print(f"  -> request_status={request_setup.get('status')} requestId={session_ids.get('requestId')!r} "
          f"fallback_used={request_setup.get('fallback_used')} query_fallback={qf_r_status}")

    # --- HYBRID phase 0d: build suspend/block affiliate pool (live query) ----
    # Each suspend/block TC needs a distinct ACTIVE affiliate or it gets 409
    # "already in target state" from prior runs. Query live affiliates and
    # rotate one per TC. Failure is non-fatal; pool stays empty and canonical
    # IDs are used as before.
    print(f"Phase 0d: building suspend/block affiliate pool (GET /banks/{{bankId}}/affiliates)...")
    sb_pool_record = pre_flight_build_suspend_block_pool(session_ids)
    print(f"  -> status={sb_pool_record.get('status')} pool_size={sb_pool_record.get('pool_size')}")

    # --- HYBRID phase 0e: build approve/reject partnership-request pool ------
    # Each approve/reject TC needs a distinct PENDING requestId — once approved
    # or rejected a requestId returns 409 on any subsequent action. Mint a fresh
    # pool of PENDING requests against unlinked affiliates. Failure is non-fatal;
    # pool stays at whatever Phase 0c provided.
    print(f"Phase 0e: building approve/reject partnership-request pool (minting up to 20)...")
    ar_pool_record = pre_flight_build_approve_reject_pool(pm_idx, session_ids)
    print(f"  -> status={ar_pool_record.get('status')} pool_size={ar_pool_record.get('pool_size')}")

    # Phase 0c fallback: if acquire_seed_partnership_request failed but Phase 0e
    # filled APPROVE_POOL with fresh PENDING IDs, seed session_ids["requestId"]
    # from that pool so PART-01 fallback substitution has a valid ID.
    if request_setup.get("status") not in ("OK", "OK_VIA_QUERY") and APPROVE_POOL:
        session_ids["requestId"] = APPROVE_POOL[0]
        request_setup["status"] = "OK_VIA_APPROVE_POOL"
        request_setup["fallback_from"] = "phase_0e_approve_pool"
        print(f"  -> Phase 0c backfilled from APPROVE_POOL: requestId={session_ids['requestId']!r}")

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

    pack_endpoints_iter = pack["endpoints"]
    if SCOPE_API_IDS:
        pack_endpoints_iter = [e for e in pack_endpoints_iter if e.get("api_id") in SCOPE_API_IDS]
        if not pack_endpoints_iter:
            print(f"ERROR: SCOPE_API_IDS {SCOPE_API_IDS} matched no endpoints in test pack")
            sys.exit(2)
    if SCOPE_ENDPOINT:
        pack_endpoints_iter = [e for e in pack_endpoints_iter if e["endpoint"] == SCOPE_ENDPOINT]
        if not pack_endpoints_iter:
            print(f"ERROR: SCOPE_ENDPOINT '{SCOPE_ENDPOINT}' not found in test pack")
            sys.exit(2)
    if _replay_failed_set:
        # Keep only endpoints that have at least one TC in the replay set.
        # Trim each endpoint's test_cases list to only the failed scenarios.
        filtered_eps = []
        for e in pack_endpoints_iter:
            aid = e["api_id"]
            tcs = [t for t in e["test_cases"] if (aid, t.get("scenario", "")) in _replay_failed_set]
            if tcs:
                filtered_eps.append({**e, "test_cases": tcs})
        pack_endpoints_iter = filtered_eps
        total_replay = sum(len(e["test_cases"]) for e in pack_endpoints_iter)
        print(f"[REPLAY] Scoped to {len(pack_endpoints_iter)} endpoints, {total_replay} TCs")

    if SCOPE_TC_IDS:
        filtered_eps = []
        for e in pack_endpoints_iter:
            tcs = [t for t in e["test_cases"] if t.get("tc_id") in SCOPE_TC_IDS]
            if tcs:
                filtered_eps.append({**e, "test_cases": tcs})
        pack_endpoints_iter = filtered_eps
        total_tc = sum(len(e["test_cases"]) for e in pack_endpoints_iter)
        print(f"[SCOPE_TC_IDS] Scoped to {len(pack_endpoints_iter)} endpoint(s), {total_tc} TC(s): {sorted(SCOPE_TC_IDS)}")

    for ep in pack_endpoints_iter:
        pack_ep = ep["endpoint"]
        api_id = ep["api_id"]
        pm_key = PACK_TO_POSTMAN.get(pack_ep)
        pm_entry = pm_idx.get(pm_key) if pm_key else None
        # Postman-key fallback: when the Postman entry exists under a different
        # method than swagger/pack declare (e.g. /banks/query keyed as GET when
        # backend is POST), try the override key. The pack's declared method
        # is force-applied below so the request goes out on the correct verb.
        if not pm_entry and pack_ep in POSTMAN_KEY_OVERRIDE:
            override_key = POSTMAN_KEY_OVERRIDE[pack_ep]
            pm_entry = pm_idx.get(override_key)
            if pm_entry:
                drift_findings.append({
                    "api_id": api_id, "pack_endpoint": pack_ep,
                    "postman_endpoint": override_key,
                    "drift_type": "postman_method_override",
                    "applied_method": pack_ep.split(" ", 1)[0],
                })
                pm_key = override_key
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
        # Force-apply the pack-declared HTTP verb when the Postman entry was
        # registered under a different method (POSTMAN_KEY_OVERRIDE case).
        # Pack endpoint string is "<METHOD> <path>"; first token is authoritative.
        pack_method = pack_ep.split(" ", 1)[0]
        if base["method"] != pack_method:
            base["method"] = pack_method
        # Provide a swagger-valid default body for endpoints whose Postman entry
        # carries no body (e.g. /banks/query keyed as GET in Postman, no payload).
        if base["body"] is None and pack_ep in POSTMAN_BODY_DEFAULT:
            base["body"] = copy.deepcopy(POSTMAN_BODY_DEFAULT[pack_ep])
        # When POSTMAN_KEY_OVERRIDE flipped the method, clear query string from
        # the Postman entry — its query params belonged to the original verb
        # (typically GET) and don't apply to the forced verb (typically POST).
        # Per-TC mutations route filter/pagination into body for POST endpoints.
        if pack_ep in POSTMAN_KEY_OVERRIDE:
            base["query"] = {}
        path_template = get_postman_path_template(pm_entry)
        # Override path when pack endpoint diverges from Postman entry (e.g., dashboard v1->v2)
        if pack_ep in PATH_TEMPLATE_OVERRIDE:
            path_template = PATH_TEMPLATE_OVERRIDE[pack_ep]
            drift_findings.append({"api_id": api_id, "pack_endpoint": pack_ep,
                                   "postman_endpoint": pm_key, "drift_type": "path_overridden_to_match_pack",
                                   "applied_template": path_template})

        print(f"  {api_id} {pack_ep} ({len(ep['test_cases'])} TCs)")
        for tc in ep["test_cases"]:
            scenario = tc.get("scenario", "")
            plan = classify_scenario(scenario, tc.get("expected_result", ""))
            evidence_path = EVIDENCE_DIR / f"{tc['tc_id']}.json"

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

            if plan["action"] == "blocked":
                detailed.append({**tc_base, "execution_status": "BLOCKED", "blocked_reason": plan["reason"]})
                counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1
                continue

            # --- HYBRID per-TC: rotate request context, then inject seeded path vars ---
            method = base["method"]
            body_after_rotation = rotate_request_context(base["body"]) if isinstance(base["body"], dict) else copy.deepcopy(base["body"])
            allow_seed_substitution = plan["action"] not in ("set_path_var", "unknown_id")

            # --- Per-TC requestId override (hardcoded fresh IDs) ---
            # When a TC is in TC_REQUEST_ID_OVERRIDE, pin its requestId directly and skip
            # pool routing. Override only fires when allow_seed_substitution is True so
            # mutation TCs still keep their intentionally-bad values.
            _tc_id_override = TC_REQUEST_ID_OVERRIDE.get(tc["tc_id"])
            # --- Strict per-endpoint pool routing ---
            # Each endpoint draws only from its own designated pool in ENDPOINT_POOL_REGISTRY.
            # Cross-endpoint borrowing is not possible — the registry has one entry per endpoint.
            # For non_pending/duplicate scenarios, ENDPOINT_SETTLED_POOL_REGISTRY is used instead;
            # CTRL and PART-01 have no settled pool (those scenarios are not in their packs).
            # Pool item types:
            #   CTRL-01/02 → (bankId, affiliateId) tuple  → injected into path_vars directly
            #   PART-01/02/03 → requestId string           → injected into path_vars directly
            # Mutation scenarios (allow_seed_substitution=False) skip pool entirely — the
            # mutation engine (set_path_var / unknown_id) provides the intentionally-bad value.
            _ep_pool = ENDPOINT_POOL_REGISTRY.get(pack_ep)
            _pool_item = None
            if _tc_id_override and allow_seed_substitution:
                # Override already set session_ids["requestId"] above — treat it as the pool item
                # so downstream injection (path_vars) picks it up correctly.
                _pool_item = _tc_id_override
            elif _ep_pool is not None and allow_seed_substitution:
                _is_settled = ("duplicate_decision" in scenario
                               or "duplicate_request_id" in scenario
                               or "non_pending_request" in scenario)
                if _is_settled:
                    _s_pool = ENDPOINT_SETTLED_POOL_REGISTRY.get(pack_ep)
                    if _s_pool:
                        _pool_item = _s_pool[0]; _s_pool.rotate(-1)
                    else:
                        # Endpoint has no settled pool (CTRL/PART-01) — use regular pool.
                        _pool_item = _ep_pool[0]; _ep_pool.rotate(-1)
                else:
                    if not _ep_pool:
                        detailed.append({**tc_base, "execution_status": "BLOCKED",
                                         "blocked_reason": f"Pool exhausted for {pack_ep} — no IDs remaining in designated pool"})
                        counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1; continue
                    _pool_item = _ep_pool[0]; _ep_pool.rotate(-1)

            # Inject pool item directly into path_vars (no session_ids intermediary).
            if _pool_item is not None:
                if isinstance(_pool_item, tuple):
                    # CTRL endpoints: (bankId, affiliateId)
                    _fx_bank, _fx_aff = _pool_item
                    session_ids["affiliateId"] = _fx_aff
                    session_ids["bankId"] = _fx_bank
                elif isinstance(_pool_item, str):
                    # PART endpoints: requestId string
                    session_ids["requestId"] = _pool_item

            path_vars = inject_seeded_path_vars(base["path_vars"], session_ids, allow_seed_substitution)

            # PART-01: Postman entry has a literal URL (no {placeholders}), so path_vars
            # comes back empty from inject_seeded_path_vars. Explicitly seed bankId and
            # requestId from pool item already loaded into session_ids above.
            if (pack_ep == "GET /api/v1/banks/{bankId}/affiliate-partnership-requests/{requestId}"
                    and allow_seed_substitution and APPROVE_REJECT_BANK_ID):
                path_vars["bankId"] = APPROVE_REJECT_BANK_ID
                if session_ids.get("requestId"):
                    path_vars["requestId"] = session_ids["requestId"]

            # CTRL-01/02: Postman may have a literal affiliateId — overwrite with pool value.
            if _pool_item is not None and isinstance(_pool_item, tuple) and allow_seed_substitution:
                _fx_bank, _fx_aff = _pool_item
                path_vars["affiliateId"] = _fx_aff
                path_vars["bankId"] = _fx_bank
            # Inject required RequestContext fields the Postman base omits but the
            # backend enforces (CTRL-01: affiliateId; CTRL-02: affiliateId+tenantId).
            # Runs AFTER rotate (so rotated requestId/idempotencyKey survive) and
            # BEFORE mutation (so missing_X scenarios can still drop the field).
            # setdefault preserves any value the Postman base or rotation already set.
            rc_fields = CANONICAL_REQUEST_CONTEXT_INJECTION.get(pack_ep)
            if rc_fields and isinstance(body_after_rotation, dict):
                rc = body_after_rotation.get("requestContext")
                if isinstance(rc, dict):
                    if "affiliateId" in rc_fields:
                        aid = path_vars.get("affiliateId") or session_ids.get("affiliateId")
                        if aid:
                            rc.setdefault("affiliateId", aid)
                    if "tenantId" in rc_fields:
                        rc.setdefault("tenantId", DEFAULT_TENANT_ID)
                # Inject top-level idempotencyKey when the endpoint requires it
                # at body root (not nested in requestContext). /suspend Postman
                # body only has it nested; backend validates it at the top level.
                if "top_level_idem" in rc_fields and plan["action"] not in ("set_field", "drop_field"):
                    body_after_rotation.setdefault("idempotencyKey", str(uuid.uuid4()))
                rc = body_after_rotation.get("requestContext")
                # 2026-05-11: ensure rc.bankId always matches URL path_vars.
                # New Postman bodies carry a hardcoded bankId inside
                # requestContext (000045f9-...). If a different bank is
                # selected via path_vars (e.g. fixture rotation, query
                # fallback), the URL/rc mismatch would cause backend to
                # reject the request. Overwrite — don't setdefault — so the
                # URL bank wins. Skipped when the scenario is mutating
                # bankId on purpose (set_path_var / unknown_id), so
                # negative tests retain their intentionally-bad value.
                if isinstance(rc, dict) and "bankId" in rc and plan["action"] not in ("set_path_var", "unknown_id"):
                    url_bank = path_vars.get("bankId")
                    if url_bank:
                        rc["bankId"] = url_bank
            query = dict(base["query"])
            body = body_after_rotation
            mutation_note = None
            override_headers = dict(base["headers"])

            if plan["action"] == "as_is":
                mutation_note = plan.get("note", "no mutation; sent Postman request as-is")
            elif plan["action"] == "drop_field":
                body = drop_field(body, plan["field"])
                mutation_note = f"dropped body field '{plan['field']}'"
            elif plan["action"] == "set_field":
                # 2026-05-10 fix (Bug C/E): if body has no match (e.g. GET endpoint
                # with no body, or filter not present in body), fall back to query
                # string mutation with camelCase preserved. Previously this was a
                # silent no-op causing false silent-accept FAILs.
                f = plan["field"]
                v = plan["value"]
                applied_in_body = False
                if isinstance(body, dict) and body:
                    body_before = json.dumps(body, sort_keys=True, default=str)
                    body = set_field(body, f, v)
                    if json.dumps(body, sort_keys=True, default=str) != body_before:
                        applied_in_body = True
                if applied_in_body:
                    mutation_note = f"set body field '{f}' to {v!r}"
                else:
                    body, query, mutation_note = smart_set_query(method, body, query, f, v)
                    mutation_note = (f"set query '{f}={v!r}' (set_field fallback — "
                                     f"body had no '{f}' field to mutate)")
            elif plan["action"] == "set_field_force":
                body = set_field_force(body, plan["field"], plan["value"])
                mutation_note = f"set body field '{plan['field']}' to {plan['value']!r} (created if absent)"
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
                    # Cluster-A redirect (2026-05-04): if the URL has no path-vars but the
                    # pack endpoint moved this scope into a body filter (e.g., cards/query
                    # bankId now lives in filters.bankId), mutate the body filter instead
                    # of blocking. Preserves the negative-test intent.
                    redirected = False
                    rules = BODY_SCOPE_INJECTION.get(pack_ep) or []
                    for parent, field, session_key in rules:
                        if session_key.lower() == plan["field"].lower():
                            if not isinstance(body, dict):
                                body = {}
                            body = copy.deepcopy(body)
                            container = body.setdefault(parent, {})
                            if isinstance(container, dict):
                                container[field] = plan["value"]
                                mutation_note = (f"redirected set_path_var '{plan['field']}' "
                                                 f"to body filter '{parent}.{field}' = {plan['value']!r} "
                                                 f"(URL has no path var; scope moved to body)")
                                redirected = True
                                break
                    if not redirected:
                        detailed.append({**tc_base, "execution_status": "BLOCKED",
                                         "blocked_reason": f"Skipped — this test wants to put an invalid value in a URL field called '{plan['field']}', but the URL has no path variables"})
                        counts["BLOCKED"] += 1; ep_counts["BLOCKED"] += 1; continue
            elif plan["action"] == "wrong_content_type":
                override_headers["Content-Type"] = "text/plain"
                mutation_note = "set Content-Type to text/plain"
            elif plan["action"] == "empty_body":
                body = {}
                mutation_note = "sent empty body {}"
            elif plan["action"] == "set_query":
                body, query, mutation_note = smart_set_query(method, body, query, plan["key"], plan["value"])
            elif plan["action"] == "set_query_pair":
                body, query, mutation_note = smart_set_query_pair(method, body, query, plan["values"])
            elif plan["action"] == "raw_invalid_json":
                body = "{not-json"
                override_headers.setdefault("Content-Type", "application/json")
                mutation_note = "sent raw invalid JSON"
            elif plan["action"] == "duplicate_array":
                f = plan["field"]
                if isinstance(body, dict) and f in body and isinstance(body[f], list) and body[f]:
                    body = copy.deepcopy(body)
                    body[f] = body[f] + [body[f][0]]
                    mutation_note = f"duplicated first element of '{f}'"
                else:
                    # Engine fallback (2026-05-10): when field isn't a non-empty list,
                    # downgrade to idempotency_double_send (semantically: "send the same
                    # request twice and check it's safe"). Used to BLOCK; now exercises
                    # the endpoint instead so we capture real signal.
                    plan = {"action": "idempotency_double_send"}
                    mutation_note = (f"duplicate_array fallback — '{f}' is not a non-empty list; "
                                     f"running idempotency double-send instead")
            elif plan["action"] == "unknown_id":
                f = plan.get("field")
                applied = False
                if f and isinstance(body, dict):
                    candidate = copy.deepcopy(body)
                    if _find_and_apply(candidate, f, "set", ZERO_UUID):
                        body = candidate
                        mutation_note = f"set body '{f}' (deep) to zero-UUID"
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
                        path_vars[target] = ZERO_UUID
                        mutation_note = f"set path var '{target}' to zero-UUID"
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

            # Cluster-A: inject seeded bankId into body filter for endpoints whose
            # new contract moved scope from path to body (e.g., cards/query).
            body = inject_body_scope(pack_ep, body, session_ids, allow_seed_substitution)

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
                # Step 2: chain a read on the bank — GET /api/v1/banks/{bankId}/affiliates is the
                # most universally meaningful follow-up for bank-scoped writes
                read_bank_id = (path_vars.get("bankId") or session_ids.get("bankId"))
                read_url = f"{BASE_URL}/api/v1/banks/{read_bank_id}/affiliates" if read_bank_id else None
                if read_url:
                    read_resp = execute("GET", read_url, {"Accept": "application/json"}, None)
                else:
                    read_resp = {"ok": False, "error": "no bankId available for read-after-write chain"}
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
            elif plan["action"] == "sla_check":
                response = execute(method, url, override_headers, body)
                threshold = plan.get("threshold_seconds", 2.0)
                elapsed = response.get("elapsed_seconds", 999)
                response["_sla"] = {"threshold_seconds": threshold, "actual_seconds": elapsed, "within_sla": elapsed <= threshold}
                mutation_note = (mutation_note or "") + f" | SLA check: {elapsed}s vs {threshold}s threshold"
            elif plan["action"] == "mint_unique_then_resend_modified":
                # Cluster-D (2026-05-04): mint a brand-new bank with an alphanumeric
                # bankCode so we have a controlled fixture, then resend with the
                # bankCode transformed (uppercase / whitespace-padded) to verify
                # backend normalization rejects the duplicate.
                fresh_code = "BNK-CD-" + uuid.uuid4().hex[:10].upper()
                first_body = copy.deepcopy(body) if isinstance(body, dict) else {}
                if isinstance(first_body, dict):
                    first_body = set_field(first_body, "bankCode", fresh_code)
                first_resp = execute(method, url, override_headers, first_body)
                transform = plan.get("transform", "identity")
                if transform == "uppercase_bankcode":
                    duplicate_code = fresh_code.upper()  # already upper; harmless no-op for digits, but for our hex string flips letters
                    duplicate_code_alt = fresh_code.lower()  # ensure case differs from fresh_code
                    duplicate_code = duplicate_code_alt if duplicate_code == fresh_code else duplicate_code
                elif transform == "whitespace_pad_bankcode":
                    duplicate_code = "  " + fresh_code + "  "
                else:
                    duplicate_code = fresh_code
                second_body = copy.deepcopy(body) if isinstance(body, dict) else {}
                if isinstance(second_body, dict):
                    second_body = set_field(second_body, "bankCode", duplicate_code)
                # rotate request context on second so idempotency keys differ
                second_body = rotate_request_context(second_body) if isinstance(second_body, dict) else second_body
                second_resp = execute(method, url, override_headers, second_body)
                response = second_resp
                response["_duplicate_check"] = {
                    "first_bankCode": fresh_code,
                    "first_status": first_resp.get("status_code"),
                    "second_bankCode_transformed": duplicate_code,
                    "second_status": second_resp.get("status_code"),
                    "transform": transform,
                    "first_ok": bool(first_resp.get("ok") and first_resp.get("status_code") and 200 <= first_resp.get("status_code") < 300),
                    "second_rejected": bool(second_resp.get("status_code") and 400 <= second_resp.get("status_code") < 500),
                }
                mutation_note = (mutation_note or "") + (
                    f" | minted with '{fresh_code}' ({first_resp.get('status_code')}); "
                    f"resent with '{duplicate_code}' ({second_resp.get('status_code')}); "
                    f"normalization-rejected={response['_duplicate_check']['second_rejected']}")
            elif plan["action"] == "mint_twice_assert_unique":
                # Cluster-D: mint two banks with different unique bankCodes, assert
                # the returned bankIds differ.
                code_a = "BNK-CDU1-" + uuid.uuid4().hex[:8].upper()
                code_b = "BNK-CDU2-" + uuid.uuid4().hex[:8].upper()
                body_a = set_field(copy.deepcopy(body), "bankCode", code_a) if isinstance(body, dict) else body
                body_b = set_field(rotate_request_context(copy.deepcopy(body)), "bankCode", code_b) if isinstance(body, dict) else body
                resp_a = execute(method, url, override_headers, body_a)
                resp_b = execute(method, url, override_headers, body_b)
                bid_a = extract_bank_id_from_response(resp_a.get("body"))
                bid_b = extract_bank_id_from_response(resp_b.get("body"))
                response = resp_b
                response["_uniqueness"] = {
                    "first_bankCode": code_a, "first_status": resp_a.get("status_code"), "first_bankId": bid_a,
                    "second_bankCode": code_b, "second_status": resp_b.get("status_code"), "second_bankId": bid_b,
                    "ids_distinct": bool(bid_a and bid_b and bid_a != bid_b),
                }
                mutation_note = (mutation_note or "") + f" | minted twice; bankIds distinct={response['_uniqueness']['ids_distinct']}"
            elif plan["action"] == "mint_then_check_audit_log":
                # Cluster-D / Cluster-B-style: mint a bank, then GET its audit-logs
                # and assert the latest entry exists (and optionally has a specific
                # field populated). This is the side-effect verification pattern.
                fresh_code = "BNK-CDA-" + uuid.uuid4().hex[:10].upper()
                mint_body = set_field(copy.deepcopy(body), "bankCode", fresh_code) if isinstance(body, dict) else body
                mint_resp = execute(method, url, override_headers, mint_body)
                response = mint_resp
                bid = extract_bank_id_from_response(mint_resp.get("body"))
                audit_url = f"{BASE_URL}/api/v1/banks/{bid}/audit-logs" if bid else None
                audit_resp = execute("POST", audit_url, {"Accept": "application/json", "Content-Type": "application/json"},
                                     {"pagination": {"page": 1, "pageSize": 50}}, timeout=15) if audit_url else {"ok": False, "error": "no bankId"}
                logs = []
                if isinstance(audit_resp.get("body"), dict):
                    logs = audit_resp["body"].get("logs") or []
                assert_field = plan.get("assert_field")
                field_present = False
                latest_entry = logs[0] if logs else None
                if assert_field and isinstance(latest_entry, dict):
                    v = latest_entry.get(assert_field)
                    field_present = isinstance(v, str) and bool(v.strip()) if isinstance(v, str) else v is not None
                response["_audit_check"] = {
                    "bankCode": fresh_code,
                    "mint_status": mint_resp.get("status_code"),
                    "bankId": bid,
                    "audit_url": audit_url,
                    "audit_status": audit_resp.get("status_code") if isinstance(audit_resp, dict) else None,
                    "log_count": len(logs),
                    "asserted_field": assert_field,
                    "asserted_field_present": field_present if assert_field else None,
                }
                mutation_note = (mutation_note or "") + (
                    f" | minted bank {bid}; audit-logs status={response['_audit_check'].get('audit_status')}; "
                    f"log_count={len(logs)}"
                    + (f"; {assert_field}_present={field_present}" if assert_field else ""))
            elif plan["action"] == "write_then_check_audit_log":
                # Cluster-B (2026-05-04): execute the primary write, then fetch
                # audit-logs scoped to the bank in question and assert a recent
                # entry exists (optionally with a specific field populated).
                # Bank scope resolution order: path_vars["bankId"] -> response
                # body bankId -> session_ids["bankId"]. Works for /admin/banks
                # (where bankId comes from the response), /banks/{bankId}/* (path),
                # and /partnerships/{requestId}/* (falls back to session).
                write_resp = execute(method, url, override_headers, body)
                response = write_resp
                audit_bank_id = (path_vars.get("bankId")
                                 or extract_bank_id_from_response(write_resp.get("body"))
                                 or session_ids.get("bankId"))
                audit_url = (f"{BASE_URL}/api/v1/banks/{audit_bank_id}/audit-logs"
                             if audit_bank_id else None)
                if audit_url:
                    audit_resp = execute("POST", audit_url,
                                         {"Accept": "application/json",
                                          "Content-Type": "application/json"},
                                         {"pagination": {"page": 1, "pageSize": 20}}, timeout=15)
                else:
                    audit_resp = {"ok": False, "status_code": None,
                                  "error": "no bankId for audit-log lookup"}
                logs = []
                if isinstance(audit_resp.get("body"), dict):
                    logs = audit_resp["body"].get("logs") or []
                assert_field = plan.get("assert_field")
                field_present = None
                latest_entry = logs[0] if logs else None
                if assert_field and isinstance(latest_entry, dict):
                    v = latest_entry.get(assert_field)
                    field_present = bool(v.strip()) if isinstance(v, str) else (v is not None)
                response["_audit_check"] = {
                    "write_status": write_resp.get("status_code"),
                    "audit_bank_id": audit_bank_id,
                    "audit_status": audit_resp.get("status_code"),
                    "log_count": len(logs),
                    "asserted_field": assert_field,
                    "asserted_field_present": field_present,
                }
                mutation_note = (mutation_note or "") + (
                    f" | write={write_resp.get('status_code')}; "
                    f"audit-logs status={audit_resp.get('status_code')} log_count={len(logs)}"
                    + (f"; {assert_field}_present={field_present}" if assert_field else ""))
            elif plan["action"] == "mint_invalid_then_check_no_orphan":
                # Cluster-D: send a bank with intentionally malformed input expected
                # to be rejected, then query for that bankCode to assert no orphan
                # was persisted (best-effort — only proves the absence the backend
                # will let us see).
                bad_code = "BNK-CD-ORPHAN-!@#-" + uuid.uuid4().hex[:6]
                bad_body = set_field(copy.deepcopy(body), "bankCode", bad_code) if isinstance(body, dict) else body
                bad_resp = execute(method, url, override_headers, bad_body)
                # Now query for that bankCode. Swagger filters has only status/country/search
                # (additionalProperties:false), so use `search` as a best-effort lookup —
                # backend search typically matches against bankCode/legalName/shortName.
                # Pagination must be nested per swagger contract.
                query_url = f"{BASE_URL}/api/v1/banks/query"
                query_body = {"filters": {"search": bad_code}, "pagination": {"page": 1, "pageSize": 5}}
                query_resp = execute("POST", query_url, {"Accept": "application/json", "Content-Type": "application/json"},
                                     query_body, timeout=15)
                hits = []
                if isinstance(query_resp.get("body"), dict):
                    hits = query_resp["body"].get("data") or []
                no_orphan = len(hits) == 0
                response = bad_resp
                response["_orphan_check"] = {
                    "bad_bankCode": bad_code,
                    "create_status": bad_resp.get("status_code"),
                    "query_status": query_resp.get("status_code"),
                    "query_hit_count": len(hits),
                    "no_orphan_observed": no_orphan,
                }
                mutation_note = (mutation_note or "") + (
                    f" | malformed create returned {bad_resp.get('status_code')}; "
                    f"follow-up query found {len(hits)} bank(s) with that code; no_orphan={no_orphan}")
            else:
                response = execute(method, url, override_headers, body)

            # --- HYBRID per-TC: GET-after-POST persistence probe ---
            # Scope: ONLY POST /api/v1/admin/banks. Fires when the write returns
            # 2xx and a bankId is extractable. Probe result attaches to the TC
            # record and refines reclassification below; never upgrades to PASS.
            probe_record = None
            if (pack_ep == "POST /api/v1/admin/banks"
                and response.get("ok")
                and isinstance(response.get("status_code"), int)
                and 200 <= response.get("status_code") < 300):
                minted_id = extract_bank_id_from_response(response.get("body"))
                probe_record = probe_get_after_post(minted_id)
                response["_persistence_probe"] = probe_record

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
                and any(tok in path_template for tok in ("{bankId}", "{affiliateId}"))):
                if verify_record.get("verified"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": ("CLUSTER_C_PERSISTENCE_SPLIT — seeded ID returns 200 on GET "
                                   "/api/v1/banks/{bankId}/affiliates but this write/state endpoint "
                                   "returns 404 for the same ID; backend write/read consistency defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "persistence_split",
                    }
                elif verify_record.get("cluster_c_suspected"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"CLUSTER_C_SEED_NOT_QUERYABLE — pre-flight verify on seeded bankId "
                                   f"({session_ids.get('bankId')}) returned 404 after 3 attempts; this 404 "
                                   "is downstream of an unusable seed, not a real validation defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "seed_not_queryable",
                    }

            # --- Per-TC probe reclassification (POST /admin/banks only) ---
            # Only refines non-PASS verdicts. Probe result NEVER upgrades to PASS.
            if probe_record and verdict["status"] != "PASS":
                kind = probe_record.get("kind")
                if kind == "not_persisted":
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"WRITE_DID_NOT_PERSIST — POST returned 2xx "
                                   f"({response.get('status_code')}) and emitted bankId "
                                   f"{extract_bank_id_from_response(response.get('body'))!r}, but "
                                   f"probe could not retrieve it on either primary or secondary "
                                   f"read path. Confirmed write-path defect, not read-side noise. "
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
                                   f"({probe_record.get('secondary_status')}) reads. Cannot confirm "
                                   f"persistence; surfaces as a read-path defect distinct from any "
                                   f"write-path issue."),
                        "schema": verdict.get("schema"),
                        "cluster": "H",
                        "defect_class": "read_path_5xx",
                    }
                elif kind == "partial_persistence":
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"PARTIAL_PERSISTENCE — bankId is retrievable on one read path "
                                   f"but not the other (primary={probe_record.get('primary_status')}, "
                                   f"secondary={probe_record.get('secondary_status')}). Write "
                                   f"persisted but indexes are inconsistent. {probe_record.get('reason')}"),
                        "schema": verdict.get("schema"),
                        "cluster": "H",
                        "defect_class": "partial_persistence",
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
            "service": "bank",
            "service_upper": "BNK",
            "run_mode": "postman_hybrid_bank",
            "report_date": dt.datetime.now().strftime("%Y-%m-%d"),
            "tester": "postman_hybrid_bank_runner",
            "base_api_url": BASE_URL,
            "swagger_source": str(SWAGGER_PATH),
            "postman_collection": str(POSTMAN_PATH),
            "test_pack": str(TEST_PACK_PATH),
            "auth_mode": "none",
            "seeded_ids": {
                "affiliateId": session_ids.get("affiliateId"),
                "bankId_preflight": session_ids.get("bankId"),
                "bankId_fallback_used": setup_record.get("fallback_used", False),
                "post_mint_verify": verify_record,
            },
            "cluster_c_reclassified_count": sum(1 for d in detailed if d.get("cluster") == "C"),
            "persistence_probe_summary": {
                "endpoint_scoped_to": "POST /api/v1/admin/banks",
                "probes_fired": sum(1 for d in detailed if d.get("probe_kind") is not None and d.get("probe_kind") != "skipped"),
                "persisted_count": sum(1 for d in detailed if d.get("probe_kind") == "persisted"),
                "not_persisted_count": sum(1 for d in detailed if d.get("probe_kind") == "not_persisted"),
                "read_path_5xx_count": sum(1 for d in detailed if d.get("probe_kind") == "read_path_5xx"),
                "partial_persistence_count": sum(1 for d in detailed if d.get("probe_kind") == "partial_persistence"),
                "transport_error_count": sum(1 for d in detailed if d.get("probe_kind") == "transport_error"),
                "write_did_not_persist_count": sum(1 for d in detailed if d.get("defect_class") == "write_did_not_persist"),
                "max_wait_seconds": PROBE_MAX_WAIT_S,
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
        "setup_steps": [setup_record, request_setup, sb_pool_record, ar_pool_record],
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
    }

    REPORT_PATH.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"\n=== RUN COMPLETE ===")
    print(f"Total: {total_tcs}  PASS: {counts['PASS']}  FAIL: {counts['FAIL']}  BLOCKED: {counts['BLOCKED']}  ERROR: {counts['ERROR']}")
    print(f"Overall: {overall}")
    print(f"Report: {REPORT_PATH}")
    print(f"Evidence dir: {EVIDENCE_DIR}")

if __name__ == "__main__":
    main()
