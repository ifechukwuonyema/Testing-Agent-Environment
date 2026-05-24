---
name: Backend Ask — Swagger / OpenAPI Constraint Audit
description: Document filed 2026-05-05 requesting backend self-audit of swagger constraints across all 8 services; gates signal quality of incoming Schemathesis property-based tests
type: reference
originSessionId: c5d57ed4-97aa-4fd6-9131-0f65dc2c5d28
---
Document file: `C:\Users\Onyema Ifechukwu\Kardit\harnesses\BACKEND_SWAGGER_AUDIT_REQUEST.md`

**Why:** Schemathesis adoption needs tight swagger constraints to produce focused defects rather than noise. Loose schemas → infinite legal input space → fuzzer flounders.

**Five sections of the ask:**
1. **Request body strictness** — `additionalProperties: false`, `required` lists, `minLength`/`maxLength`/`pattern`, numeric constraints, `enum`, `format`
2. **Response schemas** — declared per status code (2xx, 4xx error envelope, 5xx); `Content-Type` per response
3. **Auth declarations** — `security` blocks per endpoint matching what server accepts
4. **OpenAPI 3 `links`** — for stateful traversal; nice-to-have with sidecar fallback
5. **Per-service gaps** — populated after Phase 0 Batch pilot

**Severity:** MEDIUM — does not block current Postman-hybrid runs, only quality of upcoming fuzz lane

[[project_schemathesis_adoption_20260505]] [[reference_backend_verification_endpoints_ask]] [[reference_backend_onboarding_flow_ask]]
