"""Show body diff for a specific endpoint between two PMCs."""
import json, pathlib, re, sys

OLD = pathlib.Path(r"C:\Users\Onyema Ifechukwu\Downloads\Kardit.Api.postman_collection (8).json")
NEW = pathlib.Path(r"C:\Users\Onyema Ifechukwu\Downloads\Kardit.Api.postman_collection (9).json")

TARGET_KEYS = {
    "POST /api/v1/Batches/card-creation/upload",
    "POST /api/v1/cards/issuance",
    "POST /api/v1/customers/draft",
    "POST /api/v1/customers/search",
}

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
    if not path.startswith("/"): path = "/" + path
    return path

def walk(items):
    for it in items:
        if "item" in it:
            yield from walk(it["item"])
        elif "request" in it:
            req = it["request"]
            method = req.get("method", "GET").upper()
            path = normalize_path(req.get("url", ""))
            key = f"{method} {path}"
            if key in TARGET_KEYS:
                body_block = req.get("body") or {}
                raw = body_block.get("raw", "") if body_block.get("mode") == "raw" else ""
                try:
                    yield key, json.loads(raw)
                except Exception:
                    yield key, raw

old_pmc = json.loads(OLD.read_text(encoding="utf-8"))
new_pmc = json.loads(NEW.read_text(encoding="utf-8"))

old_bodies = dict(walk(old_pmc["item"]))
new_bodies = dict(walk(new_pmc["item"]))

for key in sorted(TARGET_KEYS):
    if key in old_bodies and key in new_bodies:
        o = old_bodies[key]
        n = new_bodies[key]
        if o != n:
            print(f"\n{'='*70}")
            print(f"  {key}")
            print(f"{'='*70}")
            if isinstance(o, dict) and isinstance(n, dict):
                old_keys = set(str(k) for k in _flatten(o).keys()) if hasattr(o, 'items') else set()
                new_keys = set(str(k) for k in _flatten(n).keys()) if hasattr(n, 'items') else set()
                # Just print both
                print("  OLD body:")
                print("  " + json.dumps(o, indent=2).replace("\n", "\n  "))
                print("  NEW body:")
                print("  " + json.dumps(n, indent=2).replace("\n", "\n  "))
            else:
                print("  OLD:", repr(str(o)[:200]))
                print("  NEW:", repr(str(n)[:200]))
