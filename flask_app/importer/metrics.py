"""Prometheus metrics helpers for the importer."""

from __future__ import annotations

from typing import Literal

try:
    from prometheus_client import Counter, Gauge, Histogram

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - metrics optional in some deployments
    Counter = Gauge = Histogram = None  # type: ignore
    _PROMETHEUS_AVAILABLE = False


if _PROMETHEUS_AVAILABLE:
    _salesforce_enabled_gauge = Gauge(
        "importer_salesforce_adapter_enabled_total",
        "Whether the Salesforce importer adapter is enabled (1) or disabled (0).",
    )
    _salesforce_auth_attempts = Counter(
        "importer_salesforce_auth_attempts_total",
        "Salesforce adapter authentication attempts by outcome.",
        ["outcome"],
    )
    _salesforce_batch_counter = Counter(
        "importer_salesforce_batches_total",
        "Number of Salesforce batches processed by status.",
        ["status"],
    )
    _salesforce_batch_duration = Histogram(
        "importer_salesforce_batch_duration_seconds",
        "Duration of Salesforce batch processing in seconds.",
        buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
    )
    _salesforce_unmapped_counter = Counter(
        "importer_salesforce_mapping_unmapped_total",
        "Unmapped Salesforce fields encountered during mapping.",
        ["field"],
    )
else:  # pragma: no cover - fallbacks when prometheus_client missing
    _salesforce_enabled_gauge = None
    _salesforce_auth_attempts = None
    _salesforce_batch_counter = None
    _salesforce_batch_duration = None
    _salesforce_unmapped_counter = None


def record_salesforce_adapter_status(enabled: bool) -> None:
    """Set the Salesforce adapter enabled gauge."""

    if _salesforce_enabled_gauge is None:
        return
    _salesforce_enabled_gauge.set(1 if enabled else 0)


def record_salesforce_auth_attempt(outcome: Literal["success", "failure"]) -> None:
    """Increment the Salesforce adapter authentication counter."""

    if _salesforce_auth_attempts is None:
        return
    _salesforce_auth_attempts.labels(outcome=outcome).inc()


def record_salesforce_batch(
    *,
    status: Literal["success", "failure"],
    duration_seconds: float,
    record_count: int,
) -> None:
    """Capture metrics for a Salesforce batch ingestion."""

    _ = record_count  # Placeholder for future per-record metrics
    if _salesforce_batch_counter is not None:
        _salesforce_batch_counter.labels(status=status).inc()
    if _salesforce_batch_duration is not None:
        _salesforce_batch_duration.observe(duration_seconds)


def record_salesforce_unmapped(field: str, count: int) -> None:
    """Increment unmapped-field counter."""

    if _salesforce_unmapped_counter is None:
        return
    _salesforce_unmapped_counter.labels(field=field).inc(count)

