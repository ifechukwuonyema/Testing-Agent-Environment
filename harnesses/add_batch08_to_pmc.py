"""
One-shot script: adds GET /api/v1/Batches to the Postman collection under the Batches folder.
Idempotent — skips if the entry already exists.
"""
import json, pathlib, sys

PMC_PATH = pathlib.Path(r"C:\Users\Onyema Ifechukwu\Downloads\Kardit.Api.postman.collection.json")

NEW_ITEM = {
    "name": "/api/v1/Batches",
    "request": {
        "method": "GET",
        "header": [
            {"key": "Accept", "value": "application/json"}
        ],
        "url": {
            "raw": "{{baseUrl}}/api/v1/Batches",
            "host": ["{{baseUrl}}"],
            "path": ["api", "v1", "Batches"],
            "query": [
                {"key": "BatchType",     "value": "", "disabled": True},
                {"key": "Status",        "value": "", "disabled": True},
                {"key": "ProductId",     "value": "", "disabled": True},
                {"key": "BankId",        "value": "", "disabled": True},
                {"key": "SubmittedByRef","value": "", "disabled": True},
                {"key": "TenantId",      "value": "", "disabled": True},
                {"key": "MakerUserId",   "value": "", "disabled": True},
                {"key": "CheckerUserId", "value": "", "disabled": True},
                {"key": "SubmittedFrom", "value": "", "disabled": True},
                {"key": "SubmittedTo",   "value": "", "disabled": True},
                {"key": "ApprovedFrom",  "value": "", "disabled": True},
                {"key": "ApprovedTo",    "value": "", "disabled": True},
                {"key": "ProcessedFrom", "value": "", "disabled": True},
                {"key": "ProcessedTo",   "value": "", "disabled": True},
                {"key": "Page",          "value": "1", "disabled": True},
                {"key": "PageSize",      "value": "20", "disabled": True},
                {"key": "SortBy",        "value": "", "disabled": True},
                {"key": "SortDirection", "value": "", "disabled": True},
            ],
            "variable": []
        }
    },
    "response": []
}

pmc = json.loads(PMC_PATH.read_text(encoding="utf-8"))

# Navigate to the Batches folder
def find_folder(items, name):
    for item in items:
        if item.get("name") == name and "item" in item:
            return item
    return None

v1_folder = find_folder(pmc["item"], "api")
if v1_folder:
    v1_folder = find_folder(v1_folder["item"], "v1")

batches_folder = find_folder(v1_folder["item"], "Batches") if v1_folder else None

if batches_folder is None:
    print("ERROR: Could not find Batches folder in PMC")
    sys.exit(1)

# Idempotency check
existing_names = [i.get("name") for i in batches_folder["item"]]
if "/api/v1/Batches" in existing_names:
    print("GET /api/v1/Batches already in PMC — nothing to do.")
    sys.exit(0)

# Insert at the beginning of the Batches folder (before card-creation subfolder)
batches_folder["item"].insert(0, NEW_ITEM)

PMC_PATH.write_text(json.dumps(pmc, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Done. Batches folder now has {len(batches_folder['item'])} items.")
