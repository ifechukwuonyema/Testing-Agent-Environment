"""Body-aware query mutation helpers shared by all Kardit hybrid harnesses.

Background
----------
Many Kardit endpoints (e.g. POST /api/v1/banks/query, /cards/query, /transactions/{query})
carry pagination + filter parameters in the JSON request body, not on the URL query
string. The harness's `set_query` mutations historically wrote to the URL only — which
ASP.NET Core silently ignored on POST-body endpoints, producing meaningless test
verdicts. The 2026-05-04 Postman swap also changed `filters.status` from a string
scalar to an array (`["ACTIVE"]`), so a naive scalar replacement now corrupts the
schema.

`smart_set_query` resolves both:
  - For POST requests with a dict body, find the target field at top-level or under
    common containers (filters, filter, criteria, pagination, page) and set it there.
  - Preserve the existing value's type when possible (wrap scalars into single-item
    lists if the existing value was a list; coerce numeric strings).
  - Fall back to a case-insensitive URL-query replacement (matching the prior patch).

Returns (body, query, note) — callers should reassign all three because we don't
mutate the inputs in place (defensive copies for body containers).
"""
from __future__ import annotations

import copy
from typing import Any


_BODY_CONTAINERS = ("filters", "filter", "criteria", "pagination", "page")


def _coerce(existing_val: Any, new_val: Any) -> Any:
    """Best-effort type preservation when overwriting an existing body field.

    Codex re-audit R5: list handling is idempotent — if the new value is already
    a list, pass through unchanged; if it is None, return [] rather than [None]
    (a one-element list of None breaks downstream serializers).
    """
    if isinstance(existing_val, list):
        if isinstance(new_val, list):
            return new_val
        if new_val is None:
            return []
        return [new_val]
    if isinstance(existing_val, bool):
        if isinstance(new_val, bool):
            return new_val
        if isinstance(new_val, str):
            low = new_val.lower()
            if low in ("true", "false"):
                return low == "true"
        return new_val
    if isinstance(existing_val, int):
        try:
            return int(new_val)
        except (TypeError, ValueError):
            return new_val
    if isinstance(existing_val, float):
        try:
            return float(new_val)
        except (TypeError, ValueError):
            return new_val
    return new_val


# Keys that conventionally live inside POST query body filter containers.
# When a mutation targets one of these on a POST endpoint with a dict body,
# we INSERT it into the canonical container (filters/pagination) rather than
# silently appending to the URL query string — ASP.NET Core ignores URL query
# params on POST-body endpoints, so the URL fallback would no-op the test.
_FILTER_FIELDS = frozenset({
    "status", "entitytype", "fromdate", "todate", "from_date", "to_date",
    "search", "currency", "country", "country_code", "actoruserid", "eventtype",
    "affiliateid", "bankid", "customerid", "cardid", "transactionid",
    "cardtype", "producttype", "productid",
    # Codex re-audit MEDIUM-1: transaction-domain and reporting fields the
    # third audit found in active Postman bodies that were silently dropping
    # to URL query (and being ignored by ASP.NET).
    "transactiontype", "reporttype", "reference", "merchantname",
    "merchant_name", "merchantid", "merchant_id",
})
# Pagination fields. _TOP_LEVEL_PAGINATION are paginators that conventionally
# live at the top level of the body (not under a `pagination` container) —
# Transactions/Reports use pageNumber+pageSize at top level. Inserting these
# under `pagination` would land in the wrong shape, so route them top-level.
_TOP_LEVEL_PAGINATION = frozenset({"pagenumber", "page_number"})
_PAGINATION_FIELDS = frozenset({
    "page", "pagesize", "page_size", "limit", "offset",
}) | _TOP_LEVEL_PAGINATION

# Codex re-audit MEDIUM-6 (2026-05-04): equivalence groups for paginators that
# Kardit endpoints use interchangeably across services. A mutation targeting
# `page` against a body that already has `pageNumber` must rewrite pageNumber,
# not insert a sibling `page` (the backend reads pageNumber and ignores page,
# making the test a silent no-op). Each group is a set of lowercase names; any
# member matches any other when looking up an existing field to rewrite.
_PAGINATOR_EQUIVALENCE_GROUPS = (
    frozenset({"page", "pagenumber", "page_number"}),
    frozenset({"pagesize", "page_size"}),
)


