"""
Minimal .env loader for the Kardit test harness.

Reads <repo_root>/.env and sets values as environment variables.
Process-level env vars always win — .env values are never applied if the
variable is already set, so CI/container secrets take precedence.

Supports:
  KEY=value              plain value
  KEY="value"            double-quoted (strips surrounding quotes)
  KEY='value'            single-quoted (no escape processing)
  MULTILINE_KEY="line1\\nline2"   \\n escape sequences are expanded to newlines
  # comment              ignored
  (blank lines)          ignored
"""
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1].replace("\\n", "\n").replace('\\"', '"')
        elif len(val) >= 2 and val[0] == val[-1] == "'":
            val = val[1:-1]
        os.environ[key] = val


def require(*names: str) -> None:
    """Exit with a clear message if any required env var is missing."""
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        print(f"\nERROR: Required environment variables not set: {', '.join(missing)}")
        print("  1. Copy .env.example to .env")
        print("  2. Fill in the missing values (ask the project owner for credentials)")
        print("  3. Re-run\n")
        sys.exit(1)
