---
name: Downloads Directory Layout (organized 2026-05-01)
description: Where things live in C:\Users\Onyema Ifechukwu\Downloads after the 2026-05-01 reorganization — use this to know where to look for files in future sessions
type: reference
originSessionId: 506fc878-81d5-47e4-95a1-58c711c395e6
---
The Downloads directory was reorganized on 2026-05-01 from a flat 546-entry pile into the structure below. **47 entries remain at the root** — all of them are operational Kardit files (the harness, runner kits, live test packs, etc.) and live state the harness depends on. Do **not** move root-level Kardit files without updating hard-coded paths in `postman_standalone_runner.py` and the helper scripts.

## What stays at Downloads root (47 items)

**Kardit operational** (paths hardcoded in harness — do NOT move):
- `postman_standalone_runner.py` — main standalone harness
- `Kardit.Api.postman.collection.json` — Postman value source
- `kardit_session_ids.json` — live SessionStore state
- `kardit_chain_report.yaml`, `kardit_coverage_report.yaml` — latest chain outputs
- `run_all.py` — chain orchestrator
- 6 test pack JSONs (`*_microservice_functional_test_pack_*.json`) + their `.bak` files
- 8 runner-kit subdirs (`kardit_*_api_test_agent_*/`, `kardit_runner_kit/`, `kardit_api_test_agent/`, `admin_services_api_test_agent_v1/`, `kardit_notifications_api_test_agent_v1/`)

**Helper scripts** (one-off transformers, kept at root for ad-hoc use):
- `_normalize_201_to_200.py` — pack rewriter (201→200 happy-path normalization)
- `_rewrite_blocked_reasons_plain.py` — report post-processor (BLOCKED reasons → plain English)
- `_rewrite_eval_reasons_plain.py` — report post-processor (FAIL evaluation_reasons → rich plain English)
- `_postman_inventory.py` — Postman parser
- `_write_summary_docx.py` — summary DOCX generator
- `_organize_dryrun.py` + `_organize_execute.py` — the organize scripts themselves
- `_postman_inventory.json`, `_postman_pack_match.json`, `_organize_plan.json` — script outputs

## Folder layout

| Folder | Holds | Count |
|---|---|---|
| `Kardit\reports\` | All historical Affiliate/Bank/Cards/Customer/Transactions/Batch test reports (.docx, .pdf, .yaml, .md), SRS docs (`MainSRS.pdf`, `karditSRS_text.txt`, `Software Requirement Specifications.txt`), older test data files (`*_TC.json`, `*_tc_data.json`, `admin_test_cases.*`), report generator scripts (`generate_*_report.py`, `enhance_report.py`, `single_shot.py`, `append_report*.py`, `upload_to_google_docs.py`), and Kardit-specific reference files (`Test Report YAML.docx`, `swagger.json`, `payload(s).txt`, `report_metadata.txt`, `reportformat.txt`, `Alfred_Testing_Prompt.md`, `restart claude.txt`, `skill.txt`, `full test runner command.txt`) | 149 |
| `Kardit\evidence\` | All `evidence_postman_affiliate_*` directories from past standalone runs (per-TC request/response JSON evidence) | 8 |
| `Personal\` | CV, transcripts, course registrations, school fees, exam clearances, scanned documents, anything matching name patterns `MY CV`, `LETTER OF REFERENCE`, `Onyema_Ifechukwu_*`, `2300994*`, `course reg*`, `clearance*`, `school fees*`, `Scanned Document*` | 15 |
| `Personal\Credentials\` | **Sensitive** — Google Cloud service account JSONs (`alfred-dev-agent-*.json`). Treat as secrets; do not check into VCS or share. | 2 |
| `Archive\Academic\<year>\` | All academic course materials grouped by year (2019, 2023, 2024, unknown). Includes lectures, past papers, assignments, course PPTXs/PDFs/DOCXs across course codes ACC, CIT, CSC, COS, TMC, MAT, MTH, GST, CST, CYB, STA, EDS, DTS, EOA, plus `[WEEK X]`/`[Week X]`-prefixed lecture series. | 128 (across all years) |
| `Images\` | jpg, jpeg, png, webp, gif, bmp, ico, svg | 19 |
| `Archives\` | zip, rar, 7z, tar, gz | 13 |
| `Installers\` | exe, msi, lnk, appx, appxbundle (Docker, Discord, Claude Setup, Grammarly, Node.js, etc.) | 20 |
| `Duplicates\` | All files matching duplicate-suffix patterns: ` (1)`, ` (2)`, `_compressed`, `_v2`, `_old`, `.bak`, `.bak.evalN` (NOT including the active test-pack `.bak` files at root which are referenced for rollback). User to manually review and prune. | 109 |
| `Misc\` | Genuinely ambiguous files (random PDFs, untitled `.docx`, gradient files, etc.) | 12 |
| `Misc\Code-and-Config\` | Non-Kardit code/config: apk, css, srt, ics, msix, rtf, htm, seb, grd | 12 |
| `Misc\Projects-and-Tools\` | Misc project/app dirs: `Telegram Desktop`, `Python 3.13`, `ai code`, `AI FOR OBOT`, `emotion_app`, `Free Pack`, `Blur`, `SNOW` | 7 |
| `Misc\Claude-Agent-Files\` | Claude Code agent identity/memory files placed in Downloads by other tooling: `AGENTS.md`, `IDENTITY.md`, `MEMORY.md`, `SOUL.md`, `USER.md`, `Admin.txt`. Do NOT confuse with the actual auto-memory at `~\.claude\projects\C--WINDOWS-system32\memory\MEMORY.md`. | 6 |
| `Trash\` | Office lock files (`~$*.pptx`), `desktop.ini`, `__pycache__`, `*.crdownload`, junk single-character txt files (`@.txt`, `{.txt`, `primaryContact{.txt`). Safe to delete entirely. | 11 |

## How to apply

When looking for a Kardit historical artifact (any test report from before 2026-05-01), check `Downloads\Kardit\reports\` first. When looking for evidence dirs (per-TC JSONs from a past standalone run), check `Downloads\Kardit\evidence\`. Anything currently being generated by the harness still lands in Downloads root or in fresh evidence dirs at root — those will need to be tidied periodically.

When the user asks about a personal document (CV, transcript, school fees, etc.), look in `Downloads\Personal\`.

When the user asks about an academic file by course code, search `Downloads\Archive\Academic\` recursively.

The `_organize_plan.json` at Downloads root is the full classified manifest from the 2026-05-01 reorg — useful for confirming where a specific file went without re-scanning the disk.

## Reorg artifacts (kept for traceability)

- `_organize_dryrun.py` — classifier with all the patterns/heuristics used
- `_organize_execute.py` — mover (idempotent, no overwrites)
- `_organize_plan.json` — final categorization (546 entries → 18 buckets)
