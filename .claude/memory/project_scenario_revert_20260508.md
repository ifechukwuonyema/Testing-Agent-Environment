---
name: Scenario Revert Session 2026-05-08
description: Restored +557 TCs across all 8 Kardit packs after over-aggressive swagger-driven deletions; established that scenarios are team guidance, not just runner inputs
type: project
originSessionId: 25e67922-21a5-49d1-b72c-4a36ef9151b1
---
User concluded that the scenario-deletion cycles run on 2026-05-07 and 2026-05-08 morning had been driven by faulty reasoning ("swagger silent → test invalid → delete"). Scenarios document team expectations and should remain in packs even when the runner can't auto-validate them. Full revert applied.

## Mechanism
- Script: `Downloads\_revert_packs_2026_05_08.py` — union-merge across every `.bak*` checkpoint, deduped by `tc_id`, **scoped to the endpoints currently in each pack** (removed endpoints stay removed unless restored explicitly), newest content wins on TCID conflict, scenario-name collision treated as a rename and skipped.
- Each canonical pack backed up as `<pack>.bak-2026-05-08-pre-revert`.
- Considered restoring `GET /api/v2/banks/{bankId}/dashboard` (API-BNK-01) — declared in MainSwagger.txt — but user directed against it (dashboard endpoints are out of scope for bank-pack API testing). Restoration was applied then immediately rolled back from `.bak-2026-05-08-pre-dashboard-v2-restore`. Bank pack final = 10 endpoints, 378 TCs.
- Removed-endpoints exhibit script: `Downloads\_removed_endpoints_exhibit_v2.py` (cross-pack successor lookup).
- Reports: `Downloads\Kardit\reports\revert_packs_report_2026-05-08.json`, `Downloads\Kardit\reports\removed_endpoints_exhibit_2026-05-08.json`.

## Per-service tally (TCs)

| Service | Pre-revert | Post-revert |
|---|---|---|
| affiliate | 434 | 511 (+197 revert, −120 mega-dedup) |
| bank | 308 | 384 (+70 revert, +6 BNK-06 fill) |
| cards | 751 | 879 |
| customer | 107 | 120 |
| transactions | 391 | 438 |
| batch | 158 | 188 (+19 revert, +11 fill) |
| admin | 126 | 155 |
| notifications | 135 | 186 (+14 revert, +37 NOT-GET/CRT fill) |
| **TOTAL** | **2,410** | **2,861** (+451 net) |

## Followup edits same day

- **Mega-endpoint dedup**: AFF-07/10/11 had stacked template+specific TC sets after the union-merge (80/76/75 TCs). User locked TC band as 30 floor / 40 ceiling. Wholesale-dropped the "template" prefix per endpoint via `Downloads\_dedup_mega_eps.py --apply`. Result: AFF-07→40, AFF-10→36, AFF-11→35.
- **Under-30 fills**: 5 endpoints below the new 30 floor were filled to ≥33.
- **Final compliance**: 0 endpoints under 30, 0 endpoints over 40.
