"""OpenTelemetry-based tracing with an in-process span store for the AI Control Center.

Attribute names follow the OpenTelemetry GenAI semantic conventions where they exist
(gen_ai.agent.name, gen_ai.tool.name, gen_ai.usage.*), plus consultai.* extensions.

Every span is kept in the in-process `TraceStore` (what the Control Center reads) and, when a tracer
is configured, mirrored to OpenTelemetry (Azure Monitor / any OTLP collector). The exported copy is
different on purpose: it is written when the span ends, so it carries the final token counts and cost,
it has secrets and personal identifiers scrubbed, and it leaves out client payloads (tool arguments and
results, SQL, retrieved text) unless exporting them was explicitly enabled.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer

from app.observability.redaction import PAYLOAD_KEYS
from app.security.pii import scrub, scrub_text


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


def otel_value(value: Any) -> Any:
    """OpenTelemetry attributes must be primitives or homogeneous lists of them; JSON-encode the rest."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)) and value and all(isinstance(v, str) for v in value):
        return list(value)
    return json.dumps(value, default=str)


class TraceStore:
    """Per-workflow span collection, mirrored to OpenTelemetry when a tracer is supplied."""

    def __init__(self, workflow_id: str, listener: Callable[[str, SpanRecord], None] | None = None,
                 tracer: Tracer | None = None, export_payloads: bool = False):
        self.trace_id = f"tr_{uuid.uuid4().hex[:12]}"
        self.workflow_id = workflow_id
        self.spans: list[SpanRecord] = []
        self._stack: list[str] = []
        self.listener = listener  # called with ("started" | "finished", span) for live progress
        self._tracer = tracer or trace.get_tracer("consultai")
        self._export_payloads = export_payloads

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

    def _export(self, otel_span: Any, rec: SpanRecord) -> None:
        """Copy the finished span's attributes to OpenTelemetry (scrubbed, payload-free by default)."""
        keep = {k: v for k, v in rec.attributes.items() if self._export_payloads or k not in PAYLOAD_KEYS}
        keep["consultai.span.kind"] = rec.kind
        keep["consultai.latency_ms"] = round(rec.latency_ms, 2)
        keep["consultai.status"] = rec.status
        for key, value in scrub(keep).value.items():
            exported = otel_value(value)
            if exported is not None:
                otel_span.set_attribute(key, exported)
        if rec.status == "error":
            message = scrub_text(rec.error or "")[:300]
            otel_span.set_attribute("consultai.error", message)
            otel_span.set_status(Status(StatusCode.ERROR, message))

    @contextmanager
    def span(self, name: str, kind: str, **attrs: Any) -> Iterator[SpanRecord]:
        rec = SpanRecord(f"sp_{uuid.uuid4().hex[:8]}", self._stack[-1] if self._stack else None,
                         name, kind, {"consultai.workflow_id": self.workflow_id, **attrs})
        self.spans.append(rec)
        self._stack.append(rec.span_id)
        self._notify("started", rec)
        t0 = time.perf_counter()
        # OTel would record the raw exception text (and stack) itself; we export a scrubbed error instead
        with self._tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False) as otel_span:
            try:
                yield rec
            except Exception as exc:
                rec.status, rec.error = "error", repr(exc)
                raise
            finally:
                rec.latency_ms = (time.perf_counter() - t0) * 1000
                self._stack.pop()
                self._export(otel_span, rec)  # final attributes: tokens and cost exist only now
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
