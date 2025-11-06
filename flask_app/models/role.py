# flask_app/models/role.py

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from .base import BaseModel, db


class Role(BaseModel):
    """Model for user roles in the system"""

    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_system_role = db.Column(
        db.Boolean, default=False, nullable=False
    )  # System roles cannot be deleted

    # Relationships
    permissions = db.relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    user_organizations = db.relationship("UserOrganization", back_populates="role")

    def __repr__(self):
        return f"<Role {self.name}>"

    @staticmethod
    def find_by_name(name):
        """Find role by name with error handling"""
        try:
            return Role.query.filter_by(name=name).first()
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding role by name {name}: {str(e)}")
            return None

    def has_permission(self, permission_name):
        """Check if role has a specific permission"""
        # Re-query with relationships loaded to avoid detached instance errors
        from sqlalchemy import inspect
        from sqlalchemy.orm import joinedload

        # Check if we're in a session, if not re-query
        if inspect(self).detached or not inspect(self).persistent:
            role = Role.query.options(
                joinedload(Role.permissions).joinedload(RolePermission.permission)
            ).get(self.id)
            if role:
                return any(rp.permission.name == permission_name for rp in role.permissions)
            return False
        # If in session, use relationships directly
        return any(rp.permission.name == permission_name for rp in self.permissions)


class Permission(BaseModel):
    """Model for granular permissions"""

    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(
        db.String(50), nullable=True
    )  # e.g., 'user_management', 'volunteer_management'

    # Relationships
    roles = db.relationship(
        "RolePermission", back_populates="permission", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Permission {self.name}>"

    @staticmethod
    def find_by_name(name):
        """Find permission by name with error handling"""
        try:
            return Permission.query.filter_by(name=name).first()
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error finding permission by name {name}: {str(e)}")
            return None


class RolePermission(BaseModel):
    """Junction table for Role and Permission many-to-many relationship"""

    __tablename__ = "role_permissions"

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    permission_id = db.Column(db.Integer, db.ForeignKey("permissions.id"), nullable=False)

    # Relationships
    role = db.relationship("Role", back_populates="permissions")
    permission = db.relationship("Permission", back_populates="roles")

    # Unique constraint
    __table_args__ = (db.UniqueConstraint("role_id", "permission_id", name="_role_permission_uc"),)

    def __repr__(self):
        return f"<RolePermission role={self.role_id} permission={self.permission_id}>"


class UserOrganization(BaseModel):
    """Junction table for User and Organization many-to-many relationship with role"""

    __tablename__ = "user_organizations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    user = db.relationship("User", back_populates="user_organizations")
    organization = db.relationship("Organization", back_populates="users")
    role = db.relationship("Role", back_populates="user_organizations")

    # Unique constraint - user can only have one role per organization
    __table_args__ = (db.UniqueConstraint("user_id", "organization_id", name="_user_org_uc"),)

    def __repr__(self):
        return (
            f"<UserOrganization user={self.user_id} org={self.organization_id} role={self.role_id}>"
        )
