# flask_app/utils/feature_flags.py

from flask import current_app

from flask_app.models import OrganizationFeatureFlag, SystemFeatureFlag
from flask_app.utils.permissions import get_current_organization


def get_feature_flag(flag_name, organization_id=None, default=None):
    """
    Get a feature flag value.

    Args:
        flag_name: Name of the feature flag
        organization_id: Optional organization ID. If None, uses current organization context
        default: Default value if flag doesn't exist

    Returns:
        The feature flag value, or default if not found
    """
    # First try organization-specific flag
    org_id = organization_id
    if org_id is None:
        organization = get_current_organization()
        org_id = organization.id if organization else None

    if org_id:
        value = OrganizationFeatureFlag.get_flag(org_id, flag_name, None)
        if value is not None:
            return value

    # Fall back to system-wide flag
    return SystemFeatureFlag.get_flag(flag_name, default)


def set_feature_flag(
    flag_name, value, organization_id=None, flag_type="boolean", is_system_flag=False
):
    """
    Set a feature flag value.

    Args:
        flag_name: Name of the feature flag
        value: Value to set
        organization_id: Optional organization ID. If None and not system flag,
            uses current organization context
        flag_type: Type of flag ('boolean', 'string', 'integer', 'json')
        is_system_flag: If True, sets system-wide flag instead of organization flag

    Returns:
        True if successful, False otherwise
    """
    if is_system_flag:
        return SystemFeatureFlag.set_flag(flag_name, value, flag_type)

    org_id = organization_id
    if org_id is None:
        organization = get_current_organization()
        if not organization:
            current_app.logger.error(
                "Cannot set organization feature flag without organization context"
            )
            return False
        org_id = organization.id

    return OrganizationFeatureFlag.set_flag(org_id, flag_name, value, flag_type)


def get_organization_feature_flag(organization_id, flag_name, default=None):
    """
    Get an organization-specific feature flag value.

    Args:
        organization_id: Organization ID
        flag_name: Name of the feature flag
        default: Default value if flag doesn't exist

    Returns:
        The feature flag value, or default if not found
    """
    return OrganizationFeatureFlag.get_flag(organization_id, flag_name, default)


def set_organization_feature_flag(organization_id, flag_name, value, flag_type="boolean"):
    """
    Set an organization-specific feature flag value.

    Args:
        organization_id: Organization ID
        flag_name: Name of the feature flag
        value: Value to set
        flag_type: Type of flag ('boolean', 'string', 'integer', 'json')

    Returns:
        True if successful, False otherwise
    """
    return OrganizationFeatureFlag.set_flag(organization_id, flag_name, value, flag_type)


def get_system_feature_flag(flag_name, default=None):
    """
    Get a system-wide feature flag value.

    Args:
        flag_name: Name of the feature flag
        default: Default value if flag doesn't exist

    Returns:
        The feature flag value, or default if not found
    """
    return SystemFeatureFlag.get_flag(flag_name, default)


def set_system_feature_flag(flag_name, value, flag_type="boolean", description=None):
    """
    Set a system-wide feature flag value.

    Args:
        flag_name: Name of the feature flag
        value: Value to set
        flag_type: Type of flag ('boolean', 'string', 'integer', 'json')
        description: Optional description of the flag

    Returns:
        True if successful, False otherwise
    """
    return SystemFeatureFlag.set_flag(flag_name, value, flag_type, description)


def check_feature_flag(flag_name, organization_id=None, default=False):
    """
    Check if a feature flag is enabled (convenience function for boolean flags).

    Args:
        flag_name: Name of the feature flag
        organization_id: Optional organization ID
        default: Default value if flag doesn't exist

    Returns:
        True if flag is enabled, False otherwise
    """
    value = get_feature_flag(flag_name, organization_id, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)


def require_feature_flag(flag_name, organization_id=None):
    """
    Decorator to require a feature flag to be enabled.

    Args:
        flag_name: Name of the feature flag to check
        organization_id: Optional organization ID
    """

    def decorator(f):
        from functools import wraps

        from flask import flash, redirect, url_for

        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not check_feature_flag(flag_name, organization_id):
                flash("This feature is not available.", "warning")
                return redirect(url_for("index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator
