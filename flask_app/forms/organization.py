# flask_app/forms/organization.py
"""
Forms for organization management
"""

import re

from flask import current_app
from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError


def format_enum_display(enum_value):
    """Format enum value for display (e.g., 'non_profit' -> 'Non Profit')"""
    return enum_value.replace("_", " ").title()


class CreateOrganizationForm(FlaskForm):
    """Form for creating new organizations"""

    # Basic information
    name = StringField(
        "Organization Name",
        validators=[
            DataRequired(message="Organization name is required."),
            Length(max=200, message="Organization name must be less than 200 characters."),
        ],
        render_kw={"placeholder": "Enter organization name"},
    )
    slug = StringField(
        "Slug",
        validators=[
            DataRequired(message="Slug is required."),
            Length(max=100, message="Slug must be less than 100 characters."),
        ],
        render_kw={"placeholder": "organization-slug"},
    )
    description = TextAreaField(
        "Description",
        validators=[Length(max=5000, message="Description must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter organization description", "rows": 4},
    )
    organization_type = SelectField(
        "Organization Type",
        validators=[DataRequired(message="Organization type is required.")],
        choices=[],  # Will be populated in __init__
        default="other",
    )
    is_active = BooleanField("Active", default=True)

    # Contact information
    website = StringField(
        "Website",
        validators=[],  # Validation handled in validate_website()
        render_kw={"placeholder": "https://example.com"},
    )
    phone = StringField(
        "Phone",
        validators=[Length(max=20, message="Phone number must be less than 20 characters.")],
        render_kw={"placeholder": "Enter phone number"},
    )
    email = StringField(
        "Email",
        validators=[],  # Validation handled in validate_email()
        render_kw={"placeholder": "Enter email address"},
    )

    # Business/legal information
    tax_id = StringField(
        "Tax ID / EIN",
        validators=[Length(max=50, message="Tax ID must be less than 50 characters.")],
        render_kw={"placeholder": "Enter tax ID or EIN"},
    )

    # Visual/branding
    logo_url = StringField(
        "Logo URL",
        validators=[],  # Validation handled in validate_logo_url()
        render_kw={"placeholder": "https://example.com/logo.png"},
    )

    # Contact person
    contact_person_name = StringField(
        "Contact Person Name",
        validators=[Length(max=200, message="Contact person name must be less than 200 characters.")],
        render_kw={"placeholder": "Enter contact person name"},
    )
    contact_person_title = StringField(
        "Contact Person Title",
        validators=[Length(max=100, message="Contact person title must be less than 100 characters.")],
        render_kw={"placeholder": "Enter contact person title"},
    )

    # Dates
    founded_date = DateField(
        "Founded Date",
        validators=[Optional()],
        render_kw={"placeholder": "YYYY-MM-DD"},
    )

    # Address fields
    street_address_1 = StringField(
        "Street Address",
        validators=[
            Optional(),
            Length(max=255, message="Street address must be less than 255 characters."),
        ],
        render_kw={"placeholder": "Enter street address"},
    )
    street_address_2 = StringField(
        "Street Address 2",
        validators=[Length(max=255, message="Street address 2 must be less than 255 characters.")],
        render_kw={"placeholder": "Apt, Suite, etc."},
    )
    city = StringField(
        "City",
        validators=[
            Optional(),
            Length(max=100, message="City must be less than 100 characters."),
        ],
        render_kw={"placeholder": "Enter city"},
    )
    state = StringField(
        "State",
        validators=[
            Optional(),
            Length(max=50, message="State must be less than 50 characters."),
        ],
        render_kw={"placeholder": "Enter state"},
    )
    postal_code = StringField(
        "Postal Code",
        validators=[
            Optional(),
            Length(max=20, message="Postal code must be less than 20 characters."),
        ],
        render_kw={"placeholder": "Enter postal code"},
    )
    country = StringField(
        "Country",
        validators=[
            Optional(),
            Length(max=100, message="Country must be less than 100 characters."),
        ],
        default="US",
        render_kw={"placeholder": "Enter country"},
    )
    address_type = SelectField(
        "Address Type",
        validators=[Optional()],
        choices=[],  # Will be populated in __init__
        default="work",
    )

    submit = SubmitField("Create Organization")

    def __init__(self, *args, **kwargs):
        super(CreateOrganizationForm, self).__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from flask_app.models import AddressType, OrganizationType

        # Set organization_type choices
        self.organization_type.choices = [
            (org_type.value, format_enum_display(org_type.value)) for org_type in OrganizationType
        ]

        # Set address_type choices
        self.address_type.choices = [
            (addr_type.value, format_enum_display(addr_type.value)) for addr_type in AddressType
        ]

    def validate_name(self, field):
        """Custom validation for organization name"""
        if field.data:
            # Strip whitespace
            field.data = field.data.strip()

            # Check minimum length
            if len(field.data) < 2:
                raise ValidationError("Organization name must be at least 2 characters long.")

            # Check for duplicate names
            from flask_app.models import Organization

            existing = Organization.query.filter_by(name=field.data).first()
            if existing:
                raise ValidationError("An organization with this name already exists.")

    def validate_slug(self, field):
        """Custom validation for slug"""
        if field.data:
            # Strip whitespace
            field.data = field.data.strip()

            # Check minimum length
            if len(field.data) < 2:
                raise ValidationError("Slug must be at least 2 characters long.")

            # Check format (lowercase alphanumeric with hyphens)
            if not re.match(r"^[a-z0-9-]+$", field.data):
                raise ValidationError("Slug must contain only lowercase letters, numbers, and hyphens.")

            # Check for duplicate slugs
            from flask_app.models import Organization

            existing = Organization.query.filter_by(slug=field.data).first()
            if existing:
                raise ValidationError("An organization with this slug already exists.")

    def validate_website(self, field):
        """Custom validation for website URL"""
        # Custom validators are always called if field has data
        # Optional() only stops validation if field is empty/None
        if field.data:
            field.data = field.data.strip()
            if not field.data:  # If empty after strip, skip validation
                return
            # Check max length (500 characters)
            if len(field.data) > 500:
                raise ValidationError("Website URL must be less than 500 characters.")
            # Validate URL format
            from urllib.parse import urlparse

            result = urlparse(field.data)
            if not all([result.scheme, result.netloc]):
                raise ValidationError("Please enter a valid URL.")

    def validate_logo_url(self, field):
        """Custom validation for logo URL"""
        # Custom validators are always called if field has data
        # Optional() only stops validation if field is empty/None
        if field.data:
            field.data = field.data.strip()
            if not field.data:  # If empty after strip, skip validation
                return
            # Check max length (500 characters)
            if len(field.data) > 500:
                raise ValidationError("Logo URL must be less than 500 characters.")
            # Validate URL format
            from urllib.parse import urlparse

            result = urlparse(field.data)
            if not all([result.scheme, result.netloc]):
                raise ValidationError("Please enter a valid URL.")

    def validate_email(self, field):
        """Custom validation for email"""
        # Custom validators are always called if field has data
        # Optional() only stops validation if field is empty/None
        if field.data:
            field.data = field.data.strip()
            if not field.data:  # If empty after strip, skip validation
                return
            # Check max length (255 characters)
            if len(field.data) > 255:
                raise ValidationError("Email must be less than 255 characters.")
            # Email format validation - check basic email format
            import re

            email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_pattern, field.data):
                raise ValidationError("Invalid email address.")


