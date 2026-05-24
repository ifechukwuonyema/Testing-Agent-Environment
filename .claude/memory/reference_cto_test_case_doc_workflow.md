---
name: CTO Test-Case Documentation Workflow
description: Consolidate verified test packs from all 8 Kardit services into a tabular doc (DOCX+HTML+MD), upload to Drive with auto-convert to Google Doc, share with stakeholder. Two scripts; canonical 6-column format.
type: reference
originSessionId: 932baa3f-a040-4145-856c-68e9801f6cec
---
## Scripts
- **Generator**: `C:\Users\Onyema Ifechukwu\Downloads\generate_all_service_test_cases_for_cto.py`
  - Reads all 8 verified packs; emits `.docx`, `.html`, `.md`
  - Output base: `Downloads\Kardit_Microservices_Test_Cases_<YYYY-MM-DD>.{docx,html,md}`
- **Uploader**: `C:\Users\Onyema Ifechukwu\Downloads\upload_to_google_docs.py`
  - Uses `gcloud auth print-access-token` (user creds, NOT application-default — Drive scope is restricted under app-default)
  - Multipart Drive upload with `mimeType: application/vnd.google-apps.document` for auto-convert
  - Optional `python upload_to_google_docs.py <cto_email>` to share with writer access

## One-time auth setup
```
gcloud auth login --enable-gdrive-access
```
gcloud path: `C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`

## Pack source paths (used by generator)
- Bank: `Downloads\bank_microservice_functional_test_pack_v1_40_each.json`
- Customer: `Downloads\kardit_customer_api_test_agent_v3_1\...\data\customer_microservice_functional_test_pack_v1_40_each.json`
- Transactions: `Downloads\kardit_transactions_api_test_agent_v3_1\...\data\transactions_microservice_functional_test_pack_v1_40_each.json`
- Affiliate: `Downloads\kardit_affiliate_api_test_agent_v3_1\...\data\affiliate_microservice_functional_test_pack_v1_40_each_exact.json`
- Cards: `Downloads\cards_microservice_functional_test_pack_v1_40_each.json`
- Admin: `Downloads\admin_services_api_test_agent_v1\admin_services_api_test_agent\data\admin_services_functional_test_pack_v1_30_plus.json` (note: v1, NOT v3_1)
- Batch: `Downloads\kardit_batch_api_test_agent_v3_1\...\data\batch_microservice_functional_test_pack_v3_30_each.json`
- Notifications: `Downloads\kardit_notifications_api_test_agent_v1\...\data\notifications_TC.json` (v1, NOT v3_1)

## Steps
1. Run generator → produces three files
2. (First time only) `gcloud auth login --enable-gdrive-access` in a fresh terminal
3. `python upload_to_google_docs.py [cto_email]` → returns `https://docs.google.com/document/d/<id>/edit`

## Gotchas
- Use the user-installed Python at `C:\Users\Onyema Ifechukwu\AppData\Local\Python\bin\python.exe`. The Microsoft Store `py.exe` shim may hang silently on this script.
- gcloud `application-default login` does NOT have Drive scope — must use `gcloud auth login --enable-gdrive-access`.
