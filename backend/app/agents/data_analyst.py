from __future__ import annotations

from typing import Any, Protocol

from app.data.sqlite_source import SqliteDataSource
from app.prompts import get_prompt
from app.schemas.json_schema import STR, obj
from app.tools.sql_validator import SQLValidationError, validate_readonly_sql

from .base import BaseAgent

SQL_SCHEMA = obj(sql=STR, rationale=STR)


class DataSource(Protocol):
    def query(self, sql: str) -> list[dict]: ...
    def describe(self, tables: list[str]) -> dict[str, dict]: ...


class DataAnalystAgent(BaseAgent):
    """Deterministic pipeline: semantic layer -> SQL -> validate -> permission -> run."""
    name = "data_agent"

    def __init__(self, ctx, source: DataSource | None = None):
        super().__init__(ctx)
        self.source = source or SqliteDataSource()

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        allowed = self.ctx.policy.agent_spec(self.name).get("allowed_tables", [])
        spec = view.get("engagement_spec", {})
        # semantic layer: only tables this agent may read are shown to the model
        layer = self.source.describe(allowed)
        sql = self.ctx.llm.structured(
            agent=self.name, task="simple_sql", prompt=get_prompt("sql_generation"), schema=SQL_SCHEMA,
            variables={"decision_question": spec.get("decision_question", ""),
                       "required_data": spec.get("required_data", []), "table_context": layer},
            context={"stub_output": {
                "sql": "SELECT region, SUM(revenue) AS revenue FROM finance.revenue GROUP BY region",
                "rationale": "Revenue by region from the finance semantic layer"}},
            data_classification=view.get("data_classification", "confidential")).content["sql"]
        try:
            tables = validate_readonly_sql(sql, allowed)
        except SQLValidationError as exc:
            self.ctx.log["failures"].append({"type": "sql_validation", "error": str(exc)})
            return {"analysis_results": [], "table_context": {}, "datasets": []}
        for t in tables:  # permission check per table, through the guardian
            d = self.ctx.guardian.review_tool_call(self.name, "run_sql_readonly", {}, resource=t)
            self.ctx.log["guardian_decisions"].append(d.to_dict())
            if d.action != "ALLOW":
                return {"analysis_results": [], "table_context": {}, "datasets": []}
        self.ctx.budget.record(tool_calls=1)
        with self.ctx.trace.span("tool:run_sql_readonly", "tool", **{
                "gen_ai.tool.name": "run_sql_readonly", "consultai.sql": sql}):
            try:
                rows = self.source.query(sql)
            except Exception as exc:  # noqa: BLE001  bad column, timeout...: report, never crash the workflow
                self.ctx.log["failures"].append({"type": "sql_execution", "error": str(exc)[:300]})
                return {"analysis_results": [], "table_context": {}, "datasets": []}
        return {"analysis_results": [{"query": sql, "rows": rows}],
                "table_context": self.source.describe(tables), "datasets": tables}
