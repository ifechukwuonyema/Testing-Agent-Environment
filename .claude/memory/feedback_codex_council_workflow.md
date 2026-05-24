---
name: Code Delivery Workflow (Codex → Council → Update → Self-Review → Ship)
description: Mandatory five-stage pipeline for any code change before shipping; Codex reviews drafts, Council prioritizes, then update + self-review before deploy
type: feedback
originSessionId: cd1b62a4-e023-4d8e-93ef-715c9ff3b17f
---
Established 2026-05-04. This is the canonical workflow for **any code change** before it ships, deploys, or gets called "done." Do not skip stages, do not reorder, do not declare done after stage 1.

## The five stages

**Stage 1 — Draft.** Write the code (or apply the proposed edits). Do *not* declare it final. Treat this as a working draft awaiting review.

**Stage 2 — Codex review.** Codex is the unbiased reviewer in this workflow. I have author bias on everything I write — I will never grade my own code a fail, and any phrase like "this is sound" or "Codex is just polish" coming from me is that bias talking. The user brought Codex in *because* I'm biased, not because Codex is a backup safety net. Do the rigorous trace-through, ship the best work I can, then send to Codex *without* claiming I already know it's good — let Codex assess on its own. Send the draft to Codex for analysis and confirmation:
- `codex exec --sandbox read-only --skip-git-repo-check -m gpt-5.5 --config model_reasoning_effort="xhigh" -C "C:\Users\Onyema Ifechukwu" "<prompt>" 2>/dev/null`
- Run from a parent dir that includes both the code under review AND the memory folder so Codex has project context.
- Brief Codex on what changed and what to focus on; ask for findings ranked HIGH/MEDIUM/LOW with file:line citations.
- Codex is a peer reviewer, not an authority — but its outsider view catches the class of issue I miss as the author.

**Stage 3 — Council triage.** Relay Codex's findings to the Council skill (5 advisor lenses + Chairman synthesis). The decision Council answers: *which of these findings are worth our tokens to fix, and in what order?* Not all findings are worth fixing in this pass — Council distinguishes load-bearing fixes from nice-to-haves and explicit deferrals. Do not unilaterally decide the fix scope.

**Stage 4 — Update.** Apply the Council's synthesized recommendation. Fix the prioritized findings; explicitly defer the rest with a note (so the deferral is visible to future runs and not silent debt).

**Stage 5 — Self-review.** Run the protocol in `feedback_self_review_protocol.md` before declaring done:
- Cross-fix interaction check
- Author-blind reread
- Schema parity check
- Re-grep my own prior assumptions
- Class-of-bug check (not just ticket-of-bug)
- Post-change dry-run (not just `ast.parse`)
- For 4+ fixes: re-run Codex mid-flight, not just at the end.

Only after all five stages: ship.

## Why this is the rule

- Stage 1 alone has historically produced regressions that Codex catches in seconds — confirmation bias and "ticket-closing mode" cause me to miss interactions between adjacent edits.
- Stage 2 without Stage 3 wastes tokens fixing things that aren't load-bearing for the project's actual goals.
- Stages 4 + 5 without Stage 2 ships the original blind spots.
- The user explicitly opted into this architecture because Claude alone is not reliable enough on multi-fix sessions. Respect the architecture even when the change feels "small" — small changes are where I miss the most.

## How to apply

- For one-line cosmetic changes (typos, comments), the workflow can collapse to Stage 1 + Stage 5. Anything touching logic, data flow, contracts, or shared modules: full pipeline.
- When the user says "fix all" or "skip Council," that's their override — execute as instructed, but flag in the response that the protocol was bypassed and confirm before shipping.
- Codex must always have memory access (run from `C:\Users\Onyema Ifechukwu` or pass explicit memory paths in the prompt).
- Council input must be the **Codex findings**, not my synthesis of them — I'm the executor, Council is the prioritizer, Codex is the reviewer.
- Save any new failure modes the user catches into `feedback_self_review_protocol.md` so the self-review checklist grows over time.
