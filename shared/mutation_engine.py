"""Mutation engine — Kardit runners (v2).

Maps a scenario name + a Postman happy-path request to a mutated request,
recording provenance for every TC. Misfires (engine recognizes the kind
but cannot apply it to the given payload) are tagged so the runner reports
them as FAIL+`mutation_misfire` rather than silently sending the unmutated
request.

Public entry: `apply_mutation(request, scenario, endpoint=None, swagger=None)`.

Returns a dict:
  {
    "request": <mutated dict>,
    "mutation": {
        "action": <kind>,        # e.g. "drop_field", "auth_expired_token"
        "target": <field|None>,
        "applied": True|False,   # False => misfire
        "note": <human-readable description>,
    },
  }

Pattern classification is delegated to `_mutation_audit.classify` so engine
and audit agree on every TC.

Auth note (2026-05-09): backend currently ships with `auth_mode=none`. Auth-
class mutations still fire (set/strip Authorization headers) but the backend
won't enforce, so those TCs surface as real-defect FAILs — exactly the
"auth pipeline not enforced" signal we want.
"""
from __future__ import annotations

import copy
import json
import random
import re
import string
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlencode

# Reuse the audit's pattern catalog as the single source of truth.
_AUDIT_PATH = Path(__file__).resolve().parent.parent.parent / "Downloads" / "_mutation_audit.py"
if not _AUDIT_PATH.exists():
    _AUDIT_PATH = Path(r"C:\Users\Onyema Ifechukwu\Downloads\_mutation_audit.py")

import importlib.util
_spec = importlib.util.spec_from_file_location("_mutation_audit", _AUDIT_PATH)
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)

classify = _audit.classify

# =============================================================================
# Constants used by mutations
# =============================================================================

EXPIRED_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJleHAiOjEsInN1YiI6InRlc3QifQ."
    "QHJsfYNNUbsKfgQjU2zSNKi6kXnv4UrUQH8sQK0sm-A"
)
INVALID_SIG_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJ0ZXN0In0."
    "INVALID_SIGNATURE_X" * 3
)
MALFORMED_TOKEN = "not.a.real.jwt"
SQL_INJECTION = "' OR 1=1--"
XSS_PAYLOAD = "<script>alert(1)</script>"
LARGE_STRING = "X" * 10240  # 10KB
LARGE_BODY_FIELD = "X" * 524288  # 512KB

# Role-pool placeholders. When the role-token pool ships, swap these constants
# (or load from `Downloads/role_tokens.json`).
ROLE_TOKENS = {
    "wrong": "ROLE_TOKEN_WRONG_ROLE_PLACEHOLDER",
    "bank":  "ROLE_TOKEN_BANK_USER_PLACEHOLDER",
    "admin": "ROLE_TOKEN_ADMIN_USER_PLACEHOLDER",
    "service_provider": "ROLE_TOKEN_SP_PLACEHOLDER",
    "sp_viewer": "ROLE_TOKEN_SP_VIEWER_PLACEHOLDER",
}
DEFAULT_ROLE_TOKEN = ROLE_TOKENS["wrong"]

# Foreign scope placeholder IDs. Real values can be loaded from
# `Downloads/foreign_scope_seeds.json` when ready.
FOREIGN_SCOPE_IDS = {
    "tenantId": "TNT-FOREIGN-9999",
    "bankId": "BANK-FOREIGN-9999",
    "affiliateId": "AFF-FOREIGN-9999",
    "customerId": "CUST-FOREIGN-9999",
    "cardId": "CAR-FOREIGN-9999",
}


# =============================================================================
# Helpers
# =============================================================================

def _request_copy(req: dict) -> dict:
    """Deep-copy a Postman request dict (ensures we don't mutate the caller's)."""
    return copy.deepcopy(req)


def _get_url_raw(req: dict) -> str:
    url = req.get("url")
    if isinstance(url, dict):
        return url.get("raw", "") or ""
    if isinstance(url, str):
        return url
    return ""


def _set_url_raw(req: dict, raw: str) -> None:
    url = req.get("url")
    if isinstance(url, dict):
        url["raw"] = raw
        # also rebuild path array
        tail = raw.split("?")[0]
        if "://" in tail:
            tail = tail.split("://", 1)[1]
            tail = "/" + tail.split("/", 1)[1] if "/" in tail else "/"
        tail = tail.replace("{{baseUrl}}", "").lstrip("/")
        if tail:
            url["path"] = [p for p in tail.split("/") if p]
    else:
        req["url"] = raw


def _get_body_dict(req: dict) -> dict | None:
    body = req.get("body") or {}
    if body.get("mode") == "raw":
        raw = body.get("raw", "")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def _set_body_dict(req: dict, body_dict: dict | None) -> None:
    body = req.get("body") or {}
    if body_dict is None:
        body["mode"] = "raw"
        body["raw"] = ""
    else:
        body["mode"] = "raw"
        body["raw"] = json.dumps(body_dict, indent=2)
        body.setdefault("options", {"raw": {"language": "json"}})
    req["body"] = body


def _get_header(req: dict, key: str) -> str | None:
    """Return first matching header value (case-insensitive)."""
    for h in req.get("header", []) or []:
        if h.get("key", "").lower() == key.lower():
            return h.get("value")
    return None


def _set_header(req: dict, key: str, value: str) -> None:
    headers = req.setdefault("header", [])
    # Remove existing same key
    for h in list(headers):
        if h.get("key", "").lower() == key.lower():
            headers.remove(h)
    headers.append({"key": key, "value": value, "type": "text"})


def _strip_header(req: dict, key: str) -> None:
    headers = req.get("header", []) or []
    req["header"] = [h for h in headers if h.get("key", "").lower() != key.lower()]


def _drop_field_in_dict(d: dict, field: str) -> bool:
    """Recursively drop the first occurrence of `field` in d. Returns True if dropped."""
    if not isinstance(d, dict):
        return False
    if field in d:
        del d[field]
        return True
    for v in d.values():
        if isinstance(v, dict):
            if _drop_field_in_dict(v, field):
                return True
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and _drop_field_in_dict(item, field):
                    return True
    return False


def _set_field_in_dict(d: dict, field: str, value: Any) -> bool:
    """Recursively set the first occurrence of `field` to value."""
    if not isinstance(d, dict):
        return False
    if field in d:
        d[field] = value
        return True
    for v in d.values():
        if isinstance(v, dict):
            if _set_field_in_dict(v, field, value):
                return True
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and _set_field_in_dict(item, field, value):
                    return True
    return False


def _has_field_in_dict(d: dict, field: str) -> bool:
    if not isinstance(d, dict):
        return False
    if field in d:
        return True
    for v in d.values():
        if isinstance(v, dict) and _has_field_in_dict(v, field):
            return True
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and _has_field_in_dict(item, field):
                    return True
    return False


def _camel_or_snake(field: str) -> list[str]:
    """Generate field-name variants to try (camelCase + snake_case)."""
    out = [field]
    if "_" in field:
        # snake_case → camelCase
        parts = field.split("_")
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
        out.append(camel)
    else:
        # camelCase → snake_case
        snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", field).lower()
        if snake != field:
            out.append(snake)
    return out


