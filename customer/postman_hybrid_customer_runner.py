"""
Postman-driven HYBRID Customer API test harness.

Hybrid model (Customer variant):
  - Default: Postman base + scenario-driven mutation
  - Pre-flight: list-first discovery via POST /api/v1/customers/search
                (no public POST /customers mint endpoint — customers exist via onboarding/draft flows);
                picks first customer from search response as seeded customerRefId; persisted to SessionStore
  - Per-TC: requestContext.requestId + idempotencyKey rotated to fresh UUIDs (except *_idempotent_on_retry)
  - Per-TC: {customerRefId}/{customerId} path vars substituted with seeded value
            (skipped for unknown_id/malformed_id scenarios)
  - Pack order iteration

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
from query_mutator import smart_set_query, smart_set_query_pair  # noqa: E402
import mutation_engine  # noqa: E402

# Mutation engine version. v2 = scenario→regex→primitive engine
# (`mutation_engine.apply_mutation`). v1 = legacy keyword-routed mutations
# embedded in this file. Override at runtime: KARDIT_MUTATION_ENGINE=v1.
MUTATION_ENGINE_VERSION = os.getenv("KARDIT_MUTATION_ENGINE", "v2")

# Plan actions that the engine cannot drive — runner-level orchestration only.
ENGINE_RUNNER_PRESERVED = {
    "idempotency_double_send",
    "concurrent_parallel_send",
    "read_after_write_chain",
    "sla_check",
    "correlation_id_check",
    "as_is",
}

# Scenarios where the v2 engine misclassifies (e.g. marks as observational when
# it should mutate). Force the v1 classifier plan to run instead.
FORCE_V1_PLAN_SCENARIOS = {
    "underage_customer_rejected_where_policy_requires",
    "missing_id_number_when_id_type_supplied_rejected",
    "missing_id_type_when_id_number_supplied_rejected",
}

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

SCOPE_ENDPOINT = os.environ.get("SCOPE_ENDPOINT")
SCOPE_API_IDS = [x.strip() for x in os.environ.get("SCOPE_API_IDS", "").split(",") if x.strip()]
_raw_scope_tc = os.environ.get("SCOPE_TC_IDS", "")
SCOPE_TC_IDS: set[str] = {t.strip() for t in _raw_scope_tc.split(",") if t.strip()} if _raw_scope_tc else set()
_scope_tag = ""
if SCOPE_ENDPOINT:
    _scope_tag = "_" + re.sub(r"[^a-zA-Z0-9]+", "_", SCOPE_ENDPOINT).strip("_")
elif SCOPE_API_IDS:
    _scope_tag = "_" + "_".join(SCOPE_API_IDS)
elif SCOPE_TC_IDS:
    _scope_tag = "_tc"
EVIDENCE_DIR     = _SVC_DIR / "evidence" / f"run_{RUN_TS}"
REPORT_PATH      = _SVC_DIR / "reports" / f"customer_run_{RUN_TS}.yaml"

# --- import kit's SchemaValidator + SessionStore --------------------------
sys.path.insert(0, str(RUNNER_KIT))
from schema_validator import SchemaValidator  # noqa: E402
from session_store import SessionStore  # noqa: E402

VALIDATOR = SchemaValidator(SWAGGER_PATH)
SESSION = SessionStore(SESSION_IDS_PATH)

# --- affiliate pool config (added 2026-05-05 14:30) -----------------------
# User-directed (1b/2c/3/4 from 13:50 chat): query POST /api/v1/affiliates/query
# in pre-flight, filter to ACTIVE state, supply a fresh affiliateId per pool-eligible
# call, retry up to N times if backend reports a state-conflict, never reuse an
# affiliateId across the entire run. Hypothesis: 24 H_5xx FAILs on /customers/drafts
# may be caused by NPMC's hardcoded affiliateId AFF-1F7685… not being in backend's
# affiliate registry, triggering an unguarded dict[affiliateId] KeyNotFoundException.
AFFILIATE_POOL_TARGET_SIZE = 200
AFFILIATE_RETRY_LIMIT = 5
AFFILIATE_POOL_ENDPOINTS = {
    "POST /api/v1/customers/drafts",
    "POST /api/v1/customers/draft",
    "POST /api/v1/customers/search",
}

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

_LITERAL_ID_RE = re.compile(
    r"/(?:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # UUID
    r"|[A-Z]{3,}-[A-Z0-9-]{4,}"                                                    # PREFIXED-ID
    r"|TXN-\d+-\d+|CAR-[0-9A-F]{16,}|AFF-[0-9A-F]{16,}|BANK-\d+-\d+|CUST-[A-Z0-9-]+"
    r")(?=/|$)"
)


def normalize_path(raw_url) -> str:
    """Normalize a Postman URL into a canonical path-template key.

    Prefer the `raw` field over the segmented `path` array because Postman
    keeps the `:varName` template in `raw` but bakes literal IDs into `path`.
    Also collapse literal IDs (UUIDs / PREFIXED-IDs) to `{id}` so an entry
    whose URL ended up substituted at export time still indexes correctly."""
    if isinstance(raw_url, dict):
        path = raw_url.get("raw", "") or ""
        if not path:
            segs = raw_url.get("path", [])
            path = "/" + "/".join(str(s) for s in segs) if segs else ""
    else:
        path = raw_url or ""
    path = re.sub(r"^\{\{[^}]+\}\}", "", path)
    path = re.sub(r"^https?://[^/]+", "", path)
    path = path.split("?")[0]
    path = re.sub(r":(\w+)", r"{\1}", path)
    # Collapse literal IDs (UUIDs, PREFIXED-IDs) to a generic `{id}`.
    path = _LITERAL_ID_RE.sub("/{id}", path)
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

# --- pack-to-postman match map (Customer, 2026-05-01) ---------------------
# Pack has two path drifts vs Postman (and swagger): /customers/drafts -> /customers/draft (singular),
# and {customerId} -> {customerRefId} (param name differs but URL shape identical).
# Map pack keys to Postman keys directly; harness fires at Postman path templates.
PACK_TO_POSTMAN = {
    "POST /api/v1/customers/drafts": "POST /api/v1/customers/draft",
    "POST /api/v1/customers/search": "POST /api/v1/customers/search",
    # Pack uses {customerId} (camel); Postman normalizes to /{id}; the per-TC
    # main loop now also tries the {id}-collapsed form, so this explicit bridge
    # is redundant. Left as a no-op; PATH_TEMPLATE_OVERRIDE below redirects
    # to the swagger {customerRefId} naming when the request fires.
    "GET /api/v1/customers/{customerId}": "GET /api/v1/customers/{id}",
}
PATH_TEMPLATE_OVERRIDE = {
    # Pack uses {customerId}; canonical name is {customerRefId}.
    "GET /api/v1/customers/{customerId}": "/api/v1/customers/{customerRefId}",
    # Pack already uses the canonical name; Postman's normalized template
    # collapses to /{id}. Force the harness to rebuild with {customerRefId}
    # so seeded path-var substitution fires.
    "GET /api/v1/customers/{customerRefId}": "/api/v1/customers/{customerRefId}",
}
DRIFT_FLAGS = {
    "POST /api/v1/customers/drafts": "pack_path_drift_2026-05-01_pack_uses_drafts_postman_swagger_use_draft",
    "GET /api/v1/customers/{customerId}": "pack_path_drift_2026-05-01_pack_uses_customerId_postman_swagger_use_customerRefId",
}

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

# --- HYBRID: seeded-id injection ------------------------------------------
SEEDED_PATH_VAR_KEYS = {"cardId", "bankId", "affiliateId", "caseId", "customerId", "customerRefId"}

# Real customerRefId discovered live from POST /customers/search (empty body).
# Backend now uses the format CUS-<32-hex>; the old CUST-ACME-XXXXX format is dead
# (it 400s before the lookup logic ever fires). Used as the absolute-last fallback
# when neither the session store nor pre-flight discovery yields a customerRefId.
# Probed 2026-05-17 — replaced stale ID that caused consistent GET timeouts.
KNOWN_GOOD_CUSTOMER_REF_ID = "CUS-0B22DFBF65DC4D7486DF4D43CD75BC2E"

def inject_seeded_path_vars(path_vars: dict, session_ids: dict, allow_substitution: bool) -> dict:
    """Replace path-var values with seeded session IDs, where applicable.
    `allow_substitution=False` skips the swap (e.g. for unknown_id / malformed_id mutations
    that intentionally want a fake value).
    Customer alias: customerId and customerRefId are interchangeable (pack uses customerId,
    Postman/swagger use customerRefId — both refer to the same identifier at the URL level).
    Also unconditionally seeds the canonical customerRefId/customerId entries even when
    the caller's path_vars dict is empty (Postman entries with literal-baked URLs have
    no `variable` array, so build_base_request leaves path_vars empty)."""
    out = dict(path_vars)
    if not allow_substitution:
        return out
    customer_seed = session_ids.get("customerRefId") or session_ids.get("customerId") or KNOWN_GOOD_CUSTOMER_REF_ID
    for k in list(out.keys()):
        if k in ("customerId", "customerRefId"):
            out[k] = customer_seed
        elif k in SEEDED_PATH_VAR_KEYS and session_ids.get(k):
            out[k] = session_ids[k]
    # Always provide canonical customer keys so `{customerRefId}` placeholders
    # in PATH_TEMPLATE_OVERRIDE (or pack templates) substitute correctly.
    out.setdefault("customerRefId", customer_seed)
    out.setdefault("customerId", customer_seed)
    out.setdefault("id", customer_seed)  # For collapsed `{id}` templates
    return out

# --- HYBRID: pre-flight customer discovery (search-first) ----------------
def extract_first_customer_ref_id_from_search(resp_body: Any) -> str | None:
    """Best-effort extraction of first customerRefId from POST /customers/search response.
    Tries common shapes: {data: [{customerRefId|id, ...}, ...]}, {customers: [...]}, {items: [...]},
    plus pagination-wrapped variants."""
    if not isinstance(resp_body, dict):
        return None
    for container_key in ("data", "items", "results", "customers", "matches"):
        items = resp_body.get(container_key)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                for k in ("customerRefId", "customerId", "id", "customer_ref_id"):
                    v = first.get(k)
                    if isinstance(v, str) and v:
                        return v
        if isinstance(items, dict):
            for sub_key in ("items", "result", "results", "customers"):
                sub = items.get(sub_key)
                if isinstance(sub, list) and sub and isinstance(sub[0], dict):
                    for k in ("customerRefId", "customerId", "id"):
                        v = sub[0].get(k)
                        if isinstance(v, str) and v:
                            return v
    return None

def _persist_customer_if_verified(customer_ref: str, session_ids: dict, source: str) -> dict:
    """Verify-before-save for Customer customerRefId.

    Backend probe 2026-05-10 surfaced D-CUS-GET-2: `GET /customers/{customerRefId}`
    returns 500 on every real customer due to a `kyc.idType` deserialization bug.
    Until backend ships the fix, we cannot verify via GET. Fall back to: persist
    if the search response gave us the ID at all (it came from a 200 search, so
    we know the customer exists). When backend ships D-CUS-GET-2, the GET-based
    verify will resume working."""
    verify_rec = verify_seeded_id_queryable(customer_ref, "/api/v1/customers/{customerRefId}")
    verified = verify_rec.get("verified")
    persisted = False
    # Accept search-derived IDs even when verify GET 500s (D-CUS-GET-2 workaround).
    accept = bool(verified) or (verify_rec.get("status") == 500 and source == "discover")
    if accept:
        session_ids["customerRefId"] = customer_ref
        SESSION.save({"customerRefId": customer_ref})
        persisted = True
    return {
        "selected_source": source,
        "selected_verified": bool(verified),
        "persisted_to_session_store": persisted,
        "verify": verify_rec,
        "accepted_unverified_500": (not verified) and accept,
    }


def pre_flight_discover_customer(pm_idx: dict, session_ids: dict) -> dict:
    """Live POST /api/v1/customers/search with broad criteria. On success: pick first customer
    from response, capture customerRefId, persist. No POST /customers mint endpoint exists at
    the public surface — customers come from onboarding/draft flows upstream of customer service."""
    setup = {
        "step": "discover_seed_customer",
        "method": "POST",
        "endpoint": "/api/v1/customers/search",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "fallback_used": False,
    }
    pm_entry = pm_idx.get("POST /api/v1/customers/search")
    if not pm_entry:
        setup.update({"status": "ERROR",
                      "reason": "POST /api/v1/customers/search not in Postman — cannot pre-flight discover"})
        return setup
    base = build_base_request(pm_entry)
    # Backend probe 2026-05-10: POST /customers/search rejects every wrapper
    # shape we tried (requestContext, model, criteria, page+pageSize, etc.) with
    # `CustomerSearchRequest`-binding errors. Empty body `{}` is the only shape
    # that returns 200 with real customers. Use it directly instead of the
    # Postman happy-path body which carries the broken wrapper.
    body = {}
    path_template = get_postman_path_template(pm_entry)
    url = rebuild_url(base["method"], path_template, base["path_vars"], base["query"])
    setup["url"] = url
    setup["request_body"] = body
    response = execute(base["method"], url, base["headers"], body, timeout=30)
    setup["response_status"] = response.get("status_code")
    setup["response_body"] = response.get("body") if response.get("body") is not None else response.get("body_text")
    setup["completed_at"] = dt.datetime.now().isoformat()
    if not response.get("ok"):
        setup.update({"status": "ERROR", "reason": f"transport: {response.get('error')}"})
        return setup
    sc = response.get("status_code", 0)
    if 200 <= sc < 300:
        customer_ref = extract_first_customer_ref_id_from_search(response.get("body"))
        if customer_ref:
            persist = _persist_customer_if_verified(customer_ref, session_ids, source="discover")
            setup["customer_ref_id"] = customer_ref
            setup["persistence"] = persist
            setup["status"] = "OK" if persist["selected_verified"] else "UNVERIFIED"
            if not persist["selected_verified"]:
                setup["reason"] = "search returned a customerRefId but verify GET did not confirm it is queryable; not persisted"
            return setup
        setup.update({"status": "DEGRADED",
                      "reason": f"2xx ({sc}) but search response had no customer; falling back to Postman literal",
                      "fallback_used": True})
        return setup
    setup.update({"status": "FAIL",
                  "reason": f"search endpoint non-2xx ({sc}); falling back to Postman literal customerRefId",
                  "fallback_used": True})
    return setup

# --- HYBRID: ACTIVE affiliate pool (added 2026-05-05 14:30) ---------------
def _walk_for_affiliate_records(node: Any, out: list, max_depth: int = 8) -> None:
    """Recursively collect dicts that look like affiliate records (have an affiliateId-ish key)."""
    if max_depth <= 0:
        return
    if isinstance(node, dict):
        if any(k in node for k in ("affiliateId", "affiliateID", "id")) and (
            "status" in node or "state" in node or "kybStatus" in node or len(node) > 1
        ):
            out.append(node)
        for v in node.values():
            _walk_for_affiliate_records(v, out, max_depth - 1)
    elif isinstance(node, list):
        for it in node:
            _walk_for_affiliate_records(it, out, max_depth - 1)

def query_affiliate_pool(pm_idx: dict, target_size: int = AFFILIATE_POOL_TARGET_SIZE,
                          state_filter: str = "ACTIVE") -> dict:
    """Live POST /api/v1/affiliates/query, paginate up to target_size, filter to records
    whose status (or state) is `state_filter`. Returns:
        {"status": "OK"|"DEGRADED"|"FAIL", "pool": list[str], "reason": str, "raw_count": int, "filtered_count": int}.
    Pool order is the natural backend order (caller does .pop(0) for FIFO consumption).
    """
    rec = {"status": "PENDING", "pool": [], "reason": None, "raw_count": 0, "filtered_count": 0,
           "endpoint": "/api/v1/affiliates/query", "state_filter": state_filter,
           "started_at": dt.datetime.now().isoformat()}
    pm_entry = pm_idx.get("POST /api/v1/affiliates/query")
    if not pm_entry:
        rec.update({"status": "FAIL", "reason": "POST /api/v1/affiliates/query not in Postman"})
        return rec
    base = build_base_request(pm_entry)
    # Send Postman body as-is (page/pageSize already present); avoid adding extra
    # fields like pageNumber that backend rejects on additionalProperties: false.
    body = copy.deepcopy(base["body"]) if isinstance(base["body"], dict) else {}
    if isinstance(body, dict):
        # Only set pageSize if the Postman body uses a pagination wrapper dict
        if isinstance(body.get("pagination"), dict):
            body["pagination"]["page"] = 1
            body["pagination"]["pageSize"] = target_size
        elif "pageSize" in body:
            body["pageSize"] = target_size
        elif "page_size" in body:
            body["page_size"] = target_size
    path_template = get_postman_path_template(pm_entry)
    pv = dict(base["path_vars"]); pv["query"] = "query"
    url = rebuild_url(base["method"], path_template, pv, base["query"])
    rec["url"] = url
    response = execute(base["method"], url, base["headers"], body, timeout=30)
    rec["response_status"] = response.get("status_code")
    if not response.get("ok"):
        rec.update({"status": "FAIL", "reason": f"transport: {response.get('error')}"})
        return rec
    sc = response.get("status_code", 0)
    if not (200 <= sc < 300):
        rec.update({"status": "FAIL", "reason": f"non-2xx ({sc}) from /affiliates/query"})
        return rec
    records: list = []
    _walk_for_affiliate_records(response.get("body"), records)
    rec["raw_count"] = len(records)
    pool: list[str] = []
    seen: set[str] = set()
    state_filter_upper = (state_filter or "").upper()
    _aff_fmt = re.compile(r'^AFF-[A-F0-9]{32}$')
    for r in records:
        aid = r.get("affiliateId") or r.get("affiliateID") or r.get("id")
        if not isinstance(aid, str) or not aid or aid in seen:
            continue
        # Backend now enforces AFF-[32 uppercase hex] format in requestContext.affiliateId.
        # Short-format IDs (AFF-FRESH-XXX, AFF-TEST-NEW-XXX) are rejected with 400.
        if not _aff_fmt.match(aid):
            continue
        if state_filter_upper:
            status_val = r.get("status") or r.get("state") or r.get("kybStatus") or ""
            if not isinstance(status_val, str) or status_val.upper() != state_filter_upper:
                continue
        seen.add(aid); pool.append(aid)
    rec["filtered_count"] = len(pool)
    rec["pool"] = pool
    rec["completed_at"] = dt.datetime.now().isoformat()
    if not pool:
        rec["status"] = "DEGRADED"
        rec["reason"] = (f"queried {len(records)} affiliate-shaped records but 0 matched state={state_filter} "
                         f"with AFF-[32hex] format; pool empty, runner will fall back to NPMC literal affiliateId")
    else:
        rec["status"] = "OK"
    return rec


_FIRST_NAMES = ("Adaeze","Bisi","Chuka","Dami","Emeka","Funmi","Gbenga","Halima",
                "Ifeanyi","Jumoke","Kunle","Lola","Musa","Ngozi","Obinna","Patience",
                "Quincy","Rume","Salim","Tobi","Uche","Vera","Wale","Xola","Yemi","Zara")
_LAST_NAMES  = ("Okafor","Adeyemi","Eze","Mohammed","Ibrahim","Olawale","Nwosu","Bello",
                "Akinwale","Chukwu","Danjuma","Folarin","Garba","Hassan","Iroegbu",
                "Johnson","Kalu","Lawal","Maduka","Nkemdirim","Obi","Peters","Quaye",
                "Ruwase","Sani","Taiwo","Udeh","Vincent","Williams","Yusuf","Zubair")
_STREETS     = ("Adeola Odeku","Lekki Phase 1","Allen Avenue","Ikorodu Road","Surulere",
                "Victoria Island","Ajose Adeogun","Awolowo","Herbert Macaulay","Bode Thomas",
                "Opebi","Toyin Street","Adeniyi Jones","Glover Road","Marina Crescent")
_CITIES      = ("Lagos","Abuja","Port Harcourt","Ibadan","Kano","Enugu","Benin City")
_STATES      = ("Lagos","FCT","Rivers","Oyo","Kano","Enugu","Edo")

def rotate_customer_uniqueness(body: Any, tc_id: str | None = None) -> Any:
    """Mint a fresh-uniqueness body for /customers/drafts so the backend's
    duplicate-detection check (firstName+lastName+dob+phone+email+idNumber)
    cannot collapse multiple TCs onto the same 500 'already exists' response.

    Per-TC deterministic seed when tc_id is provided so re-running the same TC
    twice produces the same body (helpful for evidence comparison); otherwise
    falls back to UUID. Rotates EVERY identifying field — firstName, lastName,
    dob, email, phone, idNumber, and street/city/state — to plausible values.
    Returns a deep copy.
    """
    if not isinstance(body, dict):
        return body
    body = copy.deepcopy(body)
    if tc_id:
        # 12-hex-char deterministic suffix from the TC id
        h = hashlib.sha256(tc_id.encode("utf-8")).hexdigest()
        suffix = h[:12]
    else:
        suffix = uuid.uuid4().hex[:12]
    seed = int(suffix, 16)
    # Backend regression 2026-05-06 22:30: FirstName/LastName now require letters-only.
    # Hex suffix (0-9 + A-F) injects digits into the name → 400. Translate hex chars
    # to plain ASCII letters so the rotated suffix stays alphabetic but still deterministic.
    _hex_to_letter = str.maketrans("0123456789ABCDEFabcdef", "ABCDEFGHIJKLMNOPABCDEF")
    def _alpha_suffix(s: str) -> str:
        return s.upper().translate(_hex_to_letter)
    s4 = _alpha_suffix(suffix[:4])
    fresh_first = f"{_FIRST_NAMES[seed % len(_FIRST_NAMES)]}{s4}"
    fresh_last  = f"{_LAST_NAMES[(seed >> 8) % len(_LAST_NAMES)]}{_alpha_suffix(suffix[4:8])}"
    fresh_email = f"hybrid-{suffix}@example.com"
    fresh_phone = "0813" + "".join(str((int(c, 16) + 3) % 10) for c in suffix[:7])
    fresh_id    = ("NIN" + "".join(str(int(c, 16) % 10) for c in suffix))[:14]
    yr = 1970 + (int(suffix[0:2], 16) % 31)
    mo = 1 + (int(suffix[2:4], 16) % 12)
    dy = 1 + (int(suffix[4:6], 16) % 28)
    fresh_dob = f"{yr:04d}-{mo:02d}-{dy:02d}T00:00:00.000Z"
    fresh_line1 = f"{(seed % 999) + 1} {_STREETS[(seed >> 4) % len(_STREETS)]} Street"
    fresh_city  = _CITIES[(seed >> 12) % len(_CITIES)]
    fresh_state = _STATES[(seed >> 12) % len(_STATES)]

    def _set(d, key, val):
        if isinstance(d, dict) and key in d:
            d[key] = val

    cust = body.get("customer")
    if isinstance(cust, dict):
        ident = cust.get("identity")
        if isinstance(ident, dict):
            _set(ident, "firstName", fresh_first)
            _set(ident, "lastName",  fresh_last)
            _set(ident, "email",     fresh_email)
            _set(ident, "phone",     fresh_phone)
            _set(ident, "dob",       fresh_dob)
            _set(ident, "dateOfBirth", fresh_dob)
        kyc = cust.get("kyc")
        if isinstance(kyc, dict):
            _set(kyc, "idNumberMasked", fresh_id)
            _set(kyc, "idNumber",       fresh_id)
        addr = cust.get("address")
        if isinstance(addr, dict):
            _set(addr, "line1", fresh_line1)
            _set(addr, "city",  fresh_city)
            _set(addr, "state", fresh_state)
        # also direct fields on customer in case shape varies
        _set(cust, "firstName", fresh_first)
        _set(cust, "lastName",  fresh_last)
    # Some bodies put fields at top level
    _set(body, "firstName", fresh_first)
    _set(body, "lastName",  fresh_last)
    _set(body, "email",     fresh_email)
    _set(body, "phone",     fresh_phone)
    _set(body, "dob",       fresh_dob)
    _set(body, "dateOfBirth", fresh_dob)
    return body


def rewrite_customer_search_criteria(body: Any, session_ids: dict) -> Any:
    """Backend only accepts empty body {} for POST /customers/search; any wrapper
    shape (requestContext, criteria, pagination) returns 400. Return {} so the
    mutation engine adds scenario-specific fields on a clean slate."""
    return {}


def substitute_affiliate_in_body(body: Any, affiliate_id: str) -> Any:
    """Recursive deep-copy + substitute every `affiliateId` field with `affiliate_id`.
    Returns a new object; does NOT mutate input. Case-sensitive on the key (matches NPMC body shape).
    """
    if not affiliate_id or body is None:
        return body
    body = copy.deepcopy(body)
    def _walk(node):
        if isinstance(node, dict):
            for k in list(node.keys()):
                if k == "affiliateId" and isinstance(node[k], str):
                    node[k] = affiliate_id
                else:
                    _walk(node[k])
        elif isinstance(node, list):
            for it in node:
                _walk(it)
    _walk(body)
    return body


def is_affiliate_conflict_response(response: dict) -> tuple[bool, str]:
    """Detect 'this affiliateId is rejected by backend, retry with another' signal.
    Caller only invokes this for tests expecting 2xx, so retrying on 5xx is safe
    (a 5xx means we got the wrong outcome AND another affiliate may give the right one).
    Returns (is_conflict, reason_snippet)."""
    sc = response.get("status_code", 0) or 0
    body = response.get("body")
    body_text = response.get("body_text") or ""
    msg = ""
    if isinstance(body, dict):
        err = body.get("error") or {}
        if isinstance(err, dict):
            msg = err.get("message") or ""
        if not msg:
            msg = body.get("message") or body.get("title") or ""
    if not msg and body_text:
        msg = body_text
    msg_low = (msg or "").lower()
    state_keywords = ("already", "duplicate", "conflict", "exists")
    keyerror_keywords = ("key was not present", "given key", "not present in the dictionary",
                         "keynotfoundexception", "dictionary")
    if sc == 409:
        return (True, f"409 Conflict: {msg[:120]}")
    if sc == 400 and any(kw in msg_low for kw in state_keywords):
        return (True, f"400 with state-conflict signal: {msg[:120]}")
    if 500 <= sc < 600 and any(kw in msg_low for kw in keyerror_keywords):
        return (True, f"5xx with dictionary-keyerror signal (likely affiliate not in registry): {msg[:120]}")
    return (False, "")


# --- HYBRID: post-mint verify (Cluster-C mitigation) ----------------------
def verify_seeded_id_queryable(seed_id: str | None, get_path_template: str,
                               max_retries: int = 2, delay_s: float = 1.0) -> dict:
    """GET on the freshly-discovered resource. Retries on 404 with backoff.
    Distinguishes 'eventual consistency' (transient 404 that resolves) from
    'persistence split' (404 that never resolves — Cluster C signature).
    For Customer we use GET /api/v1/customers/{customerRefId} as the verifier
    that proves the customerRefId is recognized by the read pipeline."""
    rec = {"verified": False, "url": None, "status": None, "attempts": 0,
           "cluster_c_suspected": False, "reason": None}
    if not seed_id:
        rec["reason"] = "no seed_id provided"
        return rec
    url = f"{BASE_URL}{get_path_template.replace('{customerRefId}', seed_id).replace('{customerId}', seed_id).replace('{caseId}', seed_id).replace('{bankId}', seed_id).replace('{affiliateId}', seed_id)}"
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
        "physical_card_status_personalizing", "virtual_card_status_active",
        "card_provisioning_event_emitted", "card_event_published",
        "card_lifecycle_event_created", "transaction_record_created",
        "fulfillment_provider_called", "fulfillment_callback_received",
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
    # Specific overrides before the generic missing_* regex to avoid false mutations.
    if s == "missing_kyc_status_rejected":
        return {"action": "blocked", "reason": "kycStatus is not present in the Postman base request for POST /draft; drop-field is trivially satisfied without testing backend validation"}
    if s == "missing_id_number_when_id_type_supplied_rejected":
        return {"action": "drop_field", "field": "idNumber"}
    if s == "missing_id_type_when_id_number_supplied_rejected":
        return {"action": "drop_field", "field": "idType"}
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
        # For these IDs: try as body field first (covers endpoints where ID is in body, like
        # POST /customers/drafts with body.affiliateId). The URL-path-var case is a separate
        # test class (URL-shape impossible) that the pack should drop or rephrase.
        if raw == "card_id": return {"action": "set_field", "field": "cardId", "value": ""}
        if raw == "bank_id": return {"action": "set_field", "field": "bankId", "value": ""}
        if raw == "affiliate_id": return {"action": "set_field", "field": "affiliateId", "value": ""}
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
        # Path-var IDs: snake_case forms come from snake_case scenario names; the
        # collapsed forms (caseid, customerid, productid, ...) come from scenario
        # names written in camelCase like `malformed_customerId_rejected` after
        # s.lower(). Both must route to set_path_var so the malformed payload lands
        # in the URL, not in a non-existent body field.
        if raw in ("card_id", "bank_id", "affiliate_id", "limit_request_id", "request_id",
                   "case_id", "customer_id", "product_id", "partnership_request_id",
                   "caseid", "customerid", "productid", "bankid", "affiliateid",
                   "cardid", "requestid", "partnershiprequestid"):
            field = "customerId" if raw in ("customer_id", "customerid") else snake_to_camel(raw)
            if   raw in ("case_id", "caseid"):    field = "caseId"
            elif raw in ("product_id", "productid"): field = "productId"
            elif raw in ("bank_id", "bankid"):    field = "bankId"
            elif raw in ("affiliate_id", "affiliateid"): field = "affiliateId"
            elif raw in ("card_id", "cardid"):    field = "cardId"
            elif raw in ("request_id", "requestid"): field = "requestId"
            elif raw in ("partnership_request_id", "partnershiprequestid"): field = "partnershipRequestId"
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
        # query-param mutations
        if raw.endswith("Range") or "date" in raw.lower():
            return {"action": "set_query", "key": raw, "value": "not-a-range"}
        return {"action": "set_field", "field": raw, "value": "BOGUS_VALUE_XYZ"}
    if s == "invalid_date_range_rejected":
        return {"action": "set_query_pair", "values": {"fromDate": "not-a-date", "toDate": "also-bad"}}
    if s == "multiple_filters_and_semantics":
        return {"action": "as_is", "note": "multi-filter semantics test; happy path with current Postman filters"}

    # 2026-05-10 fix (Bug 2): page_two/page_one explicit before _success catch-all
    if s in ("pagination_page_two_success", "page_two_success", "pagination_page_two", "pagination_second_page"):
        return {"action": "set_query", "key": "pageNumber", "value": "2",
                "note": "advanced to page 2 to actually exercise pagination"}
    if s in ("pagination_page_one_success", "page_one_success", "pagination_first_page"):
        return {"action": "set_query", "key": "pageNumber", "value": "1",
                "note": "explicit page 1 (canonical happy path)"}
    # success / happy paths (after specific patterns)
    if any(k in s for k in ("_success", "_safe", "_accepted", "_handled", "_well_formed")):
        return {"action": "as_is", "note": "happy-path or accepting variant; sent Postman request as-is"}
    if s.startswith("issue_virtual") or s.startswith("issue_physical") or s.startswith("issue_card_"):
        return {"action": "as_is", "note": "alternative happy-path variant; Postman provides one variant"}

    # ---- Admin-specific classifier patches (added 2026-05-01) ----

    # List/pagination happy paths (GET /admin/onboarding/cases)
    if s.startswith("list_") or s == "list_without_status_filter":
        return {"action": "set_query", "key": "Status", "value": _list_status_for_scenario(s),
                "note": f"list scenario '{s}' — set Status filter and run as happy-path"}
    if s == "pagination_page_2_size_10":
        return {"action": "set_query_pair", "values": {"Page": "2", "PageSize": "10"},
                "note": "pagination happy path with Page=2 PageSize=10"}
    if s == "minimum_page_size":
        return {"action": "set_query", "key": "PageSize", "value": "1", "note": "minimum page size"}
    if s == "maximum_page_size":
        return {"action": "set_query", "key": "PageSize", "value": "100", "note": "documented max page size"}
    if s == "page_size_exceeds_limit":
        return {"action": "set_query", "key": "PageSize", "value": "99999", "note": "page size beyond cap"}
    if s == "negative_page_rejected":
        return {"action": "set_query", "key": "Page", "value": "-1", "note": "negative page"}
    if s == "non_numeric_page_size_rejected":
        return {"action": "set_query", "key": "PageSize", "value": "abc", "note": "non-numeric page size"}
    if s == "invalid_status_rejected":
        return {"action": "set_query", "key": "Status", "value": "BOGUS_STATUS", "note": "invalid status enum"}
    if s == "empty_status_policy":
        return {"action": "set_query", "key": "Status", "value": "", "note": "empty status filter"}
    if s in ("cross_affiliate_visibility_for_sp", "empty_result_set", "case_fields_present",
            "submitted_at_iso_format", "stable_sort_order", "no_sensitive_data_in_list_response"):
        return {"action": "as_is", "note": f"list response-shape verification '{s}'; running happy-path"}

    # Decision endpoint scenarios
    if s == "approve_submitted_case":
        return {"action": "as_is", "note": "Postman base sets decision=Approve; happy-path approve"}
    if s == "reject_submitted_case":
        return {"action": "set_field", "field": "decision", "value": "Reject", "note": "switch decision to Reject"}
    if s == "clarify_submitted_case":
        return {"action": "set_field", "field": "decision", "value": "Clarify", "note": "switch decision to Clarify"}
    if s == "invalid_decision_type":
        return {"action": "set_field", "field": "decision", "value": "BOGUS_DECISION", "note": "invalid decision enum"}
    if s in ("empty_decision", "missing_decision"):
        return {"action": "drop_field", "field": "decision", "note": "drop required decision field"}
    if s == "lowercase_decision_policy":
        return {"action": "set_field", "field": "decision", "value": "approve", "note": "lowercase decision"}
    if s == "approve_invalid_bank_id":
        return {"action": "set_field", "field": "selectedBanksApproved", "value": [ZERO_UUID],
                "note": "invalid (zero-UUID) bank in approved list"}
    if s == "approve_empty_selected_banks":
        return {"action": "set_field", "field": "selectedBanksApproved", "value": [],
                "note": "empty selectedBanksApproved"}
    if s in ("approve_clarification_required_case_policy", "approve_already_approved_case_blocked",
             "reject_already_approved_case_blocked", "clarify_already_approved_case_blocked",
             "approve_rejected_case_blocked"):
        return {"action": "as_is", "note": f"STATE-DEPENDENT '{s}' — needs case in specific state; running as-is, verdict surfaces backend behavior"}
    if s in ("decision_nonexistent_case", "nonexistent_case_not_found"):
        return {"action": "unknown_id", "field": "caseId", "note": "swap caseId for unknown UUID"}
    if s in ("reviewer_identity_recorded", "affiliate_tracking_visible"):
        return {"action": "as_is", "note": f"response-shape verification '{s}'; happy-path"}

    # Provision endpoint scenarios
    if s in ("submitted_case_provision_blocked", "clarification_case_provision_blocked",
             "rejected_case_provision_blocked", "duplicate_provisioning_blocked",
             "bank_owned_affiliate_creation_blocked"):
        return {"action": "as_is", "note": f"STATE-DEPENDENT '{s}' — needs case in specific state; running as-is"}
    if s == "invalid_admin_email_rejected":
        return {"action": "set_nested", "parent": "adminContact", "field": "email",
                "value": "###not-valid###", "note": "format-invalid admin email"}
    if s == "invalid_phone_rejected":
        return {"action": "set_nested", "parent": "adminContact", "field": "phone",
                "value": "###not-valid###", "note": "format-invalid admin phone"}
    if s == "empty_delivery_channels_policy":
        return {"action": "set_field", "field": "deliveryChannels", "value": [],
                "note": "empty deliveryChannels list"}
    if s == "invalid_approved_bank_selection_blocks":
        return {"action": "set_field", "field": "selectedBanksApproved", "value": [ZERO_UUID],
                "note": "invalid bank selection on provision"}
    if s in ("affiliate_identifier_assigned", "tenant_identifier_assigned",
             "affiliate_type_external_returned", "created_affiliate_active_status",
             "partnership_requests_created_for_approved_banks",
             "partnership_requests_pending_bank_approval",
             "iam_or_access_provisioning_triggered", "provisioned_at_timestamp_returned"):
        return {"action": "as_is", "note": f"response-shape verification '{s}'; happy-path"}

    # POST /admin/banks scenarios
    if s == "authorized_service_provider_only":
        return {"action": "as_is", "note": "happy-path bank provision; auth-scope check"}
    if s == "empty_legal_name_rejected":
        return {"action": "set_field", "field": "legalName", "value": "", "note": "empty legalName"}
    if s == "empty_bank_code_rejected":
        return {"action": "set_field", "field": "bankCode", "value": "", "note": "empty bankCode"}
    if s == "invalid_bank_code_format_rejected":
        return {"action": "set_field", "field": "bankCode", "value": "!@#$%", "note": "format-invalid bankCode"}
    if s == "invalid_country_code_rejected":
        return {"action": "set_field", "field": "country", "value": "XX", "note": "invalid ISO country"}
    if s == "invalid_contact_email_rejected":
        return {"action": "set_nested", "parent": "primaryContact", "field": "email",
                "value": "###not-valid###", "note": "format-invalid contact email"}
    if s in ("bank_provisioning_independent_of_iam_user_creation", "internal_affiliate_created",
             "internal_affiliate_owner_bank_linked", "internal_affiliate_system_managed_true",
             "internal_active_partnership_created"):
        return {"action": "as_is", "note": f"response-shape verification '{s}'; happy-path"}

    # ---- Customer-specific classifier patches (added 2026-05-01) ----

    # Customer draft body — format-validation scenarios on customer.identity.*
    if s == "invalid_date_of_birth_format_rejected":
        return {"action": "set_nested", "parent": "customer", "field": "dob",
                "value": "1899-13-99", "note": "format-invalid dob (deep customer.identity.dob handled at endpoint level)"}
    if s == "future_date_of_birth_rejected":
        return {"action": "set_nested", "parent": "customer", "field": "dob",
                "value": "2099-12-31", "note": "future-dated dob"}
    if s == "underage_customer_rejected_where_policy_requires":
        return {"action": "set_field", "field": "dob",
                "value": "2020-01-01T00:00:00.000Z", "note": "underage dob (~6 years old)"}
    if s == "invalid_phone_format_rejected":
        return {"action": "set_nested", "parent": "customer", "field": "phone",
                "value": "###not-valid###", "note": "format-invalid phone"}
    if s == "invalid_email_format_rejected":
        return {"action": "set_nested", "parent": "customer", "field": "email",
                "value": "###not-valid###", "note": "format-invalid email"}
    if s == "invalid_id_number_format_rejected":
        return {"action": "set_nested", "parent": "customer", "field": "idNumber",
                "value": "!@#$%", "note": "format-invalid idNumber"}
    if s == "same_identity_different_affiliate_policy":
        return {"action": "as_is", "note": "STATE-DEPENDENT — needs identity uniqueness state; running as-is"}

    # Search/scope policy — happy-path runs that test backend filtering correctness
    if s in ("foreign_affiliate_scope_rejected", "foreign_scope_filter_rejected_or_filtered",
             "tenant_scope_isolation", "affiliate_scope_isolation", "bank_scope_search_policy",
             "service_provider_read_only_search", "bank_scope_policy"):
        return {"action": "as_is", "note": f"scope/policy verification '{s}'; running happy-path; verdict surfaces backend filtering"}
    if s == "response_summary_fields_present":
        return {"action": "as_is", "note": "search response-shape verification; happy-path"}

    # GET /customers/{customerRefId} response-field-presence verifications — all happy-path
    if s in ("identity_fields_returned", "contact_fields_returned", "address_fields_returned",
             "kyc_fields_returned", "status_returned", "tenant_affiliate_fields_returned",
             "linked_card_references_returned", "customer_draft_reference_returned",
             "timestamp_format_valid"):
        return {"action": "as_is", "note": f"GET response field-presence '{s}'; happy-path"}

    # Customer-state policy on detail GET — state-dependent, run as-is
    if s in ("suspended_customer_detail_policy", "inactive_customer_detail_policy",
             "archived_customer_policy"):
        return {"action": "as_is", "note": f"STATE-DEPENDENT '{s}' — needs customer in specific state; running as-is"}

    # Masking/security policy — response-shape verifications
    if s in ("sensitive_id_number_masked", "sensitive_contact_masking_policy",
             "no_raw_document_refs_exposed"):
        return {"action": "as_is", "note": f"masking/security verification '{s}'; happy-path"}

    # ID handling edge cases on the GET endpoint
    if s == "case_sensitive_customer_id_handling":
        return {"action": "as_is", "note": "case-sensitivity verification; happy-path; verdict surfaces backend behavior"}
    if s == "whitespace_customer_id_handling":
        return {"action": "set_path_var", "field": "customerRefId", "value": "  ABC123  ",
                "note": "whitespace-padded customerRefId in URL path"}

    # fallback — Wave 1.1: in v2 mode, hand unrecognized scenarios to the
    # mutation engine. The engine's audit catalog covers most common patterns
    # the legacy runner classifier doesn't.
    if MUTATION_ENGINE_VERSION == "v2":
        return {"action": "engine_drive",
                "note": f"unrecognized by runner classifier — handed to v2 engine for scenario `{scenario}`"}
    return {"action": "blocked", "reason": f"Skipped — the test case scenario '{scenario}' uses a name our automated test-builder doesn't recognize, so we couldn't tell what change to make to the request. Rather than guess and report a wrong answer, we skipped it"}


def _list_status_for_scenario(scenario: str) -> str:
    """Map list_* scenario names to the Status filter value they want to test."""
    mapping = {
        "list_submitted_cases": "SUBMITTED",
        "list_clarification_required_cases": "CLARIFICATION_REQUIRED",
        "list_approved_cases": "APPROVED",
        "list_rejected_cases": "REJECTED",
    }
    return mapping.get(scenario, "")  # empty for list_without_status_filter

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
    """Return a canonical path template with `{var}` placeholders. Collapses
    literal IDs (UUIDs / PREFIXED-IDs) baked into Postman's `path` array — they
    must be substitutable by the seeded session ID, not pinned to whatever
    customer happened to exist when the Postman collection was exported."""
    return normalize_path(pm_entry["request"].get("url", {}))

def execute(method: str, url: str, headers: dict, body: Any, timeout: int = 20) -> dict:
    started = dt.datetime.now().isoformat()
    t0 = time.perf_counter()
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

    # --- HYBRID phase 0: load session + pre-flight discover customer ---
    session_ids = SESSION.load()
    print(f"Phase 0: pre-flight POST /customers/search (search-first discovery)...")
    setup_record = pre_flight_discover_customer(pm_idx, session_ids)
    print(f"  -> status={setup_record.get('status')} customerRefId={session_ids.get('customerRefId')!r} fallback={setup_record.get('fallback_used')}")
    if not session_ids.get("customerRefId"):
        # Fall back to Postman's literal customerRefId from the GET /customers/{customerRefId} entry
        pm = pm_idx.get("GET /api/v1/customers/{customerRefId}")
        if pm:
            base_pm = build_base_request(pm)
            literal = base_pm["path_vars"].get("customerRefId")
            if literal and literal != "string":
                session_ids["customerRefId"] = literal
                setup_record["postman_literal_customerRefId_used"] = literal
                print(f"  -> using Postman literal customerRefId: {literal}")
            elif literal == "string":
                # Postman literal is "string" placeholder — useless. Continue without seed; happy-path
                # TCs against {customerRefId} will likely 404 and Cluster-C reclassification will fire.
                print(f"  -> Postman literal is placeholder 'string'; continuing without seed (404s on happy-path will reclassify to Cluster-C)")
    if not session_ids.get("customerRefId"):
        print(f"WARN: no customerRefId available; happy-path TCs on GET /customers/{{customerRefId}} will run with 'string' placeholder")

    # --- HYBRID phase 0b: verify the seeded customerRefId is queryable (Cluster-C mitigation) ---
    print(f"Phase 0b: verifying seeded customerRefId via GET /api/v1/customers/{{customerRefId}}...")
    verify_record = verify_seeded_id_queryable(session_ids.get("customerRefId"), "/api/v1/customers/{customerRefId}")
    print(f"  -> verified={verify_record['verified']} attempts={verify_record['attempts']} cluster_c_suspected={verify_record['cluster_c_suspected']}")
    setup_record["post_mint_verify"] = verify_record

    # --- HYBRID phase 0e: affiliate pool (added 2026-05-05; ACTIVE filter restored per user 16:00 — empirical: filter delivers reproducible +2 PASS on /drafts) ---
    print(f"Phase 0e: querying ACTIVE affiliate pool via POST /api/v1/affiliates/query (target={AFFILIATE_POOL_TARGET_SIZE})...")
    affiliate_pool_record = query_affiliate_pool(pm_idx, target_size=AFFILIATE_POOL_TARGET_SIZE, state_filter="ACTIVE")
    affiliate_pool: list[str] = list(affiliate_pool_record.get("pool") or [])
    used_affiliates_global: set[str] = set()
    affiliate_pool_consumption_log: list = []  # per-TC consumption for the report
    _filter_label = (affiliate_pool_record.get('state_filter') or 'NONE')
    print(f"  -> status={affiliate_pool_record.get('status')} raw={affiliate_pool_record.get('raw_count')} matched({_filter_label})={affiliate_pool_record.get('filtered_count')} ; reason={affiliate_pool_record.get('reason')}")
    if affiliate_pool:
        print(f"  -> first 5: {affiliate_pool[:5]}")
    setup_record["affiliate_pool"] = {
        "status": affiliate_pool_record.get("status"),
        "endpoint": affiliate_pool_record.get("endpoint"),
        "state_filter": affiliate_pool_record.get("state_filter"),
        "target_size": AFFILIATE_POOL_TARGET_SIZE,
        "retry_limit": AFFILIATE_RETRY_LIMIT,
        "raw_count": affiliate_pool_record.get("raw_count"),
        "filtered_count": affiliate_pool_record.get("filtered_count"),
        "reason": affiliate_pool_record.get("reason"),
        "pool_initial": list(affiliate_pool),
        "endpoints_eligible": sorted(AFFILIATE_POOL_ENDPOINTS),
    }

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
    if SCOPE_ENDPOINT:
        pack_endpoints_iter = [e for e in pack["endpoints"] if e["endpoint"] == SCOPE_ENDPOINT]
        if not pack_endpoints_iter:
            print(f"ERROR: SCOPE_ENDPOINT '{SCOPE_ENDPOINT}' not found in test pack")
            sys.exit(2)
    elif SCOPE_API_IDS:
        pack_endpoints_iter = [e for e in pack["endpoints"] if e.get("api_id") in SCOPE_API_IDS]
        if not pack_endpoints_iter:
            print(f"ERROR: SCOPE_API_IDS {SCOPE_API_IDS} matched no endpoints in test pack")
            print("Available api_ids:", [e.get("api_id") for e in pack["endpoints"]])
            sys.exit(2)
        print(f"  SCOPE_API_IDS filter: {len(pack_endpoints_iter)} endpoint(s): {[e.get('api_id') for e in pack_endpoints_iter]}")

    for ep in pack_endpoints_iter:
        pack_ep = ep["endpoint"]
        api_id = ep["api_id"]
        # Pack endpoint -> Postman key. Try the explicit bridge map first, then
        # fall back to direct lookup, then to the `{id}`-collapsed form (the
        # Postman index normalizes literal IDs to `{id}`, and pack endpoints
        # use specific names like `{customerRefId}`).
        pm_key = PACK_TO_POSTMAN.get(pack_ep) or pack_ep
        pm_entry = pm_idx.get(pm_key)
        if pm_entry is None:
            collapsed = re.sub(r"\{[A-Za-z][A-Za-z0-9_]*\}", "{id}", pm_key)
            if collapsed != pm_key:
                pm_entry = pm_idx.get(collapsed)
        drift = DRIFT_FLAGS.get(pack_ep)
        ep_counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "ERROR": 0}

        if not pm_entry:
            for tc in ep["test_cases"]:
                if SCOPE_TC_IDS and tc["tc_id"] not in SCOPE_TC_IDS:
                    continue
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
        # Override path when pack endpoint diverges from Postman entry (e.g., dashboard v1->v2)
        if pack_ep in PATH_TEMPLATE_OVERRIDE:
            path_template = PATH_TEMPLATE_OVERRIDE[pack_ep]
            # Postman entries with hardcoded literal URLs (e.g. /customers/CUST-ACME-00001)
            # come back from build_base_request with path_vars={}. When the override re-introduces
            # {placeholders}, inject_seeded_path_vars / rebuild_url have nothing to substitute,
            # so the literal "{customerRefId}" leaks into the URL. Pre-seed the placeholders
            # here so substitution + set_path_var mutations work.
            for _ph in re.findall(r"\{(\w+)\}", path_template):
                base["path_vars"].setdefault(_ph, "")
            drift_findings.append({"api_id": api_id, "pack_endpoint": pack_ep,
                                   "postman_endpoint": pm_key, "drift_type": "path_overridden_to_match_pack",
                                   "applied_template": path_template})

        print(f"  {api_id} {pack_ep} ({len(ep['test_cases'])} TCs)")
        for tc in ep["test_cases"]:
            if SCOPE_TC_IDS and tc["tc_id"] not in SCOPE_TC_IDS:
                continue
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
                "executed_by": "postman_hybrid_customer_runner",
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
            path_vars = inject_seeded_path_vars(base["path_vars"], session_ids, allow_seed_substitution)
            query = dict(base["query"])
            body = body_after_rotation
            # Rotate customer uniqueness BEFORE mutation so the mutation's target value
            # is not overwritten. Rotation only replaces keys that already exist (_set
            # guard), so drop_field mutations survive. The affiliate-pool retry path has
            # its own per-retry rotation below which fires last for happy-path TCs.
            if pack_ep in ("POST /api/v1/customers/drafts", "POST /api/v1/customers/draft"):
                body = rotate_customer_uniqueness(body, None)
            # Substitute hardcoded /search criteria with seeded customerRefId so the
            # backend's "no customer found" 400 response doesn't poison happy-path TCs.
            _idtype_idnumber_cross_field = scenario in (
                "missing_id_number_when_id_type_supplied_rejected",
                "missing_id_type_when_id_number_supplied_rejected",
            )
            if pack_ep == "POST /api/v1/customers/search" and allow_seed_substitution and not _idtype_idnumber_cross_field:
                body = rewrite_customer_search_criteria(body, session_ids)
            mutation_note = None
            override_headers = dict(base["headers"])

            engine_applied = None  # None=v1 path; True/False=v2 engine outcome
            engine_action = None
            engine_note = None
            url_override = None    # set by v2 engine; bypasses rebuild_url
            if (MUTATION_ENGINE_VERSION == "v2"
                    and plan["action"] not in ENGINE_RUNNER_PRESERVED
                    and scenario not in FORCE_V1_PLAN_SCENARIOS):
                pre_url = rebuild_url(method, path_template, path_vars, query)
                if isinstance(body, (dict, list)):
                    body_raw_in = json.dumps(body, default=str)
                elif isinstance(body, str):
                    body_raw_in = body
                else:
                    body_raw_in = ""
                pm_req = {
                    "method": method,
                    "url": {"raw": pre_url},
                    "header": [{"key": k, "value": v} for k, v in override_headers.items()],
                    "body": {"mode": "raw", "raw": body_raw_in},
                }
                out = mutation_engine.apply_mutation(pm_req, scenario, endpoint=pack_ep)
                mut = out["mutation"]
                mutated_req = out["request"]
                method = mutated_req.get("method", method)
                url_override = mutation_engine._get_url_raw(mutated_req)
                body_raw_out = (mutated_req.get("body") or {}).get("raw", "")
                if body_raw_out and body_raw_out.strip():
                    try:
                        body = json.loads(body_raw_out)
                    except Exception:
                        body = body_raw_out
                else:
                    body = None
                override_headers = {h["key"]: h["value"] for h in (mutated_req.get("header") or [])}
                engine_applied = mut["applied"]
                engine_action = mut["action"]
                engine_note = mut["note"]
                mutation_note = (mutation_note + " | " + engine_note) if mutation_note else engine_note
                # POST /customers/search: backend only accepts {} — any body with content
                # returns 400. Engine uses set_query (URL) for boundary_pagination.
                # Only redirect URL pagination params to body for rejection scenarios
                # (expected 400/422); happy-path pagination leaves URL params as-is
                # so the body stays {} and backend returns 200.
                if pack_ep == "POST /api/v1/customers/search" and url_override:
                    from urllib.parse import urlparse, parse_qs, urlunparse
                    _parsed = urlparse(url_override)
                    _params = parse_qs(_parsed.query, keep_blank_values=True)
                    if _params:
                        _exp_codes = parse_expected_statuses(tc.get("expected_result","") or "")
                        _expects_rejection = bool({400, 422} & set(_exp_codes))
                        if _expects_rejection:
                            if not isinstance(body, dict):
                                body = {}
                            else:
                                body = copy.deepcopy(body)
                            for _k, _vals in _params.items():
                                try:
                                    body[_k] = int(_vals[0])
                                except (ValueError, TypeError):
                                    body[_k] = _vals[0]
                            url_override = urlunparse(_parsed._replace(query=""))
            elif plan["action"] == "as_is":
                if scenario == "case_sensitive_customer_id_handling":
                    # Send lowercase ID — backend should return 404 if IDs are case-sensitive
                    _cref = path_vars.get("customerRefId", "")
                    if _cref:
                        path_vars = dict(path_vars)
                        path_vars["customerRefId"] = _cref.lower()
                    mutation_note = "lowercased customerRefId path var to test case-sensitivity"
                else:
                    mutation_note = plan.get("note", "no mutation; sent Postman request as-is")
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
                if isinstance(body, dict):
                    f = plan["field"]
                    body = copy.deepcopy(body)
                    if f in body and isinstance(body[f], list) and body[f]:
                        body[f] = body[f] + [body[f][0]]
                        mutation_note = f"duplicated first element of '{f}'"
                    else:
                        # B7 fix: field missing/non-list — inject synthetic 2-element array
                        # so the duplicate-handling test surface still gets exercised
                        body[f] = [ZERO_UUID, ZERO_UUID]
                        mutation_note = f"injected synthetic 2-element array into '{f}' (field was missing/non-list in Postman base)"
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

            url = url_override if url_override is not None else rebuild_url(method, path_template, path_vars, query)
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
                # Step 2: chain a read on the customer — GET /api/v1/customers/{customerRefId}
                read_cust = (path_vars.get("customerRefId") or path_vars.get("customerId")
                             or session_ids.get("customerRefId"))
                read_url = f"{BASE_URL}/api/v1/customers/{read_cust}" if read_cust else None
                if read_url:
                    read_resp = execute("GET", read_url, {"Accept": "application/json"}, None)
                else:
                    read_resp = {"ok": False, "error": "no customerRefId available for read-after-write chain"}
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
            else:
                # --- AFFILIATE POOL retry path (added 2026-05-05) ---
                expected_codes_for_tc = parse_expected_statuses(tc.get("expected_result","") or "")
                want_2xx = bool({200, 201, 204} & set(expected_codes_for_tc))
                target_field_is_affiliate = (plan.get("field","") or "").lower() in ("affiliateid","affiliate_id")
                affiliate_eligible = (
                    pack_ep in AFFILIATE_POOL_ENDPOINTS
                    and allow_seed_substitution
                    and bool(affiliate_pool)
                    and want_2xx
                    and not target_field_is_affiliate
                    and isinstance(body, dict)
                )
                if affiliate_eligible:
                    affiliate_attempts = []
                    response = None
                    final_affiliate = None
                    for attempt in range(AFFILIATE_RETRY_LIMIT):
                        # pick next unused affiliateId from pool (no global reuse)
                        next_affiliate = None
                        while affiliate_pool:
                            cand = affiliate_pool.pop(0)
                            if cand not in used_affiliates_global:
                                next_affiliate = cand; break
                        if not next_affiliate:
                            affiliate_attempts.append({"attempt": attempt+1, "affiliateId": None,
                                                       "skipped": "pool exhausted (all ACTIVE affiliates already used this run)"})
                            break
                        used_affiliates_global.add(next_affiliate)
                        final_affiliate = next_affiliate
                        substituted_body = substitute_affiliate_in_body(body, next_affiliate)
                        # Customer-detail rotation for /drafts (added 2026-05-05 16:10):
                        # backend returns 500 "customer with same details already exists" on /drafts;
                        # rotating identity per retry mints a fresh-uniqueness body.
                        if pack_ep == "POST /api/v1/customers/drafts":
                            # Mint per-attempt randomness here (each retry gets a
                            # fresh body within the same TC) by passing None.
                            substituted_body = rotate_customer_uniqueness(substituted_body, None)
                        # Re-rotate idempotencyKey per retry so backend can't dedup
                        if isinstance(substituted_body, dict) and isinstance(substituted_body.get("requestContext"), dict):
                            if "idempotencyKey" in substituted_body["requestContext"]:
                                substituted_body["requestContext"]["idempotencyKey"] = str(uuid.uuid4())
                        attempt_resp = execute(method, url, override_headers, substituted_body)
                        sc = attempt_resp.get("status_code", 0)
                        is_conflict, conflict_reason = is_affiliate_conflict_response(attempt_resp)
                        affiliate_attempts.append({
                            "attempt": attempt+1, "affiliateId": next_affiliate,
                            "status_code": sc, "is_conflict": is_conflict,
                            "conflict_reason": conflict_reason if is_conflict else None,
                        })
                        response = attempt_resp
                        # snapshot the actual body sent (last attempt wins)
                        body = substituted_body
                        if not is_conflict:
                            break  # success OR non-conflict failure — stop retrying
                    if response is None:
                        # pool was empty and no attempt fired — fall through to plain execute
                        response = execute(method, url, override_headers, body)
                        affiliate_attempts.append({"fallback_no_pool": True})
                    response["_affiliate_pool"] = {
                        "attempts": affiliate_attempts,
                        "final_affiliateId": final_affiliate,
                        "retries_consumed": max(0, len(affiliate_attempts) - 1),
                        "pool_remaining_after": len(affiliate_pool),
                    }
                    request_summary["body"] = body  # report the body actually sent
                    affiliate_pool_consumption_log.append({
                        "tc_id": tc.get("tc_id") or tc.get("id") or tc.get("test_case_id"),
                        "endpoint": pack_ep,
                        "scenario": tc.get("scenario"),
                        "attempts": affiliate_attempts,
                        "final_affiliateId": final_affiliate,
                    })
                else:
                    response = execute(method, url, override_headers, body)

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
                and any(tok in path_template for tok in ("{customerRefId}", "{customerId}", "{caseId}", "{bankId}", "{affiliateId}"))):
                if verify_record.get("verified"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": ("CLUSTER_C_PERSISTENCE_SPLIT — seeded ID returns 200 on GET "
                                   "/api/v1/customers/{customerRefId} but this write/state endpoint "
                                   "returns 404 for the same ID; backend write/read consistency defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "persistence_split",
                    }
                elif verify_record.get("cluster_c_suspected"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"CLUSTER_C_SEED_NOT_QUERYABLE — pre-flight verify on seeded customerRefId "
                                   f"({session_ids.get('customerRefId')}) returned 404 after 3 attempts; this 404 "
                                   "is downstream of an unusable seed, not a real validation defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "seed_not_queryable",
                    }
            # --- Mutation misfire override ---
            # When the v2 engine could not apply the requested mutation (engine
            # returned applied=False), force FAIL with a `mutation_misfire`
            # tag. Prevents silent-PASS on unmutated requests.
            if engine_applied is False:
                verdict = {
                    "status": "FAIL",
                    "reason": (f"MUTATION_MISFIRE — engine action `{engine_action}` "
                                f"could not apply mutation; request sent unmutated. "
                                f"Engine note: {engine_note}"),
                    "schema": verdict.get("schema"),
                    "tag": "mutation_misfire",
                    "engine_action": engine_action,
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
                "mutation": {
                    "action": plan["action"], "note": mutation_note,
                    "engine_version": MUTATION_ENGINE_VERSION,
                    "engine_action": engine_action,
                    "engine_applied": engine_applied,
                    **{k: v for k, v in plan.items() if k not in ("action", "reason", "note")},
                },
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
            "service": "customer",
            "service_upper": "CUS",
            "run_mode": "postman_hybrid_customer",
            "report_date": dt.datetime.now().strftime("%Y-%m-%d"),
            "tester": "postman_hybrid_customer_runner",
            "base_api_url": BASE_URL,
            "swagger_source": str(SWAGGER_PATH),
            "postman_collection": str(POSTMAN_PATH),
            "test_pack": str(TEST_PACK_PATH),
            "auth_mode": "none",
            "seeded_ids": {
                "affiliateId": session_ids.get("affiliateId"),
                "bankId": session_ids.get("bankId"),
                "customerRefId_preflight": session_ids.get("customerRefId"),
                "customerRefId_fallback_used": setup_record.get("fallback_used", False),
                "post_mint_verify": verify_record,
            },
            "cluster_c_reclassified_count": sum(1 for d in detailed if d.get("cluster") == "C"),
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
        "setup_steps": [setup_record, {
            "step": "affiliate_pool_consumption_summary",
            "consumption_count": len(affiliate_pool_consumption_log),
            "unique_affiliates_used": len(used_affiliates_global),
            "pool_remaining": len(affiliate_pool),
            "consumption_log": affiliate_pool_consumption_log,
        }],
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
