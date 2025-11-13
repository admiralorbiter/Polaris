# scripts/init_database.py

"""
Database initialization script.
This script creates all tables and seeds default data:
- Default roles (SUPER_ADMIN, ORG_ADMIN, COORDINATOR, VOLUNTEER, VIEWER)
- Default permissions and role-permission mappings
- Default system feature flags
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from flask_app.models import OrganizationFeatureFlag  # noqa: F401
from flask_app.models import Organization, OrganizationType, Permission, Role, RolePermission, SystemFeatureFlag, db


def create_default_roles():
    """Create default system roles"""
    roles = [
        {
            "name": "SUPER_ADMIN",
            "display_name": "Super Administrator",
            "description": "System-wide administrator with full access to all organizations",
            "is_system_role": True,
        },
        {
            "name": "ORG_ADMIN",
            "display_name": "Organization Administrator",
            "description": ("Administrator of a specific organization with full access within that org"),
            "is_system_role": True,
        },
        {
            "name": "COORDINATOR",
            "display_name": "Volunteer Coordinator",
            "description": "Can manage volunteers and schedules within an organization",
            "is_system_role": True,
        },
        {
            "name": "VOLUNTEER",
            "display_name": "Volunteer",
            "description": "Standard volunteer user with limited access",
            "is_system_role": True,
        },
        {
            "name": "VIEWER",
            "display_name": "Viewer",
            "description": "Read-only access to organization data",
            "is_system_role": True,
        },
    ]

    created_roles = {}
    for role_data in roles:
        role = Role.query.filter_by(name=role_data["name"]).first()
        if not role:
            role = Role(**role_data)
            db.session.add(role)
            db.session.flush()
        created_roles[role_data["name"]] = role

    db.session.commit()
    return created_roles


def create_default_permissions():
    """Create default permissions"""
    permissions = [
        # User Management
        {"name": "create_users", "display_name": "Create Users", "category": "user_management"},
        {"name": "edit_users", "display_name": "Edit Users", "category": "user_management"},
        {"name": "delete_users", "display_name": "Delete Users", "category": "user_management"},
        {"name": "view_users", "display_name": "View Users", "category": "user_management"},
        # Volunteer Management
        {
            "name": "create_volunteers",
            "display_name": "Create Volunteers",
            "category": "volunteer_management",
        },
        {
            "name": "edit_volunteers",
            "display_name": "Edit Volunteers",
            "category": "volunteer_management",
        },
        {
            "name": "delete_volunteers",
            "display_name": "Delete Volunteers",
            "category": "volunteer_management",
        },
        {
            "name": "view_volunteers",
            "display_name": "View Volunteers",
            "category": "volunteer_management",
        },
        # Organization Management
        {
            "name": "manage_organization",
            "display_name": "Manage Organization",
            "category": "organization_management",
        },
        {
            "name": "view_organization_settings",
            "display_name": "View Organization Settings",
            "category": "organization_management",
        },
        # Reports
        {"name": "view_reports", "display_name": "View Reports", "category": "reports"},
        {"name": "export_reports", "display_name": "Export Reports", "category": "reports"},
        {"name": "view_analytics", "display_name": "View Analytics", "category": "reports"},
        # Admin
        {"name": "system_admin", "display_name": "System Administration", "category": "admin"},
    ]

    created_permissions = {}
    for perm_data in permissions:
        perm = Permission.query.filter_by(name=perm_data["name"]).first()
        if not perm:
            perm = Permission(**perm_data)
            db.session.add(perm)
            db.session.flush()
        created_permissions[perm_data["name"]] = perm

    db.session.commit()
    return created_permissions


def assign_permissions_to_roles(roles, permissions):
    """Assign permissions to roles"""
    role_ids = [role.id for role in roles.values()]
    existing_pairs = {
        (rp.role_id, rp.permission_id)
        for rp in RolePermission.query.filter(RolePermission.role_id.in_(role_ids)).all()
    }

    def _grant(role, perm):
        key = (role.id, perm.id)
        if key not in existing_pairs:
            db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
            existing_pairs.add(key)

    super_admin = roles["SUPER_ADMIN"]
    for perm in permissions.values():
        _grant(super_admin, perm)

    org_admin = roles["ORG_ADMIN"]
    org_admin_perms = [
        "create_users",
        "edit_users",
        "delete_users",
        "view_users",
        "create_volunteers",
        "edit_volunteers",
        "delete_volunteers",
        "view_volunteers",
        "manage_organization",
        "view_organization_settings",
        "view_reports",
        "export_reports",
        "view_analytics",
    ]
    for perm_name in org_admin_perms:
        perm = permissions.get(perm_name)
        if perm:
            _grant(org_admin, perm)

    # COORDINATOR gets volunteer management and viewing permissions
    coordinator = roles["COORDINATOR"]
    coordinator_perms = [
        "create_volunteers",
        "edit_volunteers",
        "view_volunteers",
        "view_users",
        "view_reports",
        "view_analytics",
    ]
    for perm_name in coordinator_perms:
        perm = permissions.get(perm_name)
        if perm:
            _grant(coordinator, perm)

    # VOLUNTEER gets limited viewing permissions
    volunteer = roles["VOLUNTEER"]
    volunteer_perms = ["view_volunteers", "view_reports"]
    for perm_name in volunteer_perms:
        perm = permissions.get(perm_name)
        if perm:
            _grant(volunteer, perm)

    # VIEWER gets read-only permissions
    viewer = roles["VIEWER"]
    viewer_perms = ["view_users", "view_volunteers", "view_reports", "view_organization_settings"]
    for perm_name in viewer_perms:
        perm = permissions.get(perm_name)
        if perm:
            _grant(viewer, perm)

    db.session.commit()


def create_default_organization():
    """Create a default organization for bootstrapping"""
    import os

    # Check if we should create default org (default: yes)
    create_default = os.environ.get("CREATE_DEFAULT_ORG", "true").lower() == "true"

    if not create_default:
        print("Skipping default organization creation (CREATE_DEFAULT_ORG=false)")
        return None

    # Check if organization already exists
    existing = Organization.query.filter_by(slug="default").first()
    if existing:
        print("Default organization already exists")
        return existing

    default_org = Organization(
        name="Default Organization",
        slug="default",
        description="Default organization created during database initialization",
        organization_type=OrganizationType.OTHER,
        is_active=True,
    )

    db.session.add(default_org)
    db.session.commit()
    print("Default organization created (slug: 'default')")
    return default_org


def create_default_feature_flags():
    """Create default system feature flags"""
    system_flags = [
        {
            "flag_name": "maintenance_mode",
            "value": False,
            "flag_type": "boolean",
            "description": "System-wide maintenance mode",
        },
        {
            "flag_name": "registration_enabled",
            "value": True,
            "flag_type": "boolean",
            "description": "Allow new user registration",
        },
    ]

    for flag_data in system_flags:
        SystemFeatureFlag.set_flag(
            flag_data["flag_name"],
            flag_data["value"],
            flag_data["flag_type"],
            flag_data.get("description"),
        )

    print("Default system feature flags created")


def initialize_data_quality_field_config():
    """Initialize data quality field configuration with defaults"""
    from flask_app.services.data_quality_field_config_service import (
        DataQualityFieldConfigService,
    )

    if DataQualityFieldConfigService.initialize_default_config():
        print("Data quality field configuration initialized")
    else:
        print("Warning: Failed to initialize data quality field configuration")


def init_database():
    """Initialize database with all default data"""
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Importer tables (import_runs, staging_*, etc.) created alongside core schema.")
        print("Database tables created")

        print("Creating default roles...")
        roles = create_default_roles()
        print(f"Created {len(roles)} default roles")

        print("Creating default permissions...")
        permissions = create_default_permissions()
        print(f"Created {len(permissions)} default permissions")

        print("Assigning permissions to roles...")
        assign_permissions_to_roles(roles, permissions)
        print("Permissions assigned to roles")

        print("Creating default feature flags...")
        create_default_feature_flags()
        print("Default feature flags created")

        print("Initializing data quality field configuration...")
        initialize_data_quality_field_config()

        print("Creating default organization...")
        default_org = create_default_organization()
        if default_org:
            print(f"Default organization created: {default_org.name} (slug: {default_org.slug})")

        print("\nDatabase initialization complete!")
        print("\nDefault roles created:")
        for role_name, role in roles.items():
            print(f"  - {role_name}: {role.display_name}")

        print("\nNext steps:")
        print("  1. Create a super admin user: python create_admin.py")
        print("  2. Create additional organizations: python scripts/create_organization.py")
        print("  3. Or use the admin UI to create organizations")


if __name__ == "__main__":
    init_database()