def _result(req: dict, action: str, target: str | None,
            applied: bool, note: str) -> dict:
    return {
        "request": req,
        "mutation": {
            "action": action,
            "target": target,
            "applied": applied,
            "note": note,
        },
    }


def _misfire(req: dict, action: str, target: str | None, note: str) -> dict:
    return _result(req, action, target, applied=False, note=f"MISFIRE: {note}")


# =============================================================================
# Mutation primitives — auth
# =============================================================================

def _m_strip_auth(req, target, scenario, **kw):
    r = _request_copy(req)
    _strip_header(r, "Authorization")
    return _result(r, "strip_auth", None, True, "Authorization header removed")


def _m_auth_expired_token(req, target, scenario, **kw):
    r = _request_copy(req)
    _set_header(r, "Authorization", f"Bearer {EXPIRED_JWT}")
    return _result(r, "auth_expired_token", None, True, "Authorization swapped to expired JWT")


def _m_auth_invalid_token(req, target, scenario, **kw):
    r = _request_copy(req)
    _set_header(r, "Authorization", f"Bearer {INVALID_SIG_JWT}")
    return _result(r, "auth_invalid_token", None, True, "Authorization swapped to wrong-signature JWT")


def _m_auth_malformed_token(req, target, scenario, **kw):
    r = _request_copy(req)
    _set_header(r, "Authorization", f"Bearer {MALFORMED_TOKEN}")
    return _result(r, "auth_malformed_token", None, True, "Authorization swapped to non-JWT garbage")


def _m_auth_role(req, target, scenario, role_key="wrong", **kw):
    r = _request_copy(req)
    token = ROLE_TOKENS.get(role_key, DEFAULT_ROLE_TOKEN)
    _set_header(r, "Authorization", f"Bearer {token}")
    return _result(r, f"auth_{role_key}_role", None, True,
                   f"Authorization swapped to {role_key}-role token (placeholder until role pool ships)")


# =============================================================================
# Mutation primitives — field-level (body)
# =============================================================================

def _m_drop_field(req, target, scenario, endpoint=None, **kw):
    if not target:
        return _misfire(req, "drop_field", None, "no field target inferred from scenario")
    r = _request_copy(req)
    body = _get_body_dict(r)
    if body is not None:
        for variant in _alias_variants(target):
            if _drop_field_in_dict(body, variant):
                _set_body_dict(r, body)
                return _result(r, "drop_field", variant, True, f"dropped field `{variant}` from body")

    r2, ok, var = _replace_path_var(r, target, "", endpoint=endpoint)
    if ok:
        return _result(r2, "drop_field", var, True,
                        f"field `{target}` is path var; cleared path segment as fallback")

    # Field not present anywhere — this satisfies "missing X" trivially. Send
    # as-is so backend can verify required-field enforcement on a body that
    # already lacks the field.
    return _result(r, "drop_field", target, True,
                    f"field `{target}` already absent from request; sent as-is "
                    f"(satisfies drop-field semantics trivially)")


def _first_string_field(d: Any) -> str | None:
    """Return the first leaf field in `d` whose value is a non-empty string."""
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, str) and v:
                return k
        for v in d.values():
            if isinstance(v, dict):
                f = _first_string_field(v)
                if f is not None:
                    return f
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        f = _first_string_field(item)
                        if f is not None:
                            return f
    return None


def _first_leaf_field(d: Any) -> str | None:
    """Fall-back when `_first_string_field` returns None — pick any leaf key."""
    if isinstance(d, dict):
        for k, v in d.items():
            if not isinstance(v, (dict, list)):
                return k
        for v in d.values():
            if isinstance(v, dict):
                f = _first_leaf_field(v)
                if f is not None:
                    return f
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        f = _first_leaf_field(item)
                        if f is not None:
                            return f
    return None


_FIELD_ALIASES = {
    "reference": ["referenceCode", "transactionReference", "narration", "ref"],
    "reason": ["reasonCode", "comment", "remarks"],
    "account": ["destinationAccount", "sourceAccount", "accountNumber", "accountId"],
    "name": ["fullName", "customerName", "legalName", "shortName", "displayName"],
    "search": ["searchTerm", "keyword", "q", "query"],
    "amount": ["amount", "transferAmount", "withdrawAmount", "limit"],
    "balance": ["amount", "balanceAmount", "currentBalance"],
    "merchant": ["merchantName", "merchantId"],
    "country_code": ["country", "countryCode"],
    "id_number": ["idNumber", "identityNumber"],
    "kyc_level": ["kycLevel", "level"],
    "date_of_birth": ["dateOfBirth", "dob", "birthDate"],
    "customer_dob": ["dateOfBirth", "dob", "birthDate"],
    "customer_email": ["email", "emailAddress"],
    "customer_phone": ["phone", "phoneNumber", "mobile"],
    "filter_combination": ["filters", "filter"],
    "page": ["pageNumber", "pageNo", "page"],
    "page_size": ["pageSize", "pageSize"],
    "pagesize": ["pageSize"],
    "filter_array": ["filters", "filterArray"],
    "filters_tolerated": ["filters"],
}


def _alias_variants(target: str) -> list[str]:
    """Return field-name variants to attempt: camel/snake plus aliases."""
    out = list(_camel_or_snake(target))
    aliases = _FIELD_ALIASES.get(target.lower(), [])
    for a in aliases:
        for v in _camel_or_snake(a):
            if v not in out:
                out.append(v)
    return out


