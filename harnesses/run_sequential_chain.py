"""
Sequential chain runner across 8 Kardit microservices.

Runs each service's hybrid harness in order. Between services, scans the
just-finished evidence files for newly-created IDs and writes them to the
shared session file so downstream services pick them up.

Order: Bank -> Affiliate -> Customer -> Cards -> Transactions -> Batch -> Notifications -> Admin

Each service's pre-flight will:
  1. Read SessionStore (kardit_session_ids.json) and use upstream IDs.
  2. Try to mint a fresh primary ID where applicable.
  3. Fall back to the service's query endpoint (POST /<service>/query) to surface
     an existing persisted ID when mint fails or returns no extractable id.
     Applies to Bank/Affiliate/Cards. Transactions has no mint endpoint and goes
     directly to query-first.
  4. Fall back to Postman literal as a last resort.

After each service finishes, this orchestrator harvests IDs from successful
(2xx) responses in the evidence directory and updates SessionStore.

A per-service memory file is also written to the Obsidian vault, so the
Dataview leaderboard in MEMORY.md fills in live as the chain progresses.

Usage:
    py run_sequential_chain.py

The chain does NOT abort on per-service failures. If a service's pre-flight
mint fails, the harness falls back to whatever ID is already in SessionStore
or the Postman literal, and the next service still runs.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

DOWNLOADS = Path(r"C:\Users\Onyema Ifechukwu\Downloads")
HARNESSES_DIR = Path(__file__).resolve().parent
SESSION_STORE = DOWNLOADS / "kardit_session_ids.json"
VAULT = Path(r"C:\Users\Onyema Ifechukwu\.claude\projects\C--WINDOWS-system32\memory")
CHAIN_TS = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
TODAY = dt.date.today().isoformat()
CHAIN_REPORT = DOWNLOADS / f"chain_run_{CHAIN_TS}.yaml"
CHAIN_LOG = DOWNLOADS / f"chain_run_{CHAIN_TS}.log"

# (label, harness script, report-prefix, evidence-prefix)
# Order: chain finishes with Admin so it has real cases to act on.
CHAIN_SEQUENCE = [
    ("Bank",          "postman_hybrid_bank_runner.py",          "bank_postman_hybrid_report_",          "evidence_postman_bank_hybrid_"),
    ("Affiliate",     "postman_standalone_affiliate_v2.py",     "affiliate_postman_standalone_v2_report_", "evidence_postman_affiliate_v2_"),
    ("Customer",      "postman_hybrid_customer_runner.py",      "customer_postman_hybrid_report_",      "evidence_postman_customer_hybrid_"),
    ("Cards",         "postman_hybrid_cards_runner.py",         "cards_postman_hybrid_report_",         "evidence_postman_cards_hybrid_"),
    ("Transactions",  "postman_hybrid_transactions_runner.py",  "transactions_postman_hybrid_report_",  "evidence_postman_transactions_hybrid_"),
    ("Batch",         "postman_hybrid_batch_runner.py",         "batch_postman_hybrid_report_",         "evidence_postman_batch_hybrid_"),
    ("Notifications", "postman_hybrid_notifications_runner.py", "notifications_postman_hybrid_report_", "evidence_postman_notifications_hybrid_"),
    ("Admin",         "postman_hybrid_admin_runner.py",         "admin_postman_hybrid_report_",         "evidence_postman_admin_hybrid_"),
]

# Per-service IDs to harvest from successful response bodies.
# Key names match the actual response body fields the backend returns.
ID_HARVEST = {
    "Bank":          ["bankId"],
    "Affiliate":     ["affiliateId", "parentAffiliateId"],
    "Customer":      ["customerRefId", "customerId", "draftId"],
    "Cards":         ["cardId", "virtualCardId", "accountId"],
    "Transactions":  ["transactionId", "exportId"],
    "Batch":         ["batchId"],
    "Notifications": ["notificationId"],
    "Admin":         ["caseId"],
}

# Memory file naming convention in the vault.
MEMORY_FILE_TEMPLATE = "project_{service_lower}_chain_run_{date_compact}.md"


def log(msg: str) -> None:
    line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with CHAIN_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_session() -> dict:
    if SESSION_STORE.exists():
        try:
            return json.loads(SESSION_STORE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_session(data: dict) -> None:
    SESSION_STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def find_newest(prefix: str, after_ts: float) -> Path | None:
    """Find newest file/dir starting with prefix, modified after after_ts.

    Codex re-audit LOW-7 (2026-05-04): excludes .tar.gz archives created by
    retention. Without this exclusion, a freshly-archived previous run could
    be returned for an evidence prefix and break downstream `iterdir()` /
    `glob('*.json')` calls (an archive is a file, not a directory). Reports
    are .yaml; evidence is always a directory before archival; a .tar.gz
    matching either prefix is never the right answer.
    """
    candidates = []
    for p in DOWNLOADS.iterdir():
        if not p.name.startswith(prefix):
            continue
        if p.name.endswith(".tar.gz"):
            continue
        try:
            if p.stat().st_mtime >= after_ts - 5:
                candidates.append(p)
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


# Codex re-audit #11: keep this many most-recent runs per artifact prefix; older
# get archived (.tar.gz for dirs, left in place for files) to bound disk usage
# without losing audit trail. Override via CHAIN_RETENTION_KEEP env var.
RETENTION_KEEP = int(os.environ.get("CHAIN_RETENTION_KEEP", "5"))


def prune_old_runs(prefix: str, keep: int = RETENTION_KEEP) -> int:
    """Keep the N most recent dirs/files matching prefix; archive older dirs as
    .tar.gz, delete older non-yaml files. yaml reports are kept (small).

    Returns the number of items pruned.
    """
    if keep <= 0:
        return 0
    matches = []
    try:
        for p in DOWNLOADS.iterdir():
            if not p.name.startswith(prefix):
                continue
            # Skip already-compressed archives we created previously.
            if p.name.endswith(".tar.gz"):
                continue
            try:
                matches.append((p.stat().st_mtime, p))
            except OSError:
                continue
    except OSError:
        return 0
    if len(matches) <= keep:
        return 0
    matches.sort(reverse=True)  # newest first
    pruned = 0
    for _, p in matches[keep:]:
        try:
            if p.is_dir():
                # Compress the dir into .tar.gz alongside, then remove the dir.
                import shutil
                archive_target = str(p) + ".tar.gz"
                if not Path(archive_target).exists():
                    shutil.make_archive(str(p), "gztar", root_dir=str(p.parent),
                                        base_dir=p.name)
                shutil.rmtree(p)
            elif p.suffix == ".yaml":
                # Keep yaml reports — they're small and the audit trail.
                continue
            else:
                p.unlink(missing_ok=True)
            pruned += 1
        except Exception as e:
            log(f"  prune skipped {p.name}: {e}")
    return pruned


_SENTINEL_RE = re.compile(r"^0+(-0+)*$")  # zero-UUID, "00000000-0000-0000-0000-000000000000", etc.


def _is_valid_id(v: str) -> bool:
    """Reject Postman placeholders, zero-UUID, all-zero strings, and obvious sentinels.

    Canonical sentinel gate for chain harvest. Used by extract_id (evidence walk),
    direct setup harvest, seeded_ids fallback, and _verified_keys_in_report.

    DEFERRED (Codex stage-2 LOW, 2026-05-04): per-harness pre-flight extractors
    (customer/transactions/admin) do NOT sentinel-check before verify-before-save.
    Verify gates persistence in practice — a 'string' or zero-UUID would 404 on
    GET — but a future-broken verifier could let a sentinel reach SessionStore.
    Hardening would mean wiring _is_valid_id (or query_mutator._is_real_id) into
    each extractor's pick step. Not load-bearing for current behavior.
    """
    if not v:
        return False
    s = v.strip().lower()
    if s in {"string", "null", "none", "n/a", "tbd", "todo"}:
        return False
    # Strip non-alphanum to catch zero-UUID variants like "00000000-0000-0000-0000-000000000000"
    stripped = re.sub(r"[^0-9a-z]", "", s)
    if not stripped or _SENTINEL_RE.match(stripped):
        return False
    if set(stripped) <= {"0"}:
        return False
    return True


def extract_id(obj, key: str, depth: int = 0):
    """Recursively look for a key in nested dict/list. Return first non-empty string
    that is not a sentinel/placeholder value (zero-UUID, 'string' literal, etc)."""
    if depth > 12:
        return None
    if isinstance(obj, dict):
        v = obj.get(key)
        if isinstance(v, str) and _is_valid_id(v):
            return v
        for value in obj.values():
            found = extract_id(value, key, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = extract_id(value, key, depth + 1)
            if found:
                return found
    return None


def harvest_ids_from_evidence(evidence_dir: Path, keys: list[str]) -> dict:
    """Walk evidence files; collect IDs from PASS verdicts ONLY, and only when
    the per-TC persistence probe (if present) confirms the resource actually
    persisted.

    Codex re-audit HIGH-1 (2026-05-04, Council-prioritized): the prior version
    also accepted `as_is`/no-mutation evidence on the assumption that "untampered
    request = trustworthy response." But a 2xx as_is response with a schema-broken
    body still gets verdict=FAIL — and harvesting an id from a known-broken
    response poisons the chain. PASS is the only verdict that actually attests
    the response is usable; the as_is escape is dropped.

    Codex re-audit #3 (2026-05-04): Bank/Cards harnesses fire a GET-after-POST
    probe to detect phantom writes (2xx returned, but resource not retrievable).
    The runner only downgrades non-PASS verdicts on probe=not_persisted, so a
    PASS+not_persisted slips through. Harvesting a phantom id propagates it
    downstream.

    Stage-2 follow-up F2 (2026-05-04): also reject 'transport_error' — probe.py
    sets persistence_confirmed=None when the probe itself couldn't reach the
    API, so persistence is unconfirmed. Treating that as "harvest anyway"
    propagates ids whose existence was never verified.
    Rejected kinds: 'not_persisted', 'read_path_5xx', 'transport_error'.
    Allowed: 'persisted', 'partial_persistence' (id IS persisted, primary
    index drift only — see probe.py:178-180), 'skipped', or absent (probe
    not fired for this endpoint).
    """
    PROBE_REJECTS = {"not_persisted", "read_path_5xx", "transport_error"}
    found: dict[str, str] = {}
    if not evidence_dir or not evidence_dir.is_dir():
        return found
    for f in sorted(evidence_dir.glob("*.json")):
        try:
            tc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        resp = tc.get("response") or {}
        status = resp.get("status_code") or 0
        if not (200 <= status < 300):
            continue
        # Only harvest from PASS verdicts.
        verdict_status = (tc.get("verdict") or {}).get("status") or tc.get("execution_status")
        if verdict_status != "PASS":
            continue
        # Reject TCs where the persistence probe proved the write didn't persist
        # (or the read path is broken so persistence is unverifiable).
        probe = resp.get("_persistence_probe") or {}
        probe_kind = probe.get("kind") if isinstance(probe, dict) else None
        if probe_kind in PROBE_REJECTS:
            continue
        body = resp.get("body")
        if not isinstance(body, (dict, list)):
            continue
        for key in keys:
            if key in found:
                continue
            value = extract_id(body, key)
            if value:
                found[key] = value
    # Also harvest from setup_steps in the report (pre-flight provisioning records),
    # which the per-service runners write outside the per-TC evidence loop.
    return found


# Codex stage-2 follow-up (2026-05-04): per-key alias map for setup_steps
# harvesting. The keys in ID_HARVEST get matched only against their OWN aliases,
# never against another id's snake_case form. Defaults to (key, snake_case(key))
# for any id not listed here.
_SETUP_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "bankId":             ("bankId", "bank_id"),
    "affiliateId":        ("affiliateId", "affiliate_id"),
    "parentAffiliateId":  ("parentAffiliateId", "parent_affiliate_id"),
    "cardId":             ("cardId", "card_id"),
    "virtualCardId":      ("virtualCardId", "virtual_card_id"),
    "accountId":          ("accountId", "account_id"),
    "customerRefId":      ("customerRefId", "customer_ref_id", "customerRefID"),
    "customerId":         ("customerId", "customer_id"),
    "draftId":            ("draftId", "draft_id"),
    "transactionId":      ("transactionId", "transaction_id"),
    "exportId":           ("exportId", "export_id"),
    "batchId":            ("batchId", "batch_id"),
    "notificationId":     ("notificationId", "notification_id"),
    "caseId":             ("caseId", "case_id"),
}


def _camel_to_snake(name: str) -> str:
    """Convert camelCase/PascalCase to snake_case, handling acronym runs.
    Codex follow-up (2026-05-04): the prior single-pass regex
    `(?<!^)(?=[A-Z])` turned `customerRefID` into `customer_ref_i_d`. The
    two-pass standard pattern correctly produces `customer_ref_id` and
    `html_parser` from `HTMLParser`.
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


