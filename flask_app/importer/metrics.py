"""Prometheus metrics helpers for the importer."""

from __future__ import annotations

from typing import Literal

try:
    from prometheus_client import Counter, Gauge

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - metrics optional in some deployments
    Counter = Gauge = None  # type: ignore
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
else:  # pragma: no cover - fallbacks when prometheus_client missing
    _salesforce_enabled_gauge = None
    _salesforce_auth_attempts = None


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

