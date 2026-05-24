---
name: JULES.DEMO Full UI Redesign
description: Allowee app at ~/JULES.DEMO needs a full /stitch-design redesign — scheduled 2026-05-09 23:00, user said current UI is bad
type: project
originSessionId: ae2e078e-ed6c-48df-907a-10969e33a0c3
---
User flagged the Allowee app UI as "soooo bad" on 2026-05-09 and asked for a **full redesign via `/stitch-design`**, scheduled to run at **2026-05-09 23:00** (11pm local).

**Why:** User explicitly chose option 1 ("Full redesign with /stitch-design") over targeted polish or in-place modernization. They want a fresh design system synthesized and screens regenerated, not incremental tweaks.

**App context:**
- Repo: `~/JULES.DEMO`, on `main` at `8bb417a`
- Stack: Next.js 15.0.3 + Tailwind + Framer Motion + Lucide React; Node backend with Express + Prisma 5.22 + Postgres
- Routes to redesign: `/` (landing+PIN), `/dashboard`, `/budget-agent`, `/community`, `/marketplace`, `/merchant`, `/profile`
- App identity: Nigerian student finance tracker — "Allowee" — with tier-based budget personas (LAPO Baby / Yanga / Cool Kids / NEPO Babies). Nigerian university campus marketplace integration. Demo PIN `1234`.

**Setup state (already done 2026-05-09, do not redo):**
- Postgres: Docker container `jules-pg` (postgres:16) on `localhost:5432`, db/user/pw all `allowee`. Start with `docker start jules-pg` if stopped.
- `backend/.env` written with `DATABASE_URL` + `JWT_SECRET`
- Dev servers run via `cd ~/JULES.DEMO/backend && npm run dev` and `cd ~/JULES.DEMO/frontend && npm run dev`; ports 3001 + 3000

**Out of scope for the redesign run:** backend changes, route additions, dependency upgrades, README rewrite. Visual+layout only.
