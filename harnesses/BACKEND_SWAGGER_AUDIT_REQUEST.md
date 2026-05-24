# Backend Ask — Swagger / OpenAPI Constraint Audit for Property-Based Testing

**Filed:** 2026-05-05
**Filed by:** API testing harness team
**Severity:** MEDIUM — gates the quality of upcoming property-based contract tests; does not block current Postman-hybrid runs
**Status:** Open

## Summary

The harness team is rolling out **Schemathesis** (property-based contract testing driven directly by the swagger document) as a complementary lane to the existing Postman-hybrid runner. Schemathesis generates legal-but-unexplored input shapes from each schema constraint and asserts behavior against the documented contract. Its signal quality is **directly proportional to the tightness of the swagger**:

- Loose schemas → infinite legal input space → fuzzer flounders, produces low-value findings, dilutes signal
- Tight schemas → focused exploration → fuzzer finds real 5xx + silent-accept defects efficiently

This ask requests a backend self-audit (or backend confirmation) on the swagger constraints listed below, across all 8 microservices. Pilot is on Batch (healthiest service, lowest noise floor); high-5xx services follow.

## What we need

For each of the 8 services (Bank, Affiliate, Customer, Cards, Transactions, Batch, Notifications, Admin), confirm or remediate the following.

### 1. Request body strictness

| Item | Required state | Why |
|---|---|---|
| `additionalProperties` on all object schemas | Set to `false` (or explicit allowed key list) | Without it, fuzzer cannot test "extra-key rejection" — `B_silent_accept` cluster goes undetected |
| `required` arrays | Explicit list per object | Without it, fuzzer cannot test "missing-required-field rejection" |
| String fields | `minLength`, `maxLength`, `pattern` declared where business rules apply | Without them, fuzzer generates 0-length and 10kB strings indiscriminately, drowning real defects in noise |
| Numeric fields | `minimum`, `maximum`, `exclusiveMinimum`, `multipleOf` where applicable | Same noise concern as strings |
| Enum fields | Declared via `enum:` | Without it, fuzzer can't distinguish "unknown enum value" rejection from server crashes |
| `format` annotations | `uuid`, `email`, `date-time`, `ipv4`, etc. on every typed field | Drives realistic input generation |

### 2. Response schema declarations

| Item | Required state | Why |
|---|---|---|
| 2xx response schemas | Declared per endpoint | Drives `Z2_schema_drift_on_2xx` detection |
| 4xx response schemas | Declared (typically a shared error envelope) | Drives `Z1_envelope_drift_on_4xx` detection |
| 5xx response schemas | Either declared OR documented as "should not occur in normal operation" | If declared as a normal response shape, server crashes blend in with documented 5xx and `not_a_server_error` check is undermined |
| `Content-Type` declarations | Explicit per response | Catches services that lie about content type (currently uncaught in our pipeline) |

### 3. Auth declarations

| Item | Required state | Why |
|---|---|---|
| `security` blocks per endpoint | Declared (even when set to `[]` for public) | Drives `auth_enforced_on_protected_endpoints` custom check — directly maps to known Admin banks endpoint silent-accept defect (TCs 003-007 return 200 without auth) |
| Documented auth schemes | Match what the server actually accepts | A swagger that claims Bearer but server also accepts cookies (or vice versa) makes auth fuzzing produce false positives |

### 4. OpenAPI 3 `links` declarations (stateful testing — Phase 3 prerequisite)

For each resource-creating endpoint (`POST /<resource>`), declare a `links:` block pointing to the corresponding read endpoint (`GET /<resource>/{id}`). Example:

```yaml
paths:
  /api/v1/banks:
    post:
      responses:
        '200':
          links:
            GetBankById:
              operationId: getBankById
              parameters:
                bankId: '$response.body#/bankId'
```

This unlocks Schemathesis's stateful mode, which can replace most of the harness's hand-coded `get_after_post_probe` logic and reduce per-service runner complexity.

**Lower-priority but high-value** — if `links` are out of scope for backend, the harness team can author sidecar link YAMLs ourselves (~1 day per service). This ask is marked "nice to have" with that fallback.

### 5. Per-service known gaps

#### 5.1 Batches service (Phase 0 pilot, 2026-05-05)

Smoke run: 6 endpoints tested, 50 generated cases, 10 unique findings. Schemathesis output preserved at `~\Kardit\harnesses\schemathesis_runs\batch_phase0\batch_smoke.xml`.

**Request body / parameter strictness gaps (§1):**