def _m_set_field(req, target, scenario, value, action_name, **kw):
    if not target:
        return _misfire(req, action_name, None, "no field target")
    r = _request_copy(req)
    body = _get_body_dict(r)

    placeholder_targets = {"string", "field", "value"}
    effective_target = target
    if body is not None and target.lower() in placeholder_targets:
        f = _first_string_field(body) or _first_leaf_field(body)
        if f is not None:
            effective_target = f

    # Path-var-shaped target (caseId, bankId, affiliateId, customerId, ...)
    # gets path-var precedence over body. The runner's seed substitution put
    # the literal ID into the URL; for empty/malformed/unicode-id scenarios
    # the engine MUST overwrite that path segment, not bury the mutation in
    # body or query.
    endpoint = kw.get("endpoint")
    str_value = value if isinstance(value, str) else json.dumps(value) if value is not None else ""
    target_lower = target.lower()
    looks_like_path_var = (
        target_lower.endswith("id")
        or target_lower.endswith("_id")
        or target_lower in {"caseid", "bankid", "affiliateid", "customerid",
                              "cardid", "tenantid", "userid", "draftid",
                              "limitrequestid", "requestid", "case", "bank",
                              "affiliate", "customer", "card", "tenant"}
    )
    if looks_like_path_var:
        r2, ok, var = _replace_path_var(r, target, str_value, endpoint=endpoint)
        if ok:
            return _result(r2, action_name, var, True,
                            f"set path var `{var}` to {str_value!r} via {action_name}")

    if body is not None:
        set_ok = False
        for variant in _alias_variants(effective_target):
            if _set_field_in_dict(body, variant, value):
                set_ok = True
                effective_target = variant
                break
        if not set_ok and target != effective_target:
            for variant in _alias_variants(target):
                if _set_field_in_dict(body, variant, value):
                    set_ok = True
                    effective_target = variant
                    break
        if set_ok:
            _set_body_dict(r, body)
            return _result(r, action_name, effective_target, True,
                            f"set field `{effective_target}` to {value!r} via {action_name}")

    # Try query string (GET endpoints / no body / field absent in body)
    raw = _get_url_raw(r)
    str_val = value if isinstance(value, str) else json.dumps(value)
    for variant in _alias_variants(target):
        pat = re.compile(r"(?<=[?&])" + re.escape(variant) + r"=[^&#]*", re.IGNORECASE)
        if pat.search(raw):
            new_raw = pat.sub(f"{variant}={str_val}", raw)
            _set_url_raw(r, new_raw)
            return _result(r, action_name, variant, True,
                            f"set query param `{variant}` to {value!r} via {action_name}")

    # Path-var fallback for non-ID-shaped targets (final attempt before adding to body)
    if not looks_like_path_var:
        r2, ok, var = _replace_path_var(r, target, str_value, endpoint=endpoint)
        if ok:
            return _result(r2, action_name, var, True,
                            f"set path var `{var}` to {str_value!r} via {action_name}")

    # Last-ditch: ADD the field to the body. Tests `additionalProperties: false`
    # if the field is undeclared, or tests rejection if swagger declares it
    # optional but Postman omitted it. Skip for placeholder targets.
    if body is not None and target.lower() not in placeholder_targets:
        camel = _camel_or_snake(target)[-1] if target != _camel_or_snake(target)[-1] else target
        body[camel] = value
        _set_body_dict(r, body)
        return _result(r, action_name, camel, True,
                        f"added field `{camel}` to body with {value!r} (was absent; tests additionalProperties or optional-field rejection)")

    # No body, but target is named — append to query string as last resort.
    if target.lower() not in placeholder_targets:
        raw = _get_url_raw(r)
        sep = "&" if "?" in raw else "?"
        camel = _camel_or_snake(target)[-1]
        new_raw = f"{raw}{sep}{camel}={str_value}"
        _set_url_raw(r, new_raw)
        return _result(r, action_name, camel, True,
                        f"appended `{camel}={str_value}` to query (no body and absent from query)")

    if body is None:
        return _misfire(r, action_name, target, "no JSON body and field absent from query string")
    return _misfire(r, action_name, target, f"field `{target}` not present")


def _m_empty_string_field(req, target, scenario, **kw):
    # `empty_body_rejected` patterns extract target=`body`; semantically that's
    # a body-level mutation, not a field one. Redirect.
    if target and target.lower() == "body":
        return _m_empty_body(req, None, scenario)
    return _m_set_field(req, target, scenario, "", "empty_string_field", **kw)


def _m_blank_field(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, "   ", "blank_field", **kw)


def _m_null_field(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, None, "null_field", **kw)


def _m_invalid_format(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, "INVALID_FORMAT_X", "invalid_format", **kw)


def _m_invalid_enum(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, "NOT_A_REAL_ENUM_VALUE", "invalid_enum", **kw)


def _m_field_too_long(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, LARGE_STRING, "field_too_long", **kw)


def _m_negative_value(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, -1, "negative_value", **kw)


def _m_field_zero_value(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, 0, "field_zero_value", **kw)


def _m_field_insufficient_value(req, target, scenario, **kw):
    """Insufficient-value semantics: a tiny positive amount that the backend
    should reject if it considers it below limits. `balance` is rarely a
    request field — fall back to common amount-like fields."""
    primary = _m_set_field(req, target, scenario, 0.01, "field_insufficient_value", **kw)
    if primary["mutation"]["applied"]:
        return primary
    for fallback in ("amount", "minAmount", "withdrawAmount", "transferAmount"):
        out = _m_set_field(req, fallback, scenario, 0.01, "field_insufficient_value", **kw)
        if out["mutation"]["applied"]:
            out["mutation"]["note"] += f" (fallback from `{target}`)"
            return out
    return primary


def _m_special_chars_field(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, "!@#$%^&*()_+={}[]|;:,.<>?", "special_chars_field", **kw)


def _m_unicode_field(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, "测试ñàïùé😀", "unicode_field", **kw)


def _m_invalid_value(req, target, scenario, **kw):
    return _m_set_field(req, target, scenario, "INVALID_GENERIC_VALUE", "invalid_value", **kw)


def _m_currency_mismatch(req, target, scenario, **kw):
    """Currency mismatch — set currency to a code unlikely to match product.
    If body has no `currency` field, add one to test rejection."""
    r = _request_copy(req)
    body = _get_body_dict(r)
    if body is None:
        return _misfire(r, "currency_mismatch", target, "no body")
    if not _set_field_in_dict(body, "currency", "XBT"):
        body["currency"] = "XBT"
        _set_body_dict(r, body)
        return _result(r, "currency_mismatch", "currency", True,
                        "added currency=XBT to body (was absent)")
    _set_body_dict(r, body)
    return _result(r, "currency_mismatch", "currency", True, "currency forced to XBT (mismatched)")


_DATE_PAIRS = [
    ("fromDate", "toDate"),
    ("startDate", "endDate"),
    ("dateFrom", "dateTo"),
    ("from", "to"),
    ("startAt", "endAt"),
    ("createdAfter", "createdBefore"),
]


def _m_invalid_date_range(req, target, scenario, **kw):
    """Set start AFTER end across common date-pair conventions (body OR query)."""
    r = _request_copy(req)
    body = _get_body_dict(r)
    later = "2030-01-01T00:00:00Z"
    earlier = "2020-01-01T00:00:00Z"
    if body is not None:
        for fr, to in _DATE_PAIRS:
            if _set_field_in_dict(body, fr, later) and _set_field_in_dict(body, to, earlier):
                _set_body_dict(r, body)
                return _result(r, "invalid_date_range", None, True,
                                f"{fr} set after {to} (body)")

    raw = _get_url_raw(r)
    for fr, to in _DATE_PAIRS:
        if re.search(r"(?<=[?&])" + fr + r"=", raw) and re.search(r"(?<=[?&])" + to + r"=", raw):
            new = re.sub(r"(?<=[?&])" + fr + r"=[^&#]*", f"{fr}={later}", raw)
            new = re.sub(r"(?<=[?&])" + to + r"=[^&#]*", f"{to}={earlier}", new)
            _set_url_raw(r, new)
            return _result(r, "invalid_date_range", None, True,
                            f"{fr} set after {to} (query)")

    # Last-ditch: append fromDate/toDate to query string with inverted values
    sep = "&" if "?" in raw else "?"
    new = f"{raw}{sep}fromDate={later}&toDate={earlier}"
    _set_url_raw(r, new)
    return _result(r, "invalid_date_range", None, True,
                    "appended fromDate/toDate inverted to query (no existing date pair)")


def _m_field_validation(req, target, scenario, **kw):
    """Generic field-validation; default to set to invalid string."""
    return _m_set_field(req, target, scenario, "VALIDATION_TEST_INVALID", "field_validation", **kw)


# =============================================================================
# Mutation primitives — path-var
# =============================================================================

