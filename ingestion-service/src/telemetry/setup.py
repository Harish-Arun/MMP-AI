from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram

if TYPE_CHECKING:
    from src.config.settings import Settings

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics (module-level singletons)
# ---------------------------------------------------------------------------

files_detected_total = Counter(
    "files_detected_total",
    "Total files detected on the SFTP server",
    labelnames=["status"],
)

upload_success_total = Counter(
    "upload_success_total",
    "Total files successfully uploaded to S3",
)

upload_failure_total = Counter(
    "upload_failure_total",
    "Total files that failed to upload to S3",
)

sftp_reconnect_total = Counter(
    "sftp_reconnect_total",
    "Total SFTP reconnection attempts",
)

sftp_poll_duration_seconds = Histogram(
    "sftp_poll_duration_seconds",
    "Duration of each SFTP poll cycle in seconds",
)

# ---------------------------------------------------------------------------
# OTel tracer/meter (set after init_telemetry())
# ---------------------------------------------------------------------------

_tracer: trace.Tracer | None = None


def init_telemetry(settings: "Settings") -> None:
    """Initialise OTel TracerProvider and MeterProvider; configure Prometheus counters."""
    global _tracer

    resource = Resource(attributes={SERVICE_NAME: "ingestion-service"})

    # Tracer provider
    tracer_provider = TracerProvider(resource=resource)
    if settings.otel_exporter_otlp_endpoint:
        otlp_span_exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer("ingestion-service")

    # Meter provider
    if settings.otel_exporter_otlp_endpoint:
        otlp_metric_exporter = OTLPMetricExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        reader = PeriodicExportingMetricReader(otlp_metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    else:
        meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(meter_provider)

    _logger.info("telemetry_initialised", otlp=settings.otel_exporter_otlp_endpoint)


def get_tracer() -> trace.Tracer:
    """Return the OTel tracer (available after init_telemetry())."""
    if _tracer is None:
        return trace.get_tracer("ingestion-service")
    return _tracer
