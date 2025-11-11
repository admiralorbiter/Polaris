from __future__ import annotations

from flask_app.importer.mapping import (
    MappingField,
    MappingSpec,
    MappingTransform,
    SalesforceMappingTransformer,
)


def _make_spec():
    return MappingSpec(
        version=1,
        adapter="salesforce",
        object_name="Contact",
        fields=(
            MappingField(source="Id", target="external_id", required=True),
            MappingField(source="Email", target="email.primary"),
            MappingField(target="metadata.source_system", default="salesforce"),
        ),
        transforms={"normalize_phone": MappingTransform(name="normalize_phone")},
        checksum="fake",
        path=None,  # type: ignore[arg-type]
    )


def test_transformer_maps_fields():
    transformer = SalesforceMappingTransformer(_make_spec())
    result = transformer.transform({"Id": "001", "Email": "ada@example.org", "Extra": "value"})
    assert result.canonical["external_id"] == "001"
    assert result.canonical["email"]["primary"] == "ada@example.org"
    assert result.canonical["metadata"]["source_system"] == "salesforce"
    assert result.unmapped_fields == {"Extra": "value"}
    assert result.errors == []


def test_transformer_required_field_missing():
    transformer = SalesforceMappingTransformer(_make_spec())
    result = transformer.transform({"Email": "ada@example.org"})
    assert "Required field 'external_id'" in result.errors[0]

