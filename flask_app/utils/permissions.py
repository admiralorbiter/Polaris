# flask_app/utils/permissions.py

from functools import wraps
from flask import flash, redirect, url_for, request, g, current_app
from flask_login import current_user
from flask_app.models import User, Organization, Role, Permission, UserOrganization


def get_user_organizations(user):
    """Get all organizations a user belongs to"""
    if not user or not user.is_authenticated:
        return []
    
    if user.is_super_admin:
        # Super admins can access all organizations
        return Organization.query.filter_by(is_active=True).all()
    
    # Get organizations through UserOrganization relationships
    user_orgs = UserOrganization.query.filter_by(
        user_id=user.id,
        is_active=True
    ).all()
    
    return [uo.organization for uo in user_orgs if uo.organization.is_active]


def get_user_role_in_organization(user, organization):
    """Get the role a user has in a specific organization"""
    if not user or not user.is_authenticated or not organization:
        return None
    
    if user.is_super_admin:
        # Super admins have super admin role everywhere
        return Role.query.filter_by(name='SUPER_ADMIN').first()
    
    user_org = UserOrganization.query.filter_by(
        user_id=user.id,
        organization_id=organization.id,
        is_active=True
    ).first()
    
    return user_org.role if user_org else None


def has_permission(user, permission_name, organization=None):
    """Check if user has a specific permission, optionally in a specific organization"""
    if not user or not user.is_authenticated:
        return False
    
    # Super admins have all permissions
    if user.is_super_admin:
        return True
    
    # If organization is specified, check permission in that organization
    if organization:
        role = get_user_role_in_organization(user, organization)
        if role:
            return role.has_permission(permission_name)
        return False
    
    # If no organization specified, check if user has permission in any organization
    user_orgs = get_user_organizations(user)
    for org in user_orgs:
        role = get_user_role_in_organization(user, org)
        if role and role.has_permission(permission_name):
            return True
    
    return False


def has_role(user, role_name, organization=None):
    """Check if user has a specific role, optionally in a specific organization"""
    if not user or not user.is_authenticated:
        return False
    
    # Check super admin
    if role_name == 'SUPER_ADMIN':
        return user.is_super_admin
    
    if user.is_super_admin:
        # Super admins implicitly have all roles
        return True
    
    # If organization is specified, check role in that organization
    if organization:
        role = get_user_role_in_organization(user, organization)
        return role and role.name == role_name
    
    # If no organization specified, check if user has role in any organization
    user_orgs = get_user_organizations(user)
    for org in user_orgs:
        role = get_user_role_in_organization(user, org)
        if role and role.name == role_name:
            return True
    
    return False


def require_organization_membership(user, organization):
    """Check if user is a member of the organization"""
    if not user or not user.is_authenticated or not organization:
        return False
    
    if user.is_super_admin:
        return True
    
    user_org = UserOrganization.query.filter_by(
        user_id=user.id,
        organization_id=organization.id,
        is_active=True
    ).first()
    
    return user_org is not None


