from __future__ import annotations

from flask_app.importer import init_importer


def test_importer_adapters_list_reports_missing_dependencies(app, runner):
    app.config.update(
        {
            "IMPORTER_ENABLED": True,
            "IMPORTER_ADAPTERS": ("csv", "salesforce"),
        }
    )
    init_importer(app)

    result = runner.invoke(args=["importer", "adapters", "list"])

    assert result.exit_code == 0, result.output
    assert "CSV Flat File (csv): ready" in result.output
    assert "Salesforce (Bulk API) (salesforce): missing-deps" in result.output
    assert 'pip install ".[importer-salesforce]"' in result.output

