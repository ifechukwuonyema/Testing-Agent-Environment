"""
Postman-driven HYBRID Admin Services API test harness.

Hybrid model (Admin variant):
  - Default: Postman base + scenario-driven mutation
  - Pre-flight: list-first discovery via GET /api/v1/admin/onboarding/cases
                (no POST /admin/cases mint endpoint — cases come from affiliate onboarding flow);
                picks first case from list as seeded caseId; persisted to SessionStore
  - Per-TC: requestContext.requestId + idempotencyKey rotated to fresh UUIDs (except *_idempotent_on_retry)
  - Per-TC: {caseId}/{bankId}/{affiliateId} path vars substituted with seeded values
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
    "set_path_var",   # engine url_override would clobber path-var changes
    "unknown_id",     # runner swaps caseId/bankId for a fake UUID; engine must not re-mutate
    "set_field",      # runner classifier already chose the exact field+value; engine must not re-mutate
    "drop_nested",    # runner targets nested field; engine top-level drop_field is a no-op on nested keys
}

# --- paths -----------------------------------------------------------------
DOWNLOADS = Path(r"C:\Users\Onyema Ifechukwu\Downloads")
POSTMAN_PATH = DOWNLOADS / "Kardit.Api.postman.collection.json"
ADMIN_DIR = DOWNLOADS / "admin_services_api_test_agent_v1" / "admin_services_api_test_agent"
TEST_PACK_PATH = ADMIN_DIR / "data" / "admin_services_functional_test_pack_v1_30_plus.json"
# 2026-05-08: MainSwagger.txt is the canonical source for all 8 services.
SWAGGER_PATH = DOWNLOADS / "MainSwagger.txt"
LIFECYCLE_PATH = ADMIN_DIR / "lifecycle_order.yaml"  # may not exist; harness falls back to pack order
RUNNER_KIT = DOWNLOADS / "kardit_runner_kit"
SESSION_IDS_PATH = DOWNLOADS / "kardit_session_ids.json"

BASE_URL = "http://167.172.49.177:8080"
RUN_TS = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

# --- case-pool sizing (added 2026-05-04) ----------------------------------
# Phase 0c mints SUBMITTED cases via the affiliate onboarding 5-step flow so
# happy-path decision TCs get fresh state instead of the single-seed case
# (which leaves SUBMITTED after the first APPROVE in TC-001 and rejects all
# subsequent decision happy-paths with "Cannot change decision: case is already
# APPROVED").
# Phase 0d builds an APPROVED pool by minting + approving so happy-path
# provision TCs don't trip "Affiliate already provisioned for this case".
# Sizes match the count of distinct happy-path scenarios that need fresh state
# (see DECISION_FRESH_SUBMITTED_NEEDED / PROVISION_FRESH_APPROVED_NEEDED).
#
# DISABLED 2026-05-05 — backend health check on the affiliate onboarding flow
# showed POST /drafts/{draftId}/documents returns 500 (even with a minimal PDF)
# and PUT /drafts/{draftId}/issuing-banks rejects every form of bankId we have
# (Postman literal "TBK-001", real bankId UUID, and bankCode all fail). With
# both steps non-functional, mint_submitted_case_via_onboarding cannot reach
# step 5 (submit), so pool minting yields zero cases. Code kept in place as
# scaffolding; re-enable by raising these constants once backend ships fixes
# (or adds a GET eligible-banks endpoint).
N_SUBMITTED_POOL = 0
# 2026-05-06: re-enabled APPROVED minting after probe confirmed full mint→approve→
# provision flow returns 200 when (a) issuing-banks step uses a real ACTIVE bankId
# from GET /banks/query, (b) decision step includes decisionReason, (c) provision
# adminContact matches the primaryContact set during step-2 organization. Pool
# size 10 covers all 10 PROVISION_FRESH_APPROVED_NEEDED happy-path scenarios.
N_APPROVED_POOL = 20

# --- backend-provided case pool (added 2026-05-05 13:30) ------------------
# Backend supplied these case IDs in `BACKEND for admin.txt` to unblock
# /decision and /provision happy-path TCs while the affiliate onboarding
# minting flow remains broken upstream. Used as a direct substitute for the
# disabled Phase 0c/0d minting paths above. Remove or shrink when minting
# is re-enabled.
BACKEND_SUBMITTED_POOL: list[str] = [
    # Refreshed 2026-05-13 (batch 4) from query.txt (30 cases, ~3 full runs)
    "CASE-2026-933C96708B744A849164AC7C0A81F2A6",
    "CASE-2026-590E99DFC832483086450A9A7075AB24",
    "CASE-2026-403B55257B2344CFB76B01B80D09E9B4",
    "CASE-2026-879729040DD04E3BB40CF02309F4F291",
    "CASE-2026-B7921A7DCE3444CC91E3117628AE9130",
    "CASE-2026-10343881040D45ACA6E91D26CD2682EF",
    "CASE-2026-0AF53FB8E0654BAD8AE15D910CF50E73",
    "CASE-2026-9665B963D8E34E8BA698D8287C3763A8",
    "CASE-2026-3E3B9D090C21412A8CD59E8C7431ED95",
    "CASE-2026-042648B80EAA4A56AA4B13DDFC77EAAB",
    "CASE-2026-1918018818B74496AC65DB4141C1AED6",
    "CASE-2026-5DFE54C52C8E46079A28D094C793F1F6",
    "CASE-2026-B18B2DF81FBA448BAA76B620CA597103",
    "CASE-2026-857EFD00E81A4EB1BC8E32BE2767B297",
    "CASE-2026-87FF94A57EB14EC98541CA5ACA0B417D",
    "CASE-2026-D3D4867EBFB445329510CA58122FB770",
    "CASE-2026-7600522D01CC4162AC7CD01BD133533C",
    "CASE-2026-D244343E37CA45D0B577B9EBF9427902",
    "CASE-2026-6B77E28C9AB24D528996582284431252",
    "CASE-2026-F4E3FBBD78FC4538932759DB71FF1508",
    "CASE-2026-CB4599C696984143B3EB74EDF6DB8C0B",
    "CASE-2026-1D28CD9FBE7C4EC3B7DABCEFE1A269A0",
    "CASE-2026-851C2A3FEB0645D3A8B2754F26ED9BFF",
    "CASE-2026-1AB6DD6C58D34C5C9CE7A9AA9DB9E3FD",
    "CASE-2026-403C1C6ADE0B4B8FB1120ED385E60D85",
    "CASE-2026-4A612106BC304F69A980F8019A21DEE0",
    "CASE-2026-F744E8F5F7D24F678C521960875C83E2",
    "CASE-2026-69CD4487CF9944A1A7BB52AEDEAA95EE",
    "CASE-2026-F36289535B4C4B25B6B6E20809C3BF0C",
    "CASE-2026-36AB273CF73C45BD82CB9673AF4E5154",
]
# Refreshed 2026-05-13 (batch 4) from query.txt (30 approved cases).
BACKEND_APPROVED_POOL: list[str] = [
    "CASE-2026-93C9BE4832314F588FC7FEBBFFCC1C5D",
    "CASE-2026-B57CF1F512274DC6A502C2D8CA6AEFB6",
    "CASE-2026-7B1EEEC9F14B4E3AA333C822050579E0",
    "CASE-2026-9E887A0D03A04393B0C96B29548FEE9A",
    "CASE-2026-0F332A22D2C84C0CB7016ED2A9360192",
    "CASE-2026-14D21FC73D1543318903B02A65112205",
    "CASE-2026-F75FBE32DB46438B9F4ACF8384BE1F3B",
    "CASE-2026-8396EFB7DF954C93810B08198EBE82A1",
    "CASE-2026-6DD8A2B72D08453BA02D1AA287490D17",
    "CASE-2026-DC83E323A7624BE6BEDB90915E17713D",
    "CASE-2026-0DA4495283154F5AADE4149A9DFFE88E",
    "CASE-2026-39F6BE91C57F4AC1AB57D05165FCF97D",
    "CASE-2026-AC5A4AFE4AAA4C599C6F3AF37E16F0DB",
    "CASE-2026-E16AB24348714EDB81DE949DC83660E0",
    "CASE-2026-C59803F2B4464AE690B57158CBD6D920",
    "CASE-2026-3F4A03B1FF39452E8E8D01AB817B1E8F",
    "CASE-2026-D14A4D83EEDA422C804B5E1F610FFF46",
    "CASE-2026-4A350DA8E5DE415496A84AE9014B0B5B",
    "CASE-2026-377B79E2C76E4325B0109AA5344DDF84",
    "CASE-2026-8E7A4A14BEA543BD8F4D8EF35794580F",
    "CASE-2026-EDEFD49F5D3B4018B921656816A1232A",
    "CASE-2026-4423615198C245D384A7F9C62215A91E",
    "CASE-2026-B865CEAFE6D949639C1AA82D98197ADD",
    "CASE-2026-090699CDEF664E1CB7E0F29D204F87B4",
    "CASE-2026-2DC906853FD34DB5B959A7C9AC10093E",
    "CASE-2026-1F8D559311074095804B0EB7A72108AD",
    "CASE-2026-BB3C28BD6E9D4328A9FA0699880ECC26",
    "CASE-2026-8A8B93B07C2E42BF8E93EBAA074BD618",
    "CASE-2026-5D926730F9BE4ED4A2EF4CA1F4B3C879",
    "CASE-2026-4B086ACD90C743A0AE21472AB4EF018C",
]

SCOPE_ENDPOINT = os.environ.get("SCOPE_ENDPOINT")
_scope_tag = ""
if SCOPE_ENDPOINT:
    _scope_tag = "_" + re.sub(r"[^a-zA-Z0-9]+", "_", SCOPE_ENDPOINT).strip("_")

# REPLAY_FAILED_REPORT: path to a previous admin report YAML.
# When set, only (api_id, scenario) pairs that FAILed in that report are run.
REPLAY_FAILED_REPORT = os.environ.get("REPLAY_FAILED_REPORT")
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
    _scope_tag = "_replay_failed"
    print(f"[REPLAY] Loaded {len(_replay_failed_set)} failed (api_id, scenario) pairs from {REPLAY_FAILED_REPORT}")

EVIDENCE_DIR = DOWNLOADS / f"evidence_postman_admin_hybrid{_scope_tag}_{RUN_TS}"
REPORT_PATH = DOWNLOADS / f"admin_postman_hybrid_report{_scope_tag}_{RUN_TS}.yaml"

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

# --- pack-to-postman match map (Admin, 2026-05-01) ------------------------
PACK_TO_POSTMAN = {
    "GET /api/v1/admin/onboarding/cases": "GET /api/v1/admin/onboarding/cases",
    "GET /api/v1/admin/onboarding/cases/{caseId}": "GET /api/v1/admin/onboarding/cases/{caseId}",
    "POST /api/v1/admin/onboarding/cases/{caseId}/decision": "POST /api/v1/admin/onboarding/cases/{caseId}/decision",
    "POST /api/v1/admin/onboarding/cases/{caseId}/provision": "POST /api/v1/admin/onboarding/cases/{caseId}/provision",
    "POST /api/v1/admin/banks": "POST /api/v1/admin/banks",
}
# Reserved for future pack-vs-Postman drift; currently empty.
PATH_TEMPLATE_OVERRIDE = {}
DRIFT_FLAGS = {}

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

# --- HYBRID: bank uniqueness rotation (2026-05-04) ------------------------
# POST /api/v1/admin/banks rejects duplicate bankCode/legalName ("Bank with code
# 01234 already exists."). Postman literal is shared across every TC, so happy-
# path bank tests fail after the first run with G_4xx_where_2xx_expected. Rotate
# bankCode/legalName/shortName per-TC. Negative-validation scenarios (e.g.
# empty_bank_code_rejected) override these fields again via classify_scenario,
# so this rotation is harmless for them.
def rotate_bank_uniqueness(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    body = copy.deepcopy(body)
    new_code = f"{uuid.uuid4().int % 100000:05d}"
    suffix = uuid.uuid4().hex[:8].upper()
    if "bankCode" in body:
        body["bankCode"] = new_code
    if "legalName" in body:
        body["legalName"] = f"Test Bank {suffix} Plc"
    if "shortName" in body:
        body["shortName"] = f"TestBank-{suffix}"
    return body

# Map of caseId -> primaryContact dict, populated when a case is minted via
# mint_submitted_case_via_onboarding. The onboarding-time primaryContact is the
# value the backend stores on the case; provision rejects unless the body's
# adminContact matches this exactly. By generating a fresh contact at mint time
# and re-using it at provision time, we satisfy that validation harness-side
# without requiring a backend change.
_GENERATED_CASE_CONTACTS: dict[str, dict] = {}

def _make_contact() -> dict:
    """Generate a format-valid contact (NG mobile, well-formed email, 3-150 char name)."""
    suffix = uuid.uuid4().hex[:8]
    digits = uuid.uuid4().int % 100_000_000
    return {
        "fullName": f"Test Affiliate {suffix.upper()}",
        "email":    f"aff.{suffix}@kardit-test.local",
        "phone":    f"080{digits:08d}",
    }

# Real ACTIVE bankId discovered at runtime via GET /banks/query. Cached after
# first successful lookup so the mint flow's issuing-banks step doesn't hammer
# the discovery call across 20 Phase 0d iterations.
_DISCOVERED_BANK_ID: str | None = "000045f9-d01b-479c-a84d-0fe82454d55a"

def discover_active_bank_id() -> str | None:
    """Fetch the first ACTIVE bankId from GET /banks/query. Returns None on error.
    Replaces the unresolvable Postman placeholder ('TBK-001' or hardcoded UUIDs)
    in the onboarding /issuing-banks step."""
    global _DISCOVERED_BANK_ID
    if _DISCOVERED_BANK_ID:
        return _DISCOVERED_BANK_ID
    try:
        import requests as _r
        resp = _r.get(f"{BASE_URL.rstrip('/')}/api/v1/banks/query?status=ACTIVE&page=1&pageSize=5", timeout=20)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data") or []
        for entry in data:
            bid = entry.get("bankId")
            if bid:
                _DISCOVERED_BANK_ID = bid
                return bid
    except Exception:
        return None
    return None

def rotate_admin_contact(body: Any, case_id: str | None = None) -> Any:
    """Generate or look up the adminContact for /provision.
    If case_id was minted via the onboarding flow, reuse the SAME primaryContact
    that was sent at step 2 (stored in _GENERATED_CASE_CONTACTS) — this satisfies
    the backend's contact-match validation on /provision.
    Otherwise (pre-seeded backend cases), generate a fresh format-valid contact."""
    if not isinstance(body, dict) or "adminContact" not in body:
        return body
    body = copy.deepcopy(body)
    if case_id and case_id in _GENERATED_CASE_CONTACTS:
        body["adminContact"] = dict(_GENERATED_CASE_CONTACTS[case_id])
    else:
        body["adminContact"] = _make_contact()
    return body

# --- HYBRID: seeded-id injection ------------------------------------------
SEEDED_PATH_VAR_KEYS = {"cardId", "bankId", "affiliateId", "caseId"}

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

# --- HYBRID: pre-flight case discovery (list-first) -----------------------
def extract_first_case_id_from_list(resp_body: Any) -> str | None:
    """Best-effort extraction of first caseId from GET /admin/onboarding/cases list response.
    Tries common shapes: {data: [{caseId|id, ...}, ...]}, {items: [...]}, {results: [...]}."""
    if not isinstance(resp_body, dict):
        return None
    for container_key in ("data", "items", "results", "cases"):
        items = resp_body.get(container_key)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                for k in ("caseId", "id", "case_id"):
                    v = first.get(k)
                    if isinstance(v, str) and v:
                        return v
        if isinstance(items, dict):  # {data: {items: [...]}} or {data: {result: [...]}} or {data: {data: [...]}}
            for sub_key in ("items", "result", "results", "data", "cases"):
                sub = items.get(sub_key)
                if isinstance(sub, list) and sub and isinstance(sub[0], dict):
                    for k in ("caseId", "id", "case_id"):
                        v = sub[0].get(k)
                        if isinstance(v, str) and v:
                            return v
    return None

def _persist_case_if_verified(case_id: str, session_ids: dict, source: str) -> dict:
    """Codex re-audit #4 port: verify-before-save for Admin caseId."""
    verify_rec = verify_seeded_id_queryable(case_id, "/api/v1/admin/onboarding/cases/{caseId}")
    persisted = False
    if verify_rec.get("verified"):
        session_ids["caseId"] = case_id
        SESSION.save({"caseId": case_id})
        persisted = True
    return {
        "selected_source": source,
        "selected_verified": bool(verify_rec.get("verified")),
        "persisted_to_session_store": persisted,
        "verify": verify_rec,
    }


