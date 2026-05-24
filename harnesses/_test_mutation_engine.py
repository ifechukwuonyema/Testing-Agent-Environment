"""Offline test of the mutation engine.

For every TC in every pack:
  1. Locate the matching Postman entry by URL path.
  2. Run mutation_engine.apply_mutation(postman_request, scenario).
  3. Record action, applied/misfire, summary of what changed.

Output:
  Downloads\Kardit\reports\mutation_engine_test_2026-05-09.md   (human)
  Downloads\Kardit\reports\mutation_engine_test_2026-05-09.json (machine)
"""
from __future__ import annotations

import copy
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_engine  # noqa: E402

DOWNLOADS = Path(r"C:\Users\Onyema Ifechukwu\Downloads")
POSTMAN = DOWNLOADS / "Kardit.Api.postman.collection.json"

PACKS = {
    "affiliate":     DOWNLOADS / "kardit_affiliate_api_test_agent_v3_1" / "kardit_affiliate_api_test_agent_v3_1" / "data" / "affiliate_microservice_functional_test_pack_v1_40_each_exact.json",
    "bank":          DOWNLOADS / "bank_microservice_functional_test_pack_v1_40_each.json",
    "cards":         DOWNLOADS / "cards_microservice_functional_test_pack_v1_40_each.json",
    "customer":      DOWNLOADS / "kardit_customer_api_test_agent_v3_1" / "kardit_customer_api_test_agent_v3_1" / "data" / "customer_microservice_functional_test_pack_v1_40_each.json",
    "transactions":  DOWNLOADS / "kardit_transactions_api_test_agent_v3_1" / "kardit_transactions_api_test_agent_v3_1" / "data" / "transactions_microservice_functional_test_pack_v1_40_each.json",
    "batch":         DOWNLOADS / "kardit_batch_api_test_agent_v3_1" / "kardit_batch_api_test_agent_v3_1" / "data" / "batch_microservice_functional_test_pack_v3_30_each.json",
    "admin":         DOWNLOADS / "admin_services_api_test_agent_v1" / "admin_services_api_test_agent" / "data" / "admin_services_functional_test_pack_v1_30_plus.json",
    "notifications": DOWNLOADS / "kardit_notifications_api_test_agent_v1" / "kardit_notifications_api_test_agent_v1" / "data" / "notifications_TC.json",
}

OUT_MD = DOWNLOADS / "Kardit" / "reports" / "mutation_engine_test_2026-05-09.md"
OUT_JSON = DOWNLOADS / "Kardit" / "reports" / "mutation_engine_test_2026-05-09.json"


# -------- Postman index --------

def _walk_leaves(items):
    for it in items:
        if it.get("request"):
            yield it
        elif it.get("item"):
            yield from _walk_leaves(it["item"])


def _url_raw(item: dict) -> str:
    req = item.get("request") or {}
    url = req.get("url")
    if isinstance(url, dict):
        return url.get("raw", "") or ""
    if isinstance(url, str):
        return url
    return ""


_LITERAL_ID_RE = re.compile(
    r"/(?:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # UUID
    r"|[A-Z]{3,}-[A-Z0-9-]{4,}"                                                    # PREFIXED-ID
    r"|TXN-\d+-\d+|CAR-[0-9A-F]{16,}|AFF-[0-9A-F]{16,}|BANK-\d+-\d+|CUST-[A-Z0-9-]+"
    r")"
)


def _normalize_path(raw: str, *, alt_prefix: bool = False) -> str:
    """Strip protocol/host/query, replace :var with {var}, replace literal IDs
    with {id}. If `alt_prefix=True`, also produce the `/api/v1/<x>` <-> `/<x>`
    alternative prefix."""
    s = raw.split("?")[0].split("#")[0]
    if "://" in s:
        s = s.split("://", 1)[1]
        s = "/" + s.split("/", 1)[1] if "/" in s else "/"
    s = s.replace("{{baseUrl}}", "")
    if not s.startswith("/"):
        s = "/" + s
    while s.startswith("//"):
        s = s[1:]
    s = re.sub(r":([A-Za-z][A-Za-z0-9_]*)", r"{\1}", s)
    s = _LITERAL_ID_RE.sub("/{id}", s)
    if alt_prefix:
        if s.startswith("/api/v1/"):
            return s[len("/api/v1"):]  # `/notifications/...`
        else:
            return "/api/v1" + s
    return s