def _setup_aliases_for(key: str) -> tuple[str, ...]:
    """Return the aliases a setup_step may use for `key`. Defaults to
    (key, snake_case(key)) so unknown ids still get a sensible fallback
    without cross-contaminating other harvest keys."""
    aliases = _SETUP_KEY_ALIASES.get(key)
    if aliases is not None:
        return aliases
    snake = _camel_to_snake(key)
    return (key,) if snake == key else (key, snake)


def _setup_record_is_verified(setup: dict) -> bool:
    """Codex re-audit R1 + HIGH-2: a setup_step's id may only be harvested when
    its own persistence sub-record confirms the id was verified AND persisted.
    MINT_UNVERIFIED setups still carry the rejected id in bank_id/card_id/etc.
    fields — those must NOT leak into SessionStore.

    HIGH-2 (2026-05-04): the legacy OK/OK_VIA_QUERY-without-persistence path
    has been removed now that all 8 harnesses (Bank/Cards/Affiliate plus the
    re-audit-#4 port to admin/batch/customer/notifications/transactions) emit
    a persistence block. A setup_record without persistence is treated as
    unverified — no special-casing.
    """
    if not isinstance(setup, dict):
        return False
    persistence = setup.get("persistence")
    if isinstance(persistence, dict):
        return bool(persistence.get("selected_verified") and
                    persistence.get("persisted_to_session_store"))
    return False