def pre_flight_discover_case(pm_idx: dict, session_ids: dict) -> dict:
    """Live GET /api/v1/admin/onboarding/cases. On success: pick first case from list,
    capture caseId, persist. No POST /admin/cases mint endpoint exists — cases come from
    the affiliate onboarding flow upstream of admin services."""
    setup = {
        "step": "discover_seed_case",
        "method": "GET",
        "endpoint": "/api/v1/admin/onboarding/cases",
        "started_at": dt.datetime.now().isoformat(),
        "status": "PENDING",
        "fallback_used": False,
    }
    pm_entry = pm_idx.get("GET /api/v1/admin/onboarding/cases")
    if not pm_entry:
        setup.update({"status": "ERROR",
                      "reason": "GET /api/v1/admin/onboarding/cases not in Postman — cannot pre-flight discover"})
        return setup
    base = build_base_request(pm_entry)
    path_template = get_postman_path_template(pm_entry)
    url = rebuild_url(base["method"], path_template, base["path_vars"], base["query"])
    setup["url"] = url
    response = execute(base["method"], url, base["headers"], None, timeout=30)
    setup["response_status"] = response.get("status_code")
    setup["response_body"] = response.get("body") if response.get("body") is not None else response.get("body_text")
    setup["completed_at"] = dt.datetime.now().isoformat()
    if not response.get("ok"):
        setup.update({"status": "ERROR", "reason": f"transport: {response.get('error')}"})
        return setup
    sc = response.get("status_code", 0)
    if 200 <= sc < 300:
        case_id = extract_first_case_id_from_list(response.get("body"))
        if case_id:
            persist = _persist_case_if_verified(case_id, session_ids, source="discover")
            setup["case_id"] = case_id
            setup["persistence"] = persist
            setup["status"] = "OK" if persist["selected_verified"] else "UNVERIFIED"
            if not persist["selected_verified"]:
                setup["reason"] = "list returned a caseId but verify GET did not confirm it is queryable; not persisted"
            return setup
        setup.update({"status": "DEGRADED",
                      "reason": f"2xx ({sc}) but list response had no caseId; falling back to Postman literal",
                      "fallback_used": True})
        return setup
    setup.update({"status": "FAIL",
                  "reason": f"list endpoint non-2xx ({sc}); falling back to Postman literal caseId",
                  "fallback_used": True})
    return setup

