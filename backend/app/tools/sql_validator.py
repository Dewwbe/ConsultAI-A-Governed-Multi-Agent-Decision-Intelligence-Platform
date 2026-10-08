"""Read-only SQL validation run before any query reaches Databricks."""
from __future__ import annotations

import re

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|merge|copy|call|exec)\b", re.IGNORECASE)
_TABLE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)


class SQLValidationError(ValueError):
    pass


def validate_readonly_sql(sql: str, allowed_tables: list[str]) -> list[str]:
    """Return referenced tables, or raise SQLValidationError."""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise SQLValidationError("multiple statements not allowed")
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise SQLValidationError("only SELECT/WITH queries are allowed")
    if _FORBIDDEN.search(stripped):
        raise SQLValidationError("write/DDL keyword detected")
    tables = _TABLE.findall(stripped)
    cte_names = set(re.findall(r"\b([A-Za-z_]\w*)\s+as\s*\(", stripped, re.IGNORECASE))
    refs = [t for t in tables if t not in cte_names]
    denied = [t for t in refs if t not in allowed_tables]
    if denied:
        raise SQLValidationError(f"tables not permitted: {denied}")
    return refs