def harvest_ids_from_report(report_path: Path | None, keys: list[str]) -> dict:
    """Harvest pre-flight ids from the harness's YAML report metadata.

    Pre-flight setup_steps are authoritative ONLY when verified — see
    _setup_record_is_verified. report_metadata.seeded_ids is treated as
    secondary (no per-id verification flag).
    """
    found: dict[str, str] = {}
    if not report_path or not report_path.is_file():
        return found
    try:
        data = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    except Exception:
        return found
    if not isinstance(data, dict):
        return found
    # Top-level setup_steps list — only harvest from verified records.
    # Codex stage-2 follow-up (2026-05-04): aliases are PER-KEY, not universal.
    # The earlier global alias list cross-contaminated harvest dicts — a setup
    # carrying only `customer_ref_id` would populate every requested key
    # (customerRefId AND draftId AND customerId) with the same value because
    # they all matched the universal alias list.
    for setup in (data.get("setup_steps") or []):
        if not _setup_record_is_verified(setup):
            continue
        for key in keys:
            if key in found:
                continue
            for candidate_key in _setup_aliases_for(key):
                if candidate_key in setup and isinstance(setup[candidate_key], str):
                    value = setup[candidate_key]
                    # Codex stage-2 follow-up F4b (2026-05-04): use the canonical
                    # _is_valid_id sentinel check (string/null/none/n/a/tbd/todo +
                    # zero-UUID + all-zero) so direct harvest matches the gate
                    # used by _verified_keys_in_report. Previously this path
                    # accepted n/a, tbd, todo, and zero-UUIDs that the seeded_ids
                    # path rejected — gates were inconsistent.
                    if _is_valid_id(value):
                        found[key] = value
                        break
    # report_metadata.seeded_ids — Codex re-audit MEDIUM-5 (2026-05-04):
    # seeded_ids fallback is gated PER-KEY, not per-report. A key from
    # seeded_ids is only trusted if some verified setup_step in the same
    # report carries an alias for that exact key — meaning the verify-gated
    # flow attested to that specific id. Other keys in seeded_ids may be
    # stale Postman literals from before pre-flight; refusing them prevents
    # cross-id leakage.
    verified_keys = _verified_keys_in_report(data, keys)
    if verified_keys:
        seeded = ((data.get("report_metadata") or {}).get("seeded_ids") or {})
        for key in keys:
            if key in found:
                continue
            if key not in verified_keys:
                continue
            v = seeded.get(key)
            if isinstance(v, str) and _is_valid_id(v):
                found[key] = v
    return found


