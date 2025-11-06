# flask_app/models/feature_flag.py

import json

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from .base import BaseModel, db


class OrganizationFeatureFlag(BaseModel):
    """Model for organization-specific feature flags"""

    __tablename__ = "organization_feature_flags"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    flag_name = db.Column(db.String(100), nullable=False, index=True)
    flag_value = db.Column(
        db.Text, nullable=False
    )  # JSON string for complex values, or simple string/bool
    flag_type = db.Column(
        db.String(20), default="boolean", nullable=False
    )  # boolean, string, integer, json

    # Relationships
    organization = db.relationship("Organization", back_populates="feature_flags")

    # Unique constraint
    __table_args__ = (db.UniqueConstraint("organization_id", "flag_name", name="_org_flag_uc"),)

    def __repr__(self):
        return f"<OrganizationFeatureFlag org={self.organization_id} flag={self.flag_name}>"

    def get_value(self):
        """Get the typed value from flag_value"""
        if self.flag_type == "boolean":
            return self.flag_value.lower() in ("true", "1", "yes", "on")
        elif self.flag_type == "integer":
            try:
                return int(self.flag_value)
            except ValueError:
                return 0
        elif self.flag_type == "json":
            try:
                return json.loads(self.flag_value)
            except json.JSONDecodeError:
                return {}
        else:
            return self.flag_value

    def set_value(self, value):
        """Set the value with appropriate type conversion"""
        if self.flag_type == "boolean":
            self.flag_value = "true" if bool(value) else "false"
        elif self.flag_type == "integer":
            self.flag_value = str(int(value))
        elif self.flag_type == "json":
            self.flag_value = json.dumps(value) if not isinstance(value, str) else value
        else:
            self.flag_value = str(value)

    @staticmethod
    def get_flag(organization_id, flag_name, default=None):
        """Get a feature flag value for an organization"""
        try:
            flag = OrganizationFeatureFlag.query.filter_by(
                organization_id=organization_id, flag_name=flag_name
            ).first()
            return flag.get_value() if flag else default
        except SQLAlchemyError as e:
            current_app.logger.error(
                f"Database error getting flag {flag_name} for org {organization_id}: {str(e)}"
            )
            return default

    @staticmethod
    def set_flag(organization_id, flag_name, value, flag_type="boolean"):
        """Set a feature flag value for an organization"""
        try:
            flag = OrganizationFeatureFlag.query.filter_by(
                organization_id=organization_id, flag_name=flag_name
            ).first()

            if flag:
                flag.flag_type = flag_type
                flag.set_value(value)
            else:
                flag = OrganizationFeatureFlag(
                    organization_id=organization_id, flag_name=flag_name, flag_type=flag_type
                )
                flag.set_value(value)
                db.session.add(flag)

            db.session.commit()
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(
                f"Database error setting flag {flag_name} for org {organization_id}: {str(e)}"
            )
            return False


class SystemFeatureFlag(BaseModel):
    """Model for system-wide feature flags"""

    __tablename__ = "system_feature_flags"

    id = db.Column(db.Integer, primary_key=True)
    flag_name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    flag_value = db.Column(
        db.Text, nullable=False
    )  # JSON string for complex values, or simple string/bool
    flag_type = db.Column(
        db.String(20), default="boolean", nullable=False
    )  # boolean, string, integer, json
    description = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<SystemFeatureFlag {self.flag_name}>"

    def get_value(self):
        """Get the typed value from flag_value"""
        if self.flag_type == "boolean":
            return self.flag_value.lower() in ("true", "1", "yes", "on")
        elif self.flag_type == "integer":
            try:
                return int(self.flag_value)
            except ValueError:
                return 0
        elif self.flag_type == "json":
            try:
                return json.loads(self.flag_value)
            except json.JSONDecodeError:
                return {}
        else:
            return self.flag_value

    def set_value(self, value):
        """Set the value with appropriate type conversion"""
        if self.flag_type == "boolean":
            self.flag_value = "true" if bool(value) else "false"
        elif self.flag_type == "integer":
            self.flag_value = str(int(value))
        elif self.flag_type == "json":
            self.flag_value = json.dumps(value) if not isinstance(value, str) else value
        else:
            self.flag_value = str(value)

    @staticmethod
    def get_flag(flag_name, default=None):
        """Get a system feature flag value"""
        try:
            flag = SystemFeatureFlag.query.filter_by(flag_name=flag_name).first()
            return flag.get_value() if flag else default
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error getting system flag {flag_name}: {str(e)}")
            return default

    @staticmethod
    def set_flag(flag_name, value, flag_type="boolean", description=None):
        """Set a system feature flag value"""
        try:
            flag = SystemFeatureFlag.query.filter_by(flag_name=flag_name).first()

            if flag:
                flag.flag_type = flag_type
                flag.set_value(value)
                if description:
                    flag.description = description
            else:
                flag = SystemFeatureFlag(
                    flag_name=flag_name, flag_type=flag_type, description=description
                )
                flag.set_value(value)
                db.session.add(flag)

            db.session.commit()
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error setting system flag {flag_name}: {str(e)}")
            return False
