from __future__ import annotations

from types import SimpleNamespace

import pytest

from flask_app.importer.adapters import salesforce
from flask_app.importer.adapters.salesforce import (
    SalesforceAdapterAuthError,
    SalesforceAdapterConfigError,
    check_salesforce_adapter_readiness,
    ensure_salesforce_adapter_ready,
)


def _make_env(**overrides):
    env = {
        "SF_USERNAME": "alice@example.org",
        "SF_PASSWORD": "super-secret",
        "SF_SECURITY_TOKEN": "TOKEN123",
    }
    env.update(overrides)
    return env


def test_check_salesforce_readiness_reports_missing_dependencies(monkeypatch):
    def fake_import(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(salesforce, "import_module", fake_import)

    readiness = check_salesforce_adapter_readiness(env=_make_env())
    assert readiness.dependency_ok is False
    assert readiness.status == "missing-deps"
    assert any("pip install" in message for message in readiness.messages())


def test_ensure_salesforce_adapter_ready_requires_env(monkeypatch):
    def fake_import(name):
        if name == "simple_salesforce":
            return SimpleNamespace(
                Salesforce=lambda **_kwargs: None,
                SalesforceAuthenticationFailed=RuntimeError,
            )
        if name == "salesforce_bulk":
            return SimpleNamespace()
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(salesforce, "import_module", fake_import)

    env = _make_env(SF_PASSWORD="")
    with pytest.raises(SalesforceAdapterConfigError) as exc:
        ensure_salesforce_adapter_ready(env=env)
    assert "missing required env vars" in str(exc.value)


def test_ensure_salesforce_adapter_ready_raises_on_auth_failure(monkeypatch):
    class FakeAuthError(Exception):
        pass

    def fake_import(name):
        if name == "simple_salesforce":
            return SimpleNamespace(
                Salesforce=lambda **_kwargs: (_ for _ in ()).throw(FakeAuthError("invalid credentials")),
                SalesforceAuthenticationFailed=FakeAuthError,
            )
        if name == "salesforce_bulk":
            return SimpleNamespace()
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(salesforce, "import_module", fake_import)

    with pytest.raises(SalesforceAdapterAuthError) as exc:
        ensure_salesforce_adapter_ready(env=_make_env(), require_auth_ping=True)
    assert "authentication failed" in str(exc.value).lower()

