"""
Kardit targeted test runner.

Runs tests at three levels of granularity:

  By service:
    python run_target.py --service cards

  By endpoint (API-ID):
    python run_target.py --service cards --api-id API-ISS-02

  By TC-ID (auto-detects service if --service omitted):
    python run_target.py --tc TC-API-ISS-02-001
    python run_target.py --service cards --api-id API-ISS-02 --tc TC-API-ISS-02-001

Utility:
  python run_target.py --service cards --api-id API-ISS-02 --list   (list all TC-IDs)
  python run_target.py --tc TC-API-ISS-02-001 --dry-run             (print command only)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

DOWNLOADS = Path(r"C:\Users\Onyema Ifechukwu\Downloads")
KARDIT    = Path(r"C:\Users\Onyema Ifechukwu\Kardit")

# service name -> (runner script, test pack path)
SERVICE_MAP: dict[str, tuple[Path, Path]] = {
    "bank": (
        KARDIT / "bank"          / "postman_hybrid_bank_runner.py",
        KARDIT / "bank"          / "data" / "test_pack.json",
    ),
    "affiliate": (
        KARDIT / "affiliate"     / "postman_standalone_affiliate_v2.py",
        KARDIT / "affiliate"     / "data" / "test_pack.json",
    ),
    "customer": (
        KARDIT / "customer"      / "postman_hybrid_customer_runner.py",
        KARDIT / "customer"      / "data" / "test_pack.json",
    ),
    "cards": (
        KARDIT / "cards"         / "cards_e2e_runner.py",
        KARDIT / "cards"         / "data" / "test_pack.json",
    ),
    "transactions": (
        KARDIT / "transactions"  / "postman_hybrid_transactions_runner.py",
        KARDIT / "transactions"  / "data" / "test_pack.json",
    ),
    "batch": (
        KARDIT / "batch"         / "postman_hybrid_batch_runner.py",
        KARDIT / "batch"         / "data" / "test_pack.json",
    ),
    "notifications": (
        KARDIT / "notifications" / "postman_hybrid_notifications_runner.py",
        KARDIT / "notifications" / "data" / "test_pack.json",
    ),
    "admin": (
        KARDIT / "admin"         / "postman_hybrid_admin_runner.py",
        KARDIT / "admin"         / "data" / "test_pack.json",
    ),
}

# report file prefix per service (used to find the latest report after a run)
REPORT_PREFIX: dict[str, str] = {
    "bank":          "bank_postman_hybrid_report",
    "affiliate":     "affiliate_postman_standalone_v2_report",
    "customer":      "customer_postman_hybrid_report",
    "cards":         "cards_postman_hybrid_report",
    "transactions":  "transactions_postman_hybrid_report",
    "batch":         "batch_postman_hybrid_report",
    "notifications": "notifications_postman_hybrid_report",
    "admin":         "admin_postman_hybrid_report",
}


# ---------------------------------------------------------------------------
# Pack helpers
# ---------------------------------------------------------------------------

def _load_endpoints(pack_path: Path) -> list[dict]:
    if not pack_path.exists():
        return []
    try:
        with open(pack_path, encoding="utf-8") as f:
            return json.load(f).get("endpoints", [])
    except Exception:
        return []


def find_tc(tc_id: str) -> Optional[tuple[str, str, str]]:
    """Search all service packs for tc_id.

    Returns (service, api_id, endpoint_string) or None if not found.
    """
    for service, (_, pack_path) in SERVICE_MAP.items():
        for ep in _load_endpoints(pack_path):
            for tc in ep.get("test_cases", []):
                if tc.get("tc_id") == tc_id:
                    return service, ep.get("api_id", ""), ep.get("endpoint", "")
    return None


def list_tcs(service: str, api_id: str) -> list[dict]:
    """Return list of {tc_id, scenario} for a given service + api_id."""
    _, pack_path = SERVICE_MAP[service]
    for ep in _load_endpoints(pack_path):
        if ep.get("api_id") == api_id:
            return [{"tc_id": tc.get("tc_id", ""), "scenario": tc.get("scenario", "")}
                    for tc in ep.get("test_cases", [])]
    return []


def list_endpoints(service: str) -> list[dict]:
    """Return all endpoints for a service with TC counts."""
    _, pack_path = SERVICE_MAP[service]
    out = []
    for ep in _load_endpoints(pack_path):
        out.append({
            "api_id": ep.get("api_id", ""),
            "endpoint": ep.get("endpoint", ""),
            "name": ep.get("name", ""),
            "tc_count": len(ep.get("test_cases", [])),
        })
    return out


# ---------------------------------------------------------------------------
# Runner execution
# ---------------------------------------------------------------------------

def _build_env(api_id: str, tc_id: str) -> dict[str, str]:
    env = os.environ.copy()
    if api_id:
        env["SCOPE_API_IDS"] = api_id
    if tc_id:
        env["SCOPE_TC_IDS"] = tc_id
    return env


def _format_command(runner: Path, api_id: str, tc_id: str) -> str:
    parts = []
    if api_id:
        parts.append(f"SCOPE_API_IDS={api_id!r}")
    if tc_id:
        parts.append(f"SCOPE_TC_IDS={tc_id!r}")
    parts.append(f"python {runner.name}")
    return " ".join(parts)


def run_service(service: str, api_id: str = "", tc_id: str = "", dry_run: bool = False) -> int:
    runner, _ = SERVICE_MAP[service]
    if not runner.exists():
        print(f"ERROR: runner not found: {runner}")
        return 1

    cmd_display = _format_command(runner, api_id, tc_id)
    print(f"\n[run_target] Command  : {cmd_display}")
    print(f"[run_target] Full path: {runner}")
    if api_id:
        print(f"[run_target] Scope    : endpoint={api_id}")
    if tc_id:
        print(f"[run_target] Scope    : tc={tc_id}")
    print()

    if dry_run:
        print("[run_target] --dry-run active: not executing.")
        return 0

    env = _build_env(api_id, tc_id)
    proc = subprocess.run([sys.executable, str(runner)], cwd=str(DOWNLOADS), env=env)
    return proc.returncode


# ---------------------------------------------------------------------------
# Report summary
# ---------------------------------------------------------------------------

def print_report_summary(service: str, tc_id: str = "") -> None:
    prefix = REPORT_PREFIX.get(service, f"{service}_postman_hybrid_report")
    candidates = [
        p for p in DOWNLOADS.iterdir()
        if p.name.startswith(prefix) and p.suffix == ".yaml"
    ]
    if not candidates:
        print("[run_target] No report found in Downloads/.")
        return

    report = max(candidates, key=lambda p: p.stat().st_mtime)
    print(f"\n[run_target] Report: {report.name}")

    try:
        import yaml
        data = yaml.safe_load(report.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[run_target] Could not read report: {e}")
        return

    meta = data.get("report_metadata", {})
    total   = meta.get("total_test_cases", 0)
    passed  = meta.get("passed_test_cases", 0)
    failed  = meta.get("failed_test_cases", 0)
    blocked = meta.get("blocked_test_cases", 0)
    overall = meta.get("overall_status", "?")
    print(f"[run_target] Overall : {overall}")
    print(f"[run_target] Counts  : {total} total — {passed}P / {failed}F / {blocked}B")

    if not tc_id:
        return

    # Locate the single TC result in detailed_test_cases
    for tc in data.get("detailed_test_cases", []):
        tid = tc.get("test_case_id") or tc.get("tc_id") or ""
        if tid != tc_id:
            continue
        status   = tc.get("execution_status", "?")
        scenario = tc.get("scenario", "")
        endpoint = tc.get("endpoint", "")
        code     = tc.get("response_code") or ""
        print(f"\n[run_target] TC result -----------------------------------")
        print(f"  TC-ID    : {tc_id}")
        print(f"  Scenario : {scenario}")
        print(f"  Endpoint : {endpoint}")
        print(f"  Status   : {status}   HTTP: {code}")
        if status in ("FAIL", "BLOCKED"):
            ar = tc.get("actual_result") or {}
            cause  = ar.get("cause", "")
            result = ar.get("result", "")
            reason = tc.get("blocked_reason", "")
            if cause:
                print(f"  Cause    : {cause}")
            if result:
                print(f"  Result   : {result}")
            if reason:
                print(f"  Reason   : {reason}")
        print(f"[run_target] -----------------------------------------")
        return

    print(f"[run_target] TC '{tc_id}' not found in report detailed_test_cases.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run Kardit tests by microservice, endpoint, or TC-ID",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python run_target.py --tc TC-API-ISS-02-001
  python run_target.py --service cards
  python run_target.py --service cards --api-id API-ISS-02
  python run_target.py --service cards --api-id API-ISS-02 --tc TC-API-ISS-02-001
  python run_target.py --service cards --api-id API-ISS-02 --list
  python run_target.py --tc TC-API-ISS-02-001 --dry-run
        """,
    )
    ap.add_argument("--service", choices=sorted(SERVICE_MAP.keys()),
                    help="Microservice name (auto-detected from TC-ID if omitted)")
    ap.add_argument("--api-id", dest="api_id", metavar="API_ID",
                    help="Endpoint API-ID to scope to (e.g. API-ISS-02)")
    ap.add_argument("--tc", dest="tc_id", metavar="TC_ID",
                    help="Test case ID to run (e.g. TC-API-ISS-02-001)")
    ap.add_argument("--list", action="store_true",
                    help="List endpoints (or TCs if --api-id given) without running")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the command without executing it")
    args = ap.parse_args()

    service = args.service or ""
    api_id  = args.api_id  or ""
    tc_id   = args.tc_id   or ""

    # ---- --list mode -------------------------------------------------------
    if args.list:
        if not service:
            ap.error("--list requires --service")
        if api_id:
            tcs = list_tcs(service, api_id)
            if not tcs:
                print(f"No TCs found for {service}/{api_id}.")
                return 1
            print(f"\nTCs for {service} / {api_id} ({len(tcs)} total):")
            for t in tcs:
                print(f"  {t['tc_id']:<35}  {t['scenario']}")
        else:
            eps = list_endpoints(service)
            if not eps:
                print(f"No endpoints found for {service}.")
                return 1
            total = sum(e["tc_count"] for e in eps)
            print(f"\nEndpoints for {service} ({len(eps)} endpoints, {total} TCs):")
            for e in eps:
                print(f"  {e['api_id']:<20}  {e['tc_count']:>3} TCs  {e['endpoint']}  {e['name']}")
        return 0

    # ---- need at least service or tc_id ------------------------------------
    if not service and not tc_id:
        ap.print_help()
        return 1

    # ---- auto-detect service from TC-ID ------------------------------------
    if tc_id and not service:
        result = find_tc(tc_id)
        if result is None:
            print(f"ERROR: '{tc_id}' not found in any service test pack.")
            print("Tip: check the TC-ID spelling or run --list to browse available IDs.")
            return 1
        service, detected_api_id, detected_endpoint = result
        if not api_id:
            api_id = detected_api_id
        print(f"[run_target] Found '{tc_id}'  ->  service={service}  api_id={api_id}  endpoint={detected_endpoint!r}")

    # ---- execute -----------------------------------------------------------
    rc = run_service(service, api_id=api_id, tc_id=tc_id, dry_run=args.dry_run)

    if not args.dry_run:
        print_report_summary(service, tc_id=tc_id)

    return rc


if __name__ == "__main__":
    sys.exit(main())
