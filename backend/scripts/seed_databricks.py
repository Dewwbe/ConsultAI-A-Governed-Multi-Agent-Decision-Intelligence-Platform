"""Create the four demo tables in Databricks and fill them with the synthetic retail dataset.

    python backend/scripts/seed_databricks.py            # creates schemas and tables, then loads data
    python backend/scripts/seed_databricks.py --drop     # drops the demo tables first (to start clean)

Uses DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN and DATABRICKS_CATALOG from the environment or .env, and
needs permission to create schemas and tables in that catalog. The data is the same synthetic dataset the offline
demo uses, so results match. Table and column comments are written too, because the data agent's semantic layer is
built from them. Nothing outside the four demo tables is touched.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.config import get_settings
from app.data.databricks_source import DatabricksDataSource
from app.data.sqlite_source import CATALOG, SqliteDataSource

TYPES = {"finance.revenue": {"revenue": "DOUBLE"}, "finance.costs": {"cost": "DOUBLE"}, "ops.kpis": {"value": "DOUBLE"}}


def literal(value: object) -> str:
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drop", action="store_true", help="drop the demo tables first")
    args = ap.parse_args()

    s = get_settings()
    if not (s.databricks_host and s.databricks_http_path):
        print("missing settings: DATABRICKS_HOST, DATABRICKS_HTTP_PATH", file=sys.stderr)
        return 2
    db = DatabricksDataSource(host=s.databricks_host, http_path=s.databricks_http_path, token=s.databricks_token,
                              catalog=s.databricks_catalog)
    available = db.catalogs()
    if s.databricks_catalog not in available:
        print(f"catalog '{s.databricks_catalog}' not found; set DATABRICKS_CATALOG to one of: {', '.join(available)}",
              file=sys.stderr)
        return 2
    cat = s.databricks_catalog
    source = SqliteDataSource()

    with db.conn.cursor() as cur:
        for schema in sorted({t.split(".")[0] for t in CATALOG}):
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {cat}.{schema}")
        for table, meta in CATALOG.items():
            full = f"{cat}.{table}"
            if args.drop:
                cur.execute(f"DROP TABLE IF EXISTS {full}")
            rows = source.query(f"SELECT * FROM {table}")
            columns = list(rows[0])
            types = TYPES.get(table, {})
            column_sql = ", ".join(f"{c} {types.get(c, 'STRING')} COMMENT {literal(meta['columns'].get(c, ''))}"
                                   for c in columns)
            cur.execute(f"CREATE TABLE IF NOT EXISTS {full} ({column_sql}) COMMENT {literal(meta['description'])}")
            cur.execute(f"SELECT COUNT(*) FROM {full}")
            if cur.fetchone()[0]:
                print(f"{full}: already has data, left as it is (use --drop to reload)")
                continue
            for i in range(0, len(rows), 100):
                values = ", ".join("(" + ", ".join(literal(r[c]) for c in columns) + ")" for r in rows[i:i + 100])
                cur.execute(f"INSERT INTO {full} VALUES {values}")
            try:  # tags need an extra privilege; the semantic layer falls back to 'internal' without them
                cur.execute(f"ALTER TABLE {full} SET TAGS ('sensitivity' = {literal(meta['sensitivity'])})")
            except Exception as exc:  # noqa: BLE001
                print(f"  note: could not tag {full} ({type(exc).__name__}); sensitivity will read as 'internal'")
            print(f"{full}: loaded {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
