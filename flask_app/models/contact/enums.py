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


class Gender(PyEnum):
    """Gender enumeration"""

    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
    OTHER = "other"


class RaceEthnicity(PyEnum):
    """Race and ethnicity enumeration (US Census categories)"""

    WHITE = "white"
    BLACK_OR_AFRICAN_AMERICAN = "black_or_african_american"
    ASIAN = "asian"
    HISPANIC_OR_LATINO = "hispanic_or_latino"
    NATIVE_AMERICAN = "native_american"
    PACIFIC_ISLANDER = "pacific_islander"
    TWO_OR_MORE = "two_or_more"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
    OTHER = "other"


class EducationLevel(PyEnum):
    """Education level enumeration"""

    LESS_THAN_HIGH_SCHOOL = "less_than_high_school"
    HIGH_SCHOOL = "high_school"
    SOME_COLLEGE = "some_college"
    ASSOCIATES = "associates"
    BACHELORS = "bachelors"
    MASTERS = "masters"
    DOCTORATE = "doctorate"
    PROFESSIONAL = "professional"
    OTHER = "other"


class Salutation(PyEnum):
    """Salutation/title enumeration"""

    MR = "mr"
    MRS = "mrs"
    MS = "ms"
    MISS = "miss"
    DR = "dr"
    PROF = "prof"
    REV = "rev"
    HON = "hon"
    OTHER = "other"


class ClearanceStatus(PyEnum):
    """Background check/clearance status enumeration"""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    NOT_REQUIRED = "not_required"


class PreferredLanguage(PyEnum):
    """Preferred language enumeration"""

    ENGLISH = "english"
    SPANISH = "spanish"
    FRENCH = "french"
    GERMAN = "german"
    CHINESE = "chinese"
    JAPANESE = "japanese"
    KOREAN = "korean"
    ARABIC = "arabic"
    HINDI = "hindi"
    PORTUGUESE = "portuguese"
    RUSSIAN = "russian"
    ITALIAN = "italian"
    OTHER = "other"


class OrganizationType(PyEnum):
    """Organization type enumeration"""

    SCHOOL = "school"
    BUSINESS = "business"
    NON_PROFIT = "non_profit"
    GOVERNMENT = "government"
    OTHER = "other"


class VolunteerOrganizationStatus(PyEnum):
    """Volunteer-organization relationship status enumeration"""

    CURRENT = "current"  # Active relationship (end_date is None)
    PAST = "past"  # Past relationship (end_date is set)


class LocalStatus(PyEnum):
    """Local status enumeration for volunteer location"""

    UNKNOWN = "unknown"
    LOCAL = "local"
    NON_LOCAL = "non_local"