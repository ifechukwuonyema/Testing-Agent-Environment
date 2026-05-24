---
name: feedback_pre_script_post_only
description: Pre-script runs only on POST requests — never apply pre-script logic to GET endpoints
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5a397891-3858-46d1-a7e6-4750ffdda215
---

Only POST requests use the pre-script. GET endpoints do not.

**Why:** Some TCs on GET endpoints are currently FAILing because the pre-script is firing on them when it shouldn't. The pre-script does things (body construction, signing, token injection) that are only valid for POST — applying them to GETs corrupts the request and produces false FAILs that look like backend defects but are runner bugs.
**How to apply:** When investigating unexpected FAILs on GET endpoints, check first whether the pre-script is firing on that TC. Gate all pre-script logic on `method == "POST"`. Any FAIL on a GET endpoint caused by pre-script execution is a runner bug, not a backend defect — fix the runner, not the pack.
