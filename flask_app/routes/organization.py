# flask_app/routes/organization.py

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from flask_app.forms import CreateOrganizationForm, UpdateOrganizationForm
from flask_app.models import AdminLog, Organization, UserOrganization, db
from flask_app.utils.permissions import super_admin_required


def register_organization_routes(app):
    """Register organization management routes"""

    @app.route("/admin/organizations")
    @login_required
    @super_admin_required
    def admin_organizations():
        """List all organizations"""
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 20

            organizations = Organization.query.order_by(Organization.name).paginate(
                page=page, per_page=per_page, error_out=False
            )

            # Add user counts to each organization
            for org in organizations.items:
                org.user_count = UserOrganization.query.filter_by(
                    organization_id=org.id, is_active=True
                ).count()

            return render_template("admin/organizations.html", organizations=organizations)

        except Exception as e:
            current_app.logger.error(f"Error in admin organizations page: {str(e)}")
            flash("An error occurred while loading organizations.", "danger")
            return redirect(url_for("admin_dashboard"))

    @app.route("/admin/organizations/create", methods=["GET", "POST"])
    @login_required
    @super_admin_required
    def admin_create_organization():
        """Create new organization"""
        form = CreateOrganizationForm()

        try:
            if form.validate_on_submit():
                # Create new organization
                new_org, error = Organization.safe_create(
                    name=form.name.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    is_active=form.is_active.data,
                )

                if error:
                    flash(f"Error creating organization: {error}", "danger")
                else:
                    # Log admin action
                    AdminLog.log_action(
                        admin_user_id=current_user.id,
                        action="CREATE_ORGANIZATION",
                        target_user_id=None,
                        details=f"Created organization: {new_org.name}",
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get("User-Agent"),
                    )

                    flash(f"Organization {new_org.name} created successfully!", "success")
                    return redirect(url_for("admin_organizations"))

            return render_template("admin/create_organization.html", form=form)

        except Exception as e:
            current_app.logger.error(f"Error in admin create organization: {str(e)}")
            flash("An error occurred while creating organization.", "danger")
            return render_template("admin/create_organization.html", form=form)

    @app.route("/admin/organizations/<int:org_id>")
    @login_required
    @super_admin_required
    def admin_view_organization(org_id):
        """View organization details"""
        try:
            organization = db.session.get(Organization, org_id)
            if not organization:
                from flask import abort

                abort(404)

            # Get organization statistics
            from flask_app.models import User

            total_users = UserOrganization.query.filter_by(
                organization_id=org_id, is_active=True
            ).count()

            # Count active users in organization
            user_org_ids = [
                uo.user_id
                for uo in UserOrganization.query.filter_by(
                    organization_id=org_id, is_active=True
                ).all()
            ]
            active_users = (
                User.query.filter(User.id.in_(user_org_ids), User.is_active.is_(True)).count()
                if user_org_ids
                else 0
            )

            # Get users in organization
            user_orgs = UserOrganization.query.filter_by(
                organization_id=org_id, is_active=True
            ).all()

            stats = {"total_users": total_users, "active_users": active_users, "users": user_orgs}

            return render_template(
                "admin/view_organization.html", organization=organization, stats=stats
            )

        except Exception as e:
            current_app.logger.error(f"Error viewing organization {org_id}: {str(e)}")
            flash("Organization not found.", "danger")
            return redirect(url_for("admin_organizations"))

    @app.route("/admin/organizations/<int:org_id>/edit", methods=["GET", "POST"])
    @login_required
    @super_admin_required
    def admin_edit_organization(org_id):
        """Edit organization information"""
        organization = db.session.get(Organization, org_id)
        if not organization:
            from flask import abort

            abort(404)
        form = UpdateOrganizationForm(organization=organization)

        try:
            if form.validate_on_submit():
                # Update organization
                success, error = organization.safe_update(
                    name=form.name.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    is_active=form.is_active.data,
                )

                if error:
                    flash(f"Error updating organization: {error}", "danger")
                else:
                    # Log admin action
                    AdminLog.log_action(
                        admin_user_id=current_user.id,
                        action="UPDATE_ORGANIZATION",
                        target_user_id=None,
                        details=f"Updated organization: {organization.name}",
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get("User-Agent"),
                    )

                    flash(f"Organization {organization.name} updated successfully!", "success")
                    return redirect(url_for("admin_view_organization", org_id=organization.id))

            elif request.method == "GET":
                # Populate form with current organization data
                form.name.data = organization.name
                form.slug.data = organization.slug
                form.description.data = organization.description
                form.is_active.data = organization.is_active

            return render_template(
                "admin/edit_organization.html", form=form, organization=organization
            )

        except Exception as e:
            current_app.logger.error(f"Error editing organization {org_id}: {str(e)}")
            flash("An error occurred while updating organization.", "danger")
            return render_template(
                "admin/edit_organization.html", form=form, organization=organization
            )

    @app.route("/admin/organizations/<int:org_id>/delete", methods=["POST"])
    @login_required
    @super_admin_required
    def admin_delete_organization(org_id):
        """Delete organization"""
        try:
            organization = db.session.get(Organization, org_id)
            if not organization:
                from flask import abort

                abort(404)

            org_name = organization.name

            # Check if organization has users
            user_count = UserOrganization.query.filter_by(organization_id=org_id).count()
            if user_count > 0:
                flash(
                    f"Cannot delete organization {org_name}. "
                    f"It has {user_count} user(s) assigned. "
                    "Please remove all users first.",
                    "danger",
                )
                return redirect(url_for("admin_view_organization", org_id=org_id))

            # Log admin action before deletion
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="DELETE_ORGANIZATION",
                target_user_id=None,
                details=f"Deleted organization: {org_name}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            # Delete organization
            success, error = organization.safe_delete()

            if error:
                flash(f"Error deleting organization: {error}", "danger")
            else:
                flash(f"Organization {org_name} deleted successfully!", "success")

            return redirect(url_for("admin_organizations"))

        except Exception as e:
            current_app.logger.error(f"Error deleting organization {org_id}: {str(e)}")
            flash("An error occurred while deleting organization.", "danger")
            return redirect(url_for("admin_organizations"))