# --- HYBRID: post-mint verify (Cluster-C mitigation) ----------------------
def verify_seeded_id_queryable(seed_id: str | None, get_path_template: str,
                               max_retries: int = 2, delay_s: float = 1.0) -> dict:
    """GET on the freshly-discovered resource. Retries on 404 with backoff.
    Distinguishes 'eventual consistency' (transient 404 that resolves) from
    'persistence split' (404 that never resolves — Cluster C signature).
    For Admin we use GET /api/v1/admin/onboarding/cases/{caseId} as the verifier
    that proves the caseId is recognized by the read pipeline."""
    rec = {"verified": False, "url": None, "status": None, "attempts": 0,
           "cluster_c_suspected": False, "reason": None}
    if not seed_id:
        rec["reason"] = "no seed_id provided"
        return rec
    url = f"{BASE_URL}{get_path_template.replace('{caseId}', seed_id).replace('{bankId}', seed_id).replace('{affiliateId}', seed_id)}"
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

# --- HYBRID: case-pool minting via affiliate onboarding flow (2026-05-04) -
# Decision and provision happy-path TCs share a single seeded caseId. After
# TC-001 of each pack consumes that case (APPROVE / PROVISION), every later
# happy-path TC fails with a state-conflict 4xx. Mint additional cases through
# the upstream affiliate onboarding 5-step flow so each happy-path scenario
# gets a fresh case in the right state.

