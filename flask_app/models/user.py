# app/models/user.py

from datetime import datetime, timezone
from flask_login import UserMixin
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from .base import db, BaseModel

class User(BaseModel, UserMixin):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    last_login = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def get_full_name(self):
        """Return the user's full name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username
    
    def update_last_login(self):
        """Update the last login timestamp"""
        try:
            self.last_login = datetime.now(timezone.utc)
            db.session.commit()
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating last login for user {self.id}: {str(e)}")
            return False
    
    @staticmethod
    def find_by_username(username):
        """Find user by username with error handling"""
        try:
            return User.query.filter_by(username=username).first()
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding user by username {username}: {str(e)}")
            return None
    
    @staticmethod
    def find_by_email(email):
        """Find user by email with error handling"""
        try:
            return User.query.filter_by(email=email).first()
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding user by email {email}: {str(e)}")
            return None
