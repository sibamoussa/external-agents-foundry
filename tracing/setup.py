"""
tracing/setup.py
----------------
OpenTelemetry provider initialisation.

Call `init_tracing()` once at application startup.
Returns (tracer, provider) so the caller can force-flush on exit.
"""

from __future__ import annotations

import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter


def init_tracing(
    service_name: str = "weather-agent-test",
    service_version: str = "1.0.0",
    service_namespace: str = "external-weather-platform",
    connection_string: str | None = None,
) -> tuple[trace.Tracer, TracerProvider]:
    """
    Configure a TracerProvider that exports to Azure Monitor / Foundry.

    Parameters
    ----------
    service_name        : Shown as the operation name in Foundry Tracing.
    service_version     : Arbitrary semver string.
    service_namespace   : Becomes Cloud Role Name in Application Insights.
    connection_string   : App Insights connection string. Falls back to the
                          APPLICATIONINSIGHTS_CONNECTION_STRING env var.

    Returns
    -------
    (tracer, provider)  : Use the tracer for spans; call provider.force_flush()
                          before process exit.
    """
    conn_str = connection_string or os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn_str:
        raise EnvironmentError(
            "Missing APPLICATIONINSIGHTS_CONNECTION_STRING.\n"
            "Set it in your .env file or pass it explicitly to init_tracing().\n"
            "Find it in: Azure Portal > Application Insights > Overview > Connection String"
        )

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "service.namespace": service_namespace,
        }
    )

    provider = TracerProvider(resource=resource)
    exporter = AzureMonitorTraceExporter(connection_string=conn_str)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    return trace.get_tracer(__name__), provider
