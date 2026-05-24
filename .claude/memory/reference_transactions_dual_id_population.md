---
name: Transactions Dual ID Population
description: Transactions backend returns TXN-2026-XXXXX from /query and POST mint, but GET read endpoints accept TRA-32hex only — same logical entity, two ID formats
type: reference
service: Transactions
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
**Finding (2026-05-10):** The transactions service uses two different ID formats for the same logical entity depending on the endpoint:

| Path | Format | Example |
|---|---|---|
| `POST /transactions/query` response | `TXN-2026-XXXXX` (sequential) | `TXN-2026-00014` |
| POST mint response | `TXN-2026-XXXXX` (sequential) | `TXN-2026-00019` |
| `GET /transactions/{id}` | `TRA-<32hex>` | `TRA-1234567890ABCDEF1234567890ABCDEF` |
| `GET /transactions/customers/{customerId}` (the txn part) | `TRA-<32hex>` | same as above |

**Why it matters:** Round-tripping a TXN-2026-* ID from `/query` into a GET 404s every time. Fixtures shipped by backend use the TXN-2026-* format, which means GET coverage was completely broken until we probed live and discovered TRA-32hex is the only accepted GET format.

**How to apply:**
- Treat `TXN-2026-*` and `TRA-32hex` as distinct populations until backend reconciles them.
- For runner KNOWN_GOOD_FALLBACK: use `TRA-<32hex>` for `transactionId` slots feeding read endpoints, and `TXN-2026-00001` for `exportId`/query-result references.
- Documented as **D-TRX-IDS-2** in `Downloads\transactions_recommendations_2026-05-10.docx`. Do not file as resolved until backend either: (a) returns TRA-32hex from /query and mint, or (b) makes GET accept TXN-2026-*.