def _verified_keys_in_report(data: dict, keys: list[str]) -> set[str]:
    """Return the subset of `keys` that have at least one alias present in a
    verified setup_step with a valid (non-sentinel) string value. Used to
    gate seeded_ids per-key (Codex MEDIUM-5).

    Stage-2 follow-up F4 (2026-05-04): require the alias field to also carry
    a non-sentinel string value. Structural presence alone allowed an empty
    or 'string' placeholder field to authorize seeded_ids fallback for that
    key, even though no real id was ever produced.
    """
    verified_keys: set[str] = set()
    for setup in (data.get("setup_steps") or []):
        if not _setup_record_is_verified(setup):
            continue
        for key in keys:
            if key in verified_keys:
                continue
            for alias in _setup_aliases_for(key):
                v = setup.get(alias)
                if isinstance(v, str) and _is_valid_id(v):
                    verified_keys.add(key)
                    break
    return verified_keys


def summarize_setup_status(report_path: Path | None) -> dict:
    """Codex re-audit #8 (2026-05-04): make pre-flight setup outcomes visible at
    the chain-summary level so a service that ran-with-no-verified-id is not
    silently averaged into the rollup as "ran fine, see TC counts." Returns:
        {
          "all_verified": bool,        # every setup_step is verify-gated AND persisted
          "any_unverified": bool,      # at least one setup_step exists but failed verify
          "any_setup_present": bool,   # the report has a setup_steps section at all
          "statuses": [str, ...],      # per-step status strings (OK, OK_VIA_QUERY, MINT_UNVERIFIED, FAIL, ...)
        }
    """
    summary = {"all_verified": False, "any_unverified": False,
               "any_setup_present": False, "statuses": []}
    if not report_path or not report_path.is_file():
        return summary
    try:
        data = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    except Exception:
        return summary
    if not isinstance(data, dict):
        return summary
    setups = data.get("setup_steps") or []
    if not setups:
        return summary
    summary["any_setup_present"] = True
    statuses = []
    verified_count = 0
    valid_dict_count = 0
    for s in setups:
        if not isinstance(s, dict):
            # Stage-2 follow-up F5 (2026-05-04): malformed setup entries used
            # to be silently skipped, leaving any_unverified=False and the
            # rollup logging "all 0 setup steps verified". A non-dict entry
            # is itself a setup-data anomaly worth flagging as unverified.
            statuses.append("MALFORMED_NON_DICT")
            summary["any_unverified"] = True
            continue
        valid_dict_count += 1
        st = s.get("status") or "UNKNOWN"
        statuses.append(st)
        if _setup_record_is_verified(s):
            verified_count += 1
        else:
            summary["any_unverified"] = True
    summary["statuses"] = statuses
    # all_verified requires every entry (including dicts) to be verified AND
    # at least one valid dict present. A report with only malformed entries
    # is never "all verified."
    summary["all_verified"] = (
        verified_count == valid_dict_count
        and verified_count == len(setups)
        and verified_count > 0
    )
    return summary


