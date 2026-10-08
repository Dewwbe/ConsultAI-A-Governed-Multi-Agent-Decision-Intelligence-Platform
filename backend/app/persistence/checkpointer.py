"""LangGraph checkpointer matching DATABASE_URL, so paused workflows survive restarts.

SQLite for dev/tests, PostgreSQL in production. Both savers store the graph state that
`interrupt()` pauses on; the service restores the non-serialisable runtime from a snapshot.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver


def make_checkpointer(url: str) -> Any:
    if url.startswith("sqlite"):
        path = url.split("sqlite:///", 1)[-1] if "sqlite:///" in url else ":memory:"
        # a separate connection (and file, if any) for checkpoints: the saver manages its own tables
        conn = sqlite3.connect(path or ":memory:", check_same_thread=False)
        return SqliteSaver(conn)
    if url.startswith(("postgresql://", "postgres://")):
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection
        from psycopg.rows import dict_row

        conn = Connection.connect(url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    return MemorySaver()
