---
name: JULES.DEMO Backend Hardening 2026-05-11
description: Allowee backend review + 16-item hardening pass shipped 2026-05-11; frontend hardening + auth UI still pending; resume point for next session
type: project
originSessionId: 37e84c36-1b69-4589-bea8-a3443433fc59
---
User asked for a code review of `~/JULES.DEMO` (Nigerian student finance tracker). I reviewed both frontend and backend, then they asked to patch all backend issues.

**Why:** App had multiple critical defects: broken auth flow, per-controller PrismaClient instances, raw error leakage in 500s, unwired zod schemas, foot-gun no-op security stubs, missing ownership checks, no migration history.

## What shipped this session

**Backend critical fixes:**
- Singleton PrismaClient at `backend/src/lib/prisma.ts` (HMR-safe via `globalThis`); all 8 controllers swapped
- Global error handler at `backend/src/middleware/errorHandler.ts` (404 + 500)
- `JWT_SECRET` startup check — server refuses to boot if unset
- Wired `transactionSchema` and zod validation; fixed createTransaction silent-accept
- Closed user-enumeration timing oracle on login via fixed-hash bcrypt.compare
- Login status codes corrected (409 dup user, 401 bad creds)
- Login rejects soft-deleted users
- `upsertItem` ownership enforced
- `Merchant.userId` promoted to `@unique` with real `@relation`
- Deleted `securityController.ts` + `securityRoutes.ts` (no-op stubs)
- CORS now uses comma-split allowlist with origin validator
- Soft-delete filters added wherever missing
- `aiController` rewritten with dynamic categories
- DB indexes added on Transaction, Budget, Item, Merchant, SharedPlan
- `prisma:seed` script switched from ts-node → `npx tsx`

**Migration baseline established:** `backend/prisma/migrations/20260511105742_initial/migration.sql`

**Verified end-to-end:** `tsc --noEmit` clean, `prisma migrate status` clean, server boots without errors.

## What's still pending

**Critical (will gate any real demo):**
- No login/register UI exists in frontend — `localStorage.getItem('token')` reads but nothing writes it
- `AppLock.tsx:13` hardcodes PIN `"1234"` — no JWT ever issued; every authenticated backend call 401s
- `Navbar.tsx:13` links to `/transactions` which doesn't exist as a route

**Architectural:**
- 30-min JWT with no refresh flow
- Token in localStorage — XSS-exfiltratable
