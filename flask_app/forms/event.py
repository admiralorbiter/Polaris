# flask_app/forms/event.py
"""
Forms for event management
"""

import re
from datetime import datetime

from flask import current_app
from flask_wtf import FlaskForm
from wtforms import DateTimeField, IntegerField, SelectField, StringField, SubmitField, TextAreaField, TimeField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError
from wtforms.widgets import NumberInput


def format_enum_display(enum_value):
    """Format enum value for display (e.g., 'in_person' -> 'In Person')"""
    return enum_value.replace("_", " ").title()


class CreateEventForm(FlaskForm):
    """Form for creating new events"""

    # Basic information
    title = StringField(
        "Event Title",
        validators=[
            DataRequired(message="Event title is required."),
            Length(max=200, message="Event title must be less than 200 characters."),
        ],
        render_kw={"placeholder": "Enter event title"},
    )
    slug = StringField(
        "Slug",
        validators=[
            DataRequired(message="Slug is required."),
            Length(max=100, message="Slug must be less than 100 characters."),
        ],
        render_kw={"placeholder": "event-slug"},
    )
    description = TextAreaField(
        "Description",
        validators=[Length(max=5000, message="Description must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter event description", "rows": 4},
    )

    # Enums
    event_type = SelectField(
        "Event Type",
        validators=[DataRequired(message="Event type is required.")],
        choices=[],  # Will be populated in __init__
        default="other",
    )
    event_status = SelectField(
        "Event Status",
        validators=[DataRequired(message="Event status is required.")],
        choices=[],  # Will be populated in __init__
        default="draft",
    )
    event_format = SelectField(
        "Event Format",
        validators=[DataRequired(message="Event format is required.")],
        choices=[],  # Will be populated in __init__
        default="in_person",
    )
    cancellation_reason = SelectField(
        "Cancellation Reason",
        validators=[Optional()],
        choices=[],  # Will be populated in __init__
    )

    # Dates and times
    start_date = DateTimeField(
        "Start Date & Time",
        validators=[DataRequired(message="Start date and time is required.")],
        format="%Y-%m-%dT%H:%M",
        render_kw={"type": "datetime-local"},
    )
    start_time = TimeField(
        "Start Time (Optional)",
        validators=[Optional()],
        render_kw={"placeholder": "HH:MM"},
    )
    duration = IntegerField(
        "Duration (minutes)",
        validators=[
            Optional(),
            NumberRange(min=1, max=10080, message="Duration must be between 1 and 10080 minutes (7 days)."),
        ],
        widget=NumberInput(),
        render_kw={"placeholder": "Enter duration in minutes"},
    )
    registration_deadline = DateTimeField(
        "Registration Deadline (Optional)",
        validators=[Optional()],
        format="%Y-%m-%dT%H:%M",
        render_kw={"type": "datetime-local"},
    )

    # Location
    location_name = StringField(
        "Location Name",
        validators=[Length(max=200, message="Location name must be less than 200 characters.")],
        render_kw={"placeholder": "Enter location name"},
    )
    location_address = TextAreaField(
        "Location Address",
        validators=[Length(max=1000, message="Location address must be less than 1000 characters.")],
        render_kw={"placeholder": "Enter full address", "rows": 3},
    )
    virtual_link = StringField(
        "Virtual Link",
        validators=[Length(max=500, message="Virtual link must be less than 500 characters.")],
        render_kw={"placeholder": "https://zoom.us/j/..."},
    )

    # Metadata
    capacity = IntegerField(
        "Capacity (Optional)",
        validators=[Optional(), NumberRange(min=1, message="Capacity must be at least 1.")],
        widget=NumberInput(),
        render_kw={"placeholder": "Enter maximum capacity"},
    )
    cost = StringField(
        "Cost (Optional)",
        validators=[Optional()],
        render_kw={"placeholder": "0.00"},
    )

    # Organization
    organization_id = SelectField(
        "Primary Organization",
        validators=[DataRequired(message="Organization is required.")],
        choices=[],  # Will be populated in __init__
        coerce=int,
    )

    submit = SubmitField("Create Event")

    def __init__(self, *args, **kwargs):
        super(CreateEventForm, self).__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from flask_app.models import CancellationReason, EventFormat, EventStatus, EventType, Organization

        # Set event_type choices
        self.event_type.choices = [
            (event_type.value, format_enum_display(event_type.value)) for event_type in EventType
        ]

        # Set event_status choices
        self.event_status.choices = [
            (event_status.value, format_enum_display(event_status.value)) for event_status in EventStatus
        ]

        # Set event_format choices
        self.event_format.choices = [
            (event_format.value, format_enum_display(event_format.value)) for event_format in EventFormat
        ]

        # Set cancellation_reason choices
        self.cancellation_reason.choices = [("", "None")] + [
            (reason.value, format_enum_display(reason.value)) for reason in CancellationReason
        ]

        # Set organization choices
        organizations = Organization.query.filter_by(is_active=True).order_by(Organization.name).all()
        self.organization_id.choices = [(org.id, org.name) for org in organizations]

    def validate_slug(self, field):
        """Custom validation for slug"""
        if field.data:
            # Strip whitespace
            field.data = field.data.strip().lower()

            # Check minimum length
            if len(field.data) < 2:
                raise ValidationError("Slug must be at least 2 characters long.")

            # Check format (lowercase alphanumeric with hyphens)
            if not re.match(r"^[a-z0-9-]+$", field.data):
                raise ValidationError("Slug must contain only lowercase letters, numbers, and hyphens.")

            # Check for duplicate slugs
            from flask_app.models import Event

            existing = Event.query.filter_by(slug=field.data).first()
            if existing:
                raise ValidationError("An event with this slug already exists.")

    def validate_start_date(self, field):
        """Custom validation for start date"""
        if field.data:
            # Ensure start date is not in the past (allow some flexibility for drafts)
            if field.data < datetime.now() and self.event_status.data != "draft":
                raise ValidationError("Start date cannot be in the past for non-draft events.")

    def validate_registration_deadline(self, field):
        """Custom validation for registration deadline"""
        if field.data and self.start_date.data:
            # Registration deadline should be before event start
            if field.data >= self.start_date.data:
                raise ValidationError("Registration deadline must be before the event start date.")

    def validate_virtual_link(self, field):
        """Custom validation for virtual link"""
        if field.data:
            field.data = field.data.strip()
            if not field.data:  # If empty after strip, skip validation
                return
            # Check max length (500 characters)
            if len(field.data) > 500:
                raise ValidationError("Virtual link must be less than 500 characters.")
            # Validate URL format
            from urllib.parse import urlparse

            result = urlparse(field.data)
            if not all([result.scheme, result.netloc]):
                raise ValidationError("Please enter a valid URL.")

    def validate_cost(self, field):
        """Custom validation for cost"""
        if field.data:
            field.data = field.data.strip()
            if not field.data:
                return
            try:
                cost_value = float(field.data)
                if cost_value < 0:
                    raise ValidationError("Cost cannot be negative.")
                if cost_value > 999999.99:
                    raise ValidationError("Cost must be less than 1,000,000.")
            except ValueError:
                raise ValidationError("Please enter a valid number for cost.")


class UpdateEventForm(FlaskForm):
    """Form for updating existing events"""

    # Basic information
    title = StringField(
        "Event Title",
        validators=[
            DataRequired(message="Event title is required."),
            Length(max=200, message="Event title must be less than 200 characters."),
        ],
        render_kw={"placeholder": "Enter event title"},
    )
    slug = StringField(
        "Slug",
        validators=[
            DataRequired(message="Slug is required."),
            Length(max=100, message="Slug must be less than 100 characters."),
        ],
        render_kw={"placeholder": "event-slug"},
    )
    description = TextAreaField(
        "Description",
        validators=[Length(max=5000, message="Description must be less than 5000 characters.")],
        render_kw={"placeholder": "Enter event description", "rows": 4},
    )

    # Enums
    event_type = SelectField(
        "Event Type",
        validators=[DataRequired(message="Event type is required.")],
        choices=[],  # Will be populated in __init__
    )
    event_status = SelectField(
        "Event Status",
        validators=[DataRequired(message="Event status is required.")],
        choices=[],  # Will be populated in __init__
    )
    event_format = SelectField(
        "Event Format",
        validators=[DataRequired(message="Event format is required.")],
        choices=[],  # Will be populated in __init__
    )
    cancellation_reason = SelectField(
        "Cancellation Reason",
        validators=[Optional()],
        choices=[],  # Will be populated in __init__
    )

    # Dates and times
    start_date = DateTimeField(
        "Start Date & Time",
        validators=[DataRequired(message="Start date and time is required.")],
        format="%Y-%m-%dT%H:%M",
        render_kw={"type": "datetime-local"},
    )
    start_time = TimeField(
        "Start Time (Optional)",
        validators=[Optional()],
        render_kw={"placeholder": "HH:MM"},
    )
    duration = IntegerField(
        "Duration (minutes)",
        validators=[
            Optional(),
            NumberRange(min=1, max=10080, message="Duration must be between 1 and 10080 minutes (7 days)."),
        ],
        widget=NumberInput(),
        render_kw={"placeholder": "Enter duration in minutes"},
    )
    registration_deadline = DateTimeField(
        "Registration Deadline (Optional)",
        validators=[Optional()],
        format="%Y-%m-%dT%H:%M",
        render_kw={"type": "datetime-local"},
    )

    # Location
    location_name = StringField(
        "Location Name",
        validators=[Length(max=200, message="Location name must be less than 200 characters.")],
        render_kw={"placeholder": "Enter location name"},
    )
    location_address = TextAreaField(
        "Location Address",
        validators=[Length(max=1000, message="Location address must be less than 1000 characters.")],
        render_kw={"placeholder": "Enter full address", "rows": 3},
    )
    virtual_link = StringField(
        "Virtual Link",
        validators=[Length(max=500, message="Virtual link must be less than 500 characters.")],
        render_kw={"placeholder": "https://zoom.us/j/..."},
    )

    # Metadata
    capacity = IntegerField(
        "Capacity (Optional)",
        validators=[Optional(), NumberRange(min=1, message="Capacity must be at least 1.")],
        widget=NumberInput(),
        render_kw={"placeholder": "Enter maximum capacity"},
    )
    cost = StringField(
        "Cost (Optional)",
        validators=[Optional()],
        render_kw={"placeholder": "0.00"},
    )

    # Organization
    organization_id = SelectField(
        "Primary Organization",
        validators=[DataRequired(message="Organization is required.")],
        choices=[],  # Will be populated in __init__
        coerce=int,
    )

    submit = SubmitField("Save Changes")

    def __init__(self, *args, **kwargs):
        # Extract event from kwargs before calling super
        self.event = kwargs.pop("event", None)
        super(UpdateEventForm, self).__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from flask_app.models import CancellationReason, EventFormat, EventStatus, EventType, Organization

        # Set event_type choices
        self.event_type.choices = [
            (event_type.value, format_enum_display(event_type.value)) for event_type in EventType
        ]

        # Set event_status choices
        self.event_status.choices = [
            (event_status.value, format_enum_display(event_status.value)) for event_status in EventStatus
        ]

        # Set event_format choices
        self.event_format.choices = [
            (event_format.value, format_enum_display(event_format.value)) for event_format in EventFormat
        ]

        # Set cancellation_reason choices
        self.cancellation_reason.choices = [("", "None")] + [
            (reason.value, format_enum_display(reason.value)) for reason in CancellationReason
        ]

        # Set organization choices
        organizations = Organization.query.filter_by(is_active=True).order_by(Organization.name).all()
        self.organization_id.choices = [(org.id, org.name) for org in organizations]

    def validate_slug(self, field):
        """Custom validation for slug"""
        if field.data:
            # Strip whitespace
            field.data = field.data.strip().lower()

            # Check minimum length
            if len(field.data) < 2:
                raise ValidationError("Slug must be at least 2 characters long.")

            # Check format (lowercase alphanumeric with hyphens)
            if not re.match(r"^[a-z0-9-]+$", field.data):
                raise ValidationError("Slug must contain only lowercase letters, numbers, and hyphens.")

            # Check for duplicate slugs (excluding current event)
            try:
                from flask_app.models import Event

                existing = Event.query.filter_by(slug=field.data).first()
                if existing and (not self.event or existing.id != self.event.id):
                    raise ValidationError("An event with this slug already exists.")
            except ValidationError:
                raise
            except Exception:  # pragma: no cover - defensive logging
                current_app.logger.exception("Failed to validate event slug uniqueness")

    def validate_start_date(self, field):
        """Custom validation for start date"""
        if field.data:
            # Allow past dates for completed/cancelled events
            if field.data < datetime.now() and self.event_status.data not in ["draft", "completed", "cancelled"]:
                raise ValidationError("Start date cannot be in the past for active events.")

    def validate_registration_deadline(self, field):
        """Custom validation for registration deadline"""
        if field.data and self.start_date.data:
            # Registration deadline should be before event start
            if field.data >= self.start_date.data:
                raise ValidationError("Registration deadline must be before the event start date.")

    def validate_virtual_link(self, field):
        """Custom validation for virtual link"""
        if field.data:
            field.data = field.data.strip()
            if not field.data:
                return
            # Check max length (500 characters)
            if len(field.data) > 500:
                raise ValidationError("Virtual link must be less than 500 characters.")
            # Validate URL format
            from urllib.parse import urlparse

            result = urlparse(field.data)
            if not all([result.scheme, result.netloc]):
                raise ValidationError("Please enter a valid URL.")

    def validate_cost(self, field):
        """Custom validation for cost"""
        if field.data:
            field.data = field.data.strip()
            if not field.data:
                return
            try:
                cost_value = float(field.data)
                if cost_value < 0:
                    raise ValidationError("Cost cannot be negative.")
                if cost_value > 999999.99:
                    raise ValidationError("Cost must be less than 1,000,000.")
            except ValueError:
                raise ValidationError("Please enter a valid number for cost.")
