---
name: Manual Test Confirmation Triggers Pack Deletion
description: When user says a scenario validates correctly on manual testing, treat the TC as a false FAIL and delete it from the pack — not a backend defect
type: feedback
originSessionId: f1d2538a-d992-4d2c-b706-84c5fe821fa8
---
When the user says "this validates correctly on manual testing" for a FAIL scenario, delete the TC from the pack immediately. Do not file a backend ask or argue.

**Why:** The runner surfaced TC-API-LIM-01-012 (`product_currency_mismatch_rejected`) as a FAIL (200 instead of 400/422). User manually verified the backend does reject the mismatch correctly. The runner either wasn't applying the mutation correctly or was testing against the wrong card state. Either way, the TC is not producing reliable signal.

**How to apply:** User confirmation of manual correctness = runner false FAIL = pack delete. No further investigation needed unless the user asks to dig into why the runner failed it.
