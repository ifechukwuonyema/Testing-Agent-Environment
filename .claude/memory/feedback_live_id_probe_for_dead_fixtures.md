---
name: Live ID Probe When Fixtures Return 404
description: When fixture IDs from backend return 404 against GET, probe live via swagger-shaped GET to discover the actual format the backend accepts — then patch runner KNOWN_GOOD_FALLBACK
type: feedback
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
# Live ID Probe When Fixtures Return 404

**Rule:** If KNOWN_GOOD or Postman-supplied IDs 404 against the service's read endpoint, do NOT assume the endpoint is broken. Probe live first with the swagger-defined ID format pattern; if a working ID is found, patch the runner's `KNOWN_GOOD_FALLBACK` dict with the discovered value.

**Why:** Three sessions in a row (customer 2026-05-10, transactions 2026-05-10, and bank earlier) had `H_5xx` / `Cluster-C` storms that turned out to be fixture-format mismatches, not backend defects. Each time the fix was the same: probe live, discover the real format (e.g. `CUS-<32hex>` vs `CUST-ACME-XXX`; `TRA-<32hex>` vs `TXN-2026-*`), and overwrite KNOWN_GOOD. Without probing, the runner generates a wall of false-positive backend defects.

**How to apply:**

1. **Trigger:** before declaring a GET endpoint broken, run 1-3 manual GETs with the swagger-stated ID format using `curl` / inline Python `requests`.
2. **If 200:** the fixture is wrong, not the backend. Capture the working ID; patch `KNOWN_GOOD_FALLBACK` (or service-specific equivalent like `KNOWN_GOOD_CUSTOMER_REF_ID`) in the runner.
3. **If 404 from valid-format ID:** real backend gap or fixture isn't loaded — file as backend ask (D-{SVC}-IDS-1 pattern: "fixtures supplied don't exist in test env or have wrong format").
4. **If 500:** real backend defect, file accordingly.
5. **Document both the invalid and valid IDs in the backend asks DOCX** under a section like "Invalid ID Inventory" so backend sees the side-by-side pair, not just a complaint.
6. **The dual-population case (transactions):** if the service has two different ID formats for the same logical entity across mint vs read paths, that's its own backend ask (D-TRX-IDS-2 pattern). Don't try to paper over it in the runner.

**Anti-pattern to avoid:** marking 100+ TCs as `H_5xx`/`A_unexpected_4xx` and writing them up as backend defects without first probing one live request to confirm the ID format. Wasted half a session on customer until I tried `CUS-32hex` and it worked instantly.
