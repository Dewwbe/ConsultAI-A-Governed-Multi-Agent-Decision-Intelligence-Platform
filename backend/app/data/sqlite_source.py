"""Offline stand-in for Databricks (Delta tables + Unity Catalog + SQL warehouse).

`SqliteDataSource` serves a synthetic retail dataset through the same `DataSource` interface
the Databricks implementation will use: `query(sql)` for execution and `describe(tables)` for
the semantic layer, which is built from catalog metadata (column names/types come from the
database, descriptions/owner/sensitivity from the catalog comments, like Unity Catalog).
All data is synthetic placeholder data.
"""
from __future__ import annotations

import random
import sqlite3
from typing import Any

MAX_ROWS = 1000
REGIONS = ["home", "north", "south", "east"]

# Stand-in for Unity Catalog comments/tags.
CATALOG: dict[str, dict[str, Any]] = {
    "finance.revenue": {"description": "Recognised monthly revenue by region", "owner": "finance",
                        "sensitivity": "internal", "columns": {
                            "date": "Month of recognition (first day)", "region": "Sales region",
                            "revenue": "Total recognised revenue, USD"}},
    "finance.costs": {"description": "Operating costs by region", "owner": "finance",
                      "sensitivity": "internal", "columns": {
                          "date": "Month the cost was incurred", "region": "Region",
                          "cost": "Operating cost, USD"}},
    "sales.customers": {"description": "Customer accounts (no personal data)", "owner": "sales",
                        "sensitivity": "internal", "columns": {
                            "customer_id": "Anonymised customer key", "region": "Home region",
                            "segment": "Customer segment", "signup_date": "Account creation date"}},
    "ops.kpis": {"description": "Operational KPIs by month and region", "owner": "operations",
                 "sensitivity": "internal", "columns": {
                     "date": "Month", "region": "Region", "kpi": "KPI name", "value": "KPI value"}},
}

_DDL = {
    "finance.revenue": "CREATE TABLE finance.revenue (date TEXT, region TEXT, revenue REAL)",
    "finance.costs": "CREATE TABLE finance.costs (date TEXT, region TEXT, cost REAL)",
    "sales.customers": ("CREATE TABLE sales.customers (customer_id TEXT, region TEXT, segment TEXT, "
                        "signup_date TEXT)"),
    "ops.kpis": "CREATE TABLE ops.kpis (date TEXT, region TEXT, kpi TEXT, value REAL)",
}


def _months(n: int = 24) -> list[str]:
    return [f"{2024 + i // 12}-{i % 12 + 1:02d}-01" for i in range(n)]


class SqliteDataSource:
    def __init__(self, seed: int = 42):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        for schema in ("finance", "sales", "ops"):
            self.conn.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        for ddl in _DDL.values():
            self.conn.execute(ddl)
        self._seed(random.Random(seed))
        self.conn.commit()
        self.conn.execute("PRAGMA query_only = ON")  # defence in depth behind the SQL validator

    def _seed(self, rng: random.Random) -> None:
        for r_i, region in enumerate(REGIONS):
            base = 900_000 + r_i * 150_000
            for m_i, month in enumerate(_months()):
                rev = base * (1 + 0.012 * m_i) * rng.uniform(0.92, 1.08)
                self.conn.execute("INSERT INTO finance.revenue VALUES (?,?,?)", (month, region, round(rev, 2)))
                self.conn.execute("INSERT INTO finance.costs VALUES (?,?,?)",
                                  (month, region, round(rev * rng.uniform(0.66, 0.74), 2)))
                self.conn.execute("INSERT INTO ops.kpis VALUES (?,?,?,?)",
                                  (month, region, "nps", round(rng.uniform(30, 60), 1)))
            for c in range(25):
                self.conn.execute("INSERT INTO sales.customers VALUES (?,?,?,?)", (
                    f"c_{region}_{c}", region, rng.choice(["retail", "wholesale", "online"]),
                    f"2023-{rng.randint(1, 12):02d}-01"))

    def query(self, sql: str) -> list[dict]:
        cur = self.conn.execute(sql)
        cols = [d[0] for d in cur.description or []]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchmany(MAX_ROWS)]

    def describe(self, tables: list[str]) -> dict[str, dict[str, Any]]:
        """Semantic layer: live column names/types + catalog descriptions, only for `tables`."""
        out: dict[str, dict[str, Any]] = {}
        for t in tables:
            meta = CATALOG.get(t)
            if meta is None:
                continue
            schema, name = t.split(".")
            cols = {row[1]: f"{meta['columns'].get(row[1], '')} [{row[2]}]".strip()
                    for row in self.conn.execute(f"PRAGMA {schema}.table_info({name})")}
            out[t] = {"description": meta["description"], "columns": cols,
                      "owner": meta["owner"], "sensitivity": meta["sensitivity"]}
        return out
