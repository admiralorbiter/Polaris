# flask_app/forms/admin.py

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, BooleanField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Email, ValidationError, EqualTo
from flask_app.models import User
import re

class CreateUserForm(FlaskForm):
    """Form for creating new users"""
    username = StringField(
        'Username',
        validators=[
            DataRequired(message="Username is required."),
            Length(min=3, max=64, message="Username must be between 3 and 64 characters.")
        ],
        render_kw={"placeholder": "Enter username"}
    )
    email = StringField(
        'Email',
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Invalid email address."),
            Length(max=120, message="Email must be less than 120 characters.")
        ],
        render_kw={"placeholder": "Enter email address"}
    )
    first_name = StringField(
        'First Name',
        validators=[Length(max=64, message="First name must be less than 64 characters.")],
        render_kw={"placeholder": "Enter first name"}
    )
    last_name = StringField(
        'Last Name',
        validators=[Length(max=64, message="Last name must be less than 64 characters.")],
        render_kw={"placeholder": "Enter last name"}
    )
    password = PasswordField(
        'Password',
        validators=[
            DataRequired(message="Password is required."),
            Length(min=8, message="Password must be at least 8 characters long.")
        ],
        render_kw={"placeholder": "Enter password"}
    )
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[
            DataRequired(message="Please confirm password."),
            EqualTo('password', message="Passwords must match.")
        ],
        render_kw={"placeholder": "Confirm password"}
    )
    is_active = BooleanField('Active User', default=True)
    is_admin = BooleanField('Admin User', default=False)
    submit = SubmitField('Create User')
    
    def validate_username(self, field):
        """Custom validation for username"""
        if field.data:
            field.data = field.data.strip()
            
            # Check for valid characters
            if not re.match(r'^[a-zA-Z0-9_-]+$', field.data):
                raise ValidationError('Username can only contain letters, numbers, underscores, and hyphens.')
            
            # Check if username already exists
            if User.find_by_username(field.data):
                raise ValidationError('Username already exists.')
    
    def validate_email(self, field):
        """Custom validation for email"""
        if field.data:
            field.data = field.data.strip().lower()
            
            # Check if email already exists
            if User.find_by_email(field.data):
                raise ValidationError('Email already exists.')
    
    def validate_password(self, field):
        """Custom validation for password"""
        if field.data:
            # Check for password complexity
            if len(field.data) < 8:
                raise ValidationError('Password must be at least 8 characters long.')
            
            # Check for at least one uppercase, lowercase, and digit
            if not re.search(r'[A-Z]', field.data):
                raise ValidationError('Password must contain at least one uppercase letter.')
            if not re.search(r'[a-z]', field.data):
                raise ValidationError('Password must contain at least one lowercase letter.')
            if not re.search(r'\d', field.data):
                raise ValidationError('Password must contain at least one digit.')

class UpdateUserForm(FlaskForm):
    """Form for updating user information"""
    username = StringField(
        'Username',
        validators=[
            DataRequired(message="Username is required."),
            Length(min=3, max=64, message="Username must be between 3 and 64 characters.")
        ],
        render_kw={"placeholder": "Enter username"}
    )
    email = StringField(
        'Email',
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Invalid email address."),
            Length(max=120, message="Email must be less than 120 characters.")
        ],
        render_kw={"placeholder": "Enter email address"}
    )
    first_name = StringField(
        'First Name',
        validators=[Length(max=64, message="First name must be less than 64 characters.")],
        render_kw={"placeholder": "Enter first name"}
    )
    last_name = StringField(
        'Last Name',
        validators=[Length(max=64, message="Last name must be less than 64 characters.")],
        render_kw={"placeholder": "Enter last name"}
    )
    is_active = BooleanField('Active User')
    is_admin = BooleanField('Admin User')
    submit = SubmitField('Update User')
    
    def __init__(self, user=None, *args, **kwargs):
        super(UpdateUserForm, self).__init__(*args, **kwargs)
        self.user = user
    
    def validate_username(self, field):
        """Custom validation for username"""
        if field.data and self.user:
            field.data = field.data.strip()
            
            # Check for valid characters
            if not re.match(r'^[a-zA-Z0-9_-]+$', field.data):
                raise ValidationError('Username can only contain letters, numbers, underscores, and hyphens.')
            
            # Check if username already exists (excluding current user)
            existing_user = User.find_by_username(field.data)
            if existing_user and existing_user.id != self.user.id:
                raise ValidationError('Username already exists.')
    
    def validate_email(self, field):
        """Custom validation for email"""
        if field.data and self.user:
            field.data = field.data.strip().lower()
            
            # Check if email already exists (excluding current user)
            existing_user = User.find_by_email(field.data)
            if existing_user and existing_user.id != self.user.id:
                raise ValidationError('Email already exists.')

class ChangePasswordForm(FlaskForm):
    """Form for changing user password"""
    new_password = PasswordField(
        'New Password',
        validators=[
            DataRequired(message="Password is required."),
            Length(min=8, message="Password must be at least 8 characters long.")
        ],
        render_kw={"placeholder": "Enter new password"}
    )
    confirm_password = PasswordField(
        'Confirm New Password',
        validators=[
            DataRequired(message="Please confirm password."),
            EqualTo('new_password', message="Passwords must match.")
        ],
        render_kw={"placeholder": "Confirm new password"}
    )
    submit = SubmitField('Change Password')
    
    def validate_new_password(self, field):
        """Custom validation for new password"""
        if field.data:
            # Check for password complexity
            if len(field.data) < 8:
                raise ValidationError('Password must be at least 8 characters long.')
            
            # Check for at least one uppercase, lowercase, and digit
            if not re.search(r'[A-Z]', field.data):
                raise ValidationError('Password must contain at least one uppercase letter.')
            if not re.search(r'[a-z]', field.data):
                raise ValidationError('Password must contain at least one lowercase letter.')
            if not re.search(r'\d', field.data):
                raise ValidationError('Password must contain at least one digit.')

class BulkUserActionForm(FlaskForm):
    """Form for bulk user actions"""
    action = SelectField(
        'Action',
        choices=[
            ('activate', 'Activate Users'),
            ('deactivate', 'Deactivate Users'),
            ('delete', 'Delete Users'),
            ('export', 'Export User Data')
        ],
        validators=[DataRequired(message="Please select an action.")]
    )
    user_ids = StringField(
        'User IDs',
        validators=[DataRequired(message="Please select at least one user.")],
        render_kw={"placeholder": "Comma-separated user IDs"}
    )
    submit = SubmitField('Execute Action')
    
    def validate_user_ids(self, field):
        """Validate user IDs"""
        if field.data:
            try:
                ids = [int(id.strip()) for id in field.data.split(',') if id.strip()]
                if not ids:
                    raise ValidationError("Please provide valid user IDs.")
                self.user_ids_list = ids
            except ValueError:
                raise ValidationError("User IDs must be numbers separated by commas.")