def _equivalent_keys(klow: str) -> frozenset:
    """Return the set of lowercase field names that should be considered the
    same target as `klow` for body-rewrite purposes. Equivalence applies to
    paginator spelling variants only; everything else returns a singleton."""
    for grp in _PAGINATOR_EQUIVALENCE_GROUPS:
        if klow in grp:
            return grp
    return frozenset({klow})


def smart_set_query(method: str, body: Any, query: dict, key: str, value: Any
                    ) -> tuple[Any, dict, str]:
    """Set a parameter, routing into body for POST query/search endpoints when the
    field is body-resident; otherwise set as URL query (case-insensitive replace).

    Routing precedence (top-level > nested; within each level: exact > equivalent):
      1a. POST body, top-level EXACT case-insensitive match → set there.
      1b. POST body, top-level paginator-EQUIVALENT match (page ≡ pageNumber etc.) → set there.
      2a. POST body, existing nested container (filters/filter/criteria/pagination/page)
          EXACT case-insensitive match → set there.
      2b. POST body, nested container paginator-EQUIVALENT match → set there.
      3.  POST body with dict body, key looks like a known filter/pagination field
          → INSERT into the canonical container (filters or pagination), creating
          the container if absent. Codex re-audit R6: previously these dropped to
          URL query and were silently ignored by ASP.NET.
      4.  URL query (case-insensitive replace, or insert if not present).

    INVARIANT (Codex stage-2 follow-up F3b clarification, 2026-05-04): top-level
    matches always beat nested matches, even when the top-level match is only
    paginator-equivalent and a nested match is exact. Rationale: in Kardit
    bodies the top-level paginator is the canonical one the backend reads; a
    nested `page` is more likely an unrelated field (e.g., filters.page meaning
    page-of-filter-values). Equivalence-only routing applies to paginators only
    (page ≡ pageNumber ≡ page_number, pageSize ≡ page_size); other keys never
    match by equivalence.
    """
    klow = key.lower()
    eq_targets = _equivalent_keys(klow)

    # POST body routing: only when method is POST and body is a dict.
    # Stage-2 follow-up F3 (2026-05-04): exact case-insensitive match has
    # priority over paginator-equivalent match. When body has BOTH `page`
    # and `pageNumber` and the mutation targets `page`, we want `page` to
    # win regardless of dict iteration order — falling through to
    # paginator-equivalence is the fallback only.
    if method == "POST" and isinstance(body, dict):
        # 1a. Top-level EXACT case-insensitive match.
        for k in list(body.keys()):
            if k.lower() == klow:
                new_body = copy.deepcopy(body)
                new_body[k] = _coerce(body[k], value)
                return new_body, query, f"set body field '{k}={value!r}' (POST query body)"
        # 1b. Top-level paginator-equivalent match (when no exact match exists).
        if eq_targets != frozenset({klow}):
            for k in list(body.keys()):
                if k.lower() in eq_targets:
                    new_body = copy.deepcopy(body)
                    new_body[k] = _coerce(body[k], value)
                    return (new_body, query,
                            f"set body field '{k}={value!r}' (POST query body) "
                            f"(paginator-equivalent to '{key}')")
        # 2a. Nested container EXACT case-insensitive match.
        for container in _BODY_CONTAINERS:
            sub = body.get(container)
            if isinstance(sub, dict):
                for k in list(sub.keys()):
                    if k.lower() == klow:
                        new_body = copy.deepcopy(body)
                        new_body[container][k] = _coerce(sub[k], value)
                        return (new_body, query,
                                f"set body field '{container}.{k}={value!r}' (POST query body)")
        # 2b. Nested container paginator-equivalent match (when no exact match).
        if eq_targets != frozenset({klow}):
            for container in _BODY_CONTAINERS:
                sub = body.get(container)
                if isinstance(sub, dict):
                    for k in list(sub.keys()):
                        if k.lower() in eq_targets:
                            new_body = copy.deepcopy(body)
                            new_body[container][k] = _coerce(sub[k], value)
                            return (new_body, query,
                                    f"set body field '{container}.{k}={value!r}' "
                                    f"(POST query body) (paginator-equivalent to '{key}')")
        # 3. Known filter/pagination field that wasn't present — INSERT into the
        #    canonical container (or top-level for paginators that live there).
        if klow in _FILTER_FIELDS or klow in _PAGINATION_FIELDS:
            new_body = copy.deepcopy(body)
            # Top-level paginators (pageNumber, page_number): insert flat.
            if klow in _TOP_LEVEL_PAGINATION:
                new_body[key] = value
                return (new_body, query,
                        f"inserted top-level body field '{key}={value!r}' (POST query body, key was absent)")
            # Other paginators: prefer top-level if any sibling paginator already
            # lives at top level (heuristic for harnesses whose body is flat-shaped).
            if klow in _PAGINATION_FIELDS:
                has_top_level_paginator = any(
                    k.lower() in _PAGINATION_FIELDS for k in new_body
                )
                if has_top_level_paginator:
                    new_body[key] = value
                    return (new_body, query,
                            f"inserted top-level body field '{key}={value!r}' (matched flat paginator shape)")
                target_container = "pagination"
            else:
                target_container = "filters"
            existing_container_key = next(
                (k for k in new_body if k.lower() == target_container), None)
            ck = existing_container_key or target_container
            if not isinstance(new_body.get(ck), dict):
                new_body[ck] = {}
            new_body[ck][key] = value
            return (new_body, query,
                    f"inserted body field '{ck}.{key}={value!r}' (POST query body, key was absent)")

    # URL query fallback (case-insensitive replace)
    existing = next((qk for qk in query if qk.lower() == klow), None)
    target_key = existing if existing else key
    new_query = dict(query)
    new_query[target_key] = value
    return body, new_query, f"set query '{target_key}={value}'"