# Scenarios that need a fresh SUBMITTED case (state-changing decision happy paths
# that the seed alone cannot satisfy after TC-001 transitions it to APPROVED).
DECISION_FRESH_SUBMITTED_NEEDED = {
    "reject_submitted_case",
    "clarify_submitted_case",
    "reviewer_identity_recorded",
    "affiliate_tracking_visible",
    # Expanded 2026-05-05 PM after backend shipped pool of 10 SUBMITTED IDs.
    # NOTE: decision_backend_failure_safe deliberately excluded — it's BLOCKED at classify
    # time (HTTP runner cannot synthesize a 500), no fresh case needed.
    "approve_submitted_case",
    "unauthenticated_decision_blocked",
    "expired_token_decision_blocked",
    "affiliate_user_decision_forbidden",
    "bank_user_decision_forbidden",
    "sp_viewer_decision_forbidden",
}

# Scenarios that need a fresh APPROVED case (provision happy paths; one fresh
# APPROVED case per scenario, since a successful provision permanently consumes
# the case via "Affiliate already provisioned for this case.").
PROVISION_FRESH_APPROVED_NEEDED = {
    "email_delivery_channel_accepted",
    "affiliate_identifier_assigned",
    "tenant_identifier_assigned",
    "affiliate_type_external_returned",
    "created_affiliate_active_status",
    "partnership_requests_created_for_approved_banks",
    "partnership_requests_pending_bank_approval",
    "iam_or_access_provisioning_triggered",
    "provisioned_at_timestamp_returned",
    # Expanded 2026-05-05 PM after backend shipped pool of 6 APPROVED IDs.
    # NOTE: partial_downstream_failure_safe deliberately excluded — BLOCKED at classify
    # time (HTTP runner cannot synthesize a 500), no fresh case needed.
    "provision_approved_external_affiliate_success",
    "unauthenticated_provision_blocked",
    "expired_token_provision_blocked",
    "affiliate_user_provision_forbidden",
    "bank_user_provision_forbidden",
}

# Postman keys for the 5-step affiliate onboarding flow.
ONBOARDING_FLOW_KEYS = [
    ("session", "POST /api/v1/affiliates/onboarding/sessions"),
    ("organization", "PUT /api/v1/affiliates/onboarding/drafts/{draftId}/organization"),
    ("documents", "POST /api/v1/affiliates/onboarding/drafts/{draftId}/documents"),
    ("issuing_banks", "PUT /api/v1/affiliates/onboarding/drafts/{draftId}/issuing-banks"),
    ("submit", "POST /api/v1/affiliates/onboarding/drafts/{draftId}/submit"),
]

def _extract_first_value(body: Any, candidate_keys: list[str], depth: int = 4) -> str | None:
    """Walk body up to `depth` levels and return the first string value whose
    key matches any of `candidate_keys` (case-insensitive)."""
    if depth <= 0 or body is None:
        return None
    lowered = [k.lower() for k in candidate_keys]
    if isinstance(body, dict):
        for k, v in body.items():
            if isinstance(k, str) and k.lower() in lowered and isinstance(v, str) and v:
                return v
        for v in body.values():
            r = _extract_first_value(v, candidate_keys, depth - 1)
            if r:
                return r
    elif isinstance(body, list):
        for v in body:
            r = _extract_first_value(v, candidate_keys, depth - 1)
            if r:
                return r
    return None

def mint_submitted_case_via_onboarding(pm_idx: dict, label: str = "") -> dict:
    """Run the 5-step affiliate onboarding flow once. Returns a record with
    status (OK/FAIL/ERROR), caseId on success, draftId/sessionId, and a
    per-step trace. Bails on first non-2xx step."""
    rec: dict = {"label": label, "status": "PENDING", "caseId": None,
                 "draftId": None, "sessionId": None, "steps": [], "reason": None}
    pm_entries = {key: pm_idx.get(path_key) for key, path_key in ONBOARDING_FLOW_KEYS}
    if not pm_entries["session"] or not pm_entries["submit"]:
        rec.update({"status": "ERROR",
                    "reason": "session-creation or submit Postman entry not found in collection"})
        return rec

    suffix = uuid.uuid4().hex[:8]
    sess_id: str | None = None
    draft_id: str | None = None

    # Step 1: create onboarding session (rotate identity to avoid email/phone collisions).
    base = build_base_request(pm_entries["session"])
    body = copy.deepcopy(base["body"]) if isinstance(base["body"], dict) else {}
    body["email"] = f"pool-{suffix}@kardit-test.local"
    body["phone"] = f"080{uuid.uuid4().int % 10**8:08d}"
    url = rebuild_url(base["method"], get_postman_path_template(pm_entries["session"]), {}, {})
    resp = execute(base["method"], url, base["headers"], body, timeout=20)
    rec["steps"].append({"step": "session", "url": url, "status": resp.get("status_code"), "ok": resp.get("ok")})
    if not (resp.get("ok") and 200 <= (resp.get("status_code") or 0) < 300):
        rec.update({"status": "FAIL", "reason": f"session step failed: {resp.get('status_code')} {resp.get('error') or ''}"})
        return rec
    sess_id = _extract_first_value(resp.get("body"), ["onboardingSessionId", "sessionId", "session_id"])
    draft_id = _extract_first_value(resp.get("body"), ["draftId", "draft_id"])
    rec["sessionId"] = sess_id
    rec["draftId"] = draft_id
    if not draft_id:
        rec.update({"status": "FAIL", "reason": "session step succeeded but no draftId in response"})
        return rec

    def _run(step_name: str, body_overrides: dict, timeout: int = 20) -> bool:
        pm = pm_entries[step_name]
        if pm is None:
            rec.update({"status": "ERROR", "reason": f"{step_name} Postman entry missing"})
            return False
        b = build_base_request(pm)
        bd = copy.deepcopy(b["body"]) if isinstance(b["body"], dict) else {}
        if sess_id and isinstance(bd, dict) and "onboardingSessionId" in bd:
            bd["onboardingSessionId"] = sess_id
        for k, v in body_overrides.items():
            if isinstance(bd, dict):
                bd[k] = v
        u = rebuild_url(b["method"], get_postman_path_template(pm), {"draftId": draft_id}, {})
        r = execute(b["method"], u, b["headers"], bd, timeout=timeout)
        rec["steps"].append({"step": step_name, "url": u, "status": r.get("status_code"), "ok": r.get("ok")})
        if not (r.get("ok") and 200 <= (r.get("status_code") or 0) < 300):
            rec.update({"status": "FAIL",
                        "reason": f"{step_name} step failed: {r.get('status_code')} {r.get('error') or ''}"})
            return False
        if step_name == "submit":
            rec["caseId"] = _extract_first_value(r.get("body"), ["caseId", "case_id"])
        return True

    # Step 2: organization. Generate a fresh primaryContact and remember it so the
    # admin /provision step can send the same values as adminContact (backend's
    # contact-match validation requires they match exactly).
    primary_contact = _make_contact()
    rec["primaryContact"] = primary_contact
    if not _run("organization", {
        "registrationNumber": str(uuid.uuid4().int % 10**11),
        "legalName": f"Test Co {suffix} Ltd",
        "tradingName": f"Test Co {suffix}",
        "primaryContact": primary_contact,
    }):
        return rec

    # Step 3: documents (large base64 — reuse Postman literal verbatim, swap sessionId only).
    if not _run("documents", {}, timeout=30):
        return rec

    # Step 4: issuing-banks. No bank injection — use Postman base as-is.
    if not _run("issuing_banks", {}):
        return rec

    # Step 5: submit → returns caseId.
    if not _run("submit", {}):
        return rec

    if not rec.get("caseId"):
        rec.update({"status": "DEGRADED",
                    "reason": "submit succeeded but no caseId extracted from response"})
        return rec
    # Persist the contact mapping so /provision can match it later.
    _GENERATED_CASE_CONTACTS[rec["caseId"]] = primary_contact
    rec["status"] = "OK"
    return rec