def _build_postman_index() -> dict[str, dict]:
    """Index by method + canonical template. Both alt-prefix forms are stored."""
    coll = json.loads(POSTMAN.read_text(encoding="utf-8"))
    idx: dict[str, dict] = {}
    for leaf in _walk_leaves(coll.get("item", [])):
        method = (leaf.get("request") or {}).get("method", "?").upper()
        tmpl = _path_to_template(_url_raw(leaf))
        idx[f"{method} {tmpl}"] = leaf
        # alt-prefix
        alt_path = tmpl[len("/api/v1"):] if tmpl.startswith("/api/v1/") else "/api/v1" + tmpl
        idx[f"{method} {alt_path}"] = leaf
    return idx


def _path_to_template(path: str) -> str:
    """Strip query, replace `:var` and `{var}` with the canonical token `{V}`,
    replace literal IDs with `{V}`. Used so the path keys collapse to the same
    string for matching."""
    s = path.split("?")[0].split("#")[0]
    if "://" in s:
        s = s.split("://", 1)[1]
        s = "/" + s.split("/", 1)[1] if "/" in s else "/"
    s = s.replace("{{baseUrl}}", "")
    if not s.startswith("/"):
        s = "/" + s
    while s.startswith("//"):
        s = s[1:]
    s = re.sub(r":([A-Za-z][A-Za-z0-9_]*)", "{V}", s)
    s = re.sub(r"\{[A-Za-z][A-Za-z0-9_]*\}", "{V}", s)
    s = _LITERAL_ID_RE.sub("/{V}", s)
    return s


def _find_postman_for_endpoint(endpoint_str: str, postman_idx: dict[str, dict]) -> dict | None:
    """Look up by canonical method+template, with alt-prefix attempt."""
    method, path = endpoint_str.split(" ", 1)
    tmpl = _path_to_template(path)
    candidates = [tmpl]
    # alt-prefix
    if tmpl.startswith("/api/v1/"):
        candidates.append(tmpl[len("/api/v1"):])
    else:
        candidates.append("/api/v1" + tmpl)
    for c in candidates:
        key = f"{method} {c}"
        if key in postman_idx:
            return postman_idx[key]
    return None


def _summarize_change(orig: dict, mutated: dict) -> str:
    bits: list[str] = []
    if orig.get("method") != mutated.get("method"):
        bits.append(f"method: {orig.get('method')} -> {mutated.get('method')}")
    if mutation_engine._get_url_raw(orig) != mutation_engine._get_url_raw(mutated):
        bits.append("url: changed")
    o_auth = mutation_engine._get_header(orig, "Authorization")
    n_auth = mutation_engine._get_header(mutated, "Authorization")
    if o_auth != n_auth:
        bits.append(f"auth: {'set' if n_auth else 'cleared'}")
    o_ct = mutation_engine._get_header(orig, "Content-Type")
    n_ct = mutation_engine._get_header(mutated, "Content-Type")
    if o_ct != n_ct:
        bits.append("content-type: changed")
    o_body = (orig.get("body") or {}).get("raw", "")
    n_body = (mutated.get("body") or {}).get("raw", "")
    if o_body != n_body:
        bits.append(f"body: changed ({len(o_body)} -> {len(n_body)} bytes)")
    return ", ".join(bits) if bits else "(no change)"


# -------- main --------

