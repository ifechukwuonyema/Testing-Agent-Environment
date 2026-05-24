import json
from pathlib import Path
from typing import Any, Dict


SESSION_IDS_PATH = Path(r"C:\Users\Onyema Ifechukwu\Downloads\kardit_session_ids.json")


class SessionStore:
    def __init__(self, path: Path = SESSION_IDS_PATH):
        self.path = path

    def load(self) -> Dict[str, Any]:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def merge_into(self, ids: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in self.load().items():
            if v and k not in ids:
                ids[k] = v
        return ids

    def save(self, data: Dict[str, Any]) -> None:
        try:
            existing = self.load()
            existing.update({k: v for k, v in data.items() if v})
            self.path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except Exception:
            pass

    def reset(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass
