# flask_app/models/contact/teacher.py
"""
Teacher model extending Contact
"""

from ..base import db
from .base import Contact
from .enums import ContactType


class Teacher(Contact):
    """Teacher sub-class extending Contact"""

    __tablename__ = "teachers"
    __mapper_args__ = {
        "polymorphic_identity": ContactType.TEACHER,
    }

    id = db.Column(db.Integer, db.ForeignKey("contacts.id"), primary_key=True)

    # Teacher-specific fields (to be expanded)
    certification = db.Column(db.String(200), nullable=True)
    subject_areas = db.Column(db.Text, nullable=True)  # JSON or text
    hire_date = db.Column(db.Date, nullable=True)
    employee_id = db.Column(db.String(50), nullable=True, unique=True, index=True)

    def __repr__(self):
        return f"<Teacher {self.get_full_name()}>"

