# flask_app/models/contact/base.py
"""
Base Contact model with comprehensive contact information.
Supports inheritance for sub-classes via contact_type discriminator.
"""

from datetime import date

from flask import current_app
from sqlalchemy import Enum, Index
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import validates

from ..base import BaseModel, db
from .enums import (
    AgeGroup,
    ContactStatus,
    ContactType,
    EducationLevel,
    Gender,
    PreferredLanguage,
    RaceEthnicity,
    RoleType,
    Salutation,
)
from .relationships import ContactRole


class Contact(BaseModel):
    """
    Base Contact model with comprehensive contact information.
    Supports inheritance for sub-classes via contact_type discriminator.
    """

    __tablename__ = "contacts"
    __mapper_args__ = {
        "polymorphic_identity": ContactType.CONTACT,
        "polymorphic_on": "contact_type",
    }

    id = db.Column(db.Integer, primary_key=True)
    contact_type = db.Column(
        Enum(ContactType, name="contact_type_enum"),
        nullable=False,
        default=ContactType.CONTACT,
        index=True,
    )

    # Name fields
    salutation = db.Column(
        Enum(Salutation, name="salutation_enum"), nullable=True
    )  # Mr., Mrs., Dr., etc.
    first_name = db.Column(db.String(100), nullable=False, index=True)
    middle_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=False, index=True)
    suffix = db.Column(db.String(20), nullable=True)  # Jr., Sr., III, etc.
    preferred_name = db.Column(db.String(100), nullable=True)

    # Demographics
    gender = db.Column(Enum(Gender, name="gender_enum"), nullable=True)
    race = db.Column(Enum(RaceEthnicity, name="race_ethnicity_enum"), nullable=True)
    birthdate = db.Column(db.Date, nullable=True, index=True)
    age_group = db.Column(
        Enum(AgeGroup, name="age_group_enum"), nullable=True
    )  # Computed or stored
    education_level = db.Column(
        Enum(EducationLevel, name="education_level_enum"), nullable=True
    )
    is_local = db.Column(
        db.Boolean, default=True, nullable=False
    )  # Whether contact is in local area and can volunteer/do work in person
    type = db.Column(
        db.String(100), nullable=True
    )  # General category separate from contact_type

    # Contact preferences
    do_not_call = db.Column(db.Boolean, default=False, nullable=False)
    do_not_email = db.Column(db.Boolean, default=False, nullable=False)
    do_not_contact = db.Column(db.Boolean, default=False, nullable=False)

    # Additional information
    preferred_language = db.Column(
        Enum(PreferredLanguage, name="preferred_language_enum"), nullable=True
    )
    status = db.Column(
        Enum(ContactStatus, name="contact_status_enum"),
        default=ContactStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    source = db.Column(db.String(200), nullable=True)  # How contact was acquired
    last_contact_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)  # Public notes
    internal_notes = db.Column(db.Text, nullable=True)  # Staff-only notes
    photo_url = db.Column(db.String(500), nullable=True)

    # Relationships
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True
    )  # Link to User account if applicable
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=True
    )  # Primary organization (if single org model)

    # Relationships
    user = db.relationship("User", foreign_keys=[user_id], backref="contacts")
    organization = db.relationship("Organization", foreign_keys=[organization_id])
    emails = db.relationship(
        "ContactEmail", back_populates="contact", cascade="all, delete-orphan"
    )
    phones = db.relationship(
        "ContactPhone", back_populates="contact", cascade="all, delete-orphan"
    )
    addresses = db.relationship(
        "ContactAddress", back_populates="contact", cascade="all, delete-orphan"
    )
    roles = db.relationship(
        "ContactRole", back_populates="contact", cascade="all, delete-orphan"
    )
    organization_links = db.relationship(
        "ContactOrganization", back_populates="contact", cascade="all, delete-orphan"
    )
    tags = db.relationship(
        "ContactTag", back_populates="contact", cascade="all, delete-orphan"
    )
    emergency_contacts = db.relationship(
        "EmergencyContact", back_populates="contact", cascade="all, delete-orphan"
    )

    # Indexes for performance
    __table_args__ = (
        Index("idx_contact_name", "last_name", "first_name"),
        Index("idx_contact_type_status", "contact_type", "status"),
    )

    def __repr__(self):
        return f"<Contact {self.get_full_name()} ({self.contact_type.value})>"

    # Validation methods
    @validates("birthdate")
    def validate_birthdate(self, key, value):
        """Validate birthdate is not in the future"""
        if value and value > date.today():
            raise ValueError("Birthdate cannot be in the future")
        return value

    # Helper methods
    def get_full_name(self):
        """Format full name with salutation and suffix"""
        parts = []
        if self.salutation:
            # Handle enum values
            salutation_str = (
                self.salutation.value if hasattr(self.salutation, "value") else str(self.salutation)
            )
            # Format salutation nicely (e.g., "mr" -> "Mr.")
            salutation_display = salutation_str.replace("_", " ").title().replace(" ", "")
            if salutation_display.lower() in ["mr", "mrs", "ms", "miss", "dr", "prof", "rev", "hon"]:
                salutation_display = salutation_display.capitalize() + "."
            parts.append(salutation_display)
        if self.first_name:
            parts.append(self.first_name)
        if self.middle_name:
            parts.append(self.middle_name)
        if self.last_name:
            parts.append(self.last_name)
        if self.suffix:
            parts.append(self.suffix)

        return " ".join(parts) if parts else "Unknown"

    def get_display_name(self):
        """Return preferred name or full name"""
        return self.preferred_name or self.get_full_name()

    def get_primary_email(self):
        """Get primary email address"""
        primary = next((e for e in self.emails if e.is_primary), None)
        return primary.email if primary else None

    def get_primary_phone(self):
        """Get primary phone number"""
        primary = next((p for p in self.phones if p.is_primary), None)
        return primary.phone_number if primary else None

    def get_primary_address(self):
        """Get primary address"""
        primary = next((a for a in self.addresses if a.is_primary), None)
        return primary

    def get_active_roles(self):
        """Get all active role types"""
        return [
            role.role_type
            for role in self.roles
            if role.is_active and role.end_date is None
        ]

    def has_role(self, role_type):
        """Check if contact has specific role (active)"""
        if isinstance(role_type, str):
            role_type = RoleType(role_type)
        return any(
            role.role_type == role_type
            and role.is_active
            and role.end_date is None
            for role in self.roles
        )

    def add_role(self, role_type, start_date=None, notes=None):
        """Add new role to contact"""
        if isinstance(role_type, str):
            role_type = RoleType(role_type)
        if start_date is None:
            start_date = date.today()

        # Check if role already exists and is active
        existing = ContactRole.query.filter_by(
            contact_id=self.id, role_type=role_type, end_date=None
        ).first()
        if existing:
            return existing, "Role already exists"

        role = ContactRole(
            contact_id=self.id, role_type=role_type, start_date=start_date, notes=notes
        )
        db.session.add(role)
        try:
            db.session.commit()
            return role, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding role to contact {self.id}: {str(e)}")
            return None, str(e)

    def end_role(self, role_type, end_date=None):
        """End a role (set end_date)"""
        if isinstance(role_type, str):
            role_type = RoleType(role_type)
        if end_date is None:
            end_date = date.today()

        role = ContactRole.query.filter_by(
            contact_id=self.id, role_type=role_type, end_date=None
        ).first()
        if role:
            role.end_date = end_date
            role.is_active = False
            try:
                db.session.commit()
                return True, None
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Error ending role for contact {self.id}: {str(e)}"
                )
                return False, str(e)
        return False, "Role not found"

    def calculate_age(self):
        """Compute age from birthdate"""
        if not self.birthdate:
            return None
        today = date.today()
        age = (
            today.year
            - self.birthdate.year
            - ((today.month, today.day) < (self.birthdate.month, self.birthdate.day))
        )
        return age

    def get_age_group(self):
        """Determine age group category"""
        age = self.calculate_age()
        if age is None:
            return None
        if age <= 12:
            return AgeGroup.CHILD
        elif age <= 17:
            return AgeGroup.TEEN
        elif age <= 64:
            return AgeGroup.ADULT
        else:
            return AgeGroup.SENIOR

    def update_age_group(self):
        """Update stored age_group based on current age"""
        self.age_group = self.get_age_group()
        try:
            db.session.commit()
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error updating age group for contact {self.id}: {str(e)}"
            )
            return False

    def can_contact(self, method="any"):
        """
        Check if contact preferences allow communication
        method: 'call', 'email', 'any'
        """
        if self.do_not_contact:
            return False
        if method == "call" and self.do_not_call:
            return False
        if method == "email" and self.do_not_email:
            return False
        return True

    def can_volunteer_in_person(self):
        """Check if contact is local and can volunteer/do work in person"""
        return self.is_local

    @staticmethod
    def find_by_email(email):
        """Find contact by email address"""
        try:
            from .info import ContactEmail

            contact_email = ContactEmail.query.filter_by(email=email, is_primary=True).first()
            return contact_email.contact if contact_email else None
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding contact by email {email}: {str(e)}")
            return None

    @staticmethod
    def find_by_phone(phone_number):
        """Find contact by phone number"""
        try:
            from .info import ContactPhone

            contact_phone = ContactPhone.query.filter_by(
                phone_number=phone_number, is_primary=True
            ).first()
            return contact_phone.contact if contact_phone else None
        except SQLAlchemyError as e:
            current_app.logger.error(
                f"Database error finding contact by phone {phone_number}: {str(e)}"
            )
            return None