| Endpoint | Gap | Server behavior | Suggested swagger fix |
|---|---|---|---|
| `POST /api/v1/Batches/{batchId}/validate` | `RequestContext` (and its child fields `TenantId`, `UserType`, `ActorUserId`, `AffiliateId`) is required by server but not marked `required` in swagger | Returns 400 with full validation envelope when omitted | Add `required: [RequestContext]` on request body; `required: [TenantId, UserType, ActorUserId, AffiliateId]` on RequestContext schema |
| `POST /api/v1/Batches/{batchId}/validate` | Server enforces strict object validation but swagger lacks `additionalProperties: false` | Returns 400 on extra properties (test injected `x-schemathesis-unknown-property`) | Set `additionalProperties: false` on request body schema |
| `GET /api/v1/Batches/{batchId}/rows` | `Page` and `PageSize` lack numeric bounds in swagger | Server enforces `Page >= 1`, `PageSize` between 1 and 100; returns 400 otherwise | Add `minimum: 1` on `Page`; `minimum: 1, maximum: 100` on `PageSize` |

**Response schema gaps (§2):**

| Endpoint | Gap | Server behavior | Suggested swagger fix |
|---|---|---|---|
| `GET /api/v1/Batches/{batchId}` | Only `200` documented | Returns `400` for invalid batchId formats (e.g., `0`) | Document `400` response with the standard RFC 9110 problem-details envelope |
| `GET /api/v1/Batches/{batchId}/results/download` | Only `200` documented | Returns `400` for invalid batchId formats | Same as above |
| `GET /api/v1/Batches/{batchId}/rows` | Only `200` documented | Returns `400` for invalid pagination | Same as above |
| `POST /api/v1/Batches/{batchId}/validate` | Only `200` documented | Returns `400` for missing/invalid RequestContext | Same as above |

**Content-Type gaps (§2):**

4 endpoints declare response `Content-Type: text/json`:
- `GET /api/v1/Batches/{batchId}/rows`
- `POST /api/v1/Batches/card-creation/upload`
- `POST /api/v1/Batches/{batchId}/submit`
- `POST /api/v1/Batches/{batchId}/validate`

`text/json` is non-standard (RFC 8259 specifies `application/json`). Either change swagger to `application/json` (if server already returns that) or change server to actually emit `text/json` (less recommended). Currently breaks any spec-driven client's content negotiation.

**Auth declarations (§3):** Not yet probed in this smoke run — Phase 0 used unauthenticated requests. Will append after Phase 1 runner adds auth.

**OpenAPI 3 `links` (§4):** Not present on any of the 6 Batches endpoints. Stateful POST→GET traversal not currently possible without sidecar definitions.

**Extrapolation:** All four gap categories above are likely platform-wide (request-context envelope, additionalProperties, response 4xx, text/json content type). Confirming on remaining 7 services in Phase 2 and appending to subsections 5.2–5.8.

---

Subsequent service-specific findings will be appended as Phases 1–2 progress.

## What we're NOT asking for

- Rewriting any backend logic — this is a swagger document audit, not a behavior change request
- New endpoints (with the exception of Section 4's `links`, which can be sidecar-authored by the harness team)
- Changes to authentication or authorization
- Anything that affects the live Postman-hybrid runner's current pass rates

## Why now

- Schemathesis adoption pilot starts in parallel with the affiliate-onboarding backend fix work (already filed at `BACKEND_AFFILIATE_ONBOARDING_FLOW_REQUEST.md`)
- Earlier audit = lower noise floor on all subsequent fuzz runs = faster surfacing of real defects in catastrophic-tier services (Customer 100% FAIL rate, Notifications 100% FAIL rate, Transactions read 0.6% pass rate)
- Filing now also documents what "good" looks like for any new endpoints added during ongoing development

## Acceptance / response format

For each service, we'd like either:
- **Confirmation** — "Section X is already conformant" (we'll spot-check with the fuzzer)
- **Remediation plan** — list of swagger fields to tighten, with rough timeline
- **Decline with rationale** — for items the team chooses not to tighten (e.g., `additionalProperties: true` is a deliberate forward-compat choice on a specific endpoint family)

A per-service response in any of those forms is sufficient. No specific SLA — pace this against your current backlog.

## Contact

Filed by API testing harness team. Reply via the same channel as `BACKEND_AFFILIATE_ONBOARDING_FLOW_REQUEST.md` (2026-05-05) and `BACKEND_VERIFICATION_ENDPOINTS_REQUEST.md` (2026-05-03).