_PATH_VAR_RE = re.compile(r":([a-zA-Z][a-zA-Z0-9_]*)")
# Single-brace path var, NOT Postman's double-brace `{{baseUrl}}`.
_BRACE_VAR_RE = re.compile(r"(?<!\{)\{([a-zA-Z][a-zA-Z0-9_]*)\}(?!\})")
_LITERAL_ID_SEG_RE = re.compile(
    r"^(?:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[A-Z]{3,}-[A-Z0-9-]{4,}"
    r"|TXN-\d+-\d+|CAR-[0-9A-F]{16,}|AFF-[0-9A-F]{16,}|BANK-\d+-\d+|CUST-[A-Z0-9-]+"
    r")$"
)


def _strip_url_to_path(raw: str) -> tuple[str, str]:
    """Split a Postman raw URL into (prefix_to_path, path_with_query).
    Prefix is `{{baseUrl}}` or `scheme://host`. Path is what we mutate."""
    s = raw
    prefix = ""
    if s.startswith("{{"):
        end = s.find("}}")
        if end != -1:
            prefix = s[: end + 2]
            s = s[end + 2 :]
    elif "://" in s:
        proto, rest = s.split("://", 1)
        if "/" in rest:
            host, rest_path = rest.split("/", 1)
            prefix = f"{proto}://{host}"
            s = "/" + rest_path
        else:
            prefix = s
            s = ""
    return prefix, s


def _split_url_for_template(raw: str) -> tuple[str, list[str], str]:
    """Returns (prefix, path_segments, query_and_fragment)."""
    prefix, rest = _strip_url_to_path(raw)
    qf = ""
    if "?" in rest:
        rest, q = rest.split("?", 1)
        qf = "?" + q
    elif "#" in rest:
        rest, q = rest.split("#", 1)
        qf = "#" + q
    segs = [seg for seg in rest.split("/") if seg or rest == "/"]
    if rest.startswith("/") and (not segs or segs[0] != ""):
        segs = [""] + segs  # preserve leading slash
    return prefix, segs, qf


def _path_var_index_in_endpoint(endpoint: str | None, var_name: str | None) -> int | None:
    """Locate which path segment of the endpoint template carries the variable.

    Endpoint is like `GET /api/v1/cards/{cardId}/freeze`. Returns the segment
    index where the variable appears, or None if absent. When `var_name` is
    None, returns the LAST `{var}` segment (typical for "nonexistent ID"
    scenarios that don't name the field). Matching is case-insensitive and
    handles prefix/suffix overlap (e.g. `case` → `caseId`)."""
    if not endpoint:
        return None
    parts = endpoint.split(" ", 1)
    path = parts[1] if len(parts) == 2 else parts[0]
    path = path.split("?")[0]
    segs = [s for s in path.split("/") if s != ""]

    if var_name is None:
        # Pick the LAST template segment.
        last_idx = None
        for i, seg in enumerate(segs):
            if _BRACE_VAR_RE.match(seg) or _PATH_VAR_RE.match(seg.replace("{", ":").replace("}", "")):
                last_idx = i
        return (last_idx + 1) if last_idx is not None else None

    candidates = {var_name, var_name.lower()}
    candidates.update(_camel_or_snake(var_name))
    candidates = {c.lower() for c in candidates}
    for i, seg in enumerate(segs):
        m = _BRACE_VAR_RE.match(seg) or _PATH_VAR_RE.match(seg.replace("{", ":").replace("}", ""))
        if m:
            name = m.group(1).lower()
            if name in candidates:
                return i + 1
            for c in candidates:
                # Prefix / suffix overlap: `case` matches `caseId`, `bank` matches `bankId`.
                if name.startswith(c) or c.startswith(name) or name.endswith(c) or c.endswith(name):
                    return i + 1
    return None


def _replace_path_var(req: dict, var_name: str | None, value: str,
                       endpoint: str | None = None) -> tuple[dict, bool, str | None]:
    """Replace a path variable with `value`. Tries three strategies:
      1. If endpoint template provided AND var_name resolves to a segment
         index, replace the URL path segment at that index (covers literal-ID
         URLs like /cards/CAR-XXX/freeze).
      2. Match `:varName` in the raw URL (Postman convention).
      3. Match `{varName}` in the raw URL.
    """
    r = _request_copy(req)
    raw = _get_url_raw(r)

    if endpoint:
        idx = _path_var_index_in_endpoint(endpoint, var_name)
        if idx is not None:
            prefix, segs, qf = _split_url_for_template(raw)
            if 0 <= idx < len(segs):
                segs[idx] = value
                new_raw = prefix + "/".join(segs) + qf
                _set_url_raw(r, new_raw)
                return r, True, var_name or "(last_template_var)"

    matches_colon = _PATH_VAR_RE.findall(raw)
    matches_brace = _BRACE_VAR_RE.findall(raw)
    matches = matches_colon + matches_brace
    if not matches:
        return r, False, None

    target_var = None
    if var_name and var_name in matches:
        target_var = var_name
    elif var_name:
        for v in matches:
            if v.lower() == var_name.lower() or v.lower().endswith(var_name.lower()):
                target_var = v
                break
        if target_var is None:
            target_var = matches[-1]
    else:
        target_var = matches[-1]

    new_raw = re.sub(r":" + re.escape(target_var) + r"(?=$|/|\?|#)", value, raw)
    if new_raw == raw:
        new_raw = re.sub(r"\{" + re.escape(target_var) + r"\}", value, raw)
    if new_raw == raw:
        return r, False, target_var
    _set_url_raw(r, new_raw)
    return r, True, target_var


def _path_var_or_body_fallback(req, target, action_name, value, body_fallback_value, scenario, endpoint):
    """Try path-var replacement; if no path var present, fall back to setting the
    field as a body field with `body_fallback_value` (so `unknown_bankId_not_found`
    on POST /affiliates [body has bankId] still mutates)."""
    r, ok, var = _replace_path_var(req, target, value, endpoint=endpoint)
    if ok:
        return _result(r, action_name, var, True, f"set path var `{var}` to {action_name}-value")
    if not target:
        return _misfire(r, action_name, target, "no path variable in URL")
    body = _get_body_dict(r)
    if body is not None:
        for variant in _alias_variants(target):
            if _set_field_in_dict(body, variant, body_fallback_value):
                _set_body_dict(r, body)
                return _result(r, action_name, variant, True,
                                f"no path var; set body field `{variant}` to {action_name}-value as fallback")
        # ADD field if absent
        camel = _camel_or_snake(target)[-1]
        body[camel] = body_fallback_value
        _set_body_dict(r, body)
        return _result(r, action_name, camel, True,
                        f"no path var; added body field `{camel}`={body_fallback_value!r} as fallback")
    # No body: append to query string
    raw = _get_url_raw(r)
    sep = "&" if "?" in raw else "?"
    camel = _camel_or_snake(target)[-1]
    str_val = body_fallback_value if isinstance(body_fallback_value, str) else json.dumps(body_fallback_value)
    new_raw = f"{raw}{sep}{camel}={str_val}"
    _set_url_raw(r, new_raw)
    return _result(r, action_name, camel, True,
                    f"no path var, no body; appended `{camel}={str_val}` to query string")


