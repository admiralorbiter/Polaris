"""Importer adapter interfaces and concrete implementations."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Optional

from .csv_volunteers import (
    CSVAdapterError,
    CSVHeaderError,
    CSVRowError,
    VolunteerCSVAdapter,
    VolunteerCSVRow,
    VolunteerCSVStatistics,
)

OPTIONAL_IMPORT_ERRORS: Dict[str, Exception] = {}


def _load_optional_adapter(module_name: str):
    """
    Import an optional adapter module, memoising import errors for diagnostics.

    Returns:
        Imported module when available, otherwise ``None``.

    Side effects:
        Stores the latest ImportError/ModuleNotFoundError in OPTIONAL_IMPORT_ERRORS.
    """

    try:
        module = import_module(f".{module_name}", __name__)
    except ModuleNotFoundError as exc:
        OPTIONAL_IMPORT_ERRORS[module_name] = exc
        return None
    except ImportError as exc:
        OPTIONAL_IMPORT_ERRORS[module_name] = exc
        return None

    OPTIONAL_IMPORT_ERRORS.pop(module_name, None)
    return module


def ensure_optional_adapter(module_name: str):
    """
    Attempt to load an optional adapter, returning the module or raising the stored error.
    """
    module = _load_optional_adapter(module_name)
    if module is None:
        error = OPTIONAL_IMPORT_ERRORS.get(module_name)
        if error is None:
            raise RuntimeError(f"Optional adapter '{module_name}' could not be loaded for an unknown reason.")
        raise error
    return module


def get_optional_adapter_error(module_name: str) -> Optional[Exception]:
    """
    Return the last import error captured for an optional adapter, if any.
    """
    return OPTIONAL_IMPORT_ERRORS.get(module_name)


__all__ = [
    "CSVAdapterError",
    "CSVHeaderError",
    "CSVRowError",
    "VolunteerCSVAdapter",
    "VolunteerCSVRow",
    "VolunteerCSVStatistics",
    "OPTIONAL_IMPORT_ERRORS",
    "ensure_optional_adapter",
    "get_optional_adapter_error",
]
