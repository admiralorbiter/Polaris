# flask_app/forms/organization.py
"""
Forms for organization management
"""

from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import URL, DataRequired, Email, Length, Optional


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
        validators=[
            Optional(),
            URL(message="Please enter a valid URL."),
            Length(max=500, message="Website URL must be less than 500 characters."),
        ],
        render_kw={"placeholder": "https://example.com"},
    )
    phone = StringField(
        "Phone",
        validators=[Length(max=20, message="Phone number must be less than 20 characters.")],
        render_kw={"placeholder": "Enter phone number"},
    )
    email = StringField(
        "Email",
        validators=[
            Optional(),
            Email(message="Invalid email address."),
            Length(max=255, message="Email must be less than 255 characters."),
        ],
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
        validators=[
            Optional(),
            URL(message="Please enter a valid URL."),
            Length(max=500, message="Logo URL must be less than 500 characters."),
        ],
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


class UpdateOrganizationForm(FlaskForm):
    """Form for updating existing organizations"""

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
    )
    is_active = BooleanField("Active", default=True)

    # Contact information
    website = StringField(
        "Website",
        validators=[
            Optional(),
            URL(message="Please enter a valid URL."),
            Length(max=500, message="Website URL must be less than 500 characters."),
        ],
        render_kw={"placeholder": "https://example.com"},
    )
    phone = StringField(
        "Phone",
        validators=[Length(max=20, message="Phone number must be less than 20 characters.")],
        render_kw={"placeholder": "Enter phone number"},
    )
    email = StringField(
        "Email",
        validators=[
            Optional(),
            Email(message="Invalid email address."),
            Length(max=255, message="Email must be less than 255 characters."),
        ],
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
        validators=[
            Optional(),
            URL(message="Please enter a valid URL."),
            Length(max=500, message="Logo URL must be less than 500 characters."),
        ],
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