def _m_path_var_malformed(req, target, scenario, endpoint=None, **kw):
    return _path_var_or_body_fallback(req, target, "path_var_malformed",
                                       "MALFORMED-PATH-VAR-XX", "MALFORMED-VALUE-XX",
                                       scenario, endpoint)


def _m_path_var_nonexistent(req, target, scenario, endpoint=None, **kw):
    fake = f"NONEXIST-{uuid.uuid4().hex[:24].upper()}"
    return _path_var_or_body_fallback(req, target, "path_var_nonexistent",
                                       fake, fake, scenario, endpoint)


def _m_path_var_sql_injection(req, target, scenario, endpoint=None, **kw):
    return _path_var_or_body_fallback(req, target, "path_var_sql_injection",
                                       SQL_INJECTION, SQL_INJECTION, scenario, endpoint)


def _m_path_var_xss(req, target, scenario, endpoint=None, **kw):
    return _path_var_or_body_fallback(req, target, "path_var_xss",
                                       XSS_PAYLOAD, XSS_PAYLOAD, scenario, endpoint)


def _m_path_var_extremely_long(req, target, scenario, endpoint=None, **kw):
    return _path_var_or_body_fallback(req, target, "path_var_extremely_long",
                                       LARGE_STRING, LARGE_STRING, scenario, endpoint)


# =============================================================================
# Mutation primitives — body-level
# =============================================================================

def _m_empty_body(req, target, scenario, **kw):
    r = _request_copy(req)
    body = r.get("body") or {}
    body["mode"] = "raw"
    body["raw"] = ""
    r["body"] = body
    return _result(r, "empty_body", None, True, "body cleared")


def _m_malformed_json_body(req, target, scenario, **kw):
    r = _request_copy(req)
    body = r.get("body") or {}
    body["mode"] = "raw"
    body["raw"] = "{this is not valid json"
    r["body"] = body
    return _result(r, "malformed_json_body", None, True, "body replaced with invalid JSON")


def _m_unknown_property(req, target, scenario, **kw):
    r = _request_copy(req)
    body = _get_body_dict(r) or {}
    body["bogusUnknownField"] = "should-be-rejected-per-additionalProperties-false"
    _set_body_dict(r, body)
    return _result(r, "unknown_property", None, True, "added bogusUnknownField to body")


def _m_oversized_body(req, target, scenario, **kw):
    r = _request_copy(req)
    body = _get_body_dict(r) or {}
    body["__oversized_padding__"] = LARGE_BODY_FIELD
    _set_body_dict(r, body)
    return _result(r, "oversized_body", None, True, "padded body to ~512KB")


def _m_partial_payload(req, target, scenario, **kw):
    """Send only the first top-level key, drop the rest."""
    r = _request_copy(req)
    body = _get_body_dict(r)
    if not body or not isinstance(body, dict):
        return _misfire(r, "partial_payload", None, "no JSON body")
    keys = list(body.keys())
    if len(keys) <= 1:
        return _misfire(r, "partial_payload", None, "body has only 1 key; nothing to drop")
    keep = keys[0]
    new_body = {keep: body[keep]}
    _set_body_dict(r, new_body)
    return _result(r, "partial_payload", None, True,
                   f"kept only `{keep}`; dropped {len(keys)-1} other top-level keys")


def _m_html_payload(req, target, scenario, **kw):
    if not target:
        return _misfire(req, "html_payload", None, "no field target")
    return _m_set_field(req, target, scenario, "<b>html</b><script>x</script>", "html_payload", **kw)


# =============================================================================
# Mutation primitives — scope
# =============================================================================

def _m_scope_foreign(req, target, scenario, endpoint=None, **kw):
    """Swap a scope ID (tenantId, bankId, affiliateId) to a foreign value
    in body OR path. Pick by scenario hint. Fall back to injecting
    `requestContext.{scope}` into the body when the endpoint sources scope
    from auth context (no explicit field on request)."""
    r = _request_copy(req)
    candidates = []
    s = scenario.lower()
    if "tenant" in s:
        candidates = ["tenantId", "tenant_id"]
    elif "bank" in s:
        candidates = ["bankId", "bank_id"]
    elif "affiliate" in s:
        candidates = ["affiliateId", "affiliate_id"]
    else:
        candidates = ["tenantId", "bankId", "affiliateId"]
    body = _get_body_dict(r)
    swapped = False
    target_field = None
    for f in candidates:
        if body and _has_field_in_dict(body, f):
            _set_field_in_dict(body, f, FOREIGN_SCOPE_IDS.get(f) or f"FOREIGN-{f}")
            swapped = True
            target_field = f
            break
    if swapped:
        _set_body_dict(r, body)
    if not swapped:
        for f in candidates:
            r, ok, var = _replace_path_var(r, f, FOREIGN_SCOPE_IDS.get(f) or f"FOREIGN-{f}",
                                            endpoint=endpoint)
            if ok:
                swapped = True
                target_field = var
                break
    if not swapped:
        # Endpoint sources scope from auth context. Inject into body so the
        # backend has something visible to disagree with — and add a header
        # so an auth proxy that honors X-Tenant-Override sees it too.
        primary = candidates[0]
        foreign_val = FOREIGN_SCOPE_IDS.get(primary) or f"FOREIGN-{primary}"
        body = body or {}
        rc = body.setdefault("requestContext", {})
        if isinstance(rc, dict):
            rc[primary] = foreign_val
            _set_body_dict(r, body)
            target_field = f"requestContext.{primary}"
            swapped = True
        # Header marker (no-op if backend ignores)
        header_key = {
            "tenantId": "X-Tenant-Override",
            "bankId": "X-Bank-Override",
            "affiliateId": "X-Affiliate-Override",
        }.get(primary)
        if header_key:
            _set_header(r, header_key, foreign_val)
    if not swapped:
        return _misfire(r, "scope_foreign", None, "no scope field present in body or path")
    return _result(r, "scope_foreign", target_field, True,
                   f"swapped {target_field} to foreign value")


def _m_scope_unlinked(req, target, scenario, **kw):
    """Affiliate not linked to bank — use unlinked affiliate ID."""
    r, ok, var = _replace_path_var(req, "affiliateId", "AFF-UNLINKED-9999")
    if ok:
        return _result(r, "scope_unlinked", var, True, "affiliateId swapped to unlinked")
    r = _request_copy(req)
    body = _get_body_dict(r) or {}
    if _set_field_in_dict(body, "affiliateId", "AFF-UNLINKED-9999"):
        _set_body_dict(r, body)
        return _result(r, "scope_unlinked", "affiliateId", True, "affiliateId in body swapped")
    return _misfire(r, "scope_unlinked", None, "no affiliateId in body or path")


def _m_scope_no_leak(req, target, scenario, **kw):
    """Observational — verify response doesn't leak data on 403/404. Send unmutated."""
    return _result(req, "scope_no_leak", None, True,
                   "no mutation; runner verifies forbidden response shape")


