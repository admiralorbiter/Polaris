from __future__ import annotations

import pathlib

import pytest

from flask_app.importer.mapping import MappingLoadError, MappingSpec, get_active_salesforce_mapping, load_mapping


def test_load_mapping_success(tmp_path):
    mapping_yaml = tmp_path / "mapping.yaml"
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
transforms:
  parse_date:
    description: Parse date strings
""",
        encoding="utf-8",
    )

    spec = load_mapping(mapping_yaml)
    assert isinstance(spec, MappingSpec)
    assert spec.adapter == "salesforce"
    assert spec.fields[0].source == "Id"
    assert spec.fields[1].default == "salesforce"
    assert "parse_date" in spec.transforms


def test_load_mapping_requires_defaults_or_source(tmp_path):
    mapping_yaml = tmp_path / "mapping-invalid.yaml"
    mapping_yaml.write_text(
        """
version: 1
adapter: salesforce
fields:
  - target: metadata.source_system
""",
        encoding="utf-8",
    )

    with pytest.raises(MappingLoadError):
        load_mapping(mapping_yaml)


def test_get_active_salesforce_mapping(app, monkeypatch, tmp_path):
    mapping_yaml = tmp_path / "mapping.yaml"
    mapping_yaml.write_text(
        """
version: 2
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

    monkeypatch.setitem(app.config, "IMPORTER_SALESFORCE_MAPPING_PATH", str(mapping_yaml))
    with app.app_context():
        spec = get_active_salesforce_mapping()
        assert spec.version == 2
        assert spec.adapter == "salesforce"
        # cached lookup
        spec_cached = get_active_salesforce_mapping()
        assert spec_cached is spec


def test_get_active_salesforce_mapping_cache_invalidation(app, monkeypatch, tmp_path):
    """Test that mapping cache is invalidated when file modification time changes."""
    import time
    
    mapping_yaml = tmp_path / "mapping.yaml"
    mapping_yaml.write_text(
        """
version: 1
adapter: salesforce
object: Contact
fields:
  - source: Id
    target: external_id
    required: true
""",
        encoding="utf-8",
    )

    monkeypatch.setitem(app.config, "IMPORTER_SALESFORCE_MAPPING_PATH", str(mapping_yaml))
    with app.app_context():
        spec1 = get_active_salesforce_mapping()
        assert spec1.version == 1
        
        # Wait a moment to ensure different mtime
        time.sleep(0.1)
        
        # Update the file
        mapping_yaml.write_text(
            """
version: 2
adapter: salesforce
object: Contact
fields:
  - source: Id
    target: external_id
    required: true
""",
            encoding="utf-8",
        )
        
        # Should reload and get new version
        spec2 = get_active_salesforce_mapping()
        assert spec2.version == 2
        assert spec2 is not spec1  # Should be a new instance
