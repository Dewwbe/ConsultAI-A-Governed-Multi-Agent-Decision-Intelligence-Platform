"""Telemetry exporters: OpenTelemetry (OTLP / Azure Monitor) and MLflow.

Everything here is optional and off by default. Each exporter is built only when its setting is present,
its client library is imported lazily (install the `observability` extra), and a failure to export is
logged and swallowed: telemetry must never fail an engagement.
"""
from __future__ import annotations

import logging
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

log = logging.getLogger(__name__)


def build_span_exporter(settings: Any) -> SpanExporter | None:
    """OTLP wins if both are set. Returns None when no destination is configured."""
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
        if not endpoint.endswith("/v1/traces"):
            endpoint += "/v1/traces"
        return OTLPSpanExporter(endpoint=endpoint)
    if settings.applicationinsights_connection_string:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        return AzureMonitorTraceExporter(connection_string=settings.applicationinsights_connection_string)
    return None


def build_tracer_provider(settings: Any, exporter: SpanExporter | None = None) -> TracerProvider | None:
    """A TracerProvider that ships spans to the configured destination, or None if there is none.
    Pass `exporter` to inject one (tests). Injected exporters export synchronously; real ones in batches."""
    chosen = exporter or build_span_exporter(settings)
    if chosen is None:
        return None
    provider = TracerProvider(resource=Resource.create({
        "service.name": "consultai", "deployment.environment": settings.environment}))
    provider.add_span_processor(SimpleSpanProcessor(chosen) if exporter is not None else BatchSpanProcessor(chosen))
    if exporter is None:
        # The Azure exporter reads the service name from the *global* provider; without this every span arrives in
        # Application Insights as "unknown_service" and it logs a warning on each export.
        from opentelemetry import trace
        trace.set_tracer_provider(provider)
    return provider
