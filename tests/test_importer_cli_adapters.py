from __future__ import annotations

from flask_app.importer import init_importer
from flask_app.importer.adapters.salesforce import SalesforceAdapterReadiness


def test_importer_adapters_list_reports_missing_dependencies(app, runner, monkeypatch):
    app.config.update(
        {
            "IMPORTER_ENABLED": True,
            "IMPORTER_ADAPTERS": ("csv", "salesforce"),
        }
    )
    def fake_check(*, require_auth_ping=False):
        return SalesforceAdapterReadiness(
            dependency_ok=False,
            dependency_errors=("simple-salesforce is not installed",),
            missing_env_vars=(),
            auth_status="skipped",
            notes=(),
        )

    monkeypatch.setattr(
        "flask_app.importer.adapters.salesforce.check_salesforce_adapter_readiness",
        lambda **kwargs: fake_check(),
    )

    init_importer(app)

    result = runner.invoke(args=["importer", "adapters", "list"])

    assert result.exit_code == 0, result.output
    assert "CSV Flat File (csv): ready" in result.output
    assert "Salesforce (Bulk API) (salesforce): missing-deps" in result.output
    assert "simple-salesforce is not installed" in result.output