def permission_required(permission_name, org_context=True):
    """
    Decorator to require a specific permission.
    
    Args:
        permission_name: Name of the permission to check
        org_context: If True, requires organization context and checks permission in that org
                     If False, checks if user has permission in any organization
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            
            # Super admins bypass permission checks
            if current_user.is_super_admin:
                return f(*args, **kwargs)
            
            # If org_context is True, require organization context
            if org_context:
                organization = get_current_organization()
                if not organization:
                    flash('Organization context required.', 'danger')
                    return redirect(url_for('index'))
                
                if not has_permission(current_user, permission_name, organization):
                    flash('You do not have permission to access this page.', 'danger')
                    return redirect(url_for('index'))
            else:
                # Check permission in any organization
                if not has_permission(current_user, permission_name):
                    flash('You do not have permission to access this page.', 'danger')
                    return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def role_required(role_name, org_context=True):
    """
    Decorator to require a specific role.
    
    Args:
        role_name: Name of the role to check
        org_context: If True, requires organization context and checks role in that org
                    If False, checks if user has role in any organization
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            
            # Super admins bypass role checks
            if current_user.is_super_admin:
                return f(*args, **kwargs)
            
            # If org_context is True, require organization context
            if org_context:
                organization = get_current_organization()
                if not organization:
                    flash('Organization context required.', 'danger')
                    return redirect(url_for('index'))
                
                if not has_role(current_user, role_name, organization):
                    flash('You do not have the required role to access this page.', 'danger')
                    return redirect(url_for('index'))
            else:
                # Check role in any organization
                if not has_role(current_user, role_name):
                    flash('You do not have the required role to access this page.', 'danger')
                    return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def super_admin_required(f):
    """Decorator to require super admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        
        if not current_user.is_super_admin:
            flash('Super admin privileges required.', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function


def org_admin_required(f):
    """Decorator to require organization admin role in current organization"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.is_super_admin:
            return f(*args, **kwargs)
        
        organization = get_current_organization()
        if not organization:
            flash('Organization context required.', 'danger')
            return redirect(url_for('index'))
        
        if not has_role(current_user, 'ORG_ADMIN', organization):
            flash('Organization admin privileges required.', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function


def organization_required(f):
    """Decorator to ensure organization context exists"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        organization = get_current_organization()
        if not organization:
            flash('Organization context required.', 'danger')
            return redirect(url_for('index'))
        
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        
        # Check if user is member of organization (unless super admin)
        if not current_user.is_super_admin:
            if not require_organization_membership(current_user, organization):
                flash('You are not a member of this organization.', 'danger')
                return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function


def get_current_organization():
    """
    Get the current organization from Flask request context.
    This is set by middleware from URL parameter or session.
    """
    return getattr(g, 'current_organization', None)


def set_current_organization(organization):
    """Set the current organization in Flask request context"""
    g.current_organization = organization


def get_available_organizations(user):
    """
    Get organizations available for the current user to assign to other users.
    Super admins see all organizations, org admins see only their organizations.
    """
    if not user or not user.is_authenticated:
        return []
    
    if user.is_super_admin:
        return Organization.query.filter_by(is_active=True).all()
    
    return get_user_organizations(user)


def get_available_roles(user, organization=None):
    """
    Get roles available for the current user to assign.
    Super admins can assign any role, org admins can assign roles up to their level.
    """
    from flask_app.models import Role
    
    if not user or not user.is_authenticated:
        return []
    
    if user.is_super_admin:
        # Super admins can assign any role
        return Role.query.filter_by(is_system_role=True).all()
    
    # Get user's role in the organization
    if not organization:
        organization = get_current_organization()
    
    if not organization:
        return []
    
    user_role = get_user_role_in_organization(user, organization)
    if not user_role:
        return []
    
    # Role hierarchy: SUPER_ADMIN > ORG_ADMIN > COORDINATOR > VOLUNTEER > VIEWER
    role_hierarchy = {
        'SUPER_ADMIN': 5,
        'ORG_ADMIN': 4,
        'COORDINATOR': 3,
        'VOLUNTEER': 2,
        'VIEWER': 1
    }
    
    user_role_level = role_hierarchy.get(user_role.name, 0)
    
    # Return roles that are at or below the user's role level
    available_roles = []
    for role in Role.query.filter_by(is_system_role=True).all():
        role_level = role_hierarchy.get(role.name, 0)
        if role_level <= user_role_level:
            available_roles.append(role)
    
    return available_roles


def can_assign_role(user, target_role, organization=None):
    """
    Check if user can assign a specific role to another user.
    Prevents privilege escalation.
    """
    if not user or not user.is_authenticated:
        return False
    
    if user.is_super_admin:
        return True
    
    if not organization:
        organization = get_current_organization()
    
    if not organization:
        return False
    
    user_role = get_user_role_in_organization(user, organization)
    if not user_role:
        return False
    
    # Role hierarchy: SUPER_ADMIN > ORG_ADMIN > COORDINATOR > VOLUNTEER > VIEWER
    role_hierarchy = {
        'SUPER_ADMIN': 5,
        'ORG_ADMIN': 4,
        'COORDINATOR': 3,
        'VOLUNTEER': 2,
        'VIEWER': 1
    }
    
    user_role_level = role_hierarchy.get(user_role.name, 0)
    target_role_level = role_hierarchy.get(target_role.name if isinstance(target_role, Role) else target_role, 0)
    
    # Can only assign roles at or below user's level
    return target_role_level <= user_role_level


def validate_role_assignment(user, target_role, organization=None):
    """
    Validate if a role assignment is allowed.
    Returns (is_valid, error_message)
    """
    if not can_assign_role(user, target_role, organization):
        role_name = target_role.display_name if hasattr(target_role, 'display_name') else str(target_role)
        return False, f'You do not have permission to assign the role "{role_name}".'
    
    return True, None

