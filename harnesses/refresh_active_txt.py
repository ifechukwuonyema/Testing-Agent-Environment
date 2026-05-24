"""
refresh_active_txt.py

Queries the live Cards service for fresh card IDs by status and rewrites
ACTIVE.txt with up-to-date pools.  Preserves the LIMIT COMPLETE / LIM IDs
section verbatim (those are manually provisioned by the backend team).

Usage:
    python3 refresh_active_txt.py                # writes to Downloads/ACTIVE.txt
    python3 refresh_active_txt.py --dry-run      # prints output, does not write
    python3 refresh_active_txt.py --out /path    # write to a custom path
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
BASE_URL = "http://167.172.49.177:8080"
DOWNLOADS = Path(r"C:\Users\Onyema Ifechukwu\Downloads")
ACTIVE_TXT_PATH = DOWNLOADS / "ACTIVE.txt"
HEADERS = {"Accept": "application/json"}
TIMEOUT = 20
PER_SECTION = 8  # cards to keep per section


# ---------------------------------------------------------------------------
def fetch_cards(status: str) -> list[dict]:
    """GET /api/v1/cards?status=<status> → list of card objects."""
    url = f"{BASE_URL}/api/v1/cards?status={status}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  ERROR fetching status={status}: {e}", file=sys.stderr)
        return []
    body = r.json()
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "items", "content", "cards"):
            if isinstance(body.get(key), list):
                return body[key]
    print(f"  WARN: unexpected body shape for status={status}: {list(body.keys()) if isinstance(body, dict) else type(body).__name__}")
    return []


def extract_id(card: dict) -> str | None:
    return card.get("cardId") or card.get("id")


def is_physical(card: dict) -> bool:
    return (card.get("productType") or "").upper() == "PHYSICAL"


def _fulfillment_status(card: dict) -> str:
    # fulfillmentStatus is nested inside card.fulfillment{}, not top-level
    return ((card.get("fulfillment") or {}).get("fulfillmentStatus") or "").upper()


def fulfillment_failed(card: dict) -> bool:
    return _fulfillment_status(card) == "FAILED"


def fulfillment_in_progress(card: dict) -> bool:
    # Observed statuses for in-progress fulfillment: PENDING, PERSONALIZING, DISPATCHED
    return _fulfillment_status(card) in ("PENDING", "PERSONALIZING", "DISPATCHED", "IN_PROGRESS")


# ---------------------------------------------------------------------------
def read_limit_complete_section(path: Path) -> str:
    """Extract the LIMIT COMPLETE block from the existing ACTIVE.txt verbatim."""
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    # Find the section that starts with "LIMIT COMPLETE"
    marker = None
    for keyword in ("LIMIT COMPLETE", "LIMIT COMPLETE:"):
        idx = text.find(keyword)
        if idx != -1:
            marker = idx
            break
    if marker is None:
        return ""
    return text[marker:].strip()


# ---------------------------------------------------------------------------
def build_active_txt(pools: dict[str, list[str]], limit_complete_block: str) -> str:
    lines: list[str] = []
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"# Refreshed by refresh_active_txt.py at {ts}")
    lines.append("")

    def section(header: str, cards: list[str], n: int = PER_SECTION) -> None:
        lines.append(header)
        for cid in cards[:n]:
            lines.append(cid)
        lines.append("")

    section("ACTIVE:for (freeze)",         pools["active_general"])
    section("ACTIVE:(terminate)",          pools["active_terminate"])
    section("FROZEN:",                     pools["frozen"])
    section("READY:",                      pools["ready"])
    section("PENDING_ACTIVATION:",         pools["pending_activation"])
    section("PENDING ISSUANCE(PHYSICAL):for fulfillment refresh",
                                           pools["pending_issuance_physical"])
    section("ACTIVE(PHYSICAL):for reinitiate fulfillment",
                                           pools["active_physical_reinitiate"])
    section("Fulfilment reinitiate: (FAILED state)",
                                           pools["active_physical_failed"])
    section("Terminated:",                 pools["terminated"])

    if limit_complete_block:
        lines.append(limit_complete_block)
    else:
        lines.append("LIMIT COMPLETE:")
        lines.append("# Could not read from existing ACTIVE.txt — fill manually")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh ACTIVE.txt card pools from live service")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing")
    parser.add_argument("--out", type=Path, default=ACTIVE_TXT_PATH, help="Output path")
    args = parser.parse_args()

    print(f"Querying {BASE_URL} ...")

    # Preserve the LIMIT COMPLETE section before overwriting
    limit_complete_block = read_limit_complete_section(args.out)
    if limit_complete_block:
        print(f"  Preserved LIMIT COMPLETE block ({len(limit_complete_block.splitlines())} lines)")
    else:
        print("  WARN: no LIMIT COMPLETE block found in existing ACTIVE.txt — will leave placeholder")

    # Fetch all statuses
    statuses = ["ACTIVE", "PENDING_ACTIVATION", "FROZEN", "READY", "PENDING_ISSUANCE", "TERMINATED"]
    raw: dict[str, list[dict]] = {}
    for st in statuses:
        cards = fetch_cards(st)
        raw[st] = cards
        print(f"  {st}: {len(cards)} cards returned")

    # --- build pools ---
    active_all        = raw["ACTIVE"]
    active_physical   = [c for c in active_all if is_physical(c)]
    active_virtual    = [c for c in active_all if not is_physical(c)]
    active_failed_ful = [c for c in active_physical if fulfillment_failed(c)]
    active_in_prog    = [c for c in active_all if fulfillment_in_progress(c)]

    # General ACTIVE pool (prefer virtual so physical ones are reserved for reinitiate/terminate)
    active_general_ids = [extract_id(c) for c in (active_virtual + active_physical)
                          if extract_id(c)]

    # Terminate pool: any ACTIVE card; deduplicate from general so same card isn't in both
    general_set = set(active_general_ids[:PER_SECTION])
    active_terminate_ids = [extract_id(c) for c in active_all
                            if extract_id(c) and extract_id(c) not in general_set]

    pools: dict[str, list[str]] = {
        "active_general":           active_general_ids,
        "active_terminate":         active_terminate_ids,
        "frozen":                   [extract_id(c) for c in raw["FROZEN"] if extract_id(c)],
        "ready":                    [extract_id(c) for c in raw["READY"] if extract_id(c)],
        "pending_activation":       [extract_id(c) for c in raw["PENDING_ACTIVATION"] if extract_id(c)],
        "pending_issuance_physical":[extract_id(c) for c in raw["PENDING_ISSUANCE"] if extract_id(c) and is_physical(c)],
        "active_physical_reinitiate":[extract_id(c) for c in active_physical
                                      if extract_id(c) and not fulfillment_failed(c)],
        "active_physical_failed":   [extract_id(c) for c in active_failed_ful if extract_id(c)],
        "terminated":               [extract_id(c) for c in raw["TERMINATED"] if extract_id(c)],
    }

    # Summary
    print()
    print("Pool sizes (capped at 8 in output):")
    for k, v in pools.items():
        print(f"  {k}: {len(v)} available")

    output = build_active_txt(pools, limit_complete_block)

    if args.dry_run:
        print()
        print("--- DRY RUN OUTPUT ---")
        print(output)
        print("--- END ---")
        return

    args.out.write_text(output, encoding="utf-8")
    print()
    print(f"Written to: {args.out}")


if __name__ == "__main__":
    main()