def _m_scope_affiliate_state(req, target, scenario, **kw):
    """Affiliate-state-driven scope check. Observational/state precondition.
    Engine treats as no-op; runner is expected to set state before request."""
    return _result(req, "scope_affiliate_state", target, True,
                   "no payload mutation; expects runner to seed affiliate in named state")


def _m_scope_cross_owner(req, target, scenario, **kw):
    """Resource owned by another principal — swap ID to known-other-owner ID."""
    r, ok, var = _replace_path_var(req, target, "RESOURCE-OWNED-BY-OTHER-9999")
    if not ok:
        return _misfire(req, "scope_cross_owner", target, "no path variable")
    return _result(r, "scope_cross_owner", var, True, f"set :{var} to other-owner ID")


def _m_scope_user_in_org(req, target, scenario, **kw):
    """User-in-other-org check. Auth-driven; behave like wrong_role."""
    return _m_auth_role(req, target, scenario, role_key="wrong")


def _m_scope_cross(req, target, scenario, **kw):
    return _m_scope_foreign(req, target, scenario)


def _m_scope_reuse_blocked(req, target, scenario, **kw):
    """Scope-reuse on download/reference. Send same request twice — runner needs to
    track the prior response's reference. Engine emits no-mutation here; runner
    handles the "second call" semantics."""
    return _result(req, "scope_reuse_blocked", None, True,
                   "no mutation; runner expected to call twice and verify second is blocked")


# =============================================================================
# Mutation primitives — HTTP layer
# =============================================================================

def _m_wrong_method(req, target, scenario, **kw):
    r = _request_copy(req)
    cur = (r.get("method") or "GET").upper()
    new = {"GET": "DELETE", "POST": "DELETE", "PUT": "DELETE",
           "PATCH": "DELETE", "DELETE": "GET"}.get(cur, "DELETE")
    s = scenario.lower()
    # Honor scenario hint if it names a method
    for m in ("delete", "post", "put", "patch", "get", "head", "options"):
        if m + "_method" in s:
            new = m.upper()
            break
    r["method"] = new
    return _result(r, "wrong_method", None, True, f"method swapped {cur} -> {new}")


def _m_wrong_content_type(req, target, scenario, **kw):
    r = _request_copy(req)
    s = scenario.lower()
    if "text_plain" in s:
        ct = "text/plain"
    elif "xml" in s:
        ct = "application/xml"
    elif "form" in s:
        ct = "application/x-www-form-urlencoded"
    else:
        ct = "text/csv"
    _set_header(r, "Content-Type", ct)
    return _result(r, "wrong_content_type", None, True, f"Content-Type set to {ct}")


def _m_wrong_accept_header(req, target, scenario, **kw):
    r = _request_copy(req)
    _set_header(r, "Accept", "application/xml")
    return _result(r, "wrong_accept_header", None, True, "Accept set to application/xml")


def _m_unknown_query_param(req, target, scenario, **kw):
    r = _request_copy(req)
    raw = _get_url_raw(r)
    sep = "&" if "?" in raw else "?"
    raw_new = f"{raw}{sep}__bogus_unknown_query_param__=true"
    _set_url_raw(r, raw_new)
    return _result(r, "unknown_query_param", None, True, "appended unknown query parameter")


def _m_drop_idempotency_key(req, target, scenario, **kw):
    r = _request_copy(req)
    _strip_header(r, "Idempotency-Key")
    return _result(r, "drop_idempotency_key", None, True, "Idempotency-Key header removed")


# =============================================================================
# Mutation primitives — boundary / pagination
# =============================================================================

def _m_boundary_value(req, target, scenario, **kw):
    """Boundary check on numeric field. Use scenario hints to pick min/max/zero.
    If the scenario looks pagination-related, redirect to the pagination handler
    (it knows how to mutate page/pageSize across body and query)."""
    s = scenario.lower()
    if "page" in s:
        return _m_boundary_pagination(req, target, scenario, **kw)
    r = _request_copy(req)
    body = _get_body_dict(r)
    value = 0
    if "max" in s:
        value = 2**31 - 1
    elif "min" in s:
        value = -(2**31)
    elif "zero" in s:
        value = 0
    elif "negative" in s:
        value = -1
    if body and target and _set_field_in_dict(body, target, value):
        _set_body_dict(r, body)
        return _result(r, "boundary_value", target, True, f"set {target} to boundary {value}")
    raw = _get_url_raw(r)
    if "?" in raw and target:
        new = re.sub(r"(?<=[?&])" + re.escape(target) + r"=[^&]*", f"{target}={value}", raw)
        if new != raw:
            _set_url_raw(r, new)
            return _result(r, "boundary_value", target, True, f"query {target} -> {value}")
    return _misfire(r, "boundary_value", target,
                    "no field target and no pagination hint; cannot select a value to mutate")


def _paginator_variants(k: str) -> list[str]:
    """All paginator name variants to try (paginator-equivalence aware).
    For `page`: also try `pageNumber`, `page_number`. For `pageSize`: also `page_size`.
    Both case-folded and case-preserved variants. Deduped, order preserved.
    Added 2026-05-10 to fix transactions pagination mutation hitting `pageNumber`
    instead of appending unread `page=` query param."""
    klow = k.lower()
    base: list[str] = []
    # canonical
    base.extend([k, k[0].upper() + k[1:], k.lower(), k.upper()])
    # paginator equivalents
    if klow == "page":
        for eq in ("pageNumber", "PageNumber", "pagenumber", "PAGENUMBER", "page_number", "Page_Number"):
            base.append(eq)
    elif klow in ("pagesize", "page_size"):
        for eq in ("pageSize", "PageSize", "pagesize", "PAGESIZE", "page_size", "Page_Size"):
            base.append(eq)
    return list(dict.fromkeys(base))


