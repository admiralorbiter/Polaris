# flask_app/forms/volunteer.py
"""
Forms for volunteer management
"""

from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


class CreateVolunteerForm(FlaskForm):
    """Form for creating new volunteers"""

    # Name fields
    salutation = StringField(
        "Salutation",
        validators=[Length(max=20, message="Salutation must be less than 20 characters.")],
        render_kw={"placeholder": "Mr., Mrs., Dr., etc."},
    )
    first_name = StringField(
        "First Name",
        validators=[
            DataRequired(message="First name is required."),
            Length(max=100, message="First name must be less than 100 characters."),
        ],
        render_kw={"placeholder": "Enter first name"},
    )
    middle_name = StringField(
        "Middle Name",
        validators=[Length(max=100, message="Middle name must be less than 100 characters.")],
        render_kw={"placeholder": "Enter middle name"},
    )
    last_name = StringField(
        "Last Name",
        validators=[
            DataRequired(message="Last name is required."),
            Length(max=100, message="Last name must be less than 100 characters."),
        ],
        render_kw={"placeholder": "Enter last name"},
    )
    suffix = StringField(
        "Suffix",
        validators=[Length(max=20, message="Suffix must be less than 20 characters.")],
        render_kw={"placeholder": "Jr., Sr., III, etc."},
    )
    preferred_name = StringField(
        "Preferred Name",
        validators=[Length(max=100, message="Preferred name must be less than 100 characters.")],
        render_kw={"placeholder": "Enter preferred name"},
    )

    # Contact information
    email = StringField(
        "Email",
        validators=[
            Optional(),
            Email(message="Invalid email address."),
            Length(max=255, message="Email must be less than 255 characters."),
        ],
        render_kw={"placeholder": "Enter email address"},
    )
    phone_number = StringField(
        "Phone Number",
        validators=[Length(max=20, message="Phone number must be less than 20 characters.")],
        render_kw={"placeholder": "Enter phone number"},
    )
    can_text = BooleanField("Can receive text messages", default=False)

    # Demographics
    gender = StringField(
        "Gender",
        validators=[Length(max=50, message="Gender must be less than 50 characters.")],
        render_kw={"placeholder": "Enter gender"},
    )
    race = StringField(
        "Race",
        validators=[Length(max=100, message="Race must be less than 100 characters.")],
        render_kw={"placeholder": "Enter race"},
    )
    birthdate = DateField(
        "Birthdate",
        validators=[Optional()],
        render_kw={"placeholder": "YYYY-MM-DD"},
    )
    education_level = StringField(
        "Education Level",
        validators=[Length(max=100, message="Education level must be less than 100 characters.")],
        render_kw={"placeholder": "Enter education level"},
    )

    # Volunteer-specific fields
    volunteer_status = SelectField(
        "Volunteer Status",
        validators=[DataRequired(message="Volunteer status is required.")],
        choices=[],  # Will be populated in __init__
        default="active",
    )
    title = StringField(
        "Title/Position",
        validators=[Length(max=200, message="Title must be less than 200 characters.")],
        render_kw={"placeholder": "Enter job title or position"},
    )
    industry = StringField(
        "Industry",
        validators=[Length(max=200, message="Industry must be less than 200 characters.")],
        render_kw={"placeholder": "Enter industry or field"},
    )
    clearance_status = StringField(
        "Clearance Status",
        validators=[Length(max=50, message="Clearance status must be less than 50 characters.")],
        render_kw={"placeholder": "Enter clearance status"},
    )
    is_local = BooleanField("Is Local (can volunteer in person)", default=True)

    # Contact preferences
    do_not_call = BooleanField("Do Not Call", default=False)
    do_not_email = BooleanField("Do Not Email", default=False)
    do_not_contact = BooleanField("Do Not Contact", default=False)

    # Additional information
    preferred_language = StringField(
        "Preferred Language",
        validators=[Length(max=50, message="Preferred language must be less than 50 characters.")],
        render_kw={"placeholder": "Enter preferred language"},
    )
    notes = TextAreaField(
        "Notes",
        validators=[Length(max=5000, message="Notes must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter public notes", "rows": 3},
    )
    internal_notes = TextAreaField(
        "Internal Notes",
        validators=[Length(max=5000, message="Internal notes must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter internal staff-only notes", "rows": 3},
    )

    submit = SubmitField("Create Volunteer")

    def __init__(self, *args, **kwargs):
        super(CreateVolunteerForm, self).__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from flask_app.models import VolunteerStatus

        # Set volunteer_status choices
        self.volunteer_status.choices = [
            (VolunteerStatus.ACTIVE.value, "Active"),
            (VolunteerStatus.HOLD.value, "Hold"),
            (VolunteerStatus.INACTIVE.value, "Inactive"),
        ]


class UpdateVolunteerForm(FlaskForm):
    """Form for updating existing volunteers"""

    # Name fields
    salutation = StringField(
        "Salutation",
        validators=[Length(max=20, message="Salutation must be less than 20 characters.")],
        render_kw={"placeholder": "Mr., Mrs., Dr., etc."},
    )
    first_name = StringField(
        "First Name",
        validators=[
            DataRequired(message="First name is required."),
            Length(max=100, message="First name must be less than 100 characters."),
        ],
        render_kw={"placeholder": "Enter first name"},
    )
    middle_name = StringField(
        "Middle Name",
        validators=[Length(max=100, message="Middle name must be less than 100 characters.")],
        render_kw={"placeholder": "Enter middle name"},
    )
    last_name = StringField(
        "Last Name",
        validators=[
            DataRequired(message="Last name is required."),
            Length(max=100, message="Last name must be less than 100 characters."),
        ],
        render_kw={"placeholder": "Enter last name"},
    )
    suffix = StringField(
        "Suffix",
        validators=[Length(max=20, message="Suffix must be less than 20 characters.")],
        render_kw={"placeholder": "Jr., Sr., III, etc."},
    )
    preferred_name = StringField(
        "Preferred Name",
        validators=[Length(max=100, message="Preferred name must be less than 100 characters.")],
        render_kw={"placeholder": "Enter preferred name"},
    )

    # Contact information
    email = StringField(
        "Email",
        validators=[
            Optional(),
            Email(message="Invalid email address."),
            Length(max=255, message="Email must be less than 255 characters."),
        ],
        render_kw={"placeholder": "Enter email address"},
    )
    phone_number = StringField(
        "Phone Number",
        validators=[Length(max=20, message="Phone number must be less than 20 characters.")],
        render_kw={"placeholder": "Enter phone number"},
    )
    can_text = BooleanField("Can receive text messages", default=False)

    # Demographics
    gender = StringField(
        "Gender",
        validators=[Length(max=50, message="Gender must be less than 50 characters.")],
        render_kw={"placeholder": "Enter gender"},
    )
    race = StringField(
        "Race",
        validators=[Length(max=100, message="Race must be less than 100 characters.")],
        render_kw={"placeholder": "Enter race"},
    )
    birthdate = DateField(
        "Birthdate",
        validators=[Optional()],
        render_kw={"placeholder": "YYYY-MM-DD"},
    )
    education_level = StringField(
        "Education Level",
        validators=[Length(max=100, message="Education level must be less than 100 characters.")],
        render_kw={"placeholder": "Enter education level"},
    )

    # Volunteer-specific fields
    volunteer_status = SelectField(
        "Volunteer Status",
        validators=[DataRequired(message="Volunteer status is required.")],
        choices=[],  # Will be populated in __init__
        default="active",
    )
    title = StringField(
        "Title/Position",
        validators=[Length(max=200, message="Title must be less than 200 characters.")],
        render_kw={"placeholder": "Enter job title or position"},
    )
    industry = StringField(
        "Industry",
        validators=[Length(max=200, message="Industry must be less than 200 characters.")],
        render_kw={"placeholder": "Enter industry or field"},
    )
    clearance_status = StringField(
        "Clearance Status",
        validators=[Length(max=50, message="Clearance status must be less than 50 characters.")],
        render_kw={"placeholder": "Enter clearance status"},
    )
    is_local = BooleanField("Is Local (can volunteer in person)", default=True)

    # Contact preferences
    do_not_call = BooleanField("Do Not Call", default=False)
    do_not_email = BooleanField("Do Not Email", default=False)
    do_not_contact = BooleanField("Do Not Contact", default=False)

    # Additional information
    preferred_language = StringField(
        "Preferred Language",
        validators=[Length(max=50, message="Preferred language must be less than 50 characters.")],
        render_kw={"placeholder": "Enter preferred language"},
    )
    notes = TextAreaField(
        "Notes",
        validators=[Length(max=5000, message="Notes must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter public notes", "rows": 3},
    )
    internal_notes = TextAreaField(
        "Internal Notes",
        validators=[Length(max=5000, message="Internal notes must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter internal staff-only notes", "rows": 3},
    )

    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        super(UpdateVolunteerForm, self).__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from flask_app.models import VolunteerStatus

        # Set volunteer_status choices
        self.volunteer_status.choices = [
            (VolunteerStatus.ACTIVE.value, "Active"),
            (VolunteerStatus.HOLD.value, "Hold"),
            (VolunteerStatus.INACTIVE.value, "Inactive"),
        ]

