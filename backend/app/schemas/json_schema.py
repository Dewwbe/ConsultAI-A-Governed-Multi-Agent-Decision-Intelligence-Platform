"""Helpers for building JSON schemas that satisfy Azure OpenAI strict structured outputs:
every property required, no additional properties, only the supported keyword subset."""
from __future__ import annotations

from typing import Any

STR: dict[str, Any] = {"type": "string"}
NUM: dict[str, Any] = {"type": "number"}
INT: dict[str, Any] = {"type": "integer"}


def obj(**props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


_STRICT_KEYS = {"type", "properties", "required", "additionalProperties", "items", "enum",
                "description", "anyOf"}


def is_strict_ready(schema: Any) -> bool:
    """True when `schema` can be sent with `strict: true` (otherwise fall back to JSON mode)."""
    if isinstance(schema, list):
        return all(is_strict_ready(s) for s in schema)
    if not isinstance(schema, dict):
        return True
    if schema.get("type") == "object":
        props = schema.get("properties")
        if props is None or schema.get("additionalProperties") is not False:
            return False
        if set(schema.get("required", [])) != set(props):
            return False
    for key, value in schema.items():
        if key == "properties":
            if not all(is_strict_ready(v) for v in value.values()):
                return False
        elif key in ("items", "anyOf"):
            if not is_strict_ready(value):
                return False
        elif key not in _STRICT_KEYS:
            return False
    return True
