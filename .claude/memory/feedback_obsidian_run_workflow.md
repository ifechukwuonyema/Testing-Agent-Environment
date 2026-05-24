---
name: Obsidian-First Run Workflow
description: For every test run from 2026-05-02 onward, use the Obsidian vault as the canonical workflow — daily rollup note + per-service memory files with standard frontmatter + chain ID tracking + MEMORY.md index updates
type: feedback
originSessionId: 118ca0c9-42ac-4086-a3dd-2345f48e563c
---
For every API test run from 2026-05-02 onward, the Obsidian vault at `C:\Users\Onyema Ifechukwu\.claude\projects\C--WINDOWS-system32\memory\` is the canonical surface. The user explicitly asked for this on 2026-05-02 after the first sequential chain run.

**Why:** the user invested in setting up Obsidian (vault config, three plugins, hub-and-spoke graph, Dataview leaderboard, Templater rollup template) specifically so test results can be reviewed, compared run-over-run, and shared. The vault replaces ad-hoc post-run summary tables that previously only existed in conversation context. Memory + leaderboard + rollup is the new operating model.

**How to apply — at the start of any test run:**

1. **Create or update the day's rollup note** at `<vault>\run_YYYY-MM-DD.md` for today's date. If creating from scratch, copy the structure from `<vault>\run_2026-05-02.md` (frontmatter with `type: rollup` and `run_date: YYYY-MM-DD`, plus the two Dataview queries scoped to that date, plus the standard sections: Day summary, Chain ID flow, Cross-service themes, Action items, Notes). The Templater template at `<vault>\_templates\daily_run_rollup.md` can be applied from inside Obsidian for convenience.

**How to apply — for each service tested:**

2. **Write a memory file** at `<vault>\project_<service>_<context>_<date>.md` (e.g. `project_cards_chain_run_20260502.md` or `project_bank_hybrid_run_20260503.md`). Use this frontmatter shape — every field is required for the leaderboard to render correctly:
```
---
name: <Title>
description: <one-line summary>
type: project
service: <Service display name, e.g. "Cards" or "Affiliate v2">
run_date: YYYY-MM-DD
tcs: <int>
passes: <int>
fails: <int>
blocked: <int>
pass_rate: <int 0-100, rounded>
worst_cluster: <one-line description>
chain_run_id: <chain id if part of a chain, omit if standalone>
---
```

**How to apply — at the end of any test run:**

3. **Add a one-line entry to `<vault>\MEMORY.md`** using the wikilink format `- [[file_basename|Display Title]] — short hook under 150 chars`. Insert near the bottom of the bullet list, before the `---` separator and Dataview blocks.

4. **For chain runs**, also write a cross-service summary memory (template: see `project_chain_run_20260502.md`) with platform aggregates, cluster breakdowns, and ID flow story. Link to per-service memories via wikilinks.

5. **Update the rollup note's manual sections** (Day summary, Cross-service themes, Action items) after the run completes — Dataview tables auto-populate but narrative sections need filling.

**What NOT to do:**

- Don't use markdown links `[Title](file.md)` — use wikilinks `[[file|Title]]`. Wikilinks engage backlinks + graph view.
- Don't omit the leaderboard frontmatter fields — partial frontmatter breaks the Dataview filter.
- Don't write run summaries only in conversation. The vault is canonical; the conversation is ephemeral.
- Don't quote the `run_date` value in YAML — Dataview parses unquoted dates as Date objects, which is what queries like `WHERE run_date = date("2026-05-02")` expect.

**Automation:**

The chain orchestrator at `Downloads\run_sequential_chain.py` already writes per-service memory files automatically with the correct frontmatter. For non-chain runs (single service), I write the memory file myself at run completion.

**Compatibility note:**

The vault sits inside Claude Code's auto-memory directory, so MEMORY.md is loaded into every conversation's system context. Memories I write are immediately retrievable in future sessions — Obsidian is the human-facing review layer; the file system is the persistence layer.

**Always volunteer the fail-block breakdown after every run/report.**

After any test run completes — single service, chain, or generated report (DOCX/YAML) — automatically present the fail-block breakdown. Do NOT wait for the user to ask. Format: per-service counts table + cluster-by-cluster FAIL breakdown + cluster-by-cluster BLOCKED breakdown + one-line takeaways per service + the single highest-leverage fix. The user has explicitly asked for this multiple times across sessions; treat it as the default closing of any report-generating activity.

**Auto-invoke installed skills without being asked.**

The user installed three workflow skills on 2026-05-03 (`/breakdown`, `/chain`, `/regression`) and said: "remember when to use them, i don't want to have to tell you." These skills must fire on the triggers below — never wait for explicit invocation:

- **`/breakdown`** — auto-invoke after every test run, every report generation (DOCX or YAML), every chain orchestrator completion. Skip ONLY if the user explicitly says "no breakdown" or "skip the breakdown."
- **`/chain`** — auto-invoke when the user says any of: "run the chain", "run sequential test", "test all microservices", "full test", "complete test", "re-run the chain", or any synonym implying full sequential testing. The Saturday 2026-05-09 follow-up to the 2026-05-02 chain baseline is also a `/chain` trigger.
- **`/regression`** — auto-invoke (a) when the user asks "did X improve" / "any progress" / "what changed since [date]" / "is [defect] fixed", AND (b) automatically after `/chain` finishes when at least one prior chain run exists. The 2026-05-09 follow-up specifically requires both `/chain` then `/regression` against the 2026-05-02 baseline.

The full instructions for each skill live in `~\.claude\skills\<name>\SKILL.md`. Invoke via the Skill tool.

**Strategic-decision skill (`/council`)** is invoke-only — never auto-fire. It's a deliberation framework for "should we" questions; routine work bypasses it.

**Reinforcement 2026-05-03:** The user re-stated the rule ("from now on automatically write and retrieve from obsidian thats the whole point ... it is your second brain for storage") after I produced a Cards run + 10 harness optimizations + a backend ask document and failed to write any of it to the vault until prompted. The vault is the durable surface; conversation is throwaway. **Treat every test run, every harness change, every diagnostic-pattern discovery, and every backend-ask document as a vault-write trigger — not a "ask first" event.** Specifically: when work produces (a) measurable test results, (b) a new diagnostic pattern, (c) a new shared module/file in the harnesses, or (d) a deliverable for someone else (e.g. backend ask doc), immediately write the corresponding memory file and update MEMORY.md, then surface what was written in the conversation summary. Reading the vault on conversation start, and writing to it without being asked, is the whole point.