def smart_set_query_pair(method: str, body: Any, query: dict, values: dict
                         ) -> tuple[Any, dict, str]:
    """Apply smart_set_query for each key/value in `values`."""
    for k, v in values.items():
        body, query, _ = smart_set_query(method, body, query, k, v)
    return body, query, f"set query pair {values}"


# --- ID extraction from query/list responses -------------------------------
import re as _re

# Sentinel values that should never be treated as legitimate IDs.
_SENTINEL_VALUES = {"string", "null", "none", "n/a", "tbd", "todo", ""}
_SENTINEL_RE = _re.compile(r"^0+(-0+)*$")


def _is_real_id(v: Any, expected_prefix: str | None = None,
                expected_pattern: str | None = None) -> bool:
    """Reject Postman placeholders, zero-UUIDs, and shape mismatches."""
    if not isinstance(v, str) or not v:
        return False
    s = v.strip().lower()
    if s in _SENTINEL_VALUES:
        return False
    stripped = _re.sub(r"[^0-9a-z]", "", s)
    if not stripped or _SENTINEL_RE.match(stripped) or set(stripped) <= {"0"}:
        return False
    if expected_prefix and not v.startswith(expected_prefix):
        return False
    if expected_pattern and not _re.match(expected_pattern, v):
        return False
    return True


def extract_first_id_recursive(body: Any, key_candidates: tuple[str, ...],
                               expected_prefix: str | None = None,
                               expected_pattern: str | None = None,
                               max_depth: int = 12) -> str | None:
    """Recursively walk a query/list response for the first valid id under any of
    `key_candidates`. Handles arbitrary envelope shapes (data, data.data, items,
    results, nested wrappers) without each caller having to enumerate them.

    Skips sentinel values ("string", zero-UUIDs, etc.) and optionally enforces a
    prefix (e.g. "CAR-") or regex pattern for the id token shape.
    """
    if not key_candidates:
        return None

    def walk(obj: Any, depth: int = 0) -> str | None:
        if depth > max_depth:
            return None
        if isinstance(obj, dict):
            # Direct hit on any candidate key at this level
            for k in key_candidates:
                if k in obj:
                    v = obj[k]
                    if _is_real_id(v, expected_prefix, expected_pattern):
                        return v
            # Recurse into all values
            for v in obj.values():
                found = walk(v, depth + 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = walk(v, depth + 1)
                if found:
                    return found
        return None

    return walk(body)
