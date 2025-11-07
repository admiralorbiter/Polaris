# flask_app/models/event/models.py

from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import Enum, Index
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.types import DECIMAL

from ..base import BaseModel, db
from .enums import CancellationReason, EventFormat, EventStatus, EventType, EventVolunteerRole, RegistrationStatus


class Event(BaseModel):
    """Model for representing events in the volunteer management system"""

    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)

    # Enums
    event_type = db.Column(
        Enum(EventType, name="event_type_enum"),
        default=EventType.OTHER,
        nullable=False,
        index=True,
    )
    event_status = db.Column(
        Enum(EventStatus, name="event_status_enum"),
        default=EventStatus.DRAFT,
        nullable=False,
        index=True,
    )
    event_format = db.Column(
        Enum(EventFormat, name="event_format_enum"),
        default=EventFormat.IN_PERSON,
        nullable=False,
        index=True,
    )
    cancellation_reason = db.Column(
        Enum(CancellationReason, name="cancellation_reason_enum"),
        nullable=True,
    )

    # Dates and times
    start_date = db.Column(db.DateTime, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=True)  # Optional separate time field
    duration = db.Column(db.Integer, nullable=True)  # Duration in minutes
    end_date = db.Column(db.DateTime, nullable=True, index=True)  # Can be computed or stored

    # Location
    location_name = db.Column(db.String(200), nullable=True)
    location_address = db.Column(db.Text, nullable=True)
    virtual_link = db.Column(db.String(500), nullable=True)  # For virtual/hybrid events

    # Metadata
    capacity = db.Column(db.Integer, nullable=True)  # Maximum attendees
    registration_deadline = db.Column(db.DateTime, nullable=True)
    cost = db.Column(DECIMAL(10, 2), nullable=True)  # Event cost/fee

    # Foreign keys
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Relationships
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    organizations = db.relationship("EventOrganization", back_populates="event", cascade="all, delete-orphan")
    volunteers = db.relationship("EventVolunteer", back_populates="event", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (
        Index("idx_event_status_date", "event_status", "start_date"),
        Index("idx_event_type_status", "event_type", "event_status"),
    )

    def __repr__(self):
        return f"<Event {self.title} ({self.event_status.value})>"

    @staticmethod
    def find_by_slug(slug):
        """Find event by slug with error handling"""
        try:
            return Event.query.filter_by(slug=slug).first()
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding event by slug {slug}: {str(e)}")
            return None

    @staticmethod
    def find_by_id(event_id):
        """Find event by ID with error handling"""
        try:
            return db.session.get(Event, event_id)
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding event by id {event_id}: {str(e)}")
            return None

    def get_end_datetime(self):
        """Calculate end datetime from start_date + duration"""
        if not self.start_date:
            return None
        if self.end_date:
            return self.end_date
        if self.duration:
            return self.start_date + timedelta(minutes=self.duration)
        return None

    def _normalize_datetime(self, dt):
        """Normalize datetime to timezone-aware UTC for comparison"""
        if dt is None:
            return None
        if dt.tzinfo is None:
            # If naive, assume it's UTC
            return dt.replace(tzinfo=timezone.utc)
        # If already aware, convert to UTC
        return dt.astimezone(timezone.utc)

    def is_past(self):
        """Check if event is in the past"""
        if not self.start_date:
            return False
        end_datetime = self.get_end_datetime()
        comparison_time = end_datetime if end_datetime else self.start_date
        comparison_time = self._normalize_datetime(comparison_time)
        now = datetime.now(timezone.utc)
        return comparison_time < now

    def is_upcoming(self):
        """Check if event is in the future"""
        if not self.start_date:
            return False
        start_time = self._normalize_datetime(self.start_date)
        now = datetime.now(timezone.utc)
        return start_time > now

    def is_today(self):
        """Check if event is today"""
        if not self.start_date:
            return False
        now = datetime.now(timezone.utc)
        start_date_normalized = self._normalize_datetime(self.start_date)
        end_datetime = self.get_end_datetime()
        if end_datetime:
            end_datetime_normalized = self._normalize_datetime(end_datetime)
            return start_date_normalized.date() == now.date() or end_datetime_normalized.date() == now.date()
        return start_date_normalized.date() == now.date()

    def get_primary_organization(self):
        """Get the primary linked organization, or None if no organization exists"""
        try:
            primary_org_link = next((link for link in self.organizations if link.is_primary), None)
            return primary_org_link.organization if primary_org_link else None
        except (StopIteration, AttributeError):
            return None

    def get_volunteers_by_role(self, role):
        """Filter volunteers by role"""
        from ..contact import Contact

        try:
            volunteer_links = [
                link
                for link in self.volunteers
                if link.role == role and link.registration_status != RegistrationStatus.CANCELLED
            ]
            contact_ids = [link.contact_id for link in volunteer_links]
            if not contact_ids:
                return []
            return Contact.query.filter(Contact.id.in_(contact_ids)).all()
        except SQLAlchemyError as e:
            current_app.logger.error(f"Error getting volunteers by role for event {self.id}: {str(e)}")
            return []

    def get_attendance_count(self):
        """Count confirmed attendees"""
        try:
            return (
                EventVolunteer.query.filter_by(event_id=self.id)
                .filter_by(registration_status=RegistrationStatus.CONFIRMED)
                .count()
            )
        except SQLAlchemyError as e:
            current_app.logger.error(f"Error getting attendance count for event {self.id}: {str(e)}")
            return 0

    def can_register(self):
        """Check if registration is still open"""
        now = datetime.now(timezone.utc)
        if self.registration_deadline:
            deadline = self._normalize_datetime(self.registration_deadline)
            return now < deadline
        # If no deadline, allow registration until event starts
        if self.start_date:
            start = self._normalize_datetime(self.start_date)
            return now < start
        return True


class EventOrganization(BaseModel):
    """Junction table for many-to-many relationship between events and organizations"""

    __tablename__ = "event_organizations"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    event = db.relationship("Event", back_populates="organizations")
    organization = db.relationship("Organization", foreign_keys=[organization_id])

    # Constraints
    __table_args__ = (
        Index("idx_event_org", "event_id", "organization_id"),
        db.UniqueConstraint("event_id", "organization_id", name="_event_org_uc"),
    )

    def __repr__(self):
        return f"<EventOrganization event={self.event_id} org={self.organization_id}>"


class EventVolunteer(BaseModel):
    """Junction table for many-to-many relationship between events and contacts (volunteers)"""

    __tablename__ = "event_volunteers"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    role = db.Column(
        Enum(EventVolunteerRole, name="event_volunteer_role_enum"),
        default=EventVolunteerRole.ATTENDEE,
        nullable=False,
    )
    registration_status = db.Column(
        Enum(RegistrationStatus, name="registration_status_enum"),
        default=RegistrationStatus.PENDING,
        nullable=False,
        index=True,
    )
    attended = db.Column(db.Boolean, nullable=True)  # True if attended, False if no-show, None if not yet occurred

    # Relationships
    event = db.relationship("Event", back_populates="volunteers")
    contact = db.relationship("Contact", foreign_keys=[contact_id])

    # Constraints
    __table_args__ = (
        Index("idx_event_volunteer", "event_id", "contact_id"),
        Index("idx_event_volunteer_status", "event_id", "registration_status"),
        db.UniqueConstraint("event_id", "contact_id", name="_event_volunteer_uc"),
    )

    def __repr__(self):
        return f"<EventVolunteer event={self.event_id} contact={self.contact_id} role={self.role.value}>"
