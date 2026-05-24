"""
Merge new PMC download into our working collection.

Strategy:
- For entries in both: update name + body from new PMC (picks up backend body/fixture updates)
- For entries only in new: add them (new backend endpoints)
- For entries only in ours: keep them (our deliberate additions, e.g. extra query params)
- Customer-seed-ID swap: new PMC uses a different hardcoded customerRefId in the path
  — update the path directly to match new PMC
"""
import json, pathlib, re, sys

WORKING  = pathlib.Path(r"C:\Users\Onyema Ifechukwu\Downloads\Kardit.Api.postman.collection.json")
NEW_PMC  = pathlib.Path(r"C:\Users\Onyema Ifechukwu\Downloads\Kardit.Api.postman_collection (9).json")

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

def walk_and_index(items, folder=None):
    """Return dict {method_path_key: (parent_list, index_in_parent)} for leaf request nodes."""
    folder = folder or []
    idx = {}
    for i, it in enumerate(items):
        if "item" in it:
            idx.update(walk_and_index(it["item"], folder + [it.get("name", "")]))
        elif "request" in it:
            req = it["request"]
            method = req.get("method", "GET").upper()
            path = normalize_path(req.get("url", ""))
            key = f"{method} {path}"
            idx[key] = {"item": it, "parent": items, "idx": i}
    return idx

def walk_items_flat(items):
    """Yield all leaf request items."""
    for it in items:
        if "item" in it:
            yield from walk_items_flat(it["item"])
        elif "request" in it:
            yield it

working_pmc = json.loads(WORKING.read_text(encoding="utf-8"))
new_pmc     = json.loads(NEW_PMC.read_text(encoding="utf-8"))

working_idx = walk_and_index(working_pmc["item"])
new_idx     = walk_and_index(new_pmc["item"])

updates = 0
additions = 0

# 1. Apply body + name updates from new PMC onto matching entries in working collection
for key, new_entry_info in new_idx.items():
    new_item = new_entry_info["item"]
    new_req  = new_item["request"]

    if key in working_idx:
        w_item = working_idx[key]["item"]
        w_req  = w_item["request"]

        # Update name
        if w_item.get("name") != new_item.get("name"):
            print(f"  name update [{key}]: '{w_item.get('name')}' -> '{new_item.get('name')}'")
            w_item["name"] = new_item["name"]
            updates += 1

        # Update body (the main thing that changes when backend updates fixtures)
        new_body = new_req.get("body")
        if new_body and new_body != w_req.get("body"):
            print(f"  body update [{key}]")
            w_req["body"] = new_body
            updates += 1

        # Update path/url only for entries where path structure changed
        # (avoid overwriting our deliberate query-param enrichments on BATCH-08)
        new_path = normalize_path(new_req.get("url", ""))
        w_path   = normalize_path(w_req.get("url", ""))
        if new_path != w_path:
            print(f"  path update [{key}]: '{w_path}' -> '{new_path}'")
            w_req["url"] = new_req["url"]
            updates += 1

# 2. Add entries that exist only in new PMC (new backend endpoints)
for key, new_entry_info in new_idx.items():
    if key not in working_idx:
        print(f"  ADDING new entry: {key}")
        # Find the parent folder in working collection and append
        # For simplicity, walk new PMC tree to find parent folder path, recreate in working if needed
        # Simple fallback: append to top-level item list
        working_pmc["item"].append(new_entry_info["item"])
        additions += 1

# 3. Remove entries from working that exist only there AND also exist in new PMC under a different key
#    (handles customer seed-ID path swap)
#    Detect: same folder + same name but different path key
new_items_flat = list(walk_items_flat(new_pmc["item"]))
new_names = {(it.get("name", ""), normalize_path(it["request"].get("url", ""))): True for it in new_items_flat}

# Look for working entries whose name exists in new PMC but under a different path
removals = []
for key, w_info in working_idx.items():
    w_item = w_info["item"]
    w_name = w_item.get("name", "")
    if key not in new_idx:
        # Check if same name appears in new PMC under a different key
        matched_in_new = any(
            it.get("name") == w_name
            for it in new_items_flat
            if normalize_path(it["request"].get("url", "")) != normalize_path(w_item["request"].get("url", ""))
        )
        if matched_in_new:
            print(f"  REMOVING stale entry (name present in new PMC under different path): {key}")
            removals.append((w_info["parent"], w_info["idx"]))

# Remove in reverse index order to avoid index shifting
for parent, idx in sorted(removals, key=lambda x: x[1], reverse=True):
    del parent[idx]

WORKING.write_text(json.dumps(working_pmc, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nDone. Updates={updates}  Additions={additions}  Removals={len(removals)}")
