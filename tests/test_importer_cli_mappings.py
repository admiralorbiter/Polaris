from __future__ import annotations

from flask_app.importer import init_importer


def test_importer_mappings_show_outputs_yaml(app, runner, tmp_path, monkeypatch):
    mapping_yaml = tmp_path / "sf_mapping.yaml"
    mapping_yaml.write_text(
        """
version: 1
adapter: salesforce
object: Contact
fields:
  - source: Id
    target: external_id
    required: true
  - target: metadata.source_system
    default: salesforce
""",
        encoding="utf-8",
    )

    monkeypatch.setitem(app.config, "IMPORTER_ENABLED", True)
    monkeypatch.setitem(app.config, "IMPORTER_ADAPTERS", ("csv", "salesforce"))
    monkeypatch.setitem(app.config, "IMPORTER_SALESFORCE_MAPPING_PATH", str(mapping_yaml))
    init_importer(app)

    result = runner.invoke(args=["importer", "mappings", "show"])

    assert result.exit_code == 0, result.output
    assert "Adapter: salesforce" in result.output
    assert "version: 1" in result.output.lower()
    assert "external_id" in result.output