def _m_boundary_pagination(req, target, scenario, **kw):
    """Pagination boundary: page=0/-1, pageSize=0/very-large. Tries query string
    first, falls back to body fields. Edits both `page`/`pageNumber` and
    `pageSize`/`PageSize` casings (paginator-equivalence aware as of 2026-05-10)."""
    r = _request_copy(req)
    raw = _get_url_raw(r)
    s = scenario.lower()
    edits: list[tuple[str, str]] = []
    if "page_zero" in s or "page=0" in s:
        edits.append(("page", "0"))
    elif "page_size_zero" in s or "pagesize_zero" in s:
        edits.append(("pageSize", "0"))
    elif "negative_page_size" in s or "negative_pagesize" in s:
        edits.append(("pageSize", "-5"))
    elif "negative_page" in s:
        edits.append(("page", "-1"))
    elif "excessive" in s or "exceeds_limit" in s or "exceeds_max" in s:
        edits.append(("pageSize", "9999999"))
    elif "maximum_page_size" in s:
        edits.append(("pageSize", "9999999"))
    elif "minimum_page_size" in s:
        edits.append(("pageSize", "1"))
    elif "non_numeric_page_size" in s or "non_numeric_pagesize" in s:
        edits.append(("pageSize", "NOT_A_NUMBER"))
    elif "non_numeric_page" in s:
        edits.append(("page", "NOT_A_NUMBER"))
    elif "default_page_size" in s:
        edits.append(("pageSize", "20"))
    # 2026-05-10 fix (Bug 2): page_two_success / pagination_page_two_* must
    # actually advance to page 2 instead of running as-is (which silently kept
    # page=1 and hollowed out the test).
    elif "page_two" in s:
        edits.append(("page", "2"))
    elif "page_one" in s:
        edits.append(("page", "1"))

    if not edits:
        return _misfire(r, "boundary_pagination", None,
                        f"scenario `{scenario}` has no recognized pagination hint")

    # Try query string — paginator-equivalence aware (page ↔ pageNumber, pageSize ↔ page_size).
    new_raw = raw
    applied: list[str] = []
    for k, v in edits:
        applied_one = False
        for variant in _paginator_variants(k):
            pat = re.compile(r"(?<=[?&])" + re.escape(variant) + r"=[^&#]*", re.IGNORECASE)
            if pat.search(new_raw):
                new_raw = pat.sub(f"{variant}={v}", new_raw)
                applied.append(f"{variant}={v}")
                applied_one = True
                break
        if not applied_one:
            sep = "&" if "?" in new_raw else "?"
            new_raw += f"{sep}{k}={v}"
            applied.append(f"{k}={v} (appended)")
    _set_url_raw(r, new_raw)

    # Also try body — paginator-equivalence aware
    body = _get_body_dict(r)
    if body is not None:
        for k, v in edits:
            applied_body = False
            for variant in _paginator_variants(k):
                if _set_field_in_dict(body, variant, int(v) if v.lstrip("-").isdigit() else v):
                    applied.append(f"body.{variant}={v}")
                    applied_body = True
                    break
            if applied_body:
                continue
        _set_body_dict(r, body)

    return _result(r, "boundary_pagination", None, True,
                   f"applied pagination edits: {', '.join(applied)}")


def _m_boundary_rate_limit(req, target, scenario, **kw):
    """Rate-limit boundary — observational; runner is expected to fire N requests."""
    return _result(req, "boundary_rate_limit", None, True,
                   "no mutation; runner expected to flood requests to trigger rate-limit")


# =============================================================================
# Mutation primitives — duplicate / state / filter
# =============================================================================

def _m_duplicate_request(req, target, scenario, **kw):
    """Engine-level no-op; runner is expected to repeat the request to trigger
    duplicate-rejection. Provenance recorded."""
    return _result(req, "duplicate_request", None, True,
                   "no mutation; runner expected to fire request twice to trigger duplicate")


def _m_state_precondition(req, target, scenario, **kw):
    """Set entity state pre-request. Engine emits no-mutation; runner handles state seeding."""
    return _result(req, "state_precondition", target, True,
                   f"no payload mutation; runner expected to seed state per scenario `{scenario}`")


def _m_case_state_precondition(req, target, scenario, **kw):
    return _result(req, "case_state_precondition", target, True,
                   "no payload mutation; runner expected to seed case state")


def _m_invalid_session(req, target, scenario, **kw):
    """Onboarding session validation. Set onboardingSessionId per scenario hint."""
    r = _request_copy(req)
    body = _get_body_dict(r)
    if not body:
        return _misfire(r, "invalid_session", None, "no body")
    s = scenario.lower()
    if s.startswith("empty"):
        val = ""
    elif s.startswith("malformed"):
        val = "MALFORMED-SESSION-XX"
    elif s.startswith("revoked"):
        val = "onb_sess_REVOKED_TOKEN_XX"
    elif s.startswith("expired"):
        val = "onb_sess_EXPIRED_TOKEN_XX"
    else:
        val = "INVALID_SESSION_X"
    if not _set_field_in_dict(body, "onboardingSessionId", val):
        return _misfire(r, "invalid_session", None, "no onboardingSessionId in body")
    _set_body_dict(r, body)
    return _result(r, "invalid_session", "onboardingSessionId", True,
                   f"onboardingSessionId set to `{val}`")


def _m_invalid_filter_combination(req, target, scenario, **kw):
    """Filter combination invalid — typically in query body. Engine emits no-mutation
    by default; specific combinations are scenario-driven and can be expanded."""
    return _result(req, "invalid_filter_combination", None, True,
                   "no payload mutation; runner verifies invalid-combination semantics")


def _m_drop_filter_field(req, target, scenario, **kw):
    """Drop a named filter field from the body or query string. Mutates to an
    INVALID value when the filter exists; falls back to appending an invalid
    value if the filter is undeclared in either place."""
    if not target:
        return _misfire(req, "drop_filter_field", None, "no field target")
    r = _request_copy(req)
    body = _get_body_dict(r)
    dropped = False
    used_variant = target
    if body:
        filters = body.get("filters")
        if isinstance(filters, dict):
            for variant in _camel_or_snake(target):
                if variant in filters:
                    filters[variant] = "INVALID_FILTER_VALUE"
                    dropped = True
                    used_variant = variant
                    break
        if not dropped:
            for variant in _camel_or_snake(target):
                if _set_field_in_dict(body, variant, "INVALID_FILTER_VALUE"):
                    dropped = True
                    used_variant = variant
                    break
        if dropped:
            _set_body_dict(r, body)

    if not dropped:
        raw = _get_url_raw(r)
        new = raw
        for variant in _camel_or_snake(target):
            pat = re.compile(r"(?<=[?&])" + re.escape(variant) + r"=([^&#]*)",
                              re.IGNORECASE)
            if pat.search(new):
                new = pat.sub(f"{variant}=INVALID_FILTER_VALUE", new)
                dropped = True
                used_variant = variant
                break
        if dropped and new != raw:
            _set_url_raw(r, new)

    if not dropped:
        # Last-ditch: append the filter with an invalid value, so the backend
        # still gets a malformed filter signal even when the swagger filter is
        # undeclared in the happy-path Postman call.
        raw = _get_url_raw(r)
        sep = "&" if "?" in raw else "?"
        new = f"{raw}{sep}{target}=INVALID_FILTER_VALUE"
        _set_url_raw(r, new)
        return _result(r, "drop_filter_field", target, True,
                        f"appended invalid `{target}` to query string (filter not present in body or query)")

    return _result(r, "drop_filter_field", used_variant, True,
                    f"set filter `{used_variant}` to invalid value")


def _m_body_format_mismatch(req, target, scenario, **kw):
    """File-content mismatch — set declared file extension to wrong type."""
    r = _request_copy(req)
    body = _get_body_dict(r)
    if not body:
        return _misfire(r, "body_format_mismatch", None, "no body")
    if _set_field_in_dict(body, "fileName", "not_a_csv.txt"):
        _set_body_dict(r, body)
        return _result(r, "body_format_mismatch", "fileName", True,
                       "fileName set to non-csv extension")
    return _misfire(r, "body_format_mismatch", None, "no fileName in body")


def _m_auth_role_policy(req, target, scenario, **kw):
    return _m_auth_role(req, target, scenario, role_key="wrong")


# =============================================================================
# No-op / observational kinds
# =============================================================================

def _m_no_mutation(req, target, scenario, **kw):
    return _result(req, "no_mutation", None, True, "positive scenario; sent unchanged")


def _m_observational(kind: str):
    def fn(req, target, scenario, **kw):
        return _result(req, kind, target, True,
                       f"observational scenario `{kind}`; sent unchanged, runner verifies side-effect")
    return fn


