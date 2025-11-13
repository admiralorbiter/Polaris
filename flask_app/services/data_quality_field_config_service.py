# flask_app/services/data_quality_field_config_service.py
"""
Data Quality Field Configuration Service - Manage field visibility settings
"""

from typing import Dict, List, Optional, Set

from flask import current_app

from flask_app.models import SystemFeatureFlag, db


class DataQualityFieldConfigService:
    """Service for managing data quality field configuration"""

    # Flag name for storing disabled fields configuration
    FLAG_NAME = "data_quality_disabled_fields"

    # Default disabled fields (system-wide)
    DEFAULT_DISABLED_FIELDS = {
        "volunteer": ["clearance_status", "availability", "hours_logged"]
    }

    # Field definitions per entity type
    # These define which fields are available for each entity type
    FIELD_DEFINITIONS = {
        "volunteer": [
            "title",
            "industry",
            "clearance_status",
            "first_volunteer_date",
            "last_volunteer_date",
            "total_volunteer_hours",
            "skills",
            "interests",
            "availability",
            "hours_logged",
        ],
        "contact": [
            "first_name",
            "last_name",
            "middle_name",
            "preferred_name",
            "birthdate",
            "gender",
            "race",
            "age_group",
            "education_level",
            "preferred_language",
            "photo_url",
            "notes",
            "type",
            "email",
            "phone",
            "address",
            # Note: Metadata fields from ExternalIdMap are auto-discovered dynamically
            # They will appear in the dashboard automatically if present in metadata_json
        ],
        "student": [
            "grade",
            "enrollment_date",
            "student_id",
            "graduation_date",
        ],
        "teacher": [
            "certification",
            "subject_areas",
            "hire_date",
            "employee_id",
        ],
        "event": [
            "title",
            "description",
            "location_name",
            "location_address",
            "virtual_link",
            "start_date",
            "end_date",
            "duration",
            "capacity",
            "registration_deadline",
            "cost",
        ],
        "organization": [
            "name",
            "description",
            "website",
            "phone",
            "email",
            "tax_id",
            "logo_url",
            "contact_person_name",
            "contact_person_title",
            "founded_date",
            "address",
        ],
        "user": [
            "username",
            "email",
            "first_name",
            "last_name",
        ],
    }

    @classmethod
    def get_disabled_fields(cls, organization_id: Optional[int] = None) -> Dict[str, List[str]]:
        """
        Get disabled fields configuration.

        Args:
            organization_id: Optional organization ID for org-specific config (future)
                            Currently uses system-wide configuration

        Returns:
            Dictionary mapping entity_type to list of disabled field names
        """
        # For v1, use system-wide configuration
        # Future: check for org-specific override first, fall back to system-wide
        disabled_fields = SystemFeatureFlag.get_flag(cls.FLAG_NAME, default=None)

        if disabled_fields is None:
            # No configuration exists, return defaults
            return cls.DEFAULT_DISABLED_FIELDS.copy()

        # Validate and return configuration
        if not isinstance(disabled_fields, dict):
            current_app.logger.warning(
                f"Invalid disabled fields configuration format: {disabled_fields}. Using defaults."
            )
            return cls.DEFAULT_DISABLED_FIELDS.copy()

        # Ensure all entity types have lists (not missing keys)
        result = {}
        for entity_type in cls.FIELD_DEFINITIONS.keys():
            # Get disabled fields for this entity type, defaulting to empty list
            entity_disabled = disabled_fields.get(entity_type, [])
            # Ensure it's a list
            if not isinstance(entity_disabled, list):
                entity_disabled = []
            # Filter out invalid field names
            valid_fields = set(cls.FIELD_DEFINITIONS.get(entity_type, []))
            result[entity_type] = [f for f in entity_disabled if f in valid_fields]

        return result

    @classmethod
    def set_disabled_fields(
        cls, disabled_fields: Dict[str, List[str]], organization_id: Optional[int] = None
    ) -> bool:
        """
        Set disabled fields configuration.

        Args:
            disabled_fields: Dictionary mapping entity_type to list of disabled field names
            organization_id: Optional organization ID for org-specific config (future)
                            Currently uses system-wide configuration

        Returns:
            True if successful, False otherwise
        """
        # Validate configuration
        if not cls._validate_disabled_fields(disabled_fields):
            return False

        # For v1, use system-wide configuration
        # Future: store org-specific configuration if organization_id is provided
        return SystemFeatureFlag.set_flag(
            cls.FLAG_NAME,
            disabled_fields,
            flag_type="json",
            description="Data Quality Dashboard disabled fields configuration",
        )

    @classmethod
    def is_field_enabled(
        cls, entity_type: str, field_name: str, organization_id: Optional[int] = None
    ) -> bool:
        """
        Check if a field is enabled for an entity type.

        Args:
            entity_type: Entity type (e.g., "volunteer", "contact")
            field_name: Field name (e.g., "clearance_status", "availability")
            organization_id: Optional organization ID for org-specific config (future)

        Returns:
            True if field is enabled, False if disabled or invalid
        """
        # Check if entity type is valid
        if entity_type not in cls.FIELD_DEFINITIONS:
            current_app.logger.warning(f"Unknown entity type: {entity_type}")
            return False

        # Check if field name is valid
        if field_name not in cls.FIELD_DEFINITIONS[entity_type]:
            current_app.logger.warning(f"Unknown field name: {field_name} for entity type: {entity_type}")
            return False

        disabled_fields = cls.get_disabled_fields(organization_id)
        disabled_for_entity = disabled_fields.get(entity_type, [])
        return field_name not in disabled_for_entity

    @classmethod
    def get_enabled_fields(
        cls, entity_type: str, organization_id: Optional[int] = None
    ) -> List[str]:
        """
        Get list of enabled fields for an entity type.

        Args:
            entity_type: Entity type (e.g., "volunteer", "contact")
            organization_id: Optional organization ID for org-specific config (future)

        Returns:
            List of enabled field names
        """
        if entity_type not in cls.FIELD_DEFINITIONS:
            current_app.logger.warning(f"Unknown entity type: {entity_type}")
            return []

        all_fields = cls.FIELD_DEFINITIONS[entity_type]
        disabled_fields = cls.get_disabled_fields(organization_id)
        disabled_for_entity = set(disabled_fields.get(entity_type, []))

        return [field for field in all_fields if field not in disabled_for_entity]

    @classmethod
    def get_field_definitions(cls, entity_type: Optional[str] = None) -> Dict[str, List[str]]:
        """
        Get field definitions for entity type(s).

        Args:
            entity_type: Optional entity type. If None, returns all entity types

        Returns:
            Dictionary mapping entity_type to list of field names
        """
        if entity_type:
            if entity_type not in cls.FIELD_DEFINITIONS:
                current_app.logger.warning(f"Unknown entity type: {entity_type}")
                return {}
            return {entity_type: cls.FIELD_DEFINITIONS[entity_type]}

        return cls.FIELD_DEFINITIONS.copy()

    @classmethod
    def _validate_disabled_fields(cls, disabled_fields: Dict[str, List[str]]) -> bool:
        """
        Validate disabled fields configuration.

        Args:
            disabled_fields: Dictionary mapping entity_type to list of disabled field names

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(disabled_fields, dict):
            current_app.logger.error("Disabled fields must be a dictionary")
            return False

        # Validate each entity type
        for entity_type, field_list in disabled_fields.items():
            if entity_type not in cls.FIELD_DEFINITIONS:
                current_app.logger.error(f"Unknown entity type in configuration: {entity_type}")
                return False

            if not isinstance(field_list, list):
                current_app.logger.error(f"Fields for {entity_type} must be a list")
                return False

            # Validate field names
            valid_fields = set(cls.FIELD_DEFINITIONS[entity_type])
            for field_name in field_list:
                if not isinstance(field_name, str):
                    current_app.logger.error(f"Field name must be a string: {field_name}")
                    return False
                if field_name not in valid_fields:
                    current_app.logger.error(
                        f"Unknown field '{field_name}' for entity type '{entity_type}'"
                    )
                    return False

        return True

    @classmethod
    def initialize_default_config(cls) -> bool:
        """
        Initialize default configuration if it doesn't exist.

        Returns:
            True if initialized, False otherwise
        """
        existing = SystemFeatureFlag.get_flag(cls.FLAG_NAME, default=None)
        if existing is not None:
            # Configuration already exists
            return True

        # Set default configuration
        return cls.set_disabled_fields(cls.DEFAULT_DISABLED_FIELDS)

    @classmethod
    def get_field_config_for_display(
        cls, organization_id: Optional[int] = None
    ) -> Dict[str, Dict[str, Dict[str, bool]]]:
        """
        Get field configuration formatted for UI display.

        Args:
            organization_id: Optional organization ID for org-specific config (future)

        Returns:
            Dictionary with entity_types -> field_name -> enabled status
        """
        disabled_fields = cls.get_disabled_fields(organization_id)
        result = {}

        for entity_type, all_fields in cls.FIELD_DEFINITIONS.items():
            entity_config = {}
            disabled_for_entity = set(disabled_fields.get(entity_type, []))

            for field_name in all_fields:
                entity_config[field_name] = {
                    "enabled": field_name not in disabled_for_entity,
                    "display_name": cls._get_display_name(entity_type, field_name),
                }

            result[entity_type] = entity_config

        return result

    @classmethod
    def _get_display_name(cls, entity_type: str, field_name: str) -> str:
        """
        Get display name for a field.

        Args:
            entity_type: Entity type
            field_name: Field name

        Returns:
            Display name (human-readable)
        """
        # Simple display name conversion (replace underscores with spaces, title case)
        display_name = field_name.replace("_", " ").title()
        return display_name

