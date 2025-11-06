# flask_app/models/contact/relationships.py
"""
Contact relationship models: Roles, Organizations, Tags, Emergency Contacts
"""

from datetime import date

from flask import current_app
from sqlalchemy import CheckConstraint, Enum, Index
from sqlalchemy.exc import SQLAlchemyError

from ..base import BaseModel, db
from .enums import RoleType


class ContactRole(BaseModel):
    """
    Junction table for multi-class support.
    Tracks role assignments with start/end dates for history.
    """

    __tablename__ = "contact_roles"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    role_type = db.Column(Enum(RoleType, name="role_type_enum"), nullable=False)
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date, nullable=True)  # null = active
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)  # Role-specific notes

    # Relationships
    contact = db.relationship("Contact", back_populates="roles")

    # Constraints
    # Note: Uniqueness of active roles (end_date IS NULL) is enforced in application logic
    # Partial unique constraints are database-specific and not portable
    __table_args__ = (
        Index("idx_contact_role", "contact_id", "role_type"),
    )

    def __repr__(self):
        status = "active" if self.is_active and self.end_date is None else "inactive"
        return f"<ContactRole {self.role_type.value} ({status})>"

    def deactivate(self, end_date=None):
        """Deactivate this role"""
        if end_date is None:
            end_date = date.today()
        self.end_date = end_date
        self.is_active = False
        try:
            db.session.commit()
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error deactivating role {self.id}: {str(e)}")
            return False


class ContactOrganization(BaseModel):
    """
    Junction table for many-to-many relationship between contacts and organizations.
    Supports multiple organizations per contact with primary flag.
    """

    __tablename__ = "contact_organizations"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False
    )
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date, nullable=True)  # null = active

    # Relationships
    contact = db.relationship("Contact", back_populates="organization_links")
    organization = db.relationship("Organization", foreign_keys=[organization_id])

    # Constraints
    __table_args__ = (
        Index("idx_contact_org", "contact_id", "organization_id"),
        db.UniqueConstraint("contact_id", "organization_id", name="_contact_org_uc"),
    )

    def __repr__(self):
        return f"<ContactOrganization contact={self.contact_id} org={self.organization_id}>"


class ContactTag(BaseModel):
    """Flexible categorization tags for contacts"""

    __tablename__ = "contact_tags"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    tag_name = db.Column(db.String(100), nullable=False)

    # Relationships
    contact = db.relationship("Contact", back_populates="tags")

    # Constraints
    __table_args__ = (
        Index("idx_contact_tag", "tag_name"),
        db.UniqueConstraint("contact_id", "tag_name", name="_contact_tag_uc"),
    )

    def __repr__(self):
        return f"<ContactTag {self.tag_name}>"


class EmergencyContact(BaseModel):
    """Emergency contact information for contacts"""

    __tablename__ = "emergency_contacts"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    relationship = db.Column(db.String(100), nullable=True)  # parent, spouse, sibling, etc.
    phone_number = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    contact = db.relationship("Contact", back_populates="emergency_contacts")

    def __repr__(self):
        return f"<EmergencyContact {self.first_name} {self.last_name}>"

    def get_full_name(self):
        """Get full name of emergency contact"""
        return f"{self.first_name} {self.last_name}".strip()

