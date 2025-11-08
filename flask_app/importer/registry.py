"""
Lightweight adapter registry scaffolding.

Adapters register metadata here so configuration validation can occur without
loading optional provider dependencies.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class AdapterDescriptor:
    """Metadata describing an importer adapter."""

    name: str
    title: str
    optional_dependencies: Tuple[str, ...] = ()
    summary: str | None = None


def get_adapter_registry() -> Mapping[str, AdapterDescriptor]:
    """
    Return the registry of supported adapters.

    The registry intentionally contains placeholder adapters that future work
    will flesh out; keeping it here ensures configuration validation can happen
    before those adapters are implemented.
    """
    return OrderedDict(
        (
            (
                "csv",
                AdapterDescriptor(
                    name="csv",
                    title="CSV Flat File",
                    optional_dependencies=(),
                    summary="Load volunteer data from CSV uploads.",
                ),
            ),
            (
                "salesforce",
                AdapterDescriptor(
                    name="salesforce",
                    title="Salesforce (Bulk API)",
                    optional_dependencies=("simple-salesforce",),
                    summary="Pull volunteer data from Salesforce.",
                ),
            ),
            (
                "google_sheets",
                AdapterDescriptor(
                    name="google_sheets",
                    title="Google Sheets",
                    optional_dependencies=("gspread",),
                    summary="Fetch data from Google Sheets worksheets.",
                ),
            ),
        )
    )


def resolve_adapters(
    configured: Sequence[str],
    registry: Mapping[str, AdapterDescriptor] | None = None,
) -> Iterable[AdapterDescriptor]:
    """
    Map configured adapter names to registry descriptors, raising on unknowns.
    """
    registry = registry or get_adapter_registry()
    unknown = sorted({adapter for adapter in configured if adapter not in registry})
    if unknown:
        raise ValueError(
            "Unknown importer adapters configured: "
            + ", ".join(unknown)
            + ". Update configuration or register these adapters first."
        )
    return tuple(registry[adapter] for adapter in configured)

