"""
evidence_writer.py — Kardit per-run evidence and audit log writer.

Called by each service runner after every TC execution. Writes:
  - <service>/evidence/run_<timestamp>/audit.log     human-readable per-TC log
  - <service>/evidence/run_<timestamp>/summary.json  aggregate run stats
  - <service>/evidence/run_<timestamp>/tc/<TCID>.json  full TC detail record

Each TC record captures:
  - Mutation: action, field targeted, original value, mutated value
  - Request: method, URL, auth header (truncated), all headers, full payload
  - Response: status code, headers, body, duration
  - Verdict: PASS/FAIL/BLOCKED + cluster tag + plain-English reason
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# How many chars of a Bearer token to show in logs before truncating
_TOKEN_PREVIEW_LEN = 40


def _truncate_token(value: str) -> str:
    if not value:
        return ""
    if value.startswith("Bearer "):
        token = value[7:]
        preview = token[:_TOKEN_PREVIEW_LEN]
        return f"Bearer {preview}...[truncated]" if len(token) > _TOKEN_PREVIEW_LEN else value
    if len(value) > _TOKEN_PREVIEW_LEN:
        return value[:_TOKEN_PREVIEW_LEN] + "...[truncated]"
    return value


def _sanitise_headers(headers: dict) -> dict:
    """Return headers dict with auth tokens truncated — safe to write to disk."""
    out = {}
    for k, v in (headers or {}).items():
        if k.lower() in ("authorization", "x-api-key", "cookie"):
            out[k] = _truncate_token(str(v))
        else:
            out[k] = v
    return out


class EvidenceRun:
    """
    One test run for one service. Create once, call record_tc() per TC,
    then call close() to finalise summary.json and flush audit.log.

    Usage:
        run = EvidenceRun(service="bank", evidence_root=Path("bank/evidence"))
        run.record_tc(tc_id="BNK-01-001", ...)
        run.close()
    """

    def __init__(self, service: str, evidence_root: Path):
        self.service = service
        self.ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = evidence_root / f"run_{self.ts}"
        self.tc_dir = self.run_dir / "tc"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.tc_dir.mkdir(parents=True, exist_ok=True)

        self._audit_path = self.run_dir / "audit.log"
        self._summary: dict[str, Any] = {
            "service": service,
            "run_ts": self.ts,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "blocked": 0,
            "pass_rate": None,
            "clusters": {},
            "tcs": [],
        }

        # Write run header to audit log
        self._write_audit(
            f"{'='*80}\n"
            f"SERVICE : {service.upper()}\n"
            f"RUN     : {self.ts}\n"
            f"DIR     : {self.run_dir}\n"
            f"{'='*80}\n"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_tc(
        self,
        *,
        tc_id: str,
        endpoint: str,
        scenario: str,
        verdict: str,                    # PASS | FAIL | BLOCKED
        reason: str,                     # plain-English classification reason
        cluster: str | None = None,      # e.g. B_silent_accept, H_5xx
        mutation: dict | None = None,    # see _mutation_record()
        request: dict | None = None,     # see _request_record()
        response: dict | None = None,    # see _response_record()
        duration_ms: float | None = None,
    ):
        """Record one TC. Call after the HTTP exchange completes."""
        record = {
            "tc_id": tc_id,
            "endpoint": endpoint,
            "scenario": scenario,
            "verdict": verdict,
            "cluster": cluster,
            "reason": reason,
            "mutation": mutation or _mutation_record(),
            "request": request or {},
            "response": response or {},
            "duration_ms": duration_ms,
            "timestamp": datetime.now().isoformat(),
        }

        # Write per-TC JSON
        tc_file = self.tc_dir / f"{tc_id}.json"
        tc_file.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

        # Update summary counters
        self._summary["total"] += 1
        key = verdict.lower()
        if key in ("pass", "fail", "blocked"):
            self._summary[{"pass": "passed", "fail": "failed", "blocked": "blocked"}[key]] += 1
        if cluster:
            self._summary["clusters"][cluster] = self._summary["clusters"].get(cluster, 0) + 1
        self._summary["tcs"].append({"tc_id": tc_id, "verdict": verdict, "cluster": cluster})

        # Write to audit log
        self._write_audit(_format_tc_audit(record))

    def close(self):
        """Finalise the run — write summary.json and flush audit footer."""
        total = self._summary["total"]
        passed = self._summary["passed"]
        self._summary["finished_at"] = datetime.now().isoformat()
        self._summary["pass_rate"] = round(passed / total * 100, 1) if total else 0.0

        summary_file = self.run_dir / "summary.json"
        summary_file.write_text(json.dumps(self._summary, indent=2, default=str), encoding="utf-8")

        self._write_audit(
            f"\n{'='*80}\n"
            f"RESULT  : {passed}P / {self._summary['failed']}F / {self._summary['blocked']}B"
            f" ({self._summary['pass_rate']}%)\n"
            f"CLUSTERS: {json.dumps(self._summary['clusters'])}\n"
            f"{'='*80}\n"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_audit(self, text: str):
        with open(self._audit_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


# ------------------------------------------------------------------
# Record builder helpers — call these from runners to build the dicts
# ------------------------------------------------------------------

def mutation_record(
    action: str,
    description: str,
    field_targeted: str | None = None,
    original_value: Any = None,
    mutated_value: Any = None,
) -> dict:
    """Build the mutation sub-record for record_tc()."""
    return {
        "action": action,
        "description": description,
        "field_targeted": field_targeted,
        "original_value": original_value,
        "mutated_value": mutated_value,
    }


def _mutation_record() -> dict:
    return mutation_record("as_is", "Happy path — no mutation applied")


def request_record(
    method: str,
    url: str,
    headers: dict,
    payload: Any = None,
    auth_type: str = "Bearer",
) -> dict:
    """Build the request sub-record for record_tc()."""
    sanitised = _sanitise_headers(headers)
    raw_auth = headers.get("Authorization", headers.get("authorization", ""))
    return {
        "method": method,
        "url": url,
        "auth": {
            "type": auth_type,
            "header": _truncate_token(raw_auth),
        },
        "headers": sanitised,
        "payload": payload,
    }


def response_record(
    status_code: int,
    body: Any = None,
    headers: dict | None = None,
    duration_ms: float | None = None,
) -> dict:
    """Build the response sub-record for record_tc()."""
    return {
        "status_code": status_code,
        "headers": dict(headers or {}),
        "body": body,
        "duration_ms": duration_ms,
    }


# ------------------------------------------------------------------
# Audit log formatter
# ------------------------------------------------------------------

def _format_tc_audit(record: dict) -> str:
    v = record["verdict"]
    verdict_label = {"PASS": "✓ PASS", "FAIL": "✗ FAIL", "BLOCKED": "○ BLOCKED"}.get(v, v)
    ts = record.get("timestamp", "")[:19].replace("T", " ")
    cluster_str = f" [{record['cluster']}]" if record.get("cluster") else ""

    mut = record.get("mutation") or {}
    req = record.get("request") or {}
    res = record.get("response") or {}

    # Payload — compact JSON, cap at 300 chars
    payload = req.get("payload")
    payload_str = json.dumps(payload, default=str) if payload is not None else "(none)"
    if len(payload_str) > 300:
        payload_str = payload_str[:300] + "...[truncated]"

    # Response body — compact JSON, cap at 300 chars
    body = res.get("body")
    body_str = json.dumps(body, default=str) if body is not None else "(none)"
    if len(body_str) > 300:
        body_str = body_str[:300] + "...[truncated]"

    # Mutation line
    mut_desc = mut.get("description", "none")
    if mut.get("field_targeted"):
        orig = json.dumps(mut.get("original_value"), default=str)
        new = json.dumps(mut.get("mutated_value"), default=str)
        mut_line = f"{mut.get('action')} | field: {mut['field_targeted']} | {orig} → {new}"
    else:
        mut_line = mut_desc

    lines = [
        f"[{ts}] {record['tc_id']} | {verdict_label}{cluster_str}",
        f"  Endpoint  : {req.get('method', '')} {record['endpoint']}",
        f"  Scenario  : {record['scenario']}",
        f"  Mutation  : {mut_line}",
        f"  Auth      : {req.get('auth', {}).get('header', '(none)')}",
        f"  Payload   : {payload_str}",
        f"  Response  : {res.get('status_code', '?')} {body_str}",
        f"  Duration  : {res.get('duration_ms') or record.get('duration_ms') or '?'}ms",
        f"  Reason    : {record['reason']}",
        "",
    ]
    return "\n".join(lines)
