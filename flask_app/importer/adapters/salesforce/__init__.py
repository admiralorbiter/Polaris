"""Salesforce adapter readiness and dependency validation utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Mapping, Sequence, Tuple

from flask_app.importer.metrics import record_salesforce_auth_attempt

REQUIRED_ENV_VARS: Tuple[str, ...] = ("SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN")
OPTIONAL_ENV_VARS: Tuple[str, ...] = ("SF_DOMAIN", "SF_CLIENT_ID", "SF_CLIENT_SECRET", "SF_ORG_ID")


class SalesforceAdapterError(RuntimeError):
    """Base error for Salesforce adapter readiness issues."""


class SalesforceAdapterDependencyError(SalesforceAdapterError):
    """Raised when optional Salesforce dependencies are missing."""


class SalesforceAdapterConfigError(SalesforceAdapterError):
    """Raised when required configuration or environment variables are missing."""


class SalesforceAdapterAuthError(SalesforceAdapterError):
    """Raised when credentials fail authentication."""


@dataclass(frozen=True)
class SalesforceAdapterReadiness:
    dependency_ok: bool
    dependency_errors: Tuple[str, ...]
    missing_env_vars: Tuple[str, ...]
    auth_status: Literal["skipped", "ok", "failed"]
    auth_error: str | None = None
    notes: Tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if not self.dependency_ok:
            return "missing-deps"
        if self.missing_env_vars:
            return "missing-env"
        if self.auth_status == "failed":
            return "auth-error"
        return "ready"

    def messages(self) -> Tuple[str, ...]:
        messages: list[str] = []
        if not self.dependency_ok:
            if self.dependency_errors:
                messages.extend(self.dependency_errors)
            else:
                messages.append(
                    'Salesforce adapter dependencies are missing. Install via pip install ".[importer-salesforce]".'
                )
        if self.missing_env_vars:
            messages.append(f"Missing required Salesforce env vars: {', '.join(self.missing_env_vars)}")
        if self.auth_status == "failed" and self.auth_error:
            messages.append(self.auth_error)
        if self.notes:
            messages.extend(self.notes)
        return tuple(messages)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "dependency_ok": self.dependency_ok,
            "dependency_errors": list(self.dependency_errors),
            "missing_env_vars": list(self.missing_env_vars),
            "auth_status": self.auth_status,
            "messages": list(self.messages()),
        }
        if self.auth_error:
            payload["auth_error"] = self.auth_error
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


def _collect_dependency_errors() -> tuple[list[str], dict[str, object]]:
    dependency_errors: list[str] = []
    modules: dict[str, object] = {}

    try:
        simple_salesforce = import_module("simple_salesforce")
        modules["Salesforce"] = getattr(simple_salesforce, "Salesforce", None)
        modules["SalesforceAuthenticationFailed"] = getattr(simple_salesforce, "SalesforceAuthenticationFailed", None)
        if modules["Salesforce"] is None or modules["SalesforceAuthenticationFailed"] is None:
            dependency_errors.append(
                "simple-salesforce import succeeded but required classes are missing; ensure version >= 1.12.5."
            )
    except ModuleNotFoundError:
        dependency_errors.append(
            'simple-salesforce is not installed. Install via pip install ".[importer-salesforce]".'
        )
    except ImportError as exc:  # pragma: no cover - defensive
        dependency_errors.append(f"simple-salesforce import failed: {exc}")

    try:
        modules["salesforce_bulk"] = import_module("salesforce_bulk")
    except ModuleNotFoundError:
        dependency_errors.append('salesforce-bulk is not installed. Install via pip install ".[importer-salesforce]".')
    except ImportError as exc:  # pragma: no cover - defensive
        dependency_errors.append(f"salesforce-bulk import failed: {exc}")

    return dependency_errors, modules


def check_salesforce_adapter_readiness(
    env: Mapping[str, str] | None = None,
    *,
    require_auth_ping: bool = False,
) -> SalesforceAdapterReadiness:
    """
    Perform a non-raising readiness check for the Salesforce adapter.

    Args:
        env: Optional mapping of environment variables to inspect. Defaults to os.environ.
        require_auth_ping: Whether to attempt a credentialed login to validate credentials.

    Returns:
        SalesforceAdapterReadiness describing dependency and configuration status.
    """

    env = env or os.environ
    dependency_errors, modules = _collect_dependency_errors()
    missing_env = tuple(sorted(var for var in REQUIRED_ENV_VARS if not env.get(var)))

    auth_status: Literal["skipped", "ok", "failed"] = "skipped"
    auth_error: str | None = None
    if require_auth_ping and not dependency_errors and not missing_env:
        salesforce_cls = modules.get("Salesforce")
        auth_exception_cls = modules.get("SalesforceAuthenticationFailed")
        if salesforce_cls is None or auth_exception_cls is None:
            dependency_errors.append(
                "simple-salesforce does not expose Salesforce/SalesforceAuthenticationFailed; unable to auth."
            )
        else:
            domain = env.get("SF_DOMAIN", "login")
            kwargs: dict[str, str] = {
                "username": env["SF_USERNAME"],
                "password": env["SF_PASSWORD"],
                "security_token": env["SF_SECURITY_TOKEN"],
                "domain": domain,
            }
            organization_id = env.get("SF_ORG_ID")
            if organization_id:
                kwargs["organizationId"] = organization_id
            try:
                salesforce_cls(**kwargs)
                auth_status = "ok"
            except auth_exception_cls as exc:  # type: ignore[misc]
                auth_status = "failed"
                auth_error = f"Salesforce authentication failed: {exc}"
            except Exception as exc:  # pragma: no cover - defensive
                auth_status = "failed"
                auth_error = f"Unexpected Salesforce auth failure: {exc}"

    optional_missing = tuple(sorted(var for var in OPTIONAL_ENV_VARS if not env.get(var)))
    notes: Tuple[str, ...] = ()
    if optional_missing:
        notes = (
            f"Optional env vars not set: {', '.join(optional_missing)}. "
            "Set these if your org requires them."
        ),

    return SalesforceAdapterReadiness(
        dependency_ok=not dependency_errors,
        dependency_errors=tuple(dependency_errors),
        missing_env_vars=missing_env,
        auth_status=auth_status,
        auth_error=auth_error,
        notes=notes,
    )


def ensure_salesforce_adapter_ready(
    env: Mapping[str, str] | None = None,
    *,
    require_auth_ping: bool = False,
) -> SalesforceAdapterReadiness:
    """
    Validate Salesforce adapter readiness, raising actionable errors when not ready.
    """

    readiness = check_salesforce_adapter_readiness(env=env, require_auth_ping=require_auth_ping)
    if require_auth_ping:
        if readiness.auth_status == "ok":
            record_salesforce_auth_attempt("success")
        elif readiness.auth_status == "failed":
            record_salesforce_auth_attempt("failure")
    if not readiness.dependency_ok:
        raise SalesforceAdapterDependencyError("; ".join(readiness.dependency_errors))
    if readiness.missing_env_vars:
        raise SalesforceAdapterConfigError(
            "Salesforce adapter configured but missing required env vars: "
            + ", ".join(readiness.missing_env_vars)
            + ". Set these or disable the adapter."
        )
    if readiness.auth_status == "failed":
        raise SalesforceAdapterAuthError(readiness.auth_error or "Salesforce authentication failed.")
    return readiness


__all__ = [
    "REQUIRED_ENV_VARS",
    "OPTIONAL_ENV_VARS",
    "SalesforceAdapterError",
    "SalesforceAdapterDependencyError",
    "SalesforceAdapterConfigError",
    "SalesforceAdapterAuthError",
    "SalesforceAdapterReadiness",
    "check_salesforce_adapter_readiness",
    "ensure_salesforce_adapter_ready",
]

