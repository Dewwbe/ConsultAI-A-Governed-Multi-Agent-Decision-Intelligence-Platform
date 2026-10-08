"""OpenTelemetry-based tracing with an in-process span store for the AI Control Center.

Attribute names follow the OpenTelemetry GenAI semantic conventions where they exist
(gen_ai.agent.name, gen_ai.tool.name, gen_ai.usage.*), plus consultai.* extensions.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace

_tracer = trace.get_tracer("consultai")


@dataclass
class SpanRecord:
    span_id: str
    parent_id: str | None
    name: str
    kind: str  # workflow | agent | llm | tool | retrieval | guardian | evaluator | approval
    attributes: dict[str, Any] = field(default_factory=dict)
    start: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    status: str = "ok"
    error: str | None = None


class TraceStore:
    """Per-workflow span collection; swap for OTLP/MLflow export in Phase 5."""

    def __init__(self, workflow_id: str, listener: Callable[[str, SpanRecord], None] | None = None):
        self.trace_id = f"tr_{uuid.uuid4().hex[:12]}"
        self.workflow_id = workflow_id
        self.spans: list[SpanRecord] = []
        self._stack: list[str] = []
        self.listener = listener  # called with ("started" | "finished", span) for live progress

    def _notify(self, phase: str, rec: SpanRecord) -> None:
        if self.listener:
            try:
                self.listener(phase, rec)
            except Exception:  # noqa: BLE001, S110  telemetry must never break the workflow
                pass

    def restore(self, trace_id: str, spans: list[dict[str, Any]]) -> None:
        """Reload a persisted trace (after a restart) so later spans append to the same record."""
        self.trace_id = trace_id
        self.spans = [SpanRecord(**s) for s in spans]

    @contextmanager
    def span(self, name: str, kind: str, **attrs: Any) -> Iterator[SpanRecord]:
        rec = SpanRecord(f"sp_{uuid.uuid4().hex[:8]}", self._stack[-1] if self._stack else None,
                         name, kind, {"consultai.workflow_id": self.workflow_id, **attrs})
        self.spans.append(rec)
        self._stack.append(rec.span_id)
        self._notify("started", rec)
        t0 = time.perf_counter()
        with _tracer.start_as_current_span(name) as otel_span:
            for k, v in rec.attributes.items():
                otel_span.set_attribute(k, str(v) if isinstance(v, (dict, list)) else v)
            try:
                yield rec
            except Exception as exc:
                rec.status, rec.error = "error", repr(exc)
                raise
            finally:
                rec.latency_ms = (time.perf_counter() - t0) * 1000
                self._stack.pop()
                self._notify("finished", rec)

    def summary(self) -> dict[str, Any]:
        llm = [s for s in self.spans if s.kind == "llm"]
        tools = [s for s in self.spans if s.kind == "tool"]
        return {
            "trace_id": self.trace_id,
            "workflow_id": self.workflow_id,
            "span_count": len(self.spans),
            "input_tokens": sum(s.attributes.get("gen_ai.usage.input_tokens", 0) for s in llm),
            "output_tokens": sum(s.attributes.get("gen_ai.usage.output_tokens", 0) for s in llm),
            "cost_usd": round(sum(s.attributes.get("consultai.cost_usd", 0.0) for s in self.spans), 6),
            "tool_calls": len(tools),
            "tool_errors": sum(1 for s in tools if s.status == "error"),
            "spans": [s.__dict__ for s in self.spans],
        }
