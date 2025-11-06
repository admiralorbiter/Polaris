# flask_app/models/contact/enums.py
"""
Enums for contact models.
"""

from enum import Enum as PyEnum


class ContactStatus(PyEnum):
    """Contact status enumeration"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class ContactType(PyEnum):
    """Contact type discriminator for inheritance"""

    CONTACT = "contact"
    VOLUNTEER = "volunteer"
    STUDENT = "student"
    TEACHER = "teacher"


class RoleType(PyEnum):
    """Role types for multi-class support"""

    VOLUNTEER = "volunteer"
    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    DONOR = "donor"
    STAFF = "staff"
    BOARD_MEMBER = "board_member"


class EmailType(PyEnum):
    """Email address type"""

    PERSONAL = "personal"
    WORK = "work"
    OTHER = "other"


class PhoneType(PyEnum):
    """Phone number type"""

    MOBILE = "mobile"
    HOME = "home"
    WORK = "work"
    FAX = "fax"
    OTHER = "other"


class AddressType(PyEnum):
    """Address type"""

    HOME = "home"
    WORK = "work"
    MAILING = "mailing"
    OTHER = "other"


class AgeGroup(PyEnum):
    """Age group categories"""

    CHILD = "child"  # 0-12
    TEEN = "teen"  # 13-17
    ADULT = "adult"  # 18-64
    SENIOR = "senior"  # 65+


class VolunteerStatus(PyEnum):
    """Volunteer status enumeration"""

    ACTIVE = "active"
    HOLD = "hold"
    INACTIVE = "inactive"

