# flask_app/models/organization.py

from flask import current_app
from sqlalchemy import Enum, Index, func
from sqlalchemy.exc import SQLAlchemyError

from .base import BaseModel, db
from .contact.enums import AddressType, OrganizationType


class Organization(BaseModel):
    """Model for representing organizations (schools, etc.)"""

    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    settings = db.Column(db.Text, nullable=True)  # JSON string for additional settings

    # Organization type and classification
    organization_type = db.Column(
        Enum(OrganizationType, name="organization_type_enum"),
        default=OrganizationType.OTHER,
        nullable=False,
        index=True,
    )

    # Contact information
    website = db.Column(db.String(500), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(255), nullable=True)

    # Business/legal information
    tax_id = db.Column(db.String(50), nullable=True)  # EIN for non-profits, tax ID for businesses

    # Visual/branding
    logo_url = db.Column(db.String(500), nullable=True)

    # Contact person
    contact_person_name = db.Column(db.String(200), nullable=True)
    contact_person_title = db.Column(db.String(100), nullable=True)

    # Dates
    founded_date = db.Column(db.Date, nullable=True)

    # Relationships
    users = db.relationship("UserOrganization", back_populates="organization", cascade="all, delete-orphan")
    feature_flags = db.relationship(
        "OrganizationFeatureFlag", back_populates="organization", cascade="all, delete-orphan"
    )
    addresses = db.relationship("OrganizationAddress", back_populates="organization", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (Index("idx_org_type_active", "organization_type", "is_active"),)

    def __repr__(self):
        return f"<Organization {self.name}>"

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

    def get_primary_address(self):
        """Get the primary address for this organization, or None if no address exists"""
        return next((addr for addr in self.addresses if addr.is_primary), None)

    def get_active_volunteers(self):
        """Get all active volunteers associated with this organization"""
        from .contact.enums import VolunteerStatus
        from .contact.relationships import ContactOrganization
        from .contact.volunteer import Volunteer

        try:
            # Get current organization relationships for volunteers
            org_links = ContactOrganization.query.filter_by(organization_id=self.id, end_date=None).all()

            # Get volunteer contacts
            volunteer_ids = [link.contact_id for link in org_links]
            if not volunteer_ids:
                return []

            volunteers = (
                Volunteer.query.filter(Volunteer.id.in_(volunteer_ids))
                .filter_by(volunteer_status=VolunteerStatus.ACTIVE)
                .all()
            )
            return volunteers
        except SQLAlchemyError as e:
            current_app.logger.error(f"Error getting active volunteers for organization {self.id}: {str(e)}")
            return []

    def get_total_volunteer_hours(self):
        """Get total volunteer hours logged for this organization"""
        from .contact.volunteer import VolunteerHours

        try:
            total = db.session.query(func.sum(VolunteerHours.hours_worked)).filter_by(organization_id=self.id).scalar()
            return float(total) if total else 0.0
        except SQLAlchemyError as e:
            current_app.logger.error(f"Error getting total volunteer hours for organization {self.id}: {str(e)}")
            return 0.0


class OrganizationAddress(BaseModel):
    """Addresses for organizations"""

    __tablename__ = "organization_addresses"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    address_type = db.Column(Enum(AddressType, name="address_type_enum"), nullable=False)
    street_address_1 = db.Column(db.String(255), nullable=False)
    street_address_2 = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(50), nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    country = db.Column(db.String(100), default="US", nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    organization = db.relationship("Organization", back_populates="addresses")

    def __repr__(self):
        return f"<OrganizationAddress {self.city}, {self.state} ({self.address_type.value})>"

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
    def ensure_single_primary(organization_id, exclude_id=None):
        """Ensure only one primary address per organization"""
        try:
            query = OrganizationAddress.query.filter_by(organization_id=organization_id, is_primary=True)
            if exclude_id:
                query = query.filter(OrganizationAddress.id != exclude_id)
            for address in query.all():
                address.is_primary = False
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error ensuring single primary address for organization {organization_id}: {str(e)}"
            )
