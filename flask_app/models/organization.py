# flask_app/models/organization.py

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from .base import db, BaseModel


class Organization(BaseModel):
    """Model for representing organizations (schools, etc.)"""
    __tablename__ = 'organizations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    settings = db.Column(db.Text, nullable=True)  # JSON string for additional settings
    
    # Relationships
    users = db.relationship(
        'UserOrganization',
        back_populates='organization',
        cascade='all, delete-orphan'
    )
    feature_flags = db.relationship(
        'OrganizationFeatureFlag',
        back_populates='organization',
        cascade='all, delete-orphan'
    )
    
    def __repr__(self):
        return f'<Organization {self.name}>'
    
    @staticmethod
    def find_by_slug(slug):
        """Find organization by slug with error handling"""
        try:
            return Organization.query.filter_by(slug=slug).first()
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding organization by slug {slug}: {str(e)}")
            return None
    
    @staticmethod
    def find_by_id(org_id):
        """Find organization by ID with error handling"""
        try:
            return db.session.get(Organization, org_id)
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding organization by id {org_id}: {str(e)}")
            return None