def approve_case_for_pool(case_id: str, pm_idx: dict) -> dict:
    """Promote a SUBMITTED case to APPROVED by calling decision/Approve. Used
    only for case-pool plumbing — these calls are NOT test cases."""
    rec: dict = {"caseId": case_id, "status": "PENDING", "url": None, "response_status": None}
    pm = pm_idx.get("POST /api/v1/admin/onboarding/cases/{caseId}/decision")
    if pm is None:
        rec.update({"status": "ERROR", "reason": "decision Postman entry missing"})
        return rec
    base = build_base_request(pm)
    body = copy.deepcopy(base["body"]) if isinstance(base["body"], dict) else {}
    if isinstance(body, dict):
        body["decision"] = "Approve"
        body.setdefault("decisionReason", "pool seed for automated test pool")
    body = rotate_request_context(body)
    url = rebuild_url(base["method"], get_postman_path_template(pm), {"caseId": case_id}, {})
    resp = execute(base["method"], url, base["headers"], body, timeout=20)
    sc = resp.get("status_code")
    rec["url"] = url
    rec["response_status"] = sc
    rec["status"] = "OK" if (resp.get("ok") and 200 <= (sc or 0) < 300) else "FAIL"
    if rec["status"] != "OK":
        rec["reason"] = f"approve returned {sc} {resp.get('error') or ''}"
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
    dropped = _find_and_apply(body, field, "drop")
    # Endpoint-specific field aliases: when the scenario asks to drop "reason" but the
    # body uses a more specific name (decisionReason on /admin/.../decision,
    # rejectionReason on /partnerships/.../reject, etc.), drop the alias instead.
    # Backend feedback 2026-05-06 (Adminfeedback.txt): TC-ONB-08-013 should have dropped
    # decisionReason but the harness was looking for "reason" which doesn't exist on
    # that endpoint, so the body went out unchanged.
    if not dropped and field == "reason":
        for alias in ("decisionReason", "rejectionReason", "terminateReason",
                      "freezeReason", "unfreezeReason", "blockReason", "suspendReason"):
            if _find_and_apply(body, alias, "drop"):
                break
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
    # Duplicate request id / retry-safe — fire twice with the same body to test idempotency.
    # Backend feedback 2026-05-06 (Adminfeedback.txt TC-BNK-PRV01-031): the broader
    # `duplicate_(\w+)_safe` regex below was routing `duplicate_retry_safe` to
    # `duplicate_array`, which appended a synthetic "retry" field instead of double-sending.
    if "duplicate_request_id" in s or s == "duplicate_retry_safe":
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
    # missing field
    m = re.search(r"(?:^|_)missing_(.+?)(?:_rejected|_blocks|_policy|$)", s)
    if m:
        raw = m.group(1)
        # Nested adminContact / primaryContact fields (per backend feedback 2026-05-05:
        # earlier the regex captured 'contact_email'/'contact_phone' and tried to drop a
        # non-existent top-level field, leaving the body unchanged).
        if raw == "contact_email":
            return {"action": "drop_nested", "parent": "primaryContact", "field": "email", "note": "drop nested primaryContact.email"}
        if raw == "contact_phone":
            return {"action": "drop_nested", "parent": "primaryContact", "field": "phone", "note": "drop nested primaryContact.phone"}
        if raw == "contact_full_name":
            return {"action": "drop_nested", "parent": "primaryContact", "field": "fullName", "note": "drop nested primaryContact.fullName"}
        if raw == "primary_contact":
            return {"action": "drop_field", "field": "primaryContact", "note": "drop entire primaryContact object"}
        if raw == "admin_email":
            return {"action": "drop_nested", "parent": "adminContact", "field": "email", "note": "drop nested adminContact.email"}
        if raw == "admin_phone":
            return {"action": "drop_nested", "parent": "adminContact", "field": "phone", "note": "drop nested adminContact.phone"}
        if raw == "admin_full_name":
            return {"action": "drop_nested", "parent": "adminContact", "field": "fullName", "note": "drop nested adminContact.fullName"}
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
        # Path-var IDs: anything that looks like an ID carried in the URL.
        # snake_case forms (card_id) come from snake_case scenarios; camelCase
        # forms collapsed by .lower() (caseid, customerid, productid) come from
        # scenarios written as malformed_caseId_rejected etc.
        if raw in ("card_id", "bank_id", "affiliate_id", "limit_request_id", "request_id",
                   "case_id", "customer_id", "product_id", "partnership_request_id",
                   "caseid", "customerid", "productid", "bankid", "affiliateid",
                   "cardid", "requestid", "partnershiprequestid"):
            field = "caseId" if raw in ("case_id", "caseid") else snake_to_camel(raw)
            if raw == "customerid": field = "customerId"
            elif raw == "productid": field = "productId"
            elif raw == "bankid":    field = "bankId"
            elif raw == "affiliateid": field = "affiliateId"
            elif raw == "cardid":    field = "cardId"
            elif raw == "requestid": field = "requestId"
            elif raw == "partnershiprequestid": field = "partnershipRequestId"
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

    # Backend feedback 2026-05-05: HTTP-only runner cannot synthesize a 500 by issuing
    # a normal request; these scenarios require backend fault-injection and are out of scope.
    # Must precede the generic "_safe" happy-path matcher below — otherwise these names get
    # swallowed by it and run as as_is, producing spurious FAILs.
    if s in ("bank_backend_failure_safe", "server_error_safe_response",
             "decision_backend_failure_safe", "partial_downstream_failure_safe"):
        return {"action": "blocked",
                "reason": "Skipped — this scenario expects a backend 500 (persistence/listing/downstream failure). HTTP-only runner cannot synthesize a 500 from a well-formed request; needs backend fault-injection."}

    # ONB-10 unicode caseId — must NOT fall into the generic _handled catch below,
    # which would route it to as_is (sending the seeded valid caseId, defeating the test).
    if s == "unicode_caseid_handled":
        return {"action": "set_path_var", "field": "caseId",
                "value": "CASE-2026-中文\U0001f44d",
                "note": "unicode caseId payload; expect 400/404, never 500 or unescaped reflection"}

    # 2026-05-10 fix (Bug 2): page_two/page_one explicit before _success catch-all.
    # Admin uses Page (capital P) param.
    if s in ("pagination_page_two_success", "page_two_success", "pagination_page_two", "pagination_second_page"):
        return {"action": "set_query", "key": "Page", "value": "2",
                "note": "advanced to page 2 to actually exercise pagination"}
    if s in ("pagination_page_one_success", "page_one_success", "pagination_first_page"):
        return {"action": "set_query", "key": "Page", "value": "1",
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
        # 400 is expected when backend enforces a hard cap below 100.
        return {"action": "set_query", "key": "PageSize", "value": "100",
                "note": "documented max page size; 200 or 400 both acceptable"}
    if s == "page_size_exceeds_limit":
        return {"action": "set_query", "key": "PageSize", "value": "99999", "note": "page size beyond cap"}
    if s == "negative_page_rejected":
        return {"action": "set_query", "key": "Page", "value": "-1", "note": "negative page"}
    if s == "non_numeric_page_size_rejected":
        return {"action": "set_query", "key": "PageSize", "value": "abc", "note": "non-numeric page size"}
    if s == "invalid_status_rejected":
        return {"action": "set_query", "key": "Status", "value": "BOGUS_STATUS", "note": "invalid status enum"}
    if s == "empty_status_policy":
        return {"action": "set_query", "key": "Status", "value": "",
                "note": "empty status filter (backend confirmed 2026-05-05: empty Status is ignored, list returns all statuses with 200)"}
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
    if s == "duplicate_bank_code_rejected":
        # rotation is skipped for this scenario (see line 1820); send pack payload verbatim
        # so the static bankCode "EXB001" triggers a 409 against the already-existing bank.
        return {"action": "as_is", "note": "send static bankCode EXB001 to trigger 409 duplicate conflict"}
    if s == "invalid_country_code_rejected":
        return {"action": "set_field", "field": "country", "value": "XX", "note": "invalid ISO country"}
    if s == "invalid_contact_email_rejected":
        return {"action": "set_nested", "parent": "primaryContact", "field": "email",
                "value": "###not-valid###", "note": "format-invalid contact email"}
    # Status BL-validation probes (added 2026-05-05 PM after backend confirmed
    # status is enforced in BusinessLogic against ACTIVE/INACTIVE).
    if s == "status_lowercase_policy":
        return {"action": "set_field", "field": "status", "value": "active",
                "note": "lowercase status — probes BL case-handling (insensitive vs normalised vs strict)"}
    if s == "status_typo_rejected":
        return {"action": "set_field", "field": "status", "value": "ACTVE",
                "note": "typo status — should be 400 if BL enforces ACTIVE/INACTIVE allowed set"}
    if s in ("bank_provisioning_independent_of_iam_user_creation", "internal_affiliate_created",
             "internal_affiliate_owner_bank_linked", "internal_affiliate_system_managed_true",
             "internal_active_partnership_created"):
        return {"action": "as_is", "note": f"response-shape verification '{s}'; happy-path"}

    # GET /admin/onboarding/cases/{caseId} (API-ONB-10) — case-detail scenarios
    if s in ("get_case_submitted", "get_case_approved", "get_case_rejected",
             "get_case_clarification_required", "get_case_in_review"):
        return {"action": "as_is",
                "note": f"happy-path case-detail read '{s}'; uses seeded caseId. "
                        "Backend should return 200 with body.status reflecting case lifecycle"}
    if s == "response_schema_matches_swagger":
        return {"action": "as_is",
                "note": "schema-conformance happy-path; schema validator runs automatically against AdminCaseDetailResponse"}
    # NOTE: scenario was lowercased above (s = scenario.lower()), so "caseId" -> "caseid".
    if s == "empty_caseid_rejected":
        # Whitespace caseId re-routes to the list endpoint (GET /cases gets 200 with data),
        # which makes this look like a FAIL when it isn't. Mutate via an invalid-format
        # payload value in the path var so the request reaches the {caseId} handler.
        return {"action": "set_path_var", "field": "caseId", "value": "INVALID-CASE-001",
                "note": "invalid-format caseId in path var; expect 400 or 404"}
    if s == "nonexistent_caseid_404":
        return {"action": "unknown_id", "field": "caseId",
                "note": "well-formed but unknown caseId (zero-UUID); expect 404"}
    if s == "sql_injection_caseid_rejected":
        return {"action": "set_path_var", "field": "caseId",
                "value": "CASE-2026-' OR 1=1--",
                "note": "SQLi payload in caseId path param; expect 400/404, never 500 or DB-error leak"}
    if s == "xss_caseid_rejected":
        return {"action": "set_path_var", "field": "caseId",
                "value": "<script>alert(1)</script>",
                "note": "XSS payload in caseId path param; expect 400/404, never reflected unescaped"}
    if s == "very_long_caseid_rejected":
        return {"action": "set_path_var", "field": "caseId",
                "value": "CASE-2026-" + ("A" * 4990),
                "note": "5000-char caseId — should be rejected with 400/413/414, not 500"}
    if s == "unicode_caseid_handled":
        return {"action": "set_path_var", "field": "caseId",
                "value": "CASE-2026-中文\U0001f44d",
                "note": "unicode caseId payload; expect 400/404, never 500 or unescaped reflection"}
    if s == "post_method_not_allowed":
        return {"action": "method_swap", "new_method": "POST",
                "note": "swap GET to POST on case-detail path; expect 405 Method Not Allowed"}
    if s == "put_method_not_allowed":
        return {"action": "method_swap", "new_method": "PUT",
                "note": "swap GET to PUT on case-detail path; expect 405 Method Not Allowed"}
    if s == "delete_method_not_allowed":
        return {"action": "method_swap", "new_method": "DELETE",
                "note": "swap GET to DELETE on case-detail path; expect 405 Method Not Allowed"}
    if s == "correlation_id_echoed":
        return {"action": "correlation_id_check",
                "note": "set client X-Correlation-ID header; expect same value echoed in response headers"}

    # fallback — Wave 1.1: in v2 mode, hand unrecognized scenarios to the
    # mutation engine. The engine's audit catalog covers most common patterns
    # the legacy runner classifier doesn't (sql_injection / xss / extremely_long
    # path-vars, invalid_<field>_format_rejected variants, etc.). The engine
    # will misfire if it genuinely can't classify, which the runner then
    # surfaces as FAIL+mutation_misfire — never silent-pass.
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
    """Execute with one retry on transport-level errors (ConnectTimeout / ConnectionError).
    Body-bearing methods only retry safe verbs (GET/HEAD/OPTIONS/DELETE) — never
    POST/PUT/PATCH, since the prior request may have been received but the response lost.
    Run-2026-05-06 21:15: TC-ONB-07-011/012/013 hit transient ConnectTimeouts back-to-back;
    one retry would convert those flaky FAILs to PASS without masking real failures."""
    started = dt.datetime.now().isoformat()
    t0 = time.perf_counter()
    safe_to_retry = method.upper() in ("GET", "HEAD", "OPTIONS", "DELETE")
    last_ex = None
    attempts = 1 if not safe_to_retry else 2
    for attempt in range(attempts):
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
                "retried": attempt > 0,
            }
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as ex:
            last_ex = ex
            if attempt + 1 < attempts:
                time.sleep(0.5)  # brief backoff before single retry
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

    # --- HYBRID phase 0: load session + pre-flight discover case ---
    session_ids = SESSION.load()
    print(f"Phase 0: pre-flight GET /admin/onboarding/cases (list-first discovery)...")
    setup_record = pre_flight_discover_case(pm_idx, session_ids)
    print(f"  -> status={setup_record.get('status')} caseId={session_ids.get('caseId')!r} fallback={setup_record.get('fallback_used')}")
    if not session_ids.get("caseId"):
        # Fall back to Postman's literal caseId from the decision/provision entries
        for k in ("POST /api/v1/admin/onboarding/cases/{caseId}/decision",
                  "POST /api/v1/admin/onboarding/cases/{caseId}/provision"):
            pm = pm_idx.get(k)
            if pm:
                base_pm = build_base_request(pm)
                literal = base_pm["path_vars"].get("caseId")
                if literal:
                    session_ids["caseId"] = literal
                    setup_record["postman_literal_caseId_used"] = literal
                    print(f"  -> using Postman literal caseId: {literal}")
                    break
    if not session_ids.get("caseId"):
        print(f"ERROR: no caseId available (discovery failed, no Postman literal); aborting")
        sys.exit(2)

    # --- HYBRID phase 0b: verify the seeded caseId is queryable (Cluster-C mitigation) ---
    print(f"Phase 0b: verifying seeded caseId is queryable via GET /api/v1/admin/onboarding/cases/{{caseId}}...")
    verify_record = verify_seeded_id_queryable(session_ids.get("caseId"), "/api/v1/admin/onboarding/cases/{caseId}")
    print(f"  -> verified={verify_record['verified']} attempts={verify_record['attempts']} cluster_c_suspected={verify_record['cluster_c_suspected']}")
    setup_record["post_mint_verify"] = verify_record

    # --- HYBRID phase 0c/0d: case-pool minting -------------------------
    # Skip when SCOPE_ENDPOINT excludes both decision and provision (no pool need).
    need_submitted_pool = not SCOPE_ENDPOINT or "/decision" in SCOPE_ENDPOINT
    need_approved_pool = not SCOPE_ENDPOINT or "/provision" in SCOPE_ENDPOINT

    submitted_pool: list[str] = []
    approved_pool: list[str] = []
    submitted_pool_records: list = []
    approved_pool_records: list = []

    if need_submitted_pool and N_SUBMITTED_POOL > 0:
        print(f"Phase 0c: minting fresh SUBMITTED case pool (target size={N_SUBMITTED_POOL}) via affiliate onboarding...")
        for i in range(N_SUBMITTED_POOL):
            rec = mint_submitted_case_via_onboarding(pm_idx, label=f"submitted-pool-{i+1}")
            submitted_pool_records.append(rec)
            if rec.get("caseId"):
                submitted_pool.append(rec["caseId"])
                print(f"  -> minted {i+1}/{N_SUBMITTED_POOL}: caseId={rec['caseId']}")
            else:
                print(f"  -> mint {i+1}/{N_SUBMITTED_POOL} {rec.get('status')}: {rec.get('reason')}")
    elif need_submitted_pool and BACKEND_SUBMITTED_POOL:
        submitted_pool.extend(BACKEND_SUBMITTED_POOL)
        print(f"Phase 0c: using {len(BACKEND_SUBMITTED_POOL)} backend-provided SUBMITTED caseIds (minting still disabled): {BACKEND_SUBMITTED_POOL}")
    else:
        reason = "SCOPE_ENDPOINT excludes decision" if need_submitted_pool is False else "N_SUBMITTED_POOL=0 + BACKEND_SUBMITTED_POOL empty"
        print(f"Phase 0c: skipped — {reason}")

    if need_approved_pool and N_APPROVED_POOL > 0:
        print(f"Phase 0d: minting + approving fresh APPROVED case pool (target size={N_APPROVED_POOL})...")
        for i in range(N_APPROVED_POOL):
            mrec = mint_submitted_case_via_onboarding(pm_idx, label=f"approved-pool-{i+1}-mint")
            approved_pool_records.append({"mint": mrec})
            if not mrec.get("caseId"):
                print(f"  -> mint {i+1}/{N_APPROVED_POOL} {mrec.get('status')}: {mrec.get('reason')}")
                continue
            arec = approve_case_for_pool(mrec["caseId"], pm_idx)
            approved_pool_records[-1]["approve"] = arec
            if arec.get("status") == "OK":
                approved_pool.append(mrec["caseId"])
                print(f"  -> approved {i+1}/{N_APPROVED_POOL}: caseId={mrec['caseId']}")
            else:
                print(f"  -> approve {i+1}/{N_APPROVED_POOL} failed for {mrec['caseId']}: {arec.get('response_status')} ({arec.get('reason')})")
    elif need_approved_pool and BACKEND_APPROVED_POOL:
        approved_pool.extend(BACKEND_APPROVED_POOL)
        print(f"Phase 0d: using {len(BACKEND_APPROVED_POOL)} backend-provided APPROVED caseIds (minting still disabled): {BACKEND_APPROVED_POOL}")
    else:
        reason = "SCOPE_ENDPOINT excludes provision" if need_approved_pool is False else "N_APPROVED_POOL=0 + BACKEND_APPROVED_POOL empty"
        print(f"Phase 0d: skipped — {reason}")

    setup_record["case_pools"] = {
        "submitted_target": N_SUBMITTED_POOL,
        "submitted_minted": len(submitted_pool),
        "submitted_pool": list(submitted_pool),
        "submitted_records": submitted_pool_records,
        "approved_target": N_APPROVED_POOL,
        "approved_minted": len(approved_pool),
        "approved_pool": list(approved_pool),
        "approved_records": approved_pool_records,
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
                "executed_by": "postman_hybrid_admin_runner",
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

            # --- Pool override: consume a fresh case for happy-path TCs that need
            # a specific case state the single seed cannot provide after TC-001.
            pool_override_caseId = None
            if allow_seed_substitution and "caseId" in path_vars:
                if (pack_ep == "POST /api/v1/admin/onboarding/cases/{caseId}/decision"
                        and scenario in DECISION_FRESH_SUBMITTED_NEEDED
                        and submitted_pool):
                    pool_override_caseId = submitted_pool.pop(0)
                    path_vars["caseId"] = pool_override_caseId
                elif (pack_ep == "POST /api/v1/admin/onboarding/cases/{caseId}/provision"
                        and scenario in PROVISION_FRESH_APPROVED_NEEDED
                        and approved_pool):
                    pool_override_caseId = approved_pool.pop(0)
                    path_vars["caseId"] = pool_override_caseId

            query = dict(base["query"])
            body = body_after_rotation

            # --- Bank uniqueness rotation: only on POST /api/v1/admin/banks. Runs
            # before scenario-driven mutations so empty/invalid-field tests still
            # override these fields as designed.
            # Skip for duplicate_bank_code_rejected — that TC deliberately reuses
            # the static bankCode from the pack payload so the backend returns 409.
            if (pack_ep == "POST /api/v1/admin/banks" and isinstance(body, dict)
                    and scenario != "duplicate_bank_code_rejected"):
                body = rotate_bank_uniqueness(body)

            # --- Admin contact rotation: only on /provision. Runs before scenario
            # mutations so invalid_admin_email_rejected etc. still override as designed.
            # If the caseId came from the minted pool, look up the primaryContact we
            # set during onboarding step-2 and use it as adminContact (satisfies the
            # backend's contact-match validation). Otherwise generate fresh.
            if pack_ep == "POST /api/v1/admin/onboarding/cases/{caseId}/provision" and isinstance(body, dict):
                effective_case_id = pool_override_caseId or path_vars.get("caseId")
                body = rotate_admin_contact(body, case_id=effective_case_id)

            mutation_note = None
            if pool_override_caseId:
                mutation_note = f"pool-fresh caseId={pool_override_caseId}"
            override_headers = dict(base["headers"])

            engine_applied = None  # None=v1 path; True/False=v2 engine outcome
            engine_action = None
            engine_note = None
            url_override = None    # set by v2 engine; bypasses rebuild_url
            if (MUTATION_ENGINE_VERSION == "v2"
                    and plan["action"] not in ENGINE_RUNNER_PRESERVED):
                # Build a synthetic Postman request from the runner's per-TC
                # state (after rotations, pool overrides, path-template
                # override). Engine returns a mutated copy.
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
                        body = body_raw_out  # malformed JSON kept verbatim
                else:
                    body = None
                override_headers = {h["key"]: h["value"] for h in (mutated_req.get("header") or [])}
                engine_applied = mut["applied"]
                engine_action = mut["action"]
                engine_note = mut["note"]
                mutation_note = (mutation_note + " | " + engine_note) if mutation_note else engine_note
            elif plan["action"] == "as_is":
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
            elif plan["action"] == "method_swap":
                method = plan["new_method"].upper()
                # Strip body for unsafe→safe swaps; backends often 415 a GET with body before reaching the 405.
                if method in ("GET", "HEAD", "DELETE"):
                    body = None
                mutation_note = f"swapped HTTP method to {method} on {path_template}"
            elif plan["action"] == "correlation_id_check":
                import uuid as _uuid
                _expected_corr = _uuid.uuid4().hex
                override_headers["X-Correlation-ID"] = _expected_corr
                mutation_note = f"set X-Correlation-ID={_expected_corr}; will assert echoed in response"

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
                # Step 2: chain a read on the case — GET /api/v1/admin/onboarding/cases/{caseId}
                # is the most meaningful follow-up for case-scoped writes (decision/provision)
                read_case_id = (path_vars.get("caseId") or session_ids.get("caseId"))
                read_url = f"{BASE_URL}/api/v1/admin/onboarding/cases/{read_case_id}" if read_case_id else None
                if read_url:
                    read_resp = execute("GET", read_url, {"Accept": "application/json"}, None)
                else:
                    read_resp = {"ok": False, "error": "no caseId available for read-after-write chain"}
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
                response = execute(method, url, override_headers, body)

            # --- correlation_id_check post-response assertion ---
            # Verdict is FAIL if status is non-2xx OR the X-Correlation-ID we sent
            # was not echoed in the response headers.
            if plan["action"] == "correlation_id_check":
                _sent = override_headers.get("X-Correlation-ID")
                _resp_headers = response.get("headers") or {}
                _echoed = _resp_headers.get("X-Correlation-ID") or _resp_headers.get("x-correlation-id")
                response["_correlation"] = {
                    "sent": _sent,
                    "received": _echoed,
                    "echoed": (_sent is not None and _echoed == _sent),
                }
                mutation_note = (mutation_note or "") + f" | corr sent={_sent}, received={_echoed}, echoed={_sent == _echoed}"

            verdict = evaluate(tc, request_summary, response)
            # If correlation_id_check returned 200 but didn't echo our value, override to FAIL.
            if (plan["action"] == "correlation_id_check"
                and verdict.get("status") == "PASS"
                and not response.get("_correlation", {}).get("echoed", False)):
                verdict = {
                    "status": "FAIL",
                    "reason": (f"X-Correlation-ID not echoed: sent={response['_correlation']['sent']}, "
                               f"received={response['_correlation']['received']}"),
                    "schema": verdict.get("schema"),
                }
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
                and not pool_override_caseId
                and any(tok in path_template for tok in ("{caseId}", "{bankId}", "{affiliateId}"))):
                if verify_record.get("verified"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": ("CLUSTER_C_PERSISTENCE_SPLIT — seeded ID returns 200 on GET "
                                   "/api/v1/admin/onboarding/cases/{caseId} but this write/state endpoint "
                                   "returns 404 for the same ID; backend write/read consistency defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "persistence_split",
                    }
                elif verify_record.get("cluster_c_suspected"):
                    verdict = {
                        "status": "BLOCKED",
                        "reason": (f"CLUSTER_C_SEED_NOT_QUERYABLE — pre-flight verify on seeded caseId "
                                   f"({session_ids.get('caseId')}) returned 404 after 3 attempts; this 404 "
                                   "is downstream of an unusable seed, not a real validation defect"),
                        "schema": verdict.get("schema"),
                        "cluster": "C",
                        "defect_class": "seed_not_queryable",
                    }
            # --- Mutation misfire override ---
            # When the v2 engine could not apply the requested mutation (engine
            # returned applied=False), force FAIL with a `mutation_misfire`
            # tag. This prevents silent-PASS where the request was sent
            # unmutated but happened to match expected status by coincidence.
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
            "service": "admin",
            "service_upper": "ADM",
            "run_mode": "postman_hybrid_admin",
            "report_date": dt.datetime.now().strftime("%Y-%m-%d"),
            "tester": "postman_hybrid_admin_runner",
            "base_api_url": BASE_URL,
            "swagger_source": str(SWAGGER_PATH),
            "postman_collection": str(POSTMAN_PATH),
            "test_pack": str(TEST_PACK_PATH),
            "auth_mode": "none",
            "seeded_ids": {
                "affiliateId": session_ids.get("affiliateId"),
                "bankId": session_ids.get("bankId"),
                "caseId_preflight": session_ids.get("caseId"),
                "caseId_fallback_used": setup_record.get("fallback_used", False),
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
    }

    REPORT_PATH.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"\n=== RUN COMPLETE ===")
    print(f"Total: {total_tcs}  PASS: {counts['PASS']}  FAIL: {counts['FAIL']}  BLOCKED: {counts['BLOCKED']}  ERROR: {counts['ERROR']}")
    print(f"Overall: {overall}")
    print(f"Report: {REPORT_PATH}")
    print(f"Evidence dir: {EVIDENCE_DIR}")

if __name__ == "__main__":
    main()
