from __future__ import annotations

from flask_app.importer.mapping import MappingField, MappingSpec, MappingTransform, SalesforceMappingTransformer


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

    result = transformer.transform(
        {
            "Id": "001",
            "DoNotCall": True,
            "HasOptedOutOfEmail": False,
            "npsp__Do_Not_Contact__c": None,  # Should default to False
        }
    )

    assert result.canonical["contact_preferences"]["do_not_call"] is True
    assert result.canonical["contact_preferences"]["do_not_email"] is False
    assert result.canonical["contact_preferences"]["do_not_contact"] is False
    assert result.errors == []


def test_split_semicolon_transform():
    """Test that split_semicolon splits semicolon-separated values into arrays."""
    spec = MappingSpec(
        version=1,
        adapter="salesforce",
        object_name="Contact",
        fields=(
            MappingField(source="Id", target="external_id", required=True),
            MappingField(source="Volunteer_Skills__c", target="skills.volunteer_skills", transform="split_semicolon"),
            MappingField(
                source="Volunteer_Interests__c", target="interests.volunteer_interests", transform="split_semicolon"
            ),
        ),
        transforms={"split_semicolon": MappingTransform(name="split_semicolon")},
        checksum="fake",
        path=None,  # type: ignore[arg-type]
    )
    transformer = SalesforceMappingTransformer(spec)

    # Test with semicolon-separated values
    result = transformer.transform(
        {
            "Id": "001",
            "Volunteer_Skills__c": "Teaching;Tutoring;Mentoring",
            "Volunteer_Interests__c": "Education;Technology",
        }
    )
    assert result.canonical["skills"]["volunteer_skills"] == ["Teaching", "Tutoring", "Mentoring"]
    assert result.canonical["interests"]["volunteer_interests"] == ["Education", "Technology"]
    assert result.errors == []

    # Test with empty string
    result2 = transformer.transform(
        {
            "Id": "002",
            "Volunteer_Skills__c": "",
            "Volunteer_Interests__c": "",
        }
    )
    assert result2.canonical["skills"]["volunteer_skills"] == []
    assert result2.canonical["interests"]["volunteer_interests"] == []

    # Test with None
    result3 = transformer.transform(
        {
            "Id": "003",
            "Volunteer_Skills__c": None,
            "Volunteer_Interests__c": None,
        }
    )
    assert result3.canonical["skills"]["volunteer_skills"] == []
    assert result3.canonical["interests"]["volunteer_interests"] == []

    # Test with single value (no semicolon)
    result4 = transformer.transform(
        {
            "Id": "004",
            "Volunteer_Skills__c": "Teaching",
        }
    )
    assert result4.canonical["skills"]["volunteer_skills"] == ["Teaching"]

    # Test with whitespace handling
    result5 = transformer.transform(
        {
            "Id": "005",
            "Volunteer_Skills__c": "Teaching ; Tutoring ; Mentoring",
        }
    )
    assert result5.canonical["skills"]["volunteer_skills"] == ["Teaching", "Tutoring", "Mentoring"]


