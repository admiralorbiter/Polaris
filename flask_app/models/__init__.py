# app/models/__init__.py
"""
Database models package
"""

from .admin import AdminLog, SystemMetrics
from .base import BaseModel, db
from .contact import (
    AddressType,
    AgeGroup,
    Contact,
    ContactAddress,
    ContactEmail,
    ContactOrganization,
    ContactPhone,
    ContactRole,
    ContactStatus,
    ContactTag,
    ContactType,
    EmailType,
    EmergencyContact,
    PhoneType,
    RoleType,
    Student,
    Teacher,
    Volunteer,
    VolunteerAvailability,
    VolunteerHours,
    VolunteerInterest,
    VolunteerSkill,
    VolunteerStatus,
)
from .feature_flag import OrganizationFeatureFlag, SystemFeatureFlag
from .organization import Organization
from .role import Permission, Role, RolePermission, UserOrganization
from .user import User

__all__ = [
    "db",
    "BaseModel",
    "User",
    "AdminLog",
    "SystemMetrics",
    "Organization",
    "Role",
    "Permission",
    "RolePermission",
    "UserOrganization",
    "OrganizationFeatureFlag",
    "SystemFeatureFlag",
    # Contact models
    "Contact",
    "ContactEmail",
    "ContactPhone",
    "ContactAddress",
    "ContactRole",
    "ContactOrganization",
    "ContactTag",
    "EmergencyContact",
    "Volunteer",
    "Student",
    "Teacher",
    # Contact enums
    "ContactType",
    "ContactStatus",
    "RoleType",
    "EmailType",
    "PhoneType",
    "AddressType",
    "AgeGroup",
    # Volunteer models
    "VolunteerSkill",
    "VolunteerInterest",
    "VolunteerAvailability",
    "VolunteerHours",
    "VolunteerStatus",
]
