"""Databricks SQL warehouse `DataSource`.

Same two methods as `SqliteDataSource`: `query(sql)` and `describe(tables)`. The semantic layer is built from Unity
Catalog metadata (`information_schema` columns and the table/column comments). Defence in depth: the agent's SQL has
already passed `validate_readonly_sql`, the service principal should have only SELECT on the allowed tables, and
this class additionally refuses anything that is not a single SELECT/WITH statement and caps the rows it returns.
"""
from __future__ import annotations

import re
from typing import Any

MAX_ROWS = 1000
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){1,2}$")
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class DatabricksDataSource:
    def __init__(self, *, host: str = "", http_path: str = "", token: str = "", catalog: str = "main",
                 connection: Any = None, max_rows: int = MAX_ROWS):
        self._conn, self._cfg, self.catalog, self.max_rows = connection, (host, http_path, token), catalog, max_rows

    @property
    def conn(self) -> Any:
        if self._conn is None:
            from databricks import sql
            host, http_path, token = self._cfg
            if not (host and http_path):
                raise RuntimeError("DATABRICKS_HOST and DATABRICKS_HTTP_PATH must be set")
            kwargs: dict[str, Any] = {"server_hostname": host, "http_path": http_path, "catalog": self.catalog}
            if token:
                kwargs["access_token"] = token
            else:  # no token: Microsoft Entra ID, the same identity the rest of the platform uses
                from azure.identity import DefaultAzureCredential
                kwargs["access_token"] = DefaultAzureCredential().get_token(
                    "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default").token  # the Azure Databricks resource
            self._conn = sql.connect(**kwargs)
        return self._conn

    def _run(self, statement: str, params: list[Any] | None = None, limit: int | None = None) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(statement, params) if params else cur.execute(statement)
            cols = [d[0] for d in cur.description or []]
            rows = cur.fetchmany(limit) if limit else cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def query(self, sql: str) -> list[dict]:
        stripped = sql.strip().rstrip(";")
        if not _READ_ONLY.match(stripped) or ";" in stripped:
            raise PermissionError("only a single SELECT statement may run against the warehouse")
        return self._run(stripped, limit=self.max_rows)

    def catalogs(self) -> list[str]:
        return [next(iter(r.values())) for r in self._run("SHOW CATALOGS")]

    def describe(self, tables: list[str]) -> dict[str, dict[str, Any]]:
        """Semantic layer for `tables` (names like `schema.table`): description, owner, columns with types and comments."""
        out: dict[str, dict[str, Any]] = {}
        for t in tables:
            if not _NAME.match(t):
                continue
            schema, name = t.split(".")[-2:]
            cols = self._run(
                f"SELECT column_name, data_type, comment FROM {self.catalog}.information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position", [schema, name])
            if not cols:
                continue
            info = self._run(
                f"SELECT comment, table_owner FROM {self.catalog}.information_schema.tables "
                "WHERE table_schema = ? AND table_name = ?", [schema, name])
            tags = self._run(
                f"SELECT tag_value FROM {self.catalog}.information_schema.table_tags "
                "WHERE schema_name = ? AND table_name = ? AND tag_name = 'sensitivity'", [schema, name])
            head = info[0] if info else {}
            out[t] = {"description": head.get("comment") or "",
                      "columns": {c["column_name"]: f"{c.get('comment') or ''} [{c['data_type']}]".strip() for c in cols},
                      "owner": head.get("table_owner") or "unknown",
                      "sensitivity": tags[0]["tag_value"] if tags else "internal"}
        return out
