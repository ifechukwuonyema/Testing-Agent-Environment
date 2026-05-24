import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jsonschema
from jsonschema import Draft202012Validator


@dataclass
class SchemaFinding:
    valid: bool
    errors: List[str]
    schema_used: Optional[str]


class SchemaValidator:
    def __init__(self, swagger_path: Path):
        self.swagger_path = swagger_path
        self.spec: Optional[Dict[str, Any]] = None
        self._path_patterns: List[Tuple[re.Pattern, str]] = []
        self._resolved_cache: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.swagger_path.exists():
            return
        try:
            self.spec = json.loads(self.swagger_path.read_text(encoding="utf-8"))
        except Exception:
            self.spec = None
            return
        for raw_path in (self.spec.get("paths") or {}).keys():
            pattern = re.sub(r"\{[^/}]+\}", r"[^/]+", raw_path)
            self._path_patterns.append((re.compile(f"^{pattern}$"), raw_path))

    def is_active(self) -> bool:
        return self.spec is not None

    def _match_path(self, request_path: str) -> Optional[str]:
        cleaned = request_path.split("?", 1)[0]
        for pat, raw in self._path_patterns:
            if pat.match(cleaned):
                return raw
        return None

    def _response_schema(self, method: str, path: str, status_code: int) -> Optional[Dict[str, Any]]:
        if not self.is_active():
            return None
        raw_path = self._match_path(path)
        if not raw_path:
            return None
        op = ((self.spec.get("paths") or {}).get(raw_path) or {}).get(method.lower())
        if not op:
            return None
        responses = op.get("responses") or {}
        resp = responses.get(str(status_code)) or responses.get("default")
        if not resp:
            return None
        content = (resp.get("content") or {}).get("application/json") or {}
        return content.get("schema")

    def _resolve_ref(self, ref: str, stack: set) -> Any:
        if not ref.startswith("#/"):
            return {}
        if ref in self._resolved_cache:
            return self._resolved_cache[ref]
        if ref in stack:
            return {}
        stack = stack | {ref}
        node: Any = self.spec
        for part in ref.lstrip("#/").split("/"):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return {}
            if node is None:
                return {}
        resolved = self._inline(node, stack)
        self._resolved_cache[ref] = resolved
        return resolved

    def _inline(self, schema: Any, stack: set) -> Any:
        if isinstance(schema, dict):
            if "$ref" in schema and isinstance(schema["$ref"], str):
                return self._resolve_ref(schema["$ref"], stack)
            inlined = {k: self._inline(v, stack) for k, v in schema.items()}
            # OpenAPI 3.0 -> JSON Schema 2020-12 translation: `nullable: true`
            # is not understood by Draft202012Validator. Convert into a type
            # union so null is accepted at this node.
            if inlined.pop("nullable", False) is True:
                t = inlined.get("type")
                if isinstance(t, str):
                    inlined["type"] = [t, "null"]
                elif isinstance(t, list) and "null" not in t:
                    inlined["type"] = list(t) + ["null"]
                elif t is None:
                    # No primitive type — wrap as anyOf to allow null
                    return {"anyOf": [inlined, {"type": "null"}]}
            return inlined
        if isinstance(schema, list):
            return [self._inline(v, stack) for v in schema]
        return schema

    def validate_response(self, method: str, path: str, status_code: int, body: Any) -> Optional[SchemaFinding]:
        schema = self._response_schema(method, path, status_code)
        if schema is None:
            return None
        if body is None or isinstance(body, str):
            return SchemaFinding(valid=False, errors=["response body is not JSON"], schema_used=None)
        try:
            inlined = self._inline(schema, set())
            validator = Draft202012Validator(inlined)
            errors = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
            if not errors:
                return SchemaFinding(valid=True, errors=[], schema_used=None)
            messages = []
            for err in errors[:8]:
                loc = "$" + "".join(f".{p}" if isinstance(p, str) else f"[{p}]" for p in err.absolute_path)
                messages.append(f"{loc}: {err.message}")
            return SchemaFinding(valid=False, errors=messages, schema_used=None)
        except jsonschema.exceptions.SchemaError as ex:
            return SchemaFinding(valid=False, errors=[f"swagger schema error: {ex.message}"], schema_used=None)
        except Exception as ex:
            return SchemaFinding(valid=False, errors=[f"validator error: {type(ex).__name__}: {ex}"], schema_used=None)
