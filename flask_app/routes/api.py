# flask_app/routes/api.py

"""
API routes for AJAX/JSON endpoints
"""

from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from flask_app.models import Organization
from flask_app.utils.permissions import get_user_organizations


def register_api_routes(app):
    """Register API routes"""

    @app.route("/api/organizations/search", methods=["GET"])
    @login_required
    def api_search_organizations():
        """
        Search organizations endpoint for autocomplete.
        Returns JSON list of matching organizations.
        """
        try:
            query = request.args.get("q", "").strip()
            current_app.logger.info(
                f"Organization search API called with query: '{query}' "
                f"by user: {current_user.username}"
            )

            # Get organizations user has access to
            if current_user.is_super_admin:
                # Super admins can see all active organizations
                organizations = Organization.query.filter_by(is_active=True)
                current_app.logger.debug("Super admin - showing all active organizations")
            else:
                # Regular users see only their organizations
                user_orgs = get_user_organizations(current_user)
                org_ids = [org.id for org in user_orgs]
                organizations = Organization.query.filter(
                    Organization.id.in_(org_ids), Organization.is_active.is_(True)
                )
                current_app.logger.debug(f"Regular user - showing {len(org_ids)} organizations")

            # Apply search filter if query provided
            if query:
                search_term = f"%{query}%"
                organizations = organizations.filter(
                    (Organization.name.ilike(search_term)) | (Organization.slug.ilike(search_term))
                )
                current_app.logger.debug(f"Applied search filter: {search_term}")

            # Limit results and order by name
            organizations = organizations.order_by(Organization.name).limit(20).all()
            current_app.logger.info(f"Found {len(organizations)} organizations matching query")

            # Format results for Select2
            results = []
            for org in organizations:
                results.append(
                    {
                        "id": org.id,
                        "text": f"{org.name} ({org.slug})",  # Display format
                        "name": org.name,
                        "slug": org.slug,
                        "description": org.description or "",
                    }
                )

            response = {"results": results}
            current_app.logger.debug(f"Returning {len(results)} results")
            return jsonify(response)

        except Exception as e:
            current_app.logger.error(f"Error in organization search API: {str(e)}", exc_info=True)
            return (
                jsonify(
                    {"error": "An error occurred while searching organizations", "results": []}
                ),
                500,
            )

    @app.route("/api/organizations/create", methods=["POST"])
    @login_required
    def api_create_organization():
        """
        Create a new organization via AJAX.
        Used when user selects "Create new" option in autocomplete.
        """
        try:
            import re

            # Validate JSON request
            data = request.get_json() or {}
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "Invalid JSON data"}), 400

            org_name = data.get("name", "").strip()
            org_description = data.get("description") or None
            if org_description:
                org_description = org_description.strip() or None

            if not org_name:
                return jsonify({"success": False, "error": "Organization name is required"}), 400

            # Validate organization name length (max 200 characters per model)
            if len(org_name) > 200:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Organization name must be 200 characters or less",
                        }
                    ),
                    400,
                )

            # Only super admins can create organizations
            if not current_user.is_super_admin:
                return (
                    jsonify(
                        {"success": False, "error": "Only super admins can create organizations"}
                    ),
                    403,
                )

            # Generate slug from name
            slug = org_name.lower()
            slug = re.sub(r"[_\s]+", "-", slug)
            slug = re.sub(r"[^a-z0-9\-]", "", slug)
            slug = re.sub(r"-+", "-", slug)
            slug = slug.strip("-")

            # Validate slug is not empty
            if not slug:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Organization name must contain at least one letter or number",
                        }
                    ),
                    400,
                )

            # Check if organization with same name or slug already exists
            existing = Organization.query.filter(
                (Organization.name.ilike(org_name)) | (Organization.slug == slug)
            ).first()

            if existing:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f'Organization "{org_name}" already exists',
                            "organization": {
                                "id": existing.id,
                                "name": existing.name,
                                "slug": existing.slug,
                            },
                        }
                    ),
                    400,
                )

            # Create new organization
            try:
                new_org, error = Organization.safe_create(
                    name=org_name, slug=slug, description=org_description, is_active=True
                )

                if error:
                    current_app.logger.error(f"Error creating organization: {error}")
                    return jsonify({"success": False, "error": f"Database error: {error}"}), 500

                if not new_org:
                    return (
                        jsonify({"success": False, "error": "Failed to create organization"}),
                        500,
                    )
            except Exception as e:
                current_app.logger.error(
                    f"Unexpected error in api_create_organization: {str(e)}", exc_info=True
                )
                return jsonify({"success": False, "error": f"An error occurred: {str(e)}"}), 500

            # Log admin action
            from flask_app.models import AdminLog

            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="CREATE_ORGANIZATION",
                target_user_id=None,
                details=f"Created organization via API: {new_org.name}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            current_app.logger.info(
                f"Created new organization via API: {new_org.name} (ID: {new_org.id})"
            )

            return jsonify(
                {
                    "success": True,
                    "organization": {
                        "id": new_org.id,
                        "name": new_org.name,
                        "slug": new_org.slug,
                        "text": f"{new_org.name} ({new_org.slug})",
                    },
                }
            )

        except Exception as e:
            current_app.logger.error(f"Error in create organization API: {str(e)}", exc_info=True)
            return (
                jsonify(
                    {"success": False, "error": "An error occurred while creating organization"}
                ),
                500,
            )
