# flask_app/models/contact/volunteer.py
"""
Volunteer model and related models (Skills, Interests, Availability, Hours)
"""

from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import CheckConstraint, Enum, Index, func
from sqlalchemy.exc import SQLAlchemyError

from ..base import BaseModel, db
from .base import Contact
from .enums import ClearanceStatus, ContactType, VolunteerStatus


class Volunteer(Contact):
    """Volunteer sub-class extending Contact"""

    __tablename__ = "volunteers"
    __mapper_args__ = {
        "polymorphic_identity": ContactType.VOLUNTEER,
    }

    id = db.Column(db.Integer, db.ForeignKey("contacts.id"), primary_key=True)

    # Volunteer status (separate from base Contact.status)
    volunteer_status = db.Column(
        Enum(VolunteerStatus, name="volunteer_status_enum"),
        default=VolunteerStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    # Core volunteer information
    title = db.Column(db.String(200), nullable=True)  # Job title/position
    industry = db.Column(db.String(200), nullable=True)  # Industry/field they work in
    clearance_status = db.Column(
        Enum(ClearanceStatus, name="clearance_status_enum"), nullable=True
    )  # Background check/clearance status

    # Volunteer dates
    first_volunteer_date = db.Column(db.Date, nullable=True, index=True)
    last_volunteer_date = db.Column(db.Date, nullable=True, index=True)
    total_volunteer_hours = db.Column(db.Numeric(10, 2), default=0.0, nullable=False)  # Cumulative hours volunteered

    # Legacy fields (kept for backward compatibility, will be replaced by separate models)
    start_date = db.Column(db.Date, nullable=True)  # Deprecated - use first_volunteer_date
    end_date = db.Column(db.Date, nullable=True)  # Deprecated - use volunteer_status

    # Relationships
    skills = db.relationship("VolunteerSkill", back_populates="volunteer", cascade="all, delete-orphan")
    interests = db.relationship("VolunteerInterest", back_populates="volunteer", cascade="all, delete-orphan")
    availability_slots = db.relationship(
        "VolunteerAvailability",
        back_populates="volunteer",
        cascade="all, delete-orphan",
    )
    volunteer_hours = db.relationship("VolunteerHours", back_populates="volunteer", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Volunteer {self.get_full_name()} ({self.volunteer_status.value})>"

    # Helper methods
    def get_total_hours(self, recalculate=False):
        """
        Get total volunteer hours.
        If recalculate=True, sum from volunteer_hours records and update total_volunteer_hours.
        Otherwise, return stored total_volunteer_hours.
        """
        if recalculate:
            total = db.session.query(func.sum(VolunteerHours.hours_worked)).filter_by(volunteer_id=self.id).scalar()
            self.total_volunteer_hours = float(total) if total else 0.0
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating total hours for volunteer {self.id}: {str(e)}")
        return float(self.total_volunteer_hours) if self.total_volunteer_hours else 0.0

    def get_skills_list(self, category=None, verified_only=False):
        """Get list of skills, optionally filtered by category or verification status"""
        query = VolunteerSkill.query.filter_by(volunteer_id=self.id)
        if category:
            query = query.filter_by(skill_category=category)
        if verified_only:
            query = query.filter_by(verified=True)
        return query.all()

    def get_interests_list(self, category=None):
        """Get list of interests, optionally filtered by category"""
        query = VolunteerInterest.query.filter_by(volunteer_id=self.id)
        if category:
            query = query.filter_by(interest_category=category)
        return query.all()

    def is_available_on_day(self, day_of_week, date=None):
        """
        Check if volunteer is available on a specific day of week.
        day_of_week: 0=Monday, 1=Tuesday, ..., 6=Sunday
        date: Optional date to check if availability is active for that date
        """
        query = VolunteerAvailability.query.filter_by(volunteer_id=self.id, day_of_week=day_of_week, is_active=True)
        availabilities = query.all()

        if not availabilities:
            return False

        # If date provided, check if availability is active for that date
        if date:
            for avail in availabilities:
                # If recurring and no end_date, always available
                if avail.is_recurring and not avail.end_date:
                    return True
                # If recurring with dates, check if date is within range
                if avail.is_recurring and avail.start_date and avail.end_date:
                    if avail.start_date <= date <= avail.end_date:
                        return True
                # If one-time, check if date matches start_date
                if not avail.is_recurring and avail.start_date == date:
                    return True
            return False

        # No date provided, just check if any active availability exists
        return len(availabilities) > 0

    def get_availability_for_day(self, day_of_week):
        """Get all availability slots for a specific day of week"""
        return VolunteerAvailability.query.filter_by(
            volunteer_id=self.id, day_of_week=day_of_week, is_active=True
        ).all()

    def add_skill(self, skill_name, skill_category=None, proficiency_level=None, verified=False, notes=None):
        """Add a skill to the volunteer"""
        # Check if skill already exists
        existing = VolunteerSkill.query.filter_by(volunteer_id=self.id, skill_name=skill_name).first()
        if existing:
            return existing, "Skill already exists"

        skill = VolunteerSkill(
            volunteer_id=self.id,
            skill_name=skill_name,
            skill_category=skill_category,
            proficiency_level=proficiency_level,
            verified=verified,
            notes=notes,
        )
        db.session.add(skill)
        try:
            db.session.commit()
            return skill, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding skill to volunteer {self.id}: {str(e)}")
            return None, str(e)

    def add_interest(self, interest_name, interest_category=None, notes=None):
        """Add an interest to the volunteer"""
        # Check if interest already exists
        existing = VolunteerInterest.query.filter_by(volunteer_id=self.id, interest_name=interest_name).first()
        if existing:
            return existing, "Interest already exists"

        interest = VolunteerInterest(
            volunteer_id=self.id,
            interest_name=interest_name,
            interest_category=interest_category,
            notes=notes,
        )
        db.session.add(interest)
        try:
            db.session.commit()
            return interest, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding interest to volunteer {self.id}: {str(e)}")
            return None, str(e)

    def add_availability(
        self,
        day_of_week,
        start_time,
        end_time,
        timezone="UTC",
        is_recurring=True,
        start_date=None,
        end_date=None,
        notes=None,
    ):
        """Add an availability slot for the volunteer"""
        availability = VolunteerAvailability(
            volunteer_id=self.id,
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            is_recurring=is_recurring,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
        )
        db.session.add(availability)
        try:
            db.session.commit()
            return availability, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding availability to volunteer {self.id}: {str(e)}")
            return None, str(e)

    def log_hours(
        self,
        volunteer_date,
        hours_worked,
        organization_id=None,
        activity_type=None,
        notes=None,
        verified_by=None,
    ):
        """Log volunteer hours and update total"""
        hours_entry = VolunteerHours(
            volunteer_id=self.id,
            organization_id=organization_id,
            volunteer_date=volunteer_date,
            hours_worked=hours_worked,
            activity_type=activity_type,
            notes=notes,
            verified_by=verified_by,
        )
        if verified_by:
            hours_entry.verified_at = datetime.now(timezone.utc)

        db.session.add(hours_entry)

        # Update total hours and last volunteer date
        self.total_volunteer_hours = float(self.total_volunteer_hours or 0) + float(hours_worked)
        if not self.first_volunteer_date or volunteer_date < self.first_volunteer_date:
            self.first_volunteer_date = volunteer_date
        if not self.last_volunteer_date or volunteer_date > self.last_volunteer_date:
            self.last_volunteer_date = volunteer_date

        try:
            db.session.commit()
            return hours_entry, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging hours for volunteer {self.id}: {str(e)}")
            return None, str(e)

    def get_hours_by_date_range(self, start_date, end_date):
        """Get all volunteer hours within a date range"""
        return VolunteerHours.query.filter(
            VolunteerHours.volunteer_id == self.id,
            VolunteerHours.volunteer_date >= start_date,
            VolunteerHours.volunteer_date <= end_date,
        ).all()

    def get_hours_by_organization(self, organization_id):
        """Get all volunteer hours for a specific organization"""
        return VolunteerHours.query.filter_by(volunteer_id=self.id, organization_id=organization_id).all()

    def get_organizations(self, status="current"):
        """
        Get organizations associated with this volunteer.
        status: 'current' (end_date is None) or 'past' (end_date is set) or 'all'
        Returns list of ContactOrganization objects
        """
        from .relationships import ContactOrganization

        query = ContactOrganization.query.filter_by(contact_id=self.id)

        if status == "current":
            query = query.filter(ContactOrganization.end_date.is_(None))
        elif status == "past":
            query = query.filter(ContactOrganization.end_date.isnot(None))
        # If status is 'all', no additional filter

        return query.all()

    def get_current_organizations(self):
        """Get all current (active) organization relationships for this volunteer"""
        return self.get_organizations(status="current")

    def get_total_hours_by_organization(self, organization_id):
        """Get total volunteer hours for a specific organization"""
        total = (
            db.session.query(func.sum(VolunteerHours.hours_worked))
            .filter_by(volunteer_id=self.id, organization_id=organization_id)
            .scalar()
        )
        return float(total) if total else 0.0


class VolunteerSkill(BaseModel):
    """Skills that volunteers possess - separate model for expandability"""

    __tablename__ = "volunteer_skills"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    skill_name = db.Column(db.String(200), nullable=False)
    skill_category = db.Column(db.String(100), nullable=True)  # e.g., "Technical", "Language", "Medical"
    proficiency_level = db.Column(
        db.String(50), nullable=True
    )  # e.g., "Beginner", "Intermediate", "Advanced", "Expert"
    verified = db.Column(db.Boolean, default=False, nullable=False)  # Whether skill is verified
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    volunteer = db.relationship("Volunteer", back_populates="skills")

    # Constraints
    __table_args__ = (
        Index("idx_volunteer_skill", "volunteer_id", "skill_name"),
        db.UniqueConstraint("volunteer_id", "skill_name", name="_volunteer_skill_uc"),
    )

    def __repr__(self):
        return f"<VolunteerSkill {self.skill_name} ({self.proficiency_level or 'N/A'})>"


class VolunteerInterest(BaseModel):
    """Interests that volunteers have - separate model for expandability"""

    __tablename__ = "volunteer_interests"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    interest_name = db.Column(db.String(200), nullable=False)
    interest_category = db.Column(db.String(100), nullable=True)  # e.g., "Community", "Education", "Environment"
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    volunteer = db.relationship("Volunteer", back_populates="interests")

    # Constraints
    __table_args__ = (
        Index("idx_volunteer_interest", "volunteer_id", "interest_name"),
        db.UniqueConstraint("volunteer_id", "interest_name", name="_volunteer_interest_uc"),
    )

    def __repr__(self):
        return f"<VolunteerInterest {self.interest_name}>"


class VolunteerAvailability(BaseModel):
    """Availability slots for volunteers - separate model for expandability"""

    __tablename__ = "volunteer_availability"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday, 1=Tuesday, ..., 6=Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    timezone = db.Column(db.String(50), default="UTC", nullable=False)
    is_recurring = db.Column(db.Boolean, default=True, nullable=False)  # Recurring weekly vs one-time
    start_date = db.Column(db.Date, nullable=True)  # For temporary availability, when it starts
    end_date = db.Column(db.Date, nullable=True)  # For temporary availability, when it ends (null = ongoing)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    volunteer = db.relationship("Volunteer", back_populates="availability_slots")

    # Constraints
    __table_args__ = (
        Index("idx_volunteer_availability", "volunteer_id", "day_of_week"),
        CheckConstraint("end_time > start_time", name="check_time_range"),
    )

    def __repr__(self):
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_name = day_names[self.day_of_week] if 0 <= self.day_of_week <= 6 else f"Day {self.day_of_week}"
        return f"<VolunteerAvailability {day_name} {self.start_time}-{self.end_time}>"


class VolunteerHours(BaseModel):
    """Detailed time tracking for volunteers - separate model for reporting and analytics"""

    __tablename__ = "volunteer_hours"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=True
    )  # Which org they volunteered for
    volunteer_date = db.Column(db.Date, nullable=False, index=True)
    hours_worked = db.Column(db.Numeric(5, 2), nullable=False)  # Up to 999.99 hours per entry
    activity_type = db.Column(db.String(100), nullable=True)  # e.g., "Event Support", "Tutoring", "Administrative"
    notes = db.Column(db.Text, nullable=True)
    verified_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # User who verified the hours
    verified_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    volunteer = db.relationship("Volunteer", back_populates="volunteer_hours")
    organization = db.relationship("Organization", foreign_keys=[organization_id])
    verifier = db.relationship("User", foreign_keys=[verified_by])

    # Constraints
    __table_args__ = (
        Index("idx_volunteer_hours_date", "volunteer_date"),
        Index("idx_volunteer_hours_volunteer_date", "volunteer_id", "volunteer_date"),
        Index("idx_volunteer_hours_org_date", "organization_id", "volunteer_date"),
        CheckConstraint("hours_worked > 0", name="check_positive_hours"),
    )

    def __repr__(self):
        return f"<VolunteerHours {self.volunteer_date} - {self.hours_worked} hours>"
