# flask_app/forms/organization.py

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length, ValidationError, Optional
from flask_app.models import Organization
import re


def optional_length(max=-1, min=-1, message=None):
    """Validator that checks length only if field has a value"""
    def _optional_length(form, field):
        if field.data:
            # Check length directly
            data_len = len(field.data)
            if max != -1 and data_len > max:
                from wtforms.validators import ValidationError
                if message:
                    raise ValidationError(message)
                else:
                    raise ValidationError(f"Field must be less than {max + 1} characters long.")
            if min != -1 and data_len < min:
                from wtforms.validators import ValidationError
                if message:
                    raise ValidationError(message)
                else:
                    raise ValidationError(f"Field must be at least {min} characters long.")
    return _optional_length


def generate_slug(name):
    """Generate a URL-friendly slug from a name"""
    slug = name.lower()
    slug = re.sub(r'[_\s]+', '-', slug)
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


class CreateOrganizationForm(FlaskForm):
    """Form for creating new organizations"""
    name = StringField(
        'Organization Name',
        validators=[
            DataRequired(message="Organization name is required."),
            Length(min=2, max=200, message="Organization name must be between 2 and 200 characters.")
        ],
        render_kw={"placeholder": "Enter organization name"}
    )
    slug = StringField(
        'Slug (URL identifier)',
        validators=[
            DataRequired(message="Slug is required."),
            Length(min=2, max=100, message="Slug must be between 2 and 100 characters.")
        ],
        render_kw={"placeholder": "Enter URL-friendly slug (auto-generated from name)"}
    )
    description = TextAreaField(
        'Description',
        validators=[optional_length(max=1000, message="Description must be less than 1000 characters.")],
        render_kw={"placeholder": "Enter organization description (optional)", "rows": 4}
    )
    is_active = BooleanField('Active Organization', default=True)
    submit = SubmitField('Create Organization')
    
    def validate_name(self, field):
        """Custom validation for organization name"""
        if field.data:
            field.data = field.data.strip()
            
            # Check if organization name already exists
            if Organization.query.filter_by(name=field.data).first():
                raise ValidationError('An organization with this name already exists.')
    
    def validate_slug(self, field):
        """Custom validation for slug"""
        if field.data:
            field.data = field.data.strip().lower()
            
            # Check for valid characters (lowercase letters, numbers, hyphens only)
            if not re.match(r'^[a-z0-9\-]+$', field.data):
                raise ValidationError('Slug can only contain lowercase letters, numbers, and hyphens.')
            
            # Check if slug already exists
            if Organization.find_by_slug(field.data):
                raise ValidationError('An organization with this slug already exists.')


class UpdateOrganizationForm(FlaskForm):
    """Form for updating organization information"""
    name = StringField(
        'Organization Name',
        validators=[
            DataRequired(message="Organization name is required."),
            Length(min=2, max=200, message="Organization name must be between 2 and 200 characters.")
        ],
        render_kw={"placeholder": "Enter organization name"}
    )
    slug = StringField(
        'Slug (URL identifier)',
        validators=[
            DataRequired(message="Slug is required."),
            Length(min=2, max=100, message="Slug must be between 2 and 100 characters.")
        ],
        render_kw={"placeholder": "Enter URL-friendly slug"}
    )
    description = TextAreaField(
        'Description',
        validators=[optional_length(max=1000, message="Description must be less than 1000 characters.")],
        render_kw={"placeholder": "Enter organization description (optional)", "rows": 4}
    )
    is_active = BooleanField('Active Organization')
    submit = SubmitField('Update Organization')
    
    def __init__(self, organization=None, *args, **kwargs):
        super(UpdateOrganizationForm, self).__init__(*args, **kwargs)
        self.organization = organization
    
    def validate_name(self, field):
        """Custom validation for organization name"""
        if field.data and self.organization:
            field.data = field.data.strip()
            
            # Check if organization name already exists (excluding current organization)
            existing = Organization.query.filter_by(name=field.data).first()
            if existing and existing.id != self.organization.id:
                raise ValidationError('An organization with this name already exists.')
    
    def validate_slug(self, field):
        """Custom validation for slug"""
        if field.data and self.organization:
            field.data = field.data.strip().lower()
            
            # Check for valid characters
            if not re.match(r'^[a-z0-9\-]+$', field.data):
                raise ValidationError('Slug can only contain lowercase letters, numbers, and hyphens.')
            
            # Check if slug already exists (excluding current organization)
            existing = Organization.find_by_slug(field.data)
            if existing and existing.id != self.organization.id:
                raise ValidationError('An organization with this slug already exists.')

