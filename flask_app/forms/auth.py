# app/forms/auth.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError
import re

class LoginForm(FlaskForm):
    username = StringField(
        'Username', 
        validators=[
            DataRequired(message="Username is required."),
            Length(min=3, max=64, message="Username must be between 3 and 64 characters.")
        ],
        render_kw={"placeholder": "Enter your username", "autocomplete": "username"}
    )
    password = PasswordField(
        'Password', 
        validators=[
            DataRequired(message="Password is required."),
            Length(min=1, message="Password cannot be empty.")
        ],
        render_kw={"placeholder": "Enter your password", "autocomplete": "current-password"}
    )
    submit = SubmitField('Login')
    
    def validate_username(self, field):
        """Custom validation for username"""
        if field.data:
            # Remove any whitespace
            field.data = field.data.strip()
            
            # Check for valid characters (alphanumeric, underscore, hyphen)
            if not re.match(r'^[a-zA-Z0-9_-]+$', field.data):
                raise ValidationError('Username can only contain letters, numbers, underscores, and hyphens.')
    
    def validate_password(self, field):
        """Custom validation for password"""
        if field.data:
            # Check for minimum security requirements
            if len(field.data) < 6:
                raise ValidationError('Password must be at least 6 characters long.')
