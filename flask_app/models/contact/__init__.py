# flask_app/models/contact/__init__.py
"""
Contact models package.
Provides base Contact model and sub-classes (Volunteer, Student, Teacher).
"""

from .base import Contact
from .enums import (
    AddressType,
    AgeGroup,
    ContactStatus,
    ContactType,
    EmailType,
    PhoneType,
    RoleType,
    VolunteerStatus,
)
from .info import ContactAddress, ContactEmail, ContactPhone
from .relationships import (
    ContactOrganization,
    ContactRole,
    ContactTag,
    EmergencyContact,
)
from .student import Student
from .teacher import Teacher
from .volunteer import (
    Volunteer,
    VolunteerAvailability,
    VolunteerHours,
    VolunteerInterest,
    VolunteerSkill,
)

__all__ = [
    # Base model
    "Contact",
    # Enums
    "ContactType",
    "ContactStatus",
    "RoleType",
    "EmailType",
    "PhoneType",
    "AddressType",
    "AgeGroup",
    "VolunteerStatus",
    # Info models
    "ContactEmail",
    "ContactPhone",
    "ContactAddress",
    # Relationship models
    "ContactRole",
    "ContactOrganization",
    "ContactTag",
    "EmergencyContact",
    # Sub-classes
    "Volunteer",
    "Student",
    "Teacher",
    # Volunteer models
    "VolunteerSkill",
    "VolunteerInterest",
    "VolunteerAvailability",
    "VolunteerHours",
]