def parse_report(report_path: Path) -> dict:
    """Return summary metrics from the harness's YAML report."""
    if not report_path or not report_path.is_file():
        return {}
    try:
        data = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  failed to parse report {report_path.name}: {e}")
        return {}
    meta = (data or {}).get("report_metadata", {})
    return {
        "report_path": str(report_path),
        "total":   meta.get("total_test_cases", 0),
        "passed":  meta.get("passed_test_cases", 0),
        "failed":  meta.get("failed_test_cases", 0),
        "blocked": meta.get("blocked_test_cases", 0),
        "errors":  meta.get("error_test_cases", 0),
    }


def write_service_memory(service: str, run_record: dict) -> Path | None:
    """Write a memory file in the Obsidian vault for this service's chain run."""
    if not VAULT.is_dir():
        log(f"  vault not found at {VAULT} - skipping memory write")
        return None
    metrics = run_record.get("metrics", {})
    total = metrics.get("total", 0) or 0
    passed = metrics.get("passed", 0) or 0
    failed = metrics.get("failed", 0) or 0
    blocked = metrics.get("blocked", 0) or 0
    pass_rate = round(100 * passed / total) if total else 0

    date_compact = TODAY.replace("-", "")
    fname = MEMORY_FILE_TEMPLATE.format(
        service_lower=service.lower().replace(" ", "_"),
        date_compact=date_compact,
    )
    path = VAULT / fname

    consumed_ids = run_record.get("consumed_ids", {})
    created_ids = run_record.get("harvested_ids", {})

    body_lines = [
        "---",
        f"name: Kardit {service} Chain Run {TODAY}",
        f"description: {service} run as part of sequential chain on {TODAY}; "
        f"{total} TCs ({passed}P/{failed}F/{blocked}B); pass rate {pass_rate}%",
        "type: project",
        f"service: {service}",
        f"run_date: {TODAY}",
        f"tcs: {total}",
        f"passes: {passed}",
        f"fails: {failed}",
        f"blocked: {blocked}",
        f"pass_rate: {pass_rate}",
        f"chain_run_id: chain_{CHAIN_TS}",
        "worst_cluster: (see report for cluster breakdown)",
        "---",
        "",
        f"# {service} chain run — {TODAY}",
        "",
        f"Part of sequential chain `chain_{CHAIN_TS}` "
        f"(Bank -> Affiliate -> Customer -> Cards -> Transactions -> Batch -> Notifications -> Admin).",
        "",
        "## Counts",
        "",
        f"- Total: **{total}**",
        f"- PASS: **{passed}**",
        f"- FAIL: **{failed}**",
        f"- BLOCKED: **{blocked}**",
        f"- Pass rate: **{pass_rate}%**",
        "",
        "## Source artifacts",
        "",
        f"- Harness: `Kardit\\harnesses\\{run_record.get('script', '')}`",
        f"- Report: `{metrics.get('report_path', '')}`",
        f"- Evidence: `{run_record.get('evidence_dir', '')}`",
        f"- Exit code: {run_record.get('exit_code', 'n/a')}",
        f"- Duration: {run_record.get('duration_seconds', 0):.1f}s",
        "",
        "## IDs consumed from upstream (SessionStore at start)",
        "",
    ]
    if consumed_ids:
        for k, v in consumed_ids.items():
            body_lines.append(f"- `{k}`: `{v}`")
    else:
        body_lines.append("_None — first service in chain or no upstream IDs available._")
    body_lines += [
        "",
        "## IDs created and passed downstream",
        "",
    ]
    if created_ids:
        for k, v in created_ids.items():
            body_lines.append(f"- `{k}`: `{v}`")
    else:
        body_lines.append("_None — service did not create any new harvestable IDs from successful responses._")
    # Codex re-audit #8: surface pre-flight setup outcomes so a service that ran
    # with no verified id is visible at the chain-summary level (not buried).
    setup_summary = run_record.get("setup_summary") or {}
    if setup_summary.get("any_setup_present"):
        body_lines += [
            "",
            "## Pre-flight setup status",
            "",
            f"- All steps verified: **{setup_summary.get('all_verified')}**",
            f"- Any unverified: **{setup_summary.get('any_unverified')}**",
            f"- Step statuses: `{setup_summary.get('statuses')}`",
        ]
        if setup_summary.get("any_unverified"):
            body_lines.append(
                "- ⚠ At least one pre-flight step did not produce a verify-gated id; "
                "downstream services may have run with stale/literal seeds."
            )
    body_lines += [
        "",
        "## Notes",
        "",
        "_Auto-generated by `run_sequential_chain.py`. Detailed cluster breakdown lives in the YAML report; expand here after review._",
        "",
    ]
    path.write_text("\n".join(body_lines), encoding="utf-8")
    log(f"  wrote memory: {path.name}")
    return path


