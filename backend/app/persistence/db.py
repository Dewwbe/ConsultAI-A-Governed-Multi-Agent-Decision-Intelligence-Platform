"""Persistence for engagements, approvals, audit trail, events, runtime snapshots and the human
decision dataset. SQLAlchemy Core, so the same code runs on SQLite (dev/tests) and PostgreSQL
(production): set DATABASE_URL to `sqlite:///./consultai.db` or `postgresql://user:pw@host/db`.

LangGraph's own checkpoint tables are managed by its saver (see checkpointer.py).
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from typing import Any

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

meta = sa.MetaData()

engagements = sa.Table(
    "engagements", meta,
    sa.Column("workflow_id", sa.String(64), primary_key=True),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("user_id", sa.String(200), nullable=False),
    sa.Column("business_problem", sa.Text, nullable=False),
    sa.Column("industry", sa.String(200), nullable=False, default=""),
    sa.Column("data_classification", sa.String(20), nullable=False),
    sa.Column("status", sa.String(30), nullable=False),
    sa.Column("halted_reason", sa.Text),
    sa.Column("error", sa.Text),
)
approvals = sa.Table(
    "approvals", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("workflow_id", sa.String(64), nullable=False, index=True),
    sa.Column("decided_at", sa.String(40), nullable=False),
    sa.Column("approver_id", sa.String(200), nullable=False),
    sa.Column("approver_name", sa.String(200), nullable=False),
    sa.Column("approver_roles", sa.Text, nullable=False),
    sa.Column("decision", sa.String(20), nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("changes", sa.Text, nullable=False),
    sa.Column("resulting_status", sa.String(30), nullable=False),
)
audit_log = sa.Table(
    "audit_log", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("ts", sa.String(40), nullable=False),
    sa.Column("workflow_id", sa.String(64), index=True),
    sa.Column("actor_id", sa.String(200), nullable=False),
    sa.Column("action", sa.String(60), nullable=False),
    sa.Column("outcome", sa.String(30), nullable=False),   # allowed | denied | conflict | invalid
    sa.Column("detail", sa.Text, nullable=False),
)
events = sa.Table(
    "events", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("workflow_id", sa.String(64), nullable=False, index=True),
    sa.Column("ts", sa.String(40), nullable=False),
    sa.Column("type", sa.String(40), nullable=False),
    sa.Column("data", sa.Text, nullable=False),
)
snapshots = sa.Table(
    "runtime_snapshots", meta,
    sa.Column("workflow_id", sa.String(64), primary_key=True),
    sa.Column("updated_at", sa.String(40), nullable=False),
    sa.Column("data", sa.Text, nullable=False),
)
decision_dataset = sa.Table(
    "decision_dataset", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("workflow_id", sa.String(64), nullable=False, index=True),
    sa.Column("recorded_at", sa.String(40), nullable=False),
    sa.Column("record", sa.Text, nullable=False),
)


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


class Database:
    def __init__(self, url: str):
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url or url in {"sqlite://", "sqlite:///"}:
                kwargs["poolclass"] = StaticPool  # one shared in-memory connection
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.url = url
        self.engine = sa.create_engine(url, **kwargs)
        self._lock = threading.RLock()  # SQLite is single-writer; harmless on Postgres
        meta.create_all(self.engine)

    # -- engagements --------------------------------------------------------------------------
    def add_engagement(self, workflow_id: str, *, user_id: str, business_problem: str, industry: str,
                       data_classification: str, status: str = "running") -> None:
        with self._lock, self.engine.begin() as c:
            c.execute(engagements.insert().values(
                workflow_id=workflow_id, created_at=now(), user_id=user_id,
                business_problem=business_problem, industry=industry,
                data_classification=data_classification, status=status))

    def set_status(self, workflow_id: str, status: str, *, halted_reason: str | None = None,
                   error: str | None = None) -> None:
        with self._lock, self.engine.begin() as c:
            c.execute(engagements.update().where(engagements.c.workflow_id == workflow_id).values(
                status=status, halted_reason=halted_reason, error=error))

    def get_engagement(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock, self.engine.connect() as c:
            row = c.execute(engagements.select().where(engagements.c.workflow_id == workflow_id)).first()
        return dict(row._mapping) if row else None

    def list_engagements(self, status: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        q = engagements.select()
        count = sa.select(sa.func.count()).select_from(engagements)
        if status:
            q, count = q.where(engagements.c.status == status), count.where(engagements.c.status == status)
        q = q.order_by(engagements.c.created_at.desc(), engagements.c.workflow_id).limit(limit).offset(offset)
        with self._lock, self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q)], c.execute(count).scalar_one()

    def mark_interrupted(self) -> int:
        """Runs that were `running` when the process died cannot continue: fail them visibly."""
        with self._lock, self.engine.begin() as c:
            res = c.execute(engagements.update().where(engagements.c.status == "running").values(
                status="failed", error="interrupted by a service restart"))
            return res.rowcount

    # -- snapshots ------------------------------------------------------------------------------
    def save_snapshot(self, workflow_id: str, data: dict[str, Any]) -> None:
        with self._lock, self.engine.begin() as c:
            c.execute(snapshots.delete().where(snapshots.c.workflow_id == workflow_id))
            c.execute(snapshots.insert().values(workflow_id=workflow_id, updated_at=now(), data=_dumps(data)))

    def load_snapshot(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock, self.engine.connect() as c:
            row = c.execute(snapshots.select().where(snapshots.c.workflow_id == workflow_id)).first()
        return json.loads(row.data) if row else None

    # -- events ---------------------------------------------------------------------------------
    def add_event(self, workflow_id: str, type_: str, data: dict[str, Any]) -> int:
        with self._lock, self.engine.begin() as c:
            res = c.execute(events.insert().values(workflow_id=workflow_id, ts=now(), type=type_,
                                                   data=_dumps(data)))
            return int(res.inserted_primary_key[0])

    def events_after(self, workflow_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self._lock, self.engine.connect() as c:
            rows = c.execute(events.select().where(
                (events.c.workflow_id == workflow_id) & (events.c.id > after)).order_by(events.c.id))
            return [{"id": r.id, "ts": r.ts, "type": r.type, "data": json.loads(r.data)} for r in rows]

    # -- approvals / audit ------------------------------------------------------------------------
    def add_approval(self, workflow_id: str, *, approver_id: str, approver_name: str, roles: list[str],
                     decision: str, reason: str, changes: dict[str, Any], resulting_status: str) -> None:
        with self._lock, self.engine.begin() as c:
            c.execute(approvals.insert().values(
                workflow_id=workflow_id, decided_at=now(), approver_id=approver_id,
                approver_name=approver_name, approver_roles=_dumps(roles), decision=decision,
                reason=reason, changes=_dumps(changes), resulting_status=resulting_status))

    def approvals_for(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._lock, self.engine.connect() as c:
            rows = c.execute(approvals.select().where(approvals.c.workflow_id == workflow_id)
                             .order_by(approvals.c.id))
            return [{"decided_at": r.decided_at, "approver_id": r.approver_id,
                     "approver_name": r.approver_name, "approver_roles": json.loads(r.approver_roles),
                     "decision": r.decision, "reason": r.reason, "changes": json.loads(r.changes),
                     "resulting_status": r.resulting_status} for r in rows]

    def add_audit(self, *, actor_id: str, action: str, outcome: str, workflow_id: str | None = None,
                  detail: dict[str, Any] | None = None) -> None:
        with self._lock, self.engine.begin() as c:
            c.execute(audit_log.insert().values(ts=now(), workflow_id=workflow_id, actor_id=actor_id,
                                                action=action, outcome=outcome, detail=_dumps(detail or {})))

    def audit_for(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        q = audit_log.select().order_by(audit_log.c.id)
        if workflow_id:
            q = q.where(audit_log.c.workflow_id == workflow_id)
        with self._lock, self.engine.connect() as c:
            return [{"ts": r.ts, "workflow_id": r.workflow_id, "actor_id": r.actor_id, "action": r.action,
                     "outcome": r.outcome, "detail": json.loads(r.detail)} for r in c.execute(q)]

    # -- evaluation dataset -----------------------------------------------------------------------
    def add_decision_record(self, workflow_id: str, record: dict[str, Any]) -> None:
        with self._lock, self.engine.begin() as c:
            c.execute(decision_dataset.insert().values(workflow_id=workflow_id, recorded_at=now(),
                                                       record=_dumps(record)))

    def decision_records(self) -> list[dict[str, Any]]:
        with self._lock, self.engine.connect() as c:
            return [{"workflow_id": r.workflow_id, "recorded_at": r.recorded_at, **json.loads(r.record)}
                    for r in c.execute(decision_dataset.select().order_by(decision_dataset.c.id))]
