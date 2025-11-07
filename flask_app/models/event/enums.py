# flask_app/models/event/enums.py
"""
Enums for event models.
"""

from enum import Enum as PyEnum


class EventType(PyEnum):
    """Event type enumeration"""

    WORKSHOP = "workshop"
    MEETING = "meeting"
    TRAINING = "training"
    FUNDRAISER = "fundraiser"
    COMMUNITY_EVENT = "community_event"
    OTHER = "other"


class EventStatus(PyEnum):
    """Event status enumeration"""

    DRAFT = "draft"
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventFormat(PyEnum):
    """Event format enumeration"""

    IN_PERSON = "in_person"
    VIRTUAL = "virtual"
    HYBRID = "hybrid"


class CancellationReason(PyEnum):
    """Event cancellation reason enumeration"""

    WEATHER = "weather"
    LOW_ATTENDANCE = "low_attendance"
    EMERGENCY = "emergency"
    SCHEDULING_CONFLICT = "scheduling_conflict"
    OTHER = "other"


class EventVolunteerRole(PyEnum):
    """Event volunteer role enumeration"""

    ORGANIZER = "organizer"
    ATTENDEE = "attendee"
    SPEAKER = "speaker"
    VOLUNTEER = "volunteer"
    STAFF = "staff"
    OTHER = "other"


class RegistrationStatus(PyEnum):
    """Registration status enumeration"""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    CANCELLED = "cancelled"