def run_one_service(service: str, script: str, report_prefix: str, evidence_prefix: str) -> dict:
    log(f"---- {service}: {script} ----")
    consumed = dict(load_session())
    log(f"  SessionStore at start: {consumed}")

    started = time.time()
    started_iso = dt.datetime.now().isoformat()
    script_path = HARNESSES_DIR / script
    if not script_path.is_file():
        log(f"  ERROR: harness not found: {script_path}")
        return {
            "service": service, "script": script, "status": "missing_harness",
            "started": started_iso, "ended": dt.datetime.now().isoformat(),
            "duration_seconds": 0, "exit_code": -1,
            "consumed_ids": consumed, "harvested_ids": {}, "metrics": {},
        }

    try:
        # Codex M7: Cards (and any future harness) compresses evidence dir into
        # .tar.gz then deletes the dir, but the chain harvester reads dirs.
        # Force-keep evidence dirs so per-TC ID harvest still works.
        env = os.environ.copy()
        env["KEEP_EVIDENCE_DIR"] = "1"
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(DOWNLOADS),
            timeout=3600,
            env=env,
            check=False,
        )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        log(f"  TIMEOUT after 3600s for {service}")
        exit_code = -1
    except Exception as e:
        log(f"  EXCEPTION running {service}: {e}")
        exit_code = -2

    ended = time.time()
    duration = ended - started

    report_path = find_newest(report_prefix, after_ts=started)
    evidence_dir = find_newest(evidence_prefix, after_ts=started)
    log(f"  report: {report_path.name if report_path else '(none)'}")
    log(f"  evidence: {evidence_dir.name if evidence_dir else '(none)'}")

    metrics = parse_report(report_path) if report_path else {}
    setup_summary = summarize_setup_status(report_path) if report_path else {
        "all_verified": False, "any_unverified": False, "any_setup_present": False,
        "statuses": [],
    }
    if setup_summary.get("any_unverified"):
        log(f"  WARN: pre-flight had unverified setup steps; statuses={setup_summary['statuses']}")
    elif setup_summary.get("any_setup_present"):
        log(f"  pre-flight: all {len(setup_summary['statuses'])} setup steps verified")
    harvest_keys = ID_HARVEST.get(service, [])
    # Codex re-audit R2: verified pre-flight ids are authoritative.
    # Order: verified report ids first, then fill missing slots from PASS-verdict
    # evidence. Inverting prevents per-TC ids from overriding the seeded ones.
    harvested: dict[str, str] = {}
    if report_path and harvest_keys:
        harvested.update(harvest_ids_from_report(report_path, harvest_keys))
    if evidence_dir and harvest_keys:
        evidence_harvested = harvest_ids_from_evidence(evidence_dir, harvest_keys)
        for k, v in evidence_harvested.items():
            harvested.setdefault(k, v)

    # Apply harvested IDs to SessionStore (only NEW values).
    session = load_session()
    actually_new = {}
    for k, v in harvested.items():
        if session.get(k) != v:
            actually_new[k] = v
            session[k] = v
    if actually_new:
        save_session(session)
        log(f"  HARVESTED new IDs -> SessionStore: {actually_new}")
    else:
        log(f"  no new IDs harvested (harness wrote its own primary ID, or none found in 2xx responses)")

    # Codex re-audit #11: bound disk usage by archiving older evidence dirs.
    # Keep the N most recent per prefix; report yamls are preserved (audit trail).
    pruned_evidence = prune_old_runs(evidence_prefix)
    pruned_reports = prune_old_runs(report_prefix)
    if pruned_evidence or pruned_reports:
        log(f"  retention: archived {pruned_evidence} evidence dirs, pruned {pruned_reports} report items")

    record = {
        "service": service,
        "script": script,
        "status": "ok" if exit_code == 0 else f"exit_{exit_code}",
        "started": started_iso,
        "ended": dt.datetime.now().isoformat(),
        "duration_seconds": round(duration, 1),
        "exit_code": exit_code,
        "report_path": str(report_path) if report_path else "",
        "evidence_dir": str(evidence_dir) if evidence_dir else "",
        "consumed_ids": consumed,
        "harvested_ids": actually_new,
        "metrics": metrics,
        "setup_summary": setup_summary,  # Codex re-audit #8: visible in chain rollup
        "session_after": dict(session),
    }

    write_service_memory(service, record)
    log(f"  done: P={metrics.get('passed', 0)} F={metrics.get('failed', 0)} B={metrics.get('blocked', 0)} (took {duration:.1f}s)")
    return record