def test_nested_field_mappings():
    """Test that nested fields are correctly mapped (skills, interests, engagement, demographics, address)."""
    spec = MappingSpec(
        version=1,
        adapter="salesforce",
        object_name="Contact",
        fields=(
            MappingField(source="Id", target="external_id", required=True),
            MappingField(source="Volunteer_Skills__c", target="skills.volunteer_skills", transform="split_semicolon"),
            MappingField(source="Volunteer_Skills_Text__c", target="skills.volunteer_skills_text"),
            MappingField(
                source="Volunteer_Interests__c", target="interests.volunteer_interests", transform="split_semicolon"
            ),
            MappingField(
                source="First_Volunteer_Date__c", target="engagement.first_volunteer_date", transform="parse_date"
            ),
            MappingField(
                source="Number_of_Attended_Volunteer_Sessions__c", target="engagement.attended_sessions_count"
            ),
            MappingField(
                source="Last_Email_Message__c", target="engagement.last_email_message_at", transform="parse_datetime"
            ),
            MappingField(source="Racial_Ethnic_Background__c", target="demographics.racial_ethnic_background"),
            MappingField(source="Age_Group__c", target="demographics.age_group"),
            MappingField(source="Highest_Level_of_Educational__c", target="demographics.highest_education_level"),
            MappingField(source="MailingStreet", target="address.mailing.street"),
            MappingField(source="MailingCity", target="address.mailing.city"),
            MappingField(source="MailingState", target="address.mailing.state"),
            MappingField(source="MailingPostalCode", target="address.mailing.postal_code"),
            MappingField(source="MailingCountry", target="address.mailing.country"),
            MappingField(source="npe01__Home_Street__c", target="address.home.street"),
            MappingField(source="npe01__Home_City__c", target="address.home.city"),
            MappingField(source="Volunteer_Recruitment_Notes__c", target="notes.recruitment_notes"),
            MappingField(source="Description", target="notes.description"),
        ),
        transforms={
            "split_semicolon": MappingTransform(name="split_semicolon"),
            "parse_date": MappingTransform(name="parse_date"),
            "parse_datetime": MappingTransform(name="parse_datetime"),
        },
        checksum="fake",
        path=None,  # type: ignore[arg-type]
    )
    transformer = SalesforceMappingTransformer(spec)

    result = transformer.transform(
        {
            "Id": "001",
            "Volunteer_Skills__c": "Teaching;Tutoring",
            "Volunteer_Skills_Text__c": "Additional skills text",
            "Volunteer_Interests__c": "Education",
            "First_Volunteer_Date__c": "2024-01-15",
            "Number_of_Attended_Volunteer_Sessions__c": "5",
            "Last_Email_Message__c": "2024-01-20T10:30:00.000Z",
            "Racial_Ethnic_Background__c": "Asian",
            "Age_Group__c": "Adult",
            "Highest_Level_of_Educational__c": "Bachelors",
            "MailingStreet": "123 Main St",
            "MailingCity": "Springfield",
            "MailingState": "IL",
            "MailingPostalCode": "62701",
            "MailingCountry": "US",
            "npe01__Home_Street__c": "456 Oak Ave",
            "npe01__Home_City__c": "Springfield",
            "Volunteer_Recruitment_Notes__c": "Recruited at event",
            "Description": "General description",
        }
    )

    # Verify skills
    assert result.canonical["skills"]["volunteer_skills"] == ["Teaching", "Tutoring"]
    assert result.canonical["skills"]["volunteer_skills_text"] == "Additional skills text"

    # Verify interests
    assert result.canonical["interests"]["volunteer_interests"] == ["Education"]

    # Verify engagement
    assert result.canonical["engagement"]["first_volunteer_date"] == "2024-01-15"
    assert result.canonical["engagement"]["attended_sessions_count"] == "5"
    assert result.canonical["engagement"]["last_email_message_at"] == "2024-01-20T10:30:00.000Z"

    # Verify demographics
    assert result.canonical["demographics"]["racial_ethnic_background"] == "Asian"
    assert result.canonical["demographics"]["age_group"] == "Adult"
    assert result.canonical["demographics"]["highest_education_level"] == "Bachelors"

    # Verify address
    assert result.canonical["address"]["mailing"]["street"] == "123 Main St"
    assert result.canonical["address"]["mailing"]["city"] == "Springfield"
    assert result.canonical["address"]["mailing"]["state"] == "IL"
    assert result.canonical["address"]["mailing"]["postal_code"] == "62701"
    assert result.canonical["address"]["mailing"]["country"] == "US"
    assert result.canonical["address"]["home"]["street"] == "456 Oak Ave"
    assert result.canonical["address"]["home"]["city"] == "Springfield"

    # Verify notes
    assert result.canonical["notes"]["recruitment_notes"] == "Recruited at event"
    assert result.canonical["notes"]["description"] == "General description"

    assert result.errors == []


