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


def test_transformer_boolean_default_with_none():
    """Test that boolean defaults are applied even when source value is None."""
    spec = MappingSpec(
        version=1,
        adapter="salesforce",
        object_name="Contact",
        fields=(
            MappingField(source="Id", target="external_id", required=True),
            MappingField(source="DoNotCall", target="contact_preferences.do_not_call", default=False),
            MappingField(source="HasOptedOutOfEmail", target="contact_preferences.do_not_email", default=False),
        ),
        transforms={},
        checksum="fake",
        path=None,  # type: ignore[arg-type]
    )
    transformer = SalesforceMappingTransformer(spec)
    
    # Test with None values (Salesforce returns None for unset booleans)
    result = transformer.transform({"Id": "001", "DoNotCall": None, "HasOptedOutOfEmail": None})
    assert result.canonical["contact_preferences"]["do_not_call"] is False
    assert result.canonical["contact_preferences"]["do_not_email"] is False
    assert result.errors == []
    
    # Test with empty string
    result2 = transformer.transform({"Id": "002", "DoNotCall": "", "HasOptedOutOfEmail": ""})
    assert result2.canonical["contact_preferences"]["do_not_call"] is False
    assert result2.canonical["contact_preferences"]["do_not_email"] is False


def test_transformer_boolean_normalization():
    """Test that string boolean values are normalized to actual booleans."""
    spec = MappingSpec(
        version=1,
        adapter="salesforce",
        object_name="Contact",
        fields=(
            MappingField(source="Id", target="external_id", required=True),
            MappingField(source="DoNotCall", target="contact_preferences.do_not_call", default=False),
        ),
        transforms={},
        checksum="fake",
        path=None,  # type: ignore[arg-type]
    )
    transformer = SalesforceMappingTransformer(spec)
    
    # Test with string "true"
    result = transformer.transform({"Id": "001", "DoNotCall": "true"})
    assert result.canonical["contact_preferences"]["do_not_call"] is True
    
    # Test with string "false"
    result2 = transformer.transform({"Id": "002", "DoNotCall": "false"})
    assert result2.canonical["contact_preferences"]["do_not_call"] is False
    
    # Test with actual boolean True
    result3 = transformer.transform({"Id": "003", "DoNotCall": True})
    assert result3.canonical["contact_preferences"]["do_not_call"] is True
    
    # Test with actual boolean False
    result4 = transformer.transform({"Id": "004", "DoNotCall": False})
    assert result4.canonical["contact_preferences"]["do_not_call"] is False


def test_transformer_contact_preferences_mapping():
    """Test that contact preferences are correctly mapped to nested structure."""
    spec = MappingSpec(
        version=1,
        adapter="salesforce",
        object_name="Contact",
        fields=(
            MappingField(source="Id", target="external_id", required=True),
            MappingField(source="DoNotCall", target="contact_preferences.do_not_call", default=False),
            MappingField(source="HasOptedOutOfEmail", target="contact_preferences.do_not_email", default=False),
            MappingField(source="npsp__Do_Not_Contact__c", target="contact_preferences.do_not_contact", default=False),
        ),
        transforms={},
        checksum="fake",
        path=None,  # type: ignore[arg-type]
    )
    transformer = SalesforceMappingTransformer(spec)
    
    result = transformer.transform({
        "Id": "001",
        "DoNotCall": True,
        "HasOptedOutOfEmail": False,
        "npsp__Do_Not_Contact__c": None,  # Should default to False
    })
    
    assert result.canonical["contact_preferences"]["do_not_call"] is True
    assert result.canonical["contact_preferences"]["do_not_email"] is False
    assert result.canonical["contact_preferences"]["do_not_contact"] is False
    assert result.errors == []
