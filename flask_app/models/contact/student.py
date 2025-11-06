# flask_app/models/contact/student.py
"""
Student model extending Contact
"""

from ..base import db
from .base import Contact
from .enums import ContactType


class Student(Contact):
    """Student sub-class extending Contact"""

    __tablename__ = "students"
    __mapper_args__ = {
        "polymorphic_identity": ContactType.STUDENT,
    }

    id = db.Column(db.Integer, db.ForeignKey("contacts.id"), primary_key=True)

    # Student-specific fields (to be expanded)
    grade = db.Column(db.String(20), nullable=True)
    enrollment_date = db.Column(db.Date, nullable=True)
    student_id = db.Column(db.String(50), nullable=True, unique=True, index=True)
    graduation_date = db.Column(db.Date, nullable=True)

    def __repr__(self):
        return f"<Student {self.get_full_name()}>"