def test_transformer_event_type_normalization():
    """Test that event type transforms normalize correctly."""
    spec = MappingSpec(
        version=1,
        adapter="salesforce",
        object_name="Session__c",
        fields=(
            MappingField(source="Id", target="external_id", required=True),
            MappingField(source="Session_Type__c", target="event_type", transform="normalize_session_type"),
            MappingField(source="Session_Status__c", target="event_status", transform="normalize_session_status"),
            MappingField(source="Format__c", target="event_format", transform="normalize_event_format"),
            MappingField(
                source="Cancellation_Reason__c", target="cancellation_reason", transform="normalize_cancellation_reason"
            ),
        ),
        transforms={
            "normalize_session_type": MappingTransform(name="normalize_session_type"),
            "normalize_session_status": MappingTransform(name="normalize_session_status"),
            "normalize_event_format": MappingTransform(name="normalize_event_format"),
            "normalize_cancellation_reason": MappingTransform(name="normalize_cancellation_reason"),
        },
        checksum="fake",
        path=None,  # type: ignore[arg-type]
    )
    transformer = SalesforceMappingTransformer(spec)

    # Test session type normalization
    result = transformer.transform(
        {
            "Id": "001",
            "Session_Type__c": "Campus Visit",
            "Session_Status__c": "Confirmed",
            "Format__c": "In-Person",
            "Cancellation_Reason__c": None,
        }
    )
    assert result.canonical["event_type"] == "community_event"
    assert result.canonical["event_status"] == "confirmed"
    assert result.canonical["event_format"] == "in_person"

    # Test various session types
    test_cases = [
        ("Career Speaker", "community_event"),
        ("Workplace Visit", "community_event"),
        ("HealthStart", "community_event"),
        ("BFI", "community_event"),
        ("Career Fair", "community_event"),
        ("Workshop", "workshop"),
        ("Meeting", "meeting"),
        ("Training", "training"),
        ("Fundraiser", "fundraiser"),
    ]

    for session_type, expected in test_cases:
        result = transformer.transform(
            {
                "Id": "002",
                "Session_Type__c": session_type,
                "Session_Status__c": "Confirmed",
                "Format__c": "In-Person",
            }
        )
        assert result.canonical["event_type"] == expected, f"Failed for {session_type}"

    # Test status normalization
    status_cases = [
        ("Draft", "draft"),
        ("Requested", "requested"),
        ("Confirmed", "confirmed"),
        ("Completed", "completed"),
        ("Cancelled", "cancelled"),
        ("Canceled", "cancelled"),  # Alternative spelling
    ]

    for status, expected in status_cases:
        result = transformer.transform(
            {
                "Id": "003",
                "Session_Type__c": "Workshop",
                "Session_Status__c": status,
                "Format__c": "In-Person",
            }
        )
        assert result.canonical["event_status"] == expected, f"Failed for {status}"

    # Test format normalization
    format_cases = [
        ("In-Person", "in_person"),
        ("In Person", "in_person"),
        ("Virtual", "virtual"),
        ("Online", "virtual"),
        ("Hybrid", "hybrid"),
    ]

    for format_val, expected in format_cases:
        result = transformer.transform(
            {
                "Id": "004",
                "Session_Type__c": "Workshop",
                "Session_Status__c": "Confirmed",
                "Format__c": format_val,
            }
        )
        assert result.canonical["event_format"] == expected, f"Failed for {format_val}"

    # Test cancellation reason normalization
    reason_cases = [
        ("Weather", "weather"),
        ("Low Attendance", "low_attendance"),
        ("Emergency", "emergency"),
        ("Scheduling Conflict", "scheduling_conflict"),
        ("Conflict", "scheduling_conflict"),
    ]

    for reason, expected in reason_cases:
        result = transformer.transform(
            {
                "Id": "005",
                "Session_Type__c": "Workshop",
                "Session_Status__c": "Cancelled",
                "Format__c": "In-Person",
                "Cancellation_Reason__c": reason,
            }
        )
        assert result.canonical["cancellation_reason"] == expected, f"Failed for {reason}"
