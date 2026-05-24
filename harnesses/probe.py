"""GET-after-POST persistence probe (currently used by Bank and Cards harnesses).

Adoption status (2026-05-04)
----------------------------
ACTIVE consumers: postman_hybrid_bank_runner.py, postman_hybrid_cards_runner.py.
NOT YET PORTED: admin, batch, customer, notifications, transactions, affiliate.
The other harnesses keep local verify-loop copies for now (deliberate, see Codex
audit M10 — full port deferred to a separate refactor pass alongside L11).
Once a harness is ported, add it to this list rather than letting drift accrue.

Purpose
-------
Diagnose whether a 2xx write actually persisted by reading the resource back.
Distinct from per-service pre-flight verify loops; this fires per-TC for every
successful write to a probe-enabled endpoint.

The probe MUST NEVER upgrade a verdict to PASS. Its job is to refine
attribution (write-path vs read-path vs persisted). Each runner is responsible
for applying the result to verdicts; this module only produces the diagnostic
record.

Result kinds
------------
- persisted: primary GET returned 2xx; write confirmed
- not_persisted: primary 404 after retries AND secondary 404/non-2xx; write defect
- read_path_5xx: primary 5xx and secondary not-2xx; cannot confirm persistence
- partial_persistence: one read path 2xx, the other 404/5xx; index drift
- transport_error: probe could not reach the API
- skipped: no resource_id extractable
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

DEFAULT_MAX_WAIT_S = float(os.environ.get("PROBE_MAX_WAIT_S", "6.0"))


def probe_get_after_post(
    resource_id: str | None,
    base_url: str,
    execute: Callable[..., dict[str, Any]],
    primary_path_template: str,
    secondary_path_template: str | None = None,
    token_replacements: dict[str, str] | None = None,
    max_retries: int = 2,
    delay_s: float = 1.0,
    max_wait_s: float | None = None,
) -> dict:
    """Run a GET-after-POST persistence probe.

    Parameters
    ----------
    resource_id : the id minted by the POST (e.g. cardId, bankId). If None,
        probe returns kind="skipped".
    base_url : harness BASE_URL (e.g. "http://167.172.49.177:8080").
    execute : the runner's HTTP executor; must return a dict with keys
        "ok", "status_code", "body", "error" (matches existing harness conv).
    primary_path_template : path template with {token} placeholders to fill
        with resource_id (e.g. "/api/v1/cards/{cardId}").
    secondary_path_template : optional fallback probe path. When primary
        returns 5xx, secondary disambiguates read-path-broken from
        id-not-persisted. If None, no fallback.
    token_replacements : extra {token}->resource_id substitutions beyond the
        natural set ({cardId}, {bankId}, {affiliateId}, {batchId}). Use when
        the probe path has a non-standard placeholder name.
    max_retries : additional attempts after the first call (so total
        attempts = max_retries + 1). Defaults to 2 (3 attempts total).
    delay_s : base linear backoff in seconds between retries (1s, 2s, 3s).
    max_wait_s : hard wall-clock cap. Defaults to PROBE_MAX_WAIT_S env var.
    """
    if max_wait_s is None:
        max_wait_s = DEFAULT_MAX_WAIT_S

    rec = {
        "kind": "skipped",
        "primary_url": None,
        "primary_status": None,
        "primary_attempts": 0,
        "secondary_url": None,
        "secondary_status": None,
        "persistence_confirmed": None,
        "reason": None,
    }

    if not resource_id:
        rec["reason"] = "no resource_id extracted from POST response"
        return rec

    started = time.monotonic()

    def _resolve(template: str) -> str:
        out = template
        # Caller-supplied substitutions apply FIRST (they win over standard
        # token replacement). Use this when the path has multiple tokens
        # that must resolve to different values (e.g. nested mint endpoints).
        if token_replacements:
            for token, value in token_replacements.items():
                if not token.startswith("{"):
                    token = "{" + token + "}"
                out = out.replace(token, value)
        # Standard token set every Kardit harness uses; substitutes whatever
        # tokens remain with resource_id.
        for token in ("{cardId}", "{bankId}", "{affiliateId}", "{batchId}",
                      "{customerId}", "{transactionId}", "{notificationId}",
                      "{loadRequestId}", "{limitRequestId}"):
            out = out.replace(token, resource_id)
        return f"{base_url}{out}"

    primary_url = _resolve(primary_path_template)
    rec["primary_url"] = primary_url
    last_primary_status = None
    primary_5xx = False

    for attempt in range(max_retries + 1):
        if time.monotonic() - started > max_wait_s:
            rec.update({
                "kind": "not_persisted",
                "primary_status": last_primary_status,
                "persistence_confirmed": False,
                "reason": f"probe exceeded max wait {max_wait_s}s before 2xx",
            })
            return rec
        rec["primary_attempts"] = attempt + 1
        resp = execute("GET", primary_url, {"Accept": "application/json"}, None, timeout=10)
        sc = resp.get("status_code")
        last_primary_status = sc
        if not resp.get("ok"):
            rec.update({
                "kind": "transport_error",
                "primary_status": sc,
                "persistence_confirmed": None,
                "reason": f"primary probe transport error: {resp.get('error')}",
            })
            return rec
        if sc and 200 <= sc < 300:
            rec.update({
                "kind": "persisted",
                "primary_status": sc,
                "persistence_confirmed": True,
                "reason": f"primary GET returned {sc} on attempt {attempt + 1}",
            })
            return rec
        if sc and 500 <= sc < 600:
            primary_5xx = True
            break
        if sc != 404:
            rec.update({
                "kind": "not_persisted",
                "primary_status": sc,
                "persistence_confirmed": False,
                "reason": f"primary GET returned non-2xx non-404 non-5xx ({sc}); treating as not persisted",
            })
            return rec
        if attempt < max_retries:
            time.sleep(delay_s * (attempt + 1))

    if not secondary_path_template:
        rec.update({
            "kind": "not_persisted" if not primary_5xx else "read_path_5xx",
            "primary_status": last_primary_status,
            "persistence_confirmed": False if not primary_5xx else None,
            "reason": (f"primary {'5xx' if primary_5xx else '404'} ({last_primary_status}) "
                       "and no secondary configured"),
        })
        return rec

    secondary_url = _resolve(secondary_path_template)
    rec["secondary_url"] = secondary_url
    sec_resp = execute("GET", secondary_url, {"Accept": "application/json"}, None, timeout=10)
    sec_sc = sec_resp.get("status_code")
    rec["secondary_status"] = sec_sc

    if primary_5xx:
        if sec_resp.get("ok") and sec_sc and 200 <= sec_sc < 300:
            rec.update({
                "kind": "partial_persistence",
                "primary_status": last_primary_status,
                "persistence_confirmed": True,
                "reason": (f"primary returned 5xx ({last_primary_status}) but secondary "
                           f"({secondary_path_template}) returned {sec_sc}; id is persisted, "
                           "primary read path is broken"),
            })
            return rec
        rec.update({
            "kind": "read_path_5xx",
            "primary_status": last_primary_status,
            "persistence_confirmed": None,
            "reason": (f"primary returned 5xx ({last_primary_status}) and secondary returned "
                       f"{sec_sc}; cannot determine persistence — read path defect"),
        })
        return rec

    if sec_resp.get("ok") and sec_sc and 200 <= sec_sc < 300:
        rec.update({
            "kind": "partial_persistence",
            "primary_status": last_primary_status,
            "persistence_confirmed": True,
            "reason": (f"primary 404'd after {max_retries + 1} attempts but secondary "
                       f"({secondary_path_template}) returned {sec_sc}; id is persisted, "
                       "primary index missing or stale"),
        })
        return rec

    rec.update({
        "kind": "not_persisted",
        "primary_status": last_primary_status,
        "persistence_confirmed": False,
        "reason": (f"primary 404 after {max_retries + 1} attempts AND secondary returned "
                   f"{sec_sc}; id not retrievable on either read path — write did not persist"),
    })
    return rec


def state_effect_probe(
    resource_id: str | None,
    base_url: str,
    execute: Callable[..., dict[str, Any]],
    verify_path_template: str,
    expected_field_path: str,
    expected_value: Any,
    token_replacements: dict[str, str] | None = None,
    max_retries: int = 1,
    delay_s: float = 1.0,
) -> dict:
    """Verify a state-changing write by reading back the affected field.

    Distinct from probe_get_after_post: that asks "does the resource exist?"
    This asks "did the resource's state actually change?" Useful for moving
    B1_db_verify BLOCKEDs to PASS/FAIL when the state effect is observable
    via an existing GET endpoint.

    Parameters
    ----------
    resource_id : id of the resource whose state should have changed.
    verify_path_template : GET endpoint that returns the resource state.
    expected_field_path : dot-path into the response body, e.g. "data.status"
        or "balance.amount". Supports nested objects only (no array index).
    expected_value : value the field should equal after the write. May be
        a string, number, bool, None, or a callable (lambda) that takes the
        actual value and returns True/False. If callable, the probe records
        the predicate result and the actual value.

    Returns dict with kind ∈ {state_confirmed, state_mismatch,
    state_field_missing, state_get_failed, skipped}.
    """
    rec = {
        "kind": "skipped",
        "verify_url": None,
        "verify_status": None,
        "expected_field_path": expected_field_path,
        "expected_value": expected_value if not callable(expected_value) else "<predicate>",
        "actual_value": None,
        "state_confirmed": None,
        "reason": None,
    }
    if not resource_id:
        rec["reason"] = "no resource_id available for state verification"
        return rec

    out = verify_path_template
    if token_replacements:
        for token, value in token_replacements.items():
            if not token.startswith("{"):
                token = "{" + token + "}"
            out = out.replace(token, value)
    for token in ("{cardId}", "{bankId}", "{affiliateId}", "{batchId}",
                  "{customerId}", "{transactionId}", "{notificationId}",
                  "{loadRequestId}", "{limitRequestId}"):
        out = out.replace(token, resource_id)
    url = f"{base_url}{out}"
    rec["verify_url"] = url

    last_status = None
    body = None
    for attempt in range(max_retries + 1):
        resp = execute("GET", url, {"Accept": "application/json"}, None, timeout=10)
        sc = resp.get("status_code")
        last_status = sc
        if resp.get("ok") and sc and 200 <= sc < 300:
            body = resp.get("body")
            break
        if attempt < max_retries:
            time.sleep(delay_s * (attempt + 1))
    rec["verify_status"] = last_status

    if body is None:
        rec.update({
            "kind": "state_get_failed",
            "state_confirmed": False,
            "reason": f"verify GET returned {last_status}; cannot read state",
        })
        return rec

    actual = body
    parts = [p for p in expected_field_path.split(".") if p]
    for p in parts:
        if isinstance(actual, dict) and p in actual:
            actual = actual[p]
        else:
            rec.update({
                "kind": "state_field_missing",
                "actual_value": None,
                "state_confirmed": False,
                "reason": f"field '{expected_field_path}' not present in response body",
            })
            return rec
    rec["actual_value"] = actual

    if callable(expected_value):
        try:
            ok = bool(expected_value(actual))
        except Exception as e:
            rec.update({
                "kind": "state_mismatch",
                "state_confirmed": False,
                "reason": f"predicate raised: {e}",
            })
            return rec
        rec.update({
            "kind": "state_confirmed" if ok else "state_mismatch",
            "state_confirmed": ok,
            "reason": (f"predicate {'matched' if ok else 'did not match'} "
                       f"actual value {actual!r}"),
        })
        return rec

    if actual == expected_value:
        rec.update({
            "kind": "state_confirmed",
            "state_confirmed": True,
            "reason": f"actual value {actual!r} matches expected {expected_value!r}",
        })
        return rec
    rec.update({
        "kind": "state_mismatch",
        "state_confirmed": False,
        "reason": f"expected {expected_value!r}, got {actual!r}",
    })
    return rec