class UpdateOrganizationForm(FlaskForm):
    """Form for updating existing organizations"""

    # Basic information
    name = StringField(
        "Organization Name",
        validators=[
            DataRequired(message="Organization name is required."),
            Length(min=2, max=200, message="Organization name must be between 2 and 200 characters."),
        ],
        render_kw={"placeholder": "Enter organization name"},
    )
    slug = StringField(
        "Slug",
        validators=[
            DataRequired(message="Slug is required."),
            Length(min=2, max=100, message="Slug must be between 2 and 100 characters."),
        ],
        render_kw={"placeholder": "organization-slug"},
    )
    description = TextAreaField(
        "Description",
        validators=[Length(max=5000, message="Description must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter organization description", "rows": 4},
    )
    organization_type = SelectField(
        "Organization Type",
        validators=[DataRequired(message="Organization type is required.")],
        choices=[],  # Will be populated in __init__
    )
    is_active = BooleanField("Active", default=True)

    # Contact information
    website = StringField(
        "Website",
        validators=[],  # Validation handled in validate_website()
        render_kw={"placeholder": "https://example.com"},
    )
    phone = StringField(
        "Phone",
        validators=[Length(max=20, message="Phone number must be less than 20 characters.")],
        render_kw={"placeholder": "Enter phone number"},
    )
    email = StringField(
        "Email",
        validators=[],  # Validation handled in validate_email()
        render_kw={"placeholder": "Enter email address"},
    )

    # Business/legal information
    tax_id = StringField(
        "Tax ID / EIN",
        validators=[Length(max=50, message="Tax ID must be less than 50 characters.")],
        render_kw={"placeholder": "Enter tax ID or EIN"},
    )

    # Visual/branding
    logo_url = StringField(
        "Logo URL",
        validators=[],  # Validation handled in validate_logo_url()
        render_kw={"placeholder": "https://example.com/logo.png"},
    )

    # Contact person
    contact_person_name = StringField(
        "Contact Person Name",
        validators=[Length(max=200, message="Contact person name must be less than 200 characters.")],
        render_kw={"placeholder": "Enter contact person name"},
    )
    contact_person_title = StringField(
        "Contact Person Title",
        validators=[Length(max=100, message="Contact person title must be less than 100 characters.")],
        render_kw={"placeholder": "Enter contact person title"},
    )

    # Dates
    founded_date = DateField(
        "Founded Date",
        validators=[Optional()],
        render_kw={"placeholder": "YYYY-MM-DD"},
    )

    # Address fields
    street_address_1 = StringField(
        "Street Address",
        validators=[
            Optional(),
            Length(max=255, message="Street address must be less than 255 characters."),
        ],
        render_kw={"placeholder": "Enter street address"},
    )
    street_address_2 = StringField(
        "Street Address 2",
        validators=[Length(max=255, message="Street address 2 must be less than 255 characters.")],
        render_kw={"placeholder": "Apt, Suite, etc."},
    )
    city = StringField(
        "City",
        validators=[
            Optional(),
            Length(max=100, message="City must be less than 100 characters."),
        ],
        render_kw={"placeholder": "Enter city"},
    )
    state = StringField(
        "State",
        validators=[
            Optional(),
            Length(max=50, message="State must be less than 50 characters."),
        ],
        render_kw={"placeholder": "Enter state"},
    )
    postal_code = StringField(
        "Postal Code",
        validators=[
            Optional(),
            Length(max=20, message="Postal code must be less than 20 characters."),
        ],
        render_kw={"placeholder": "Enter postal code"},
    )
    country = StringField(
        "Country",
        validators=[
            Optional(),
            Length(max=100, message="Country must be less than 100 characters."),
        ],
        default="US",
        render_kw={"placeholder": "Enter country"},
    )
    address_type = SelectField(
        "Address Type",
        validators=[Optional()],
        choices=[],  # Will be populated in __init__
    )

    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        # Extract organization from kwargs before calling super
        self.organization = kwargs.pop("organization", None)
        super(UpdateOrganizationForm, self).__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from flask_app.models import AddressType, OrganizationType

        # Set organization_type choices
        self.organization_type.choices = [
            (org_type.value, format_enum_display(org_type.value)) for org_type in OrganizationType
        ]

        # Set address_type choices
        self.address_type.choices = [
            (addr_type.value, format_enum_display(addr_type.value)) for addr_type in AddressType
        ]

    def validate_name(self, field):
        """Custom validation for organization name"""
        if field.data:
            # Strip whitespace
            field.data = field.data.strip()

            # Check minimum length
            if len(field.data) < 2:
                raise ValidationError("Organization name must be at least 2 characters long.")

            # Check for duplicate names (excluding current organization)
            try:
                from flask_app.models import Organization

                existing = Organization.query.filter_by(name=field.data).first()
                if existing and (not self.organization or existing.id != self.organization.id):
                    raise ValidationError("An organization with this name already exists.")
            except ValidationError:
                # Re-raise ValidationError so it's properly caught by form validation
                raise
            except Exception:  # pragma: no cover - defensive logging
                current_app.logger.exception("Failed to validate organization name uniqueness")

    def validate_slug(self, field):
        """Custom validation for slug"""
        if field.data:
            # Strip whitespace
            field.data = field.data.strip()

            # Check minimum length
            if len(field.data) < 2:
                raise ValidationError("Slug must be at least 2 characters long.")

            # Check format (lowercase alphanumeric with hyphens)
            if not re.match(r"^[a-z0-9-]+$", field.data):
                raise ValidationError("Slug must contain only lowercase letters, numbers, and hyphens.")

            # Check for duplicate slugs (excluding current organization)
            try:
                from flask_app.models import Organization

                existing = Organization.query.filter_by(slug=field.data).first()
                if existing and (not self.organization or existing.id != self.organization.id):
                    raise ValidationError("An organization with this slug already exists.")
            except ValidationError:
                # Re-raise ValidationError so it's properly caught by form validation
                raise
            except Exception:  # pragma: no cover - defensive logging
                current_app.logger.exception("Failed to validate organization slug uniqueness")

    def validate_website(self, field):
        """Custom validation for website URL"""
        if field.data:
            field.data = field.data.strip()
            if not field.data:  # If empty after strip, skip validation
                return
            # Check max length (500 characters)
            if len(field.data) > 500:
                raise ValidationError("Website URL must be less than 500 characters.")
            # Validate URL format
            try:
                from urllib.parse import urlparse

                result = urlparse(field.data)
                if not all([result.scheme, result.netloc]):
                    raise ValidationError("Please enter a valid URL.")
            except ValidationError:
                raise
            except Exception:
                raise ValidationError("Please enter a valid URL.")

    def validate_logo_url(self, field):
        """Custom validation for logo URL"""
        # Custom validators are always called if field has data
        # Optional() only stops validation if field is empty/None
        if field.data:
            field.data = field.data.strip()
            if not field.data:  # If empty after strip, skip validation
                return
            # Check max length (500 characters)
            if len(field.data) > 500:
                raise ValidationError("Logo URL must be less than 500 characters.")
            # Validate URL format
            from urllib.parse import urlparse

            result = urlparse(field.data)
            if not all([result.scheme, result.netloc]):
                raise ValidationError("Please enter a valid URL.")

    def validate_email(self, field):
        """Custom validation for email"""
        # Custom validators are always called if field has data
        # Optional() only stops validation if field is empty/None
        if field.data:
            field.data = field.data.strip()
            if not field.data:  # If empty after strip, skip validation
                return
            # Check max length (255 characters)
            if len(field.data) > 255:
                raise ValidationError("Email must be less than 255 characters.")
            # Email format validation - check basic email format
            import re

            email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_pattern, field.data):
                raise ValidationError("Invalid email address.")
