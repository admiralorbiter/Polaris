# flask_app/middleware/org_context.py

from flask import current_app, g, request, session

from flask_app.models import Organization
from flask_app.utils.permissions import get_user_organizations, set_current_organization


def init_org_context_middleware(app):
    """Initialize organization context middleware"""

    @app.before_request
    def set_organization_context():
        """Set the current organization from URL parameter or session"""
        g.current_organization = None

        # Skip for static files and certain routes
        if request.endpoint in ("static", "login", "logout"):
            return

        # Try to get organization from URL parameter (e.g., /org/<org_id>/...)
        org_id = request.args.get("org_id")
        org_slug = request.args.get("org_slug")

        # Or from URL path (e.g., /org/<org_id>/volunteers)
        if not org_id and not org_slug:
            # Try to extract from path
            path_parts = request.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] == "org":
                org_slug = path_parts[1]

        # Or from session
        if not org_id and not org_slug:
            org_id = session.get("current_organization_id")
            org_slug = session.get("current_organization_slug")

        organization = None

        if org_id:
            try:
                organization = Organization.find_by_id(int(org_id))
            except (ValueError, TypeError):
                current_app.logger.warning(f"Invalid organization ID: {org_id}")

        if not organization and org_slug:
            organization = Organization.find_by_slug(org_slug)

        # If organization found, set it in context
        if organization:
            # Verify organization is active
            if not organization.is_active:
                current_app.logger.warning(
                    f"Attempted access to inactive organization: {organization.id}"
                )
                organization = None
            else:
                set_current_organization(organization)
                # Store in session for future requests
                session["current_organization_id"] = organization.id
                session["current_organization_slug"] = organization.slug

        # If user is logged in and has only one organization, auto-select it
        from flask_login import current_user

        if not organization and current_user.is_authenticated:
            user_orgs = get_user_organizations(current_user)
            if len(user_orgs) == 1:
                set_current_organization(user_orgs[0])
                session["current_organization_id"] = user_orgs[0].id
                session["current_organization_slug"] = user_orgs[0].slug