def main() -> int:
    if not POSTMAN.exists():
        print(f"missing: {POSTMAN}", file=sys.stderr)
        return 1
    postman_idx = _build_postman_index()
    print(f"loaded postman: {len(postman_idx)} leaves", file=sys.stderr)

    results: list[dict] = []
    per_service_summary: dict[str, dict] = {}
    overall_action_counts: Counter = Counter()
    overall_misfire_count = 0
    overall_no_postman = 0

    for svc, pack_path in PACKS.items():
        if not pack_path.exists():
            continue
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        action_counts: Counter = Counter()
        misfires: list[dict] = []
        no_postman: list[dict] = []
        applied_count = 0
        total = 0

        for ep in pack.get("endpoints", []):
            ep_str = ep.get("endpoint", "")
            postman_leaf = _find_postman_for_endpoint(ep_str, postman_idx)
            for tc in ep.get("test_cases", []):
                total += 1
                tcid = tc.get("tc_id", "")
                scen = tc.get("scenario", "")
                if not postman_leaf:
                    no_postman.append({"tc_id": tcid, "endpoint": ep_str, "scenario": scen})
                    overall_no_postman += 1
                    continue
                postman_req = copy.deepcopy(postman_leaf.get("request", {}))
                out = mutation_engine.apply_mutation(postman_req, scen, endpoint=ep_str)
                mut = out["mutation"]
                action = mut["action"]
                applied = mut["applied"]
                action_counts[action] += 1
                overall_action_counts[action] += 1
                if applied:
                    applied_count += 1
                    summary = _summarize_change(postman_req, out["request"])
                else:
                    summary = "MISFIRE"
                    misfires.append({
                        "tc_id": tcid, "endpoint": ep_str, "scenario": scen,
                        "action": action, "note": mut["note"],
                    })
                    overall_misfire_count += 1
                results.append({
                    "service": svc, "endpoint": ep_str, "tc_id": tcid,
                    "scenario": scen, "action": action, "applied": applied,
                    "note": mut["note"], "change": summary,
                })

        per_service_summary[svc] = {
            "total": total, "applied": applied_count,
            "misfires": misfires, "no_postman": no_postman,
            "action_counts": dict(action_counts),
        }

    # --- write JSON ---
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "generated_at": "2026-05-09",
        "totals": {
            "tcs": sum(s["total"] for s in per_service_summary.values()),
            "applied": sum(s["applied"] for s in per_service_summary.values()),
            "misfires": overall_misfire_count,
            "no_postman_match": overall_no_postman,
        },
        "overall_action_counts": dict(overall_action_counts.most_common()),
        "per_service": per_service_summary,
        "records": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- write markdown ---
    md = ["# Mutation engine offline test — 2026-05-09\n"]
    total_tcs = sum(s["total"] for s in per_service_summary.values())
    total_applied = sum(s["applied"] for s in per_service_summary.values())
    md.append(f"**Total TCs:** {total_tcs}")
    md.append(f"**Applied:** {total_applied} ({100.0*total_applied/total_tcs:.1f}%)")
    md.append(f"**Misfires:** {overall_misfire_count}")
    md.append(f"**No postman match:** {overall_no_postman}\n")

    md.append("## Per-service\n")
    md.append("| Service | Total | Applied | Misfires | No-postman |")
    md.append("|---|---|---|---|---|")
    for svc, s in per_service_summary.items():
        md.append(f"| {svc} | {s['total']} | {s['applied']} | {len(s['misfires'])} | {len(s['no_postman'])} |")

    md.append("\n## Action distribution (top 30)\n")
    md.append("| Action | Count |")
    md.append("|---|---|")
    for k, n in overall_action_counts.most_common(30):
        md.append(f"| `{k}` | {n} |")

    if overall_misfire_count:
        md.append(f"\n## Misfires ({overall_misfire_count})\n")
        md.append("| service | tc_id | endpoint | scenario | action | note |")
        md.append("|---|---|---|---|---|---|")
        for svc, s in per_service_summary.items():
            for m in s["misfires"]:
                md.append(f"| {svc} | {m['tc_id']} | `{m['endpoint']}` | "
                          f"`{m['scenario']}` | {m['action']} | {m['note']} |")

    if overall_no_postman:
        md.append(f"\n## No Postman entry found ({overall_no_postman})\n")
        md.append("These pack endpoints don't match any Postman leaf. Check path alignment.\n")
        md.append("| service | endpoint | sample tc_id |")
        md.append("|---|---|---|")
        seen_eps = set()
        for svc, s in per_service_summary.items():
            for n in s["no_postman"]:
                key = (svc, n["endpoint"])
                if key in seen_eps:
                    continue
                seen_eps.add(key)
                md.append(f"| {svc} | `{n['endpoint']}` | {n['tc_id']} |")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    # stdout summary
    print(f"\n# Mutation engine offline test")
    print(f"Total TCs: {total_tcs}")
    print(f"Applied: {total_applied} ({100.0*total_applied/total_tcs:.1f}%)")
    print(f"Misfires: {overall_misfire_count}")
    print(f"No-postman: {overall_no_postman}")
    print(f"\nReport: {OUT_MD}")
    print(f"JSON:   {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
