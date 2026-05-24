---
name: feedback_no_auth_sentinel
description: __NO_AUTH__ sentinel pattern for testing auth-rejection scenarios through execute() without restructuring the runner
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5a397891-3858-46d1-a7e6-4750ffdda215
---

Use `override_headers["Authorization"] = "__NO_AUTH__"` to test unauthenticated / missing-token scenarios through an auth-injecting `execute()` function — do NOT block these scenarios as untestable.

**Why:** `execute()` auto-injects Bearer tokens on every request. Without the sentinel, auth-rejection scenarios either receive a valid token (false PASS) or must be BLOCKED. The sentinel lets the TC flow through the normal path while stripping auth before wire transmission.

**How to apply:**
- In `execute()`, add a guard before the normal token injection:
  ```python
  h = dict(headers or {})
  if h.get("Authorization") == "__NO_AUTH__":
      del h["Authorization"]   # send with no Authorization header
  elif "Authorization" not in h and TOKEN_MANAGER.get_token():
      h["Authorization"] = f"Bearer {TOKEN_MANAGER.get_token()}"
  ```
- In the TC loop, map scenario name tokens to bad credentials:
  ```python
  _FUNC_AUTH_CRED = {
      "unauthenticated_rejected": "__NO_AUTH__",
      "missing_token_rejected":   "__NO_AUTH__",
      "invalid_token_rejected":   "Bearer garbage_invalid_token_abc123",
      "wrong_audience_rejected":  "__BANK_TOKEN__",  # inject real bank-scoped token
  }
  ```
- `__BANK_TOKEN__` → resolve at runtime to `f"Bearer {TOKEN_MANAGER.get_bank()}"`.
- ECDSA signing in `execute()` still fires (body bytes signed) — only the Bearer layer is under test.
- Only `unsupported_accept_header_handled` remains BLOCKED (execute() forces Accept:application/json — truly untestable through this runner).