def main() -> int:
    log(f"=== Sequential chain run start: {CHAIN_TS} ===")
    log(f"Vault: {VAULT}")
    log(f"SessionStore: {SESSION_STORE}")
    log(f"Initial session: {load_session()}")

    chain_log: list[dict] = []
    for label, script, report_prefix, evidence_prefix in CHAIN_SEQUENCE:
        record = run_one_service(label, script, report_prefix, evidence_prefix)
        chain_log.append(record)

    summary = {
        "chain_metadata": {
            "chain_run_id": f"chain_{CHAIN_TS}",
            "run_date": TODAY,
            "started":  chain_log[0]["started"]  if chain_log else "",
            "ended":    chain_log[-1]["ended"]   if chain_log else "",
            "services_total": len(CHAIN_SEQUENCE),
            "services_completed_ok": sum(1 for r in chain_log if r.get("status") == "ok"),
            "session_initial": chain_log[0]["consumed_ids"] if chain_log else {},
            "session_final": load_session(),
            "id_flow": {
                r["service"]: {"consumed": r.get("consumed_ids", {}), "created": r.get("harvested_ids", {})}
                for r in chain_log
            },
        },
        "services": [
            {
                "service": r["service"],
                "status": r["status"],
                "duration_seconds": r.get("duration_seconds", 0),
                "exit_code": r.get("exit_code"),
                "metrics": r.get("metrics", {}),
                "consumed_ids": r.get("consumed_ids", {}),
                "harvested_ids": r.get("harvested_ids", {}),
                # Codex stage-2 follow-up F1 (2026-05-04): D6's setup_summary
                # was being populated on the per-service record but dropped
                # here. The chain rollup needs it visible so a service that
                # ran with no verified pre-flight is surfaced cross-service.
                "setup_summary": r.get("setup_summary", {}),
                "report_path": r.get("report_path", ""),
                "evidence_dir": r.get("evidence_dir", ""),
            }
            for r in chain_log
        ],
    }
    CHAIN_REPORT.write_text(yaml.safe_dump(summary, sort_keys=False, allow_unicode=True), encoding="utf-8")
    log(f"=== Chain done. Report: {CHAIN_REPORT} ===")
    log(f"Final SessionStore: {load_session()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
