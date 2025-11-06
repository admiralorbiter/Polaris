# flask_app/models/contact/info.py
"""
Contact information models: Email, Phone, Address
"""

from flask import current_app
from sqlalchemy import Enum, Index
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import validates

from ..base import BaseModel, db
from .enums import AddressType, EmailType, PhoneType


class ContactEmail(BaseModel):
    """Email addresses for contacts"""

    __tablename__ = "contact_emails"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    email_type = db.Column(Enum(EmailType, name="email_type_enum"), nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    contact = db.relationship("Contact", back_populates="emails")

    # Constraints
    __table_args__ = (
        Index("idx_contact_email", "email"),
        db.UniqueConstraint("contact_id", "email", name="_contact_email_uc"),
    )

    def __repr__(self):
        return f"<ContactEmail {self.email} ({self.email_type.value})>"

    @validates("email")
    def validate_email(self, key, value):
        """Validate email format"""
        if value:
            from email_validator import validate_email, EmailNotValidError

            try:
                validate_email(value)
            except EmailNotValidError:
                raise ValueError(f"Invalid email format: {value}")
        return value

    @staticmethod
    def ensure_single_primary(contact_id, exclude_id=None):
        """Ensure only one primary email per contact"""
        try:
            # Set all other emails to non-primary
            query = ContactEmail.query.filter_by(contact_id=contact_id, is_primary=True)
            if exclude_id:
                query = query.filter(ContactEmail.id != exclude_id)
            for email in query.all():
                email.is_primary = False
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error ensuring single primary email for contact {contact_id}: {str(e)}"
            )


class ContactPhone(BaseModel):
    """Phone numbers for contacts"""

    __tablename__ = "contact_phones"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    phone_type = db.Column(Enum(PhoneType, name="phone_type_enum"), nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    can_text = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    contact = db.relationship("Contact", back_populates="phones")

    # Constraints
    __table_args__ = (
        Index("idx_contact_phone", "phone_number"),
        db.UniqueConstraint("contact_id", "phone_number", name="_contact_phone_uc"),
    )

    def __repr__(self):
        return f"<ContactPhone {self.phone_number} ({self.phone_type.value})>"

    @staticmethod
    def ensure_single_primary(contact_id, exclude_id=None):
        """Ensure only one primary phone per contact"""
        try:
            query = ContactPhone.query.filter_by(contact_id=contact_id, is_primary=True)
            if exclude_id:
                query = query.filter(ContactPhone.id != exclude_id)
            for phone in query.all():
                phone.is_primary = False
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error ensuring single primary phone for contact {contact_id}: {str(e)}"
            )


class ContactAddress(BaseModel):
    """Addresses for contacts"""

    __tablename__ = "contact_addresses"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    address_type = db.Column(Enum(AddressType, name="address_type_enum"), nullable=False)
    street_address_1 = db.Column(db.String(255), nullable=False)
    street_address_2 = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(50), nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    country = db.Column(db.String(100), default="US", nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    contact = db.relationship("Contact", back_populates="addresses")

    def __repr__(self):
        return f"<ContactAddress {self.city}, {self.state} ({self.address_type.value})>"

    def get_full_address(self):
        """Get formatted full address"""
        parts = [self.street_address_1]
        if self.street_address_2:
            parts.append(self.street_address_2)
        parts.extend([f"{self.city}, {self.state} {self.postal_code}"])
        if self.country != "US":
            parts.append(self.country)
        return ", ".join(parts)

    @staticmethod
    def ensure_single_primary(contact_id, exclude_id=None):
        """Ensure only one primary address per contact"""
        try:
            query = ContactAddress.query.filter_by(contact_id=contact_id, is_primary=True)
            if exclude_id:
                query = query.filter(ContactAddress.id != exclude_id)
            for address in query.all():
                address.is_primary = False
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error ensuring single primary address for contact {contact_id}: {str(e)}"
            )

