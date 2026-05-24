"""
Compare two Postman collections: show added/removed/changed request entries.
Usage: python diff_pmc.py <old.json> <new.json>
"""
import json, pathlib, sys, re

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

def walk(items, folder=None):
    folder = folder or []
    out = {}
    for it in items:
        if "item" in it:
            out.update(walk(it["item"], folder + [it.get("name", "")]))
        elif "request" in it:
            req = it["request"]
            method = req.get("method", "GET").upper()
            path = normalize_path(req.get("url", ""))
            key = f"{method} {path}"
            # store body + headers signature for change detection
            body_raw = ""
            body_block = req.get("body") or {}
            if body_block.get("mode") == "raw":
                body_raw = body_block.get("raw", "")
            hdrs = {h["key"]: h.get("value", "") for h in (req.get("header") or []) if not h.get("disabled")}
            out[key] = {"folder": "/".join(folder), "name": it.get("name", ""), "body_sig": body_raw[:120], "headers": hdrs}
    return out

if len(sys.argv) < 3:
    print("Usage: python diff_pmc.py <old.json> <new.json>")
    sys.exit(1)

old = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
new = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))

old_idx = walk(old["item"])
new_idx = walk(new["item"])

added   = {k: v for k, v in new_idx.items() if k not in old_idx}
removed = {k: v for k, v in old_idx.items() if k not in new_idx}
changed = {}
for k in set(old_idx) & set(new_idx):
    o, n = old_idx[k], new_idx[k]
    if o["body_sig"] != n["body_sig"] or o["name"] != n["name"]:
        changed[k] = {"old_name": o["name"], "new_name": n["name"],
                      "body_changed": o["body_sig"] != n["body_sig"]}

print(f"Old: {len(old_idx)} entries   New: {len(new_idx)} entries")
print()
if added:
    print(f"=== ADDED ({len(added)}) ===")
    for k, v in sorted(added.items()):
        print(f"  + {k}  [{v['folder']}]  name='{v['name']}'")
if removed:
    print(f"\n=== REMOVED ({len(removed)}) ===")
    for k, v in sorted(removed.items()):
        print(f"  - {k}  [{v['folder']}]  name='{v['name']}'")
if changed:
    print(f"\n=== CHANGED ({len(changed)}) ===")
    for k, v in sorted(changed.items()):
        flags = []
        if v["old_name"] != v["new_name"]: flags.append(f"name: '{v['old_name']}' -> '{v['new_name']}'")
        if v["body_changed"]: flags.append("body changed")
        print(f"  ~ {k}  [{', '.join(flags)}]")
if not added and not removed and not changed:
    print("No structural changes detected.")