# =============================================================================
# Dispatch table
# =============================================================================

HANDLERS = {
    # auth
    "strip_auth": _m_strip_auth,
    "auth_expired_token": _m_auth_expired_token,
    "auth_expired_token_named": _m_auth_expired_token,
    "auth_invalid_token": _m_auth_invalid_token,
    "auth_malformed_token": _m_auth_malformed_token,
    "auth_wrong_role": lambda r, t, s, **kw: _m_auth_role(r, t, s, role_key="wrong"),
    "auth_bank_user": lambda r, t, s, **kw: _m_auth_role(r, t, s, role_key="bank"),
    "auth_admin_user": lambda r, t, s, **kw: _m_auth_role(r, t, s, role_key="admin"),
    "auth_service_provider": lambda r, t, s, **kw: _m_auth_role(r, t, s, role_key="service_provider"),
    "auth_sp_viewer": lambda r, t, s, **kw: _m_auth_role(r, t, s, role_key="sp_viewer"),
    "auth_role_policy": _m_auth_role_policy,
    # field-level
    "drop_field": _m_drop_field,
    "empty_string_field": _m_empty_string_field,
    "blank_field": _m_blank_field,
    "null_field": _m_null_field,
    "invalid_format": _m_invalid_format,
    "invalid_enum": _m_invalid_enum,
    "field_too_long": _m_field_too_long,
    "negative_value": _m_negative_value,
    "field_zero_value": _m_field_zero_value,
    "field_insufficient_value": _m_field_insufficient_value,
    "special_chars_field": _m_special_chars_field,
    "unicode_field": _m_unicode_field,
    "invalid_value": _m_invalid_value,
    "currency_mismatch": _m_currency_mismatch,
    "invalid_date_range": _m_invalid_date_range,
    "field_validation": _m_field_validation,
    # path-var
    "path_var_malformed": _m_path_var_malformed,
    "path_var_nonexistent": _m_path_var_nonexistent,
    "path_var_sql_injection": _m_path_var_sql_injection,
    "path_var_xss": _m_path_var_xss,
    "path_var_extremely_long": _m_path_var_extremely_long,
    # body-level
    "empty_body": _m_empty_body,
    "malformed_json_body": _m_malformed_json_body,
    "unknown_property": _m_unknown_property,
    "oversized_body": _m_oversized_body,
    "partial_payload": _m_partial_payload,
    "html_payload": _m_html_payload,
    # scope
    "scope_foreign": _m_scope_foreign,
    "scope_unlinked": _m_scope_unlinked,
    "scope_no_leak": _m_scope_no_leak,
    "scope_affiliate_state": _m_scope_affiliate_state,
    "scope_cross_owner": _m_scope_cross_owner,
    "scope_user_in_org": _m_scope_user_in_org,
    "scope_cross": _m_scope_cross,
    "scope_reuse_blocked": _m_scope_reuse_blocked,
    # http
    "wrong_method": _m_wrong_method,
    "wrong_content_type": _m_wrong_content_type,
    "wrong_accept_header": _m_wrong_accept_header,
    "unknown_query_param": _m_unknown_query_param,
    "drop_idempotency_key": _m_drop_idempotency_key,
    # boundary
    "boundary_value": _m_boundary_value,
    "boundary_pagination": _m_boundary_pagination,
    "boundary_rate_limit": _m_boundary_rate_limit,
    # state / filter
    "duplicate_request": _m_duplicate_request,
    "state_precondition": _m_state_precondition,
    "case_state_precondition": _m_case_state_precondition,
    "invalid_session": _m_invalid_session,
    "invalid_filter_combination": _m_invalid_filter_combination,
    "drop_filter_field": _m_drop_filter_field,
    "body_format_mismatch": _m_body_format_mismatch,
    # no-op / observational kinds (all go through `_m_observational`)
    "no_mutation": _m_no_mutation,
    "no_mutation_fallback_positive": _m_no_mutation,
    "padding_placeholder": _m_no_mutation,
}


def _make_observational_handlers():
    obs_kinds = [
        "observational_response_shape", "observational_audit_log",
        "observational_idempotency", "observational_concurrency",
        "observational_correlation", "observational_read_only",
        "observational_persistence", "observational_event_emitted",
        "observational_state_verified", "observational_processing_outcome",
        "observational_security", "observational_edge_data",
        "observational_filter_semantics", "observational_path_robustness",
        "observational_no_persistence_on_failure", "observational_metrics",
        "observational_read_after_write", "observational_complex_body",
        "observational_input_safety", "observational_headers_response",
        "observational_event_emission", "observational_cms",
    ]
    for k in obs_kinds:
        HANDLERS[k] = _m_observational(k)


_make_observational_handlers()


# =============================================================================
# Public entry point
# =============================================================================

def apply_mutation(request: dict, scenario: str,
                    endpoint: str | None = None,
                    swagger: dict | None = None) -> dict:
    """Apply the mutation matching the scenario to the Postman request.

    Args:
        request: Postman v2 request dict (method, url, header, body).
        scenario: scenario name from the test pack TC.
        endpoint: optional pack endpoint string (e.g. "POST /api/v1/cards/issuance");
            used only by future swagger-aware mutations (none yet).
        swagger: pre-loaded MainSwagger.txt dict (optional; same future use).

    Returns:
        {"request": <mutated_dict>, "mutation": {...provenance...}}
    """
    cls = classify(scenario)
    kind = cls["kind"]
    target = cls["target"]
    handler = HANDLERS.get(kind)
    if handler is None:
        # Truly unrecognized — engine doesn't know what to do.
        return _misfire(request, kind or "unrecognized", target,
                        f"no handler for kind `{kind}` (scenario `{scenario}`)")
    try:
        return handler(request, target, scenario, endpoint=endpoint, swagger=swagger)
    except Exception as exc:
        return _misfire(request, kind, target, f"handler raised: {exc!r}")


# =============================================================================
# CLI smoke
# =============================================================================

if __name__ == "__main__":
    sample_req = {
        "method": "POST",
        "url": {"raw": "{{baseUrl}}/api/v1/customers/draft", "path": ["api", "v1", "customers", "draft"]},
        "header": [{"key": "Authorization", "value": "Bearer ORIG_TOKEN"}],
        "body": {
            "mode": "raw",
            "raw": json.dumps({
                "requestContext": {"tenantId": "TNT-1", "affiliateId": "AFF-1"},
                "customer": {"identity": {"firstName": "Pat", "lastName": "M"}},
            }),
        },
    }
    for scen in [
        "happy_path_success",
        "missing_tenantId_rejected",
        "expired_token_rejected",
        "wrong_role_rejected",
        "tenantId_with_sql_injection_payload",
        "malformed_json_rejected",
        "delete_method_not_allowed",
        "unicode_firstName_handled",
        "invalid_currency_enum_rejected",
    ]:
        r = apply_mutation(sample_req, scen)
        print(f"  {scen:<40} -> action={r['mutation']['action']:<25} "
              f"applied={r['mutation']['applied']}  note={r['mutation']['note'][:80]}")
