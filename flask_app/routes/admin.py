# flask_app/routes/admin.py

from datetime import datetime, timedelta, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc
from werkzeug.security import generate_password_hash

from flask_app.forms import ChangePasswordForm, CreateUserForm, UpdateUserForm
from flask_app.models import AdminLog, Organization, SystemMetrics, User, db
from flask_app.services.data_quality_service import DataQualityService
from flask_app.services.data_quality_field_config_service import (
    DataQualityFieldConfigService,
)
from flask_app.services.data_sampling_service import DataSamplingService
from flask_app.utils.permissions import get_current_organization, permission_required


def register_admin_routes(app):
    """Register admin dashboard routes"""

    @app.route("/admin")
    @login_required
    @permission_required("view_users", org_context=False)
    def admin_dashboard():
        """Admin dashboard main page"""
        try:
            organization = get_current_organization()

            # Get system statistics
            if current_user.is_super_admin:
                # Super admin sees all users
                total_users = User.query.count()
                active_users = User.query.filter_by(is_active=True).count()
                super_admin_users = User.query.filter_by(is_super_admin=True).count()
            else:
                # Organization-specific stats (if org context exists)
                if organization:
                    from flask_app.models import UserOrganization

                    org_user_ids = [
                        uo.user_id
                        for uo in UserOrganization.query.filter_by(
                            organization_id=organization.id, is_active=True
                        ).all()
                    ]
                    total_users = len(org_user_ids)
                    active_users = User.query.filter(User.id.in_(org_user_ids), User.is_active.is_(True)).count()
                    super_admin_users = 0
                else:
                    total_users = 0
                    active_users = 0
                    super_admin_users = 0

            # Get recent users (last 30 days)
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            if current_user.is_super_admin:
                recent_users = User.query.filter(User.created_at >= thirty_days_ago).count()
            elif organization:
                from flask_app.models import UserOrganization

                org_user_ids = [
                    uo.user_id
                    for uo in UserOrganization.query.filter_by(organization_id=organization.id, is_active=True).all()
                ]
                recent_users = User.query.filter(User.id.in_(org_user_ids), User.created_at >= thirty_days_ago).count()
            else:
                recent_users = 0

            # Get recent admin actions
            if current_user.is_super_admin:
                recent_actions = AdminLog.query.order_by(desc(AdminLog.created_at)).limit(10).all()
            else:
                recent_actions = (
                    AdminLog.query.filter_by(admin_user_id=current_user.id)
                    .order_by(desc(AdminLog.created_at))
                    .limit(10)
                    .all()
                )

            # Update system metrics (only for super admin)
            if current_user.is_super_admin:
                SystemMetrics.set_metric("total_users", total_users)
                SystemMetrics.set_metric("active_users", active_users)

            stats = {
                "total_users": total_users,
                "active_users": active_users,
                "super_admin_users": super_admin_users,
                "recent_users": recent_users,
                "recent_actions": recent_actions,
                "organization": organization,
            }

            current_app.logger.info(f"Admin dashboard accessed by {current_user.username}")
            return render_template("admin/dashboard.html", stats=stats)

        except Exception as e:
            current_app.logger.error(f"Error in admin dashboard: {str(e)}")
            flash("An error occurred while loading the dashboard.", "danger")
            return render_template("admin/dashboard.html", stats={})

    @app.route("/admin/users")
    @login_required
    @permission_required("view_users", org_context=False)
    def admin_users():
        """Admin user management page"""
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 20

            organization = get_current_organization()

            if current_user.is_super_admin:
                # Super admin sees all users
                users = User.query.paginate(page=page, per_page=per_page, error_out=False)
            elif organization:
                # Organization admin sees only users in their organization
                from flask_app.models import UserOrganization

                org_user_ids = [
                    uo.user_id
                    for uo in UserOrganization.query.filter_by(organization_id=organization.id, is_active=True).all()
                ]
                users = User.query.filter(User.id.in_(org_user_ids)).paginate(
                    page=page, per_page=per_page, error_out=False
                )
            else:
                # No organization context - show empty
                from flask_sqlalchemy import Pagination

                users = Pagination(page=page, per_page=per_page, total=0, items=[])

            return render_template("admin/users.html", users=users, organization=organization)

        except Exception as e:
            current_app.logger.error(f"Error in admin users page: {str(e)}")
            flash("An error occurred while loading users.", "danger")
            return redirect(url_for("admin_dashboard"))

    @app.route("/admin/users/create", methods=["GET", "POST"])
    @login_required
    @permission_required("create_users", org_context=False)
    def admin_create_user():
        """Create new user"""
        form = CreateUserForm()
        organization = get_current_organization()

        try:
            if form.validate_on_submit():
                # Only super admin can create super admin users
                # Handle boolean field - HTML forms send 'on' for checked, nothing for unchecked
                # WTForms BooleanField should handle this, but ensure we get proper boolean
                is_super_admin = False
                # Check request.form first (for test cases that pass boolean/string)
                # Flask request.form always returns strings, so we need to check
                # both None and string values
                is_super_admin_val = request.form.get("is_super_admin")
                if is_super_admin_val is not None:
                    # request.form returns strings, so check string values
                    if isinstance(is_super_admin_val, str):
                        is_super_admin_val_lower = is_super_admin_val.lower().strip()
                        if is_super_admin_val_lower in ("false", "0", "off", "no", "none", ""):
                            is_super_admin = False
                        else:
                            # Any non-empty string that's not explicitly false is treated as True
                            is_super_admin = True
                    elif isinstance(is_super_admin_val, bool):
                        is_super_admin = is_super_admin_val
                    else:
                        # If it's truthy and not a string/bool, treat as True
                        is_super_admin = bool(is_super_admin_val)
                # Otherwise check form field (for HTML forms)
                elif hasattr(form, "is_super_admin") and form.is_super_admin.data:
                    is_super_admin = True

                form_data = form.is_super_admin.data if hasattr(form, "is_super_admin") else "N/A"
                current_app.logger.debug(
                    f"is_super_admin determined: {is_super_admin} "
                    f"(from request.form: {is_super_admin_val}, from form.data: {form_data})"
                )

                if is_super_admin and not current_user.is_super_admin:
                    flash("Only super admins can create super admin users.", "danger")
                    return render_template("admin/create_user.html", form=form, organization=organization)

                # Validate organization/role only if:
                # 1. The new user is NOT a super admin, AND
                # 2. The current user creating them is NOT a super admin
                # Super admins can create users without organization assignment
                if not is_super_admin and not current_user.is_super_admin:
                    # Get organization ID from request.form (hidden field set by JS)
                    # or form field
                    org_id_raw = request.form.get("organization_id", "").strip()
                    if not org_id_raw and hasattr(form, "organization_search") and form.organization_search.data:
                        org_id_raw = str(form.organization_search.data)

                    # Convert to int if it's a valid number
                    try:
                        org_id = int(org_id_raw) if org_id_raw and org_id_raw.isdigit() else None
                    except (ValueError, TypeError):
                        org_id = None

                    role_id = form.role_id.data if hasattr(form, "role_id") and form.role_id.data else None

                    current_app.logger.debug(
                        f"Organization ID from request: {org_id_raw}, " f"converted: {org_id}, Role ID: {role_id}"
                    )

                    if not org_id or org_id == 0:
                        flash(
                            "Organization is required for non-super admin users. "
                            "Please select an organization from the dropdown.",
                            "danger",
                        )
                        return render_template("admin/create_user.html", form=form, organization=organization)

                    if not role_id or role_id == 0:
                        flash("Role is required when organization is selected.", "danger")
                        return render_template("admin/create_user.html", form=form, organization=organization)

                # Create new user within transaction to prevent race conditions
                # Database unique constraints will catch any duplicate usernames/emails
                # that might occur between form validation and creation
                try:
                    new_user, error = User.safe_create(
                        username=form.username.data.strip(),
                        email=form.email.data.strip().lower(),
                        password_hash=generate_password_hash(form.password.data),
                        first_name=form.first_name.data.strip() if form.first_name.data else None,
                        last_name=form.last_name.data.strip() if form.last_name.data else None,
                        is_active=form.is_active.data,
                        is_super_admin=is_super_admin,
                    )

                    if error:
                        # Check if error is due to unique constraint violation (race condition)
                        error_lower = error.lower()
                        if "unique" in error_lower or "duplicate" in error_lower or "already exists" in error_lower:
                            if "username" in error_lower or "user" in error_lower:
                                flash(
                                    "Username already exists. Please choose a different username.",
                                    "danger",
                                )
                            elif "email" in error_lower:
                                flash(
                                    "Email address already exists. Please use a different email.",
                                    "danger",
                                )
                            else:
                                flash(
                                    "A user with this information already exists. " "Please check username and email.",
                                    "danger",
                                )
                        else:
                            flash(f"Error creating user: {error}", "danger")
                        current_app.logger.error(f"Error creating user: {error}")
                        return render_template("admin/create_user.html", form=form, organization=organization)
                except Exception as create_exception:
                    # Catch any unexpected errors during user creation
                    current_app.logger.error(f"Unexpected error creating user: {str(create_exception)}", exc_info=True)
                    flash(
                        "An unexpected error occurred while creating the user. Please try again.",
                        "danger",
                    )
                    return render_template("admin/create_user.html", form=form, organization=organization)

                if not new_user:
                    flash("Failed to create user. Please try again.", "danger")
                    current_app.logger.error("User creation returned None without error")
                    return render_template("admin/create_user.html", form=form, organization=organization)
                else:
                    # Add user to organization if organization_id is provided
                    # (for non-super-admin users)
                    # Get organization ID from request.form (hidden field set by JS)
                    # or form field
                    org_id_raw = request.form.get("organization_id", "").strip()
                    if not org_id_raw and hasattr(form, "organization_search") and form.organization_search.data:
                        org_id_raw = str(form.organization_search.data)

                    try:
                        org_id = int(org_id_raw) if org_id_raw and org_id_raw.isdigit() else None
                    except (ValueError, TypeError):
                        org_id = None

                    # Get role_id from form or request
                    role_id = None
                    if hasattr(form, "role_id") and form.role_id.data and form.role_id.data != 0:
                        role_id = form.role_id.data
                    elif request.form.get("role_id"):
                        try:
                            role_id_val = int(request.form.get("role_id"))
                            if role_id_val != 0:
                                role_id = role_id_val
                        except (ValueError, TypeError):
                            role_id = None

                    # Add to organization if org_id is provided and role_id is provided
                    # For super admins creating regular users, we still want to assign
                    # them to organizations. Only skip if the user being created is a
                    # super admin
                    if org_id and role_id and not is_super_admin:
                        from flask_app.models import Organization, Role, UserOrganization

                        # Verify organization exists
                        org = db.session.get(Organization, org_id)
                        role = db.session.get(Role, role_id)

                        if org and role:
                            # Check if user already in organization
                            existing = UserOrganization.query.filter_by(
                                user_id=new_user.id, organization_id=org_id
                            ).first()

                            if not existing:
                                user_org = UserOrganization(
                                    user_id=new_user.id,
                                    organization_id=org_id,
                                    role_id=role_id,
                                    is_active=True,
                                )
                                db.session.add(user_org)
                                try:
                                    db.session.commit()
                                    current_app.logger.info(
                                        f"Added user {new_user.username} to organization "
                                        f"{org.name} with role {role.display_name}"
                                    )
                                except Exception as commit_error:
                                    db.session.rollback()
                                    current_app.logger.error(f"Error adding user to organization: {str(commit_error)}")
                                    # Don't fail user creation if org assignment fails
                                    flash(
                                        f"User created but failed to add to organization: " f"{str(commit_error)}",
                                        "warning",
                                    )
                        else:
                            current_app.logger.warning(
                                f"Could not add user to organization: org={org_id}, role={role_id}"
                            )

                    # Log admin action
                    try:
                        AdminLog.log_action(
                            admin_user_id=current_user.id,
                            action="CREATE_USER",
                            target_user_id=new_user.id,
                            details=f"Created user: {new_user.username}",
                            ip_address=request.remote_addr,
                            user_agent=request.headers.get("User-Agent"),
                        )
                    except Exception as log_error:
                        current_app.logger.error(f"Error logging admin action: {log_error}")

                    flash(f"User {new_user.username} created successfully!", "success")
                    current_app.logger.info(
                        f"User {new_user.username} created successfully, redirecting to admin_users"
                    )
                    return redirect(url_for("admin_users"))

            # Render form for GET requests or validation errors
            if request.method == "GET":
                # Create fresh form for GET requests
                form = CreateUserForm()
            return render_template("admin/create_user.html", form=form, organization=organization)

        except Exception as e:
            current_app.logger.error(f"Error in admin create user: {str(e)}")
            flash("An error occurred while creating user.", "danger")
            return render_template("admin/create_user.html", form=form, organization=organization)

    @app.route("/admin/users/<int:user_id>")
    @login_required
    @permission_required("view_users", org_context=False)
    def admin_view_user(user_id):
        """View user details"""
        try:
            user = db.session.get(User, user_id)
            if not user:
                from flask import abort

                abort(404)
            organization = get_current_organization()

            # Check if user is in organization (unless super admin)
            if not current_user.is_super_admin and organization:
                from flask_app.models import UserOrganization

                user_org = UserOrganization.query.filter_by(
                    user_id=user_id, organization_id=organization.id, is_active=True
                ).first()
                if not user_org:
                    flash("User not found in this organization.", "danger")
                    return redirect(url_for("admin_users"))

            # Get admin actions for this user
            if current_user.is_super_admin:
                actions = (
                    AdminLog.query.filter_by(target_user_id=user_id).order_by(desc(AdminLog.created_at)).limit(10).all()
                )
            else:
                actions = (
                    AdminLog.query.filter_by(admin_user_id=current_user.id, target_user_id=user_id)
                    .order_by(desc(AdminLog.created_at))
                    .limit(10)
                    .all()
                )

            return render_template("admin/view_user.html", user=user, actions=actions, organization=organization)

        except Exception as e:
            current_app.logger.error(f"Error viewing user {user_id}: {str(e)}")
            flash("User not found.", "danger")
            return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    @permission_required("edit_users", org_context=False)
    def admin_edit_user(user_id):
        """Edit user information"""
        user = db.session.get(User, user_id)
        if not user:
            from flask import abort

            abort(404)
        form = UpdateUserForm(user=user)
        organization = get_current_organization()

        try:
            # Check if user is in organization (unless super admin)
            if not current_user.is_super_admin and organization:
                from flask_app.models import UserOrganization

                user_org = UserOrganization.query.filter_by(
                    user_id=user_id, organization_id=organization.id, is_active=True
                ).first()
                if not user_org:
                    flash("User not found in this organization.", "danger")
                    return redirect(url_for("admin_users"))

            if form.validate_on_submit():
                # Only super admin can change super admin status
                is_super_admin = form.is_super_admin.data if hasattr(form, "is_super_admin") else user.is_super_admin
                if is_super_admin != user.is_super_admin and not current_user.is_super_admin:
                    flash("Only super admins can change super admin status.", "danger")
                    return render_template("admin/edit_user.html", form=form, user=user, organization=organization)

                # Update user
                success, error = user.safe_update(
                    username=form.username.data.strip(),
                    email=form.email.data.strip().lower(),
                    first_name=form.first_name.data.strip() if form.first_name.data else None,
                    last_name=form.last_name.data.strip() if form.last_name.data else None,
                    is_active=form.is_active.data,
                    is_super_admin=is_super_admin,
                )

                if error:
                    flash(f"Error updating user: {error}", "danger")
                else:
                    # Handle organization/role assignment if not super admin and fields provided
                    if not is_super_admin and hasattr(form, "role_id"):
                        # Get organization ID from request.form (hidden field set by JavaScript)
                        org_id_raw = request.form.get("organization_id", "").strip()

                        try:
                            org_id = int(org_id_raw) if org_id_raw and org_id_raw.isdigit() else None
                        except (ValueError, TypeError):
                            org_id = None
                        role_id = form.role_id.data

                        current_app.logger.debug(
                            f"Edit User - Organization ID from form: {org_id_raw}, "
                            f"converted: {org_id}, Role ID: {role_id}"
                        )

                        if org_id and org_id != 0 and role_id and role_id != 0:
                            from flask_app.models import Organization, Role, UserOrganization

                            # Verify organization and role exist
                            org = db.session.get(Organization, org_id)
                            role = db.session.get(Role, role_id)

                            if org and role:
                                # Check if user already in organization
                                existing = UserOrganization.query.filter_by(
                                    user_id=user.id, organization_id=org_id
                                ).first()

                                if existing:
                                    # Update existing membership
                                    existing.role_id = role_id
                                    existing.is_active = True
                                else:
                                    # Create new membership
                                    user_org = UserOrganization(
                                        user_id=user.id,
                                        organization_id=org_id,
                                        role_id=role_id,
                                        is_active=True,
                                    )
                                    db.session.add(user_org)

                                try:
                                    db.session.commit()
                                except Exception as commit_error:
                                    db.session.rollback()
                                    current_app.logger.error(
                                        f"Error updating user organization membership: " f"{str(commit_error)}"
                                    )
                                    flash(
                                        f"Error updating organization membership: " f"{str(commit_error)}",
                                        "danger",
                                    )
                                    return render_template(
                                        "admin/edit_user.html",
                                        form=form,
                                        user=user,
                                        organization=organization,
                                    )

                    # Log admin action
                    AdminLog.log_action(
                        admin_user_id=current_user.id,
                        action="UPDATE_USER",
                        target_user_id=user.id,
                        details=f"Updated user: {user.username}",
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get("User-Agent"),
                    )

                    flash(f"User {user.username} updated successfully!", "success")
                    return redirect(url_for("admin_view_user", user_id=user.id))

            elif request.method == "GET":
                # Populate form with current user data
                form.username.data = user.username
                form.email.data = user.email
                form.first_name.data = user.first_name
                form.last_name.data = user.last_name
                form.is_active.data = user.is_active
                if hasattr(form, "is_super_admin"):
                    form.is_super_admin.data = user.is_super_admin

            return render_template("admin/edit_user.html", form=form, user=user, organization=organization)

        except Exception as e:
            current_app.logger.error(f"Error editing user {user_id}: {str(e)}")
            flash("An error occurred while updating user.", "danger")
            return render_template("admin/edit_user.html", form=form, user=user, organization=organization)

    @app.route("/admin/users/<int:user_id>/change-password", methods=["GET", "POST"])
    @login_required
    @permission_required("edit_users", org_context=False)
    def admin_change_password(user_id):
        """Change user password"""
        user = db.session.get(User, user_id)
        if not user:
            from flask import abort

            abort(404)
        form = ChangePasswordForm()

        try:
            if form.validate_on_submit():
                # Update password
                success, error = user.safe_update(password_hash=generate_password_hash(form.new_password.data))

                if error:
                    flash(f"Error changing password: {error}", "danger")
                else:
                    # Log admin action
                    AdminLog.log_action(
                        admin_user_id=current_user.id,
                        action="CHANGE_PASSWORD",
                        target_user_id=user.id,
                        details=f"Password changed for user: {user.username}",
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get("User-Agent"),
                    )

                    flash(f"Password changed successfully for {user.username}!", "success")
                    return redirect(url_for("admin_view_user", user_id=user.id))

            return render_template("admin/change_password.html", form=form, user=user)

        except Exception as e:
            current_app.logger.error(f"Error changing password for user {user_id}: {str(e)}")
            flash("An error occurred while changing password.", "danger")
            return render_template("admin/change_password.html", form=form, user=user)

    @app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
    @login_required
    @permission_required("delete_users", org_context=False)
    def admin_delete_user(user_id):
        """Delete user"""
        try:
            user = db.session.get(User, user_id)
            if not user:
                from flask import abort

                abort(404)

            # Prevent deleting self
            if user.id == current_user.id:
                flash("You cannot delete your own account.", "danger")
                return redirect(url_for("admin_view_user", user_id=user_id))

            username = user.username

            # Log admin action before deletion
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="DELETE_USER",
                target_user_id=user.id,
                details=f"Deleted user: {username}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            # Delete user
            success, error = user.safe_delete()

            if error:
                flash(f"Error deleting user: {error}", "danger")
            else:
                flash(f"User {username} deleted successfully!", "success")

            return redirect(url_for("admin_users"))

        except Exception as e:
            current_app.logger.error(f"Error deleting user {user_id}: {str(e)}")
            flash("An error occurred while deleting user.", "danger")
            return redirect(url_for("admin_users"))

    @app.route("/admin/logs")
    @login_required
    @permission_required("view_users", org_context=False)
    def admin_logs():
        """View admin action logs"""
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 50

            logs = AdminLog.query.order_by(desc(AdminLog.created_at)).paginate(
                page=page, per_page=per_page, error_out=False
            )

            return render_template("admin/logs.html", logs=logs)

        except Exception as e:
            current_app.logger.error(f"Error loading admin logs: {str(e)}")
            flash("An error occurred while loading logs.", "danger")
            return redirect(url_for("admin_dashboard"))

    @app.route("/admin/stats")
    @login_required
    @permission_required("view_users", org_context=False)
    def admin_stats():
        """Get system statistics as JSON"""
        try:
            organization = get_current_organization()

            if current_user.is_super_admin:
                stats = {
                    "total_users": SystemMetrics.get_metric("total_users"),
                    "active_users": SystemMetrics.get_metric("active_users"),
                    "super_admin_users": User.query.filter_by(is_super_admin=True).count(),
                    "recent_logins": User.query.filter(
                        User.last_login >= datetime.now(timezone.utc) - timedelta(days=7)
                    ).count(),
                }
            elif organization:
                from flask_app.models import UserOrganization

                org_user_ids = [
                    uo.user_id
                    for uo in UserOrganization.query.filter_by(organization_id=organization.id, is_active=True).all()
                ]
                stats = {
                    "total_users": len(org_user_ids),
                    "active_users": User.query.filter(User.id.in_(org_user_ids), User.is_active.is_(True)).count(),
                    "super_admin_users": 0,
                    "recent_logins": User.query.filter(
                        User.id.in_(org_user_ids),
                        User.last_login >= datetime.now(timezone.utc) - timedelta(days=7),
                    ).count(),
                }
            else:
                stats = {
                    "total_users": 0,
                    "active_users": 0,
                    "super_admin_users": 0,
                    "recent_logins": 0,
                }

            return jsonify(stats)

        except Exception as e:
            current_app.logger.error(f"Error getting stats: {str(e)}")
            return jsonify({"error": "Failed to get statistics"}), 500

    # Data Quality Dashboard Routes
    @app.route("/admin/data-quality")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_dashboard():
        """Main data quality dashboard page"""
        try:
            organization = get_current_organization()

            # Get available organizations for filter
            if current_user.is_super_admin:
                organizations = Organization.query.filter_by(is_active=True).all()
            else:
                organizations = [organization] if organization else []

            # Log dashboard access
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="DATA_QUALITY_DASHBOARD_VIEW",
                details="Viewed data quality dashboard",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            current_app.logger.info(f"Data quality dashboard accessed by {current_user.username}")
            return render_template(
                "admin/data_quality.html",
                organization=organization,
                organizations=organizations,
                is_super_admin=current_user.is_super_admin,
            )
        except Exception as e:
            current_app.logger.error(f"Error in data quality dashboard: {str(e)}")
            flash("An error occurred while loading the data quality dashboard.", "danger")
            return redirect(url_for("admin_dashboard"))

    @app.route("/admin/data-quality/fields")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_fields():
        """Field configuration page for data quality dashboard"""
        try:
            organization = get_current_organization()

            # Log page access
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="DATA_QUALITY_FIELDS_VIEW",
                details="Viewed data quality field configuration",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            current_app.logger.info(f"Data quality field configuration accessed by {current_user.username}")
            return render_template(
                "admin/data_quality_fields.html",
                organization=organization,
                is_super_admin=current_user.is_super_admin,
            )
        except Exception as e:
            current_app.logger.error(f"Error in data quality fields page: {str(e)}")
            flash("An error occurred while loading the field configuration page.", "danger")
            return redirect(url_for("data_quality_dashboard"))

    @app.route("/admin/data-quality/api/clear-cache", methods=["POST"])
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_clear_cache():
        """Clear data quality metrics cache"""
        try:
            DataQualityService._clear_cache()
            return jsonify({"success": True, "message": "Cache cleared successfully"}), 200
        except Exception as e:
            current_app.logger.error(f"Error clearing data quality cache: {str(e)}", exc_info=True)
            return jsonify({"error": "Failed to clear cache"}), 500

    @app.route("/admin/data-quality/api/metrics")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_metrics():
        """Get overall metrics as JSON"""
        try:
            # Check if cache should be cleared
            clear_cache = request.args.get("clear_cache", "false").lower() == "true"
            if clear_cache:
                DataQualityService._clear_cache()
            
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Get overall metrics
            metrics = DataQualityService.get_overall_health_score(organization_id=organization_id)

            # Convert to JSON-serializable format
            response = {
                "overall_health_score": metrics.overall_health_score,
                "total_entities": metrics.total_entities,
                "timestamp": metrics.timestamp.isoformat(),
                "entity_metrics": [
                    {
                        "entity_type": em.entity_type,
                        "total_records": em.total_records,
                        "overall_completeness": em.overall_completeness,
                        "key_metrics": em.key_metrics,
                        "fields": [
                            {
                                "field_name": f.field_name,
                                "total_records": f.total_records,
                                "records_with_value": f.records_with_value,
                                "records_without_value": f.records_without_value,
                                "completeness_percentage": f.completeness_percentage,
                                "status": f.status,
                            }
                            for f in em.fields
                        ],
                    }
                    for em in metrics.entity_metrics
                ],
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error getting data quality metrics: {str(e)}", exc_info=True)
            return jsonify({"error": "Failed to get data quality metrics"}), 500

    @app.route("/admin/data-quality/api/entity/<entity_type>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_entity_metrics(entity_type):
        """Get entity-specific metrics"""
        try:
            # Check if cache should be cleared
            clear_cache = request.args.get("clear_cache", "false").lower() == "true"
            if clear_cache:
                DataQualityService._clear_cache()
            
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Get entity metrics
            metrics = DataQualityService.get_entity_metrics(entity_type=entity_type, organization_id=organization_id)

            # Convert to JSON-serializable format
            response = {
                "entity_type": metrics.entity_type,
                "total_records": metrics.total_records,
                "overall_completeness": metrics.overall_completeness,
                "key_metrics": metrics.key_metrics,
                "fields": [
                    {
                        "field_name": field.field_name,
                        "total_records": field.total_records,
                        "records_with_value": field.records_with_value,
                        "records_without_value": field.records_without_value,
                        "completeness_percentage": field.completeness_percentage,
                        "status": field.status,
                    }
                    for field in metrics.fields
                ],
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error getting entity metrics for {entity_type}: {str(e)}", exc_info=True)
            return jsonify({"error": f"Failed to get metrics for {entity_type}"}), 500

    @app.route("/admin/data-quality/api/export")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_export():
        """Export metrics as CSV/JSON"""
        try:
            import csv
            import io
            import json

            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            format_type = request.args.get("format", "json").lower()
            if format_type not in ("csv", "json"):
                return jsonify({"error": "Format must be 'csv' or 'json'"}), 400

            # Get overall metrics
            metrics = DataQualityService.get_overall_health_score(organization_id=organization_id)

            # Log export
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="DATA_QUALITY_EXPORT",
                details=f"Exported data quality metrics as {format_type}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            if format_type == "json":
                # Export as JSON
                response_data = {
                    "overall_health_score": metrics.overall_health_score,
                    "total_entities": metrics.total_entities,
                    "timestamp": metrics.timestamp.isoformat(),
                    "entity_metrics": [
                        {
                            "entity_type": em.entity_type,
                            "total_records": em.total_records,
                            "overall_completeness": em.overall_completeness,
                            "key_metrics": em.key_metrics,
                            "fields": [
                                {
                                    "field_name": field.field_name,
                                    "total_records": field.total_records,
                                    "records_with_value": field.records_with_value,
                                    "records_without_value": field.records_without_value,
                                    "completeness_percentage": field.completeness_percentage,
                                    "status": field.status,
                                }
                                for field in em.fields
                            ],
                        }
                        for em in metrics.entity_metrics
                    ],
                }

                from flask import make_response

                response = make_response(json.dumps(response_data, indent=2))
                response.headers["Content-Type"] = "application/json"
                response.headers[
                    "Content-Disposition"
                ] = f'attachment; filename="data_quality_metrics_{metrics.timestamp.strftime("%Y%m%d_%H%M%S")}.json"'
                return response
            else:
                # Export as CSV
                output = io.StringIO()
                writer = csv.writer(output)

                # Write header
                writer.writerow(
                    [
                        "Entity Type",
                        "Field Name",
                        "Total Records",
                        "Records With Value",
                        "Records Without Value",
                        "Completeness Percentage",
                        "Status",
                    ]
                )

                # Write data
                for em in metrics.entity_metrics:
                    for field in em.fields:
                        writer.writerow(
                            [
                                em.entity_type,
                                field.field_name,
                                field.total_records,
                                field.records_with_value,
                                field.records_without_value,
                                field.completeness_percentage,
                                field.status,
                            ]
                        )

                from flask import make_response

                response = make_response(output.getvalue())
                response.headers["Content-Type"] = "text/csv; charset=utf-8"
                response.headers[
                    "Content-Disposition"
                ] = f'attachment; filename="data_quality_metrics_{metrics.timestamp.strftime("%Y%m%d_%H%M%S")}.csv"'
                return response

        except Exception as e:
            current_app.logger.error(f"Error exporting data quality metrics: {str(e)}", exc_info=True)
            return jsonify({"error": "Failed to export data quality metrics"}), 500

    # Data Sampling API Endpoints
    @app.route("/admin/data-quality/api/samples/<entity_type>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_samples(entity_type):
        """Get sample records for an entity type"""
        try:
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Get sample size from query parameter
            sample_size = request.args.get("sample_size", type=int)

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Get samples
            result = DataSamplingService.get_samples(
                entity_type=entity_type,
                sample_size=sample_size,
                organization_id=organization_id,
            )

            # Convert to JSON-serializable format
            response = {
                "entity_type": result.entity_type,
                "total_records": result.total_records,
                "sample_size": result.sample_size,
                "timestamp": result.timestamp.isoformat(),
                "samples": [
                    {
                        "id": s.id,
                        "data": s.data,
                        "completeness_score": s.completeness_score,
                        "completeness_level": s.completeness_level,
                        "is_edge_case": s.is_edge_case,
                        "edge_case_reasons": s.edge_case_reasons,
                    }
                    for s in result.samples
                ],
            }

            # Log access
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="DATA_QUALITY_SAMPLES_VIEW",
                details=f"Viewed samples for {entity_type}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error getting samples for {entity_type}: {str(e)}", exc_info=True)
            return jsonify({"error": f"Failed to get samples for {entity_type}"}), 500

    @app.route("/admin/data-quality/api/statistics/<entity_type>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_statistics(entity_type):
        """Get statistical summaries for an entity type"""
        try:
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Get statistics
            statistics = DataSamplingService.get_statistics(entity_type=entity_type, organization_id=organization_id)

            # Convert to JSON-serializable format
            response = {
                "entity_type": entity_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "statistics": {
                    field_name: {
                        "field_name": stat.field_name,
                        "total_count": stat.total_count,
                        "non_null_count": stat.non_null_count,
                        "null_count": stat.null_count,
                        "unique_values": stat.unique_values,
                        "most_common_values": stat.most_common_values,
                        "min_value": str(stat.min_value) if stat.min_value is not None else None,
                        "max_value": str(stat.max_value) if stat.max_value is not None else None,
                        "avg_value": stat.avg_value,
                        "value_distribution": stat.value_distribution,
                    }
                    for field_name, stat in statistics.items()
                },
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error getting statistics for {entity_type}: {str(e)}", exc_info=True)
            return jsonify({"error": f"Failed to get statistics for {entity_type}"}), 500

    @app.route("/admin/data-quality/api/edge-cases/<entity_type>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_edge_cases(entity_type):
        """Get edge cases for an entity type"""
        try:
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Get limit from query parameter
            limit = request.args.get("limit", type=int, default=20)

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Get edge cases
            edge_cases = DataSamplingService.get_edge_cases(
                entity_type=entity_type, limit=limit, organization_id=organization_id
            )

            # Convert to JSON-serializable format
            response = {
                "entity_type": entity_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "edge_cases": [
                    {
                        "id": ec.id,
                        "data": ec.data,
                        "completeness_score": ec.completeness_score,
                        "completeness_level": ec.completeness_level,
                        "edge_case_reasons": ec.edge_case_reasons,
                    }
                    for ec in edge_cases
                ],
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error getting edge cases for {entity_type}: {str(e)}", exc_info=True)
            return jsonify({"error": f"Failed to get edge cases for {entity_type}"}), 500

    @app.route("/admin/data-quality/api/export-samples/<entity_type>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_export_samples(entity_type):
        """Export sample records as CSV/JSON"""
        try:
            import csv
            import io
            import json

            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            format_type = request.args.get("format", "json").lower()
            if format_type not in ("csv", "json"):
                return jsonify({"error": "Format must be 'csv' or 'json'"}), 400

            sample_size = request.args.get("sample_size", type=int)

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Get samples
            result = DataSamplingService.get_samples(
                entity_type=entity_type,
                sample_size=sample_size,
                organization_id=organization_id,
            )

            # Log export
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action="DATA_QUALITY_SAMPLES_EXPORT",
                details=f"Exported samples for {entity_type} as {format_type}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            if format_type == "json":
                # Export as JSON
                response_data = {
                    "entity_type": result.entity_type,
                    "total_records": result.total_records,
                    "sample_size": result.sample_size,
                    "timestamp": result.timestamp.isoformat(),
                    "samples": [
                        {
                            "id": s.id,
                            "data": s.data,
                            "completeness_score": s.completeness_score,
                            "completeness_level": s.completeness_level,
                            "is_edge_case": s.is_edge_case,
                            "edge_case_reasons": s.edge_case_reasons,
                        }
                        for s in result.samples
                    ],
                }

                from flask import make_response

                response = make_response(json.dumps(response_data, indent=2, default=str))
                response.headers["Content-Type"] = "application/json"
                timestamp_str = result.timestamp.strftime("%Y%m%d_%H%M%S")
                response.headers[
                    "Content-Disposition"
                ] = f'attachment; filename="data_quality_samples_{entity_type}_{timestamp_str}.json"'
                return response
            else:
                # Export as CSV
                if not result.samples:
                    return jsonify({"error": "No samples to export"}), 400

                output = io.StringIO()
                writer = csv.writer(output)

                # Get all field names from first sample
                field_names = list(result.samples[0].data.keys())
                field_names.extend(["completeness_score", "completeness_level", "is_edge_case", "edge_case_reasons"])

                # Write header
                writer.writerow(field_names)

                # Write data
                for sample in result.samples:
                    row = [sample.data.get(field, "") for field in result.samples[0].data.keys()]
                    row.append(sample.completeness_score)
                    row.append(sample.completeness_level)
                    row.append(sample.is_edge_case)
                    row.append("; ".join(sample.edge_case_reasons) if sample.edge_case_reasons else "")
                    writer.writerow(row)

                from flask import make_response

                response = make_response(output.getvalue())
                response.headers["Content-Type"] = "text/csv; charset=utf-8"
                timestamp_str = result.timestamp.strftime("%Y%m%d_%H%M%S")
                response.headers[
                    "Content-Disposition"
                ] = f'attachment; filename="data_quality_samples_{entity_type}_{timestamp_str}.csv"'
                return response

        except Exception as e:
            current_app.logger.error(f"Error exporting samples for {entity_type}: {str(e)}", exc_info=True)
            return jsonify({"error": f"Failed to export samples for {entity_type}"}), 500

    # Field-Specific API Endpoints
    @app.route("/admin/data-quality/api/field-samples/<entity_type>/<field_name>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_field_samples(entity_type, field_name):
        """Get sample records filtered by a specific field"""
        try:
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Get sample size from query parameter
            sample_size = request.args.get("sample_size", type=int)

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Check if field is enabled (disabled fields should not be accessible)
            if not DataQualityFieldConfigService.is_field_enabled(entity_type, field_name, organization_id):
                return jsonify({"error": f"Field {field_name} is disabled and cannot be accessed"}), 403

            # Get field-specific samples
            result = DataSamplingService.get_field_samples(
                entity_type=entity_type,
                field_name=field_name,
                sample_size=sample_size,
                organization_id=organization_id,
            )

            # Convert to JSON-serializable format
            response = {
                "entity_type": result.entity_type,
                "field_name": field_name,
                "total_records": result.total_records,
                "sample_size": result.sample_size,
                "timestamp": result.timestamp.isoformat(),
                "samples": [
                    {
                        "id": s.id,
                        "data": s.data,
                        "completeness_score": s.completeness_score,
                        "completeness_level": s.completeness_level,
                        "is_edge_case": s.is_edge_case,
                        "edge_case_reasons": s.edge_case_reasons,
                    }
                    for s in result.samples
                ],
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(
                f"Error getting field samples for {entity_type}.{field_name}: {str(e)}", exc_info=True
            )
            return jsonify({"error": f"Failed to get field samples for {field_name}"}), 500

    @app.route("/admin/data-quality/api/field-statistics/<entity_type>/<field_name>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_field_statistics(entity_type, field_name):
        """Get statistics for a specific field"""
        try:
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Check if field is enabled (disabled fields should not be accessible)
            if not DataQualityFieldConfigService.is_field_enabled(entity_type, field_name, organization_id):
                return jsonify({"error": f"Field {field_name} is disabled and cannot be accessed"}), 403

            # Get field statistics
            statistics = DataSamplingService.get_field_statistics(
                entity_type=entity_type, field_name=field_name, organization_id=organization_id
            )

            if not statistics:
                return jsonify({"error": f"Field {field_name} not found"}), 404

            # Convert to JSON-serializable format
            response = {
                "entity_type": entity_type,
                "field_name": field_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "statistics": {
                    "field_name": statistics.field_name,
                    "total_count": statistics.total_count,
                    "non_null_count": statistics.non_null_count,
                    "null_count": statistics.null_count,
                    "unique_values": statistics.unique_values,
                    "most_common_values": statistics.most_common_values,
                    "min_value": str(statistics.min_value) if statistics.min_value is not None else None,
                    "max_value": str(statistics.max_value) if statistics.max_value is not None else None,
                    "avg_value": statistics.avg_value,
                    "value_distribution": statistics.value_distribution,
                },
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(
                f"Error getting field statistics for {entity_type}.{field_name}: {str(e)}", exc_info=True
            )
            return jsonify({"error": f"Failed to get statistics for {field_name}"}), 500

    @app.route("/admin/data-quality/api/field-edge-cases/<entity_type>/<field_name>")
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_field_edge_cases(entity_type, field_name):
        """Get edge cases for a specific field"""
        try:
            organization = get_current_organization()
            organization_id = None

            # Get organization_id from query parameter if super admin
            if current_user.is_super_admin:
                org_id_param = request.args.get("organization_id", type=int)
                if org_id_param:
                    organization_id = org_id_param
            elif organization:
                # Non-super admin can only see their organization
                organization_id = organization.id

            # Get limit from query parameter
            limit = request.args.get("limit", type=int, default=20)

            # Validate entity type
            valid_entity_types = [
                "contact",
                "volunteer",
                "student",
                "teacher",
                "event",
                "organization",
                "user",
            ]
            if entity_type not in valid_entity_types:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Check if field is enabled (disabled fields should not be accessible)
            if not DataQualityFieldConfigService.is_field_enabled(entity_type, field_name, organization_id):
                return jsonify({"error": f"Field {field_name} is disabled and cannot be accessed"}), 403

            # Get field-specific edge cases
            edge_cases = DataSamplingService.get_field_edge_cases(
                entity_type=entity_type, field_name=field_name, limit=limit, organization_id=organization_id
            )

            # Convert to JSON-serializable format
            response = {
                "entity_type": entity_type,
                "field_name": field_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "edge_cases": [
                    {
                        "id": ec.id,
                        "data": ec.data,
                        "completeness_score": ec.completeness_score,
                        "completeness_level": ec.completeness_level,
                        "edge_case_reasons": ec.edge_case_reasons,
                    }
                    for ec in edge_cases
                ],
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(
                f"Error getting field edge cases for {entity_type}.{field_name}: {str(e)}", exc_info=True
            )
            return jsonify({"error": f"Failed to get edge cases for {field_name}"}), 500

    # Field Configuration API Endpoints
    @app.route("/admin/data-quality/api/field-config", methods=["GET"])
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_field_config():
        """Get current field configuration"""
        try:
            organization = get_current_organization()
            organization_id = None

            # For v1, use system-wide configuration
            # Future: support org-specific configuration
            # if current_user.is_super_admin:
            #     org_id_param = request.args.get("organization_id", type=int)
            #     if org_id_param:
            #         organization_id = org_id_param
            # elif organization:
            #     organization_id = organization.id

            # Get field configuration for display
            config = DataQualityFieldConfigService.get_field_config_for_display(organization_id)

            # Ensure all entity types are present (debug/logging)
            expected_entity_types = ["volunteer", "contact", "student", "teacher", "event", "organization", "user"]
            for entity_type in expected_entity_types:
                if entity_type not in config:
                    current_app.logger.warning(f"Entity type {entity_type} missing from field configuration")
                    # Add empty config for missing entity types
                    config[entity_type] = {}

            # Get field definitions
            field_definitions = DataQualityFieldConfigService.get_field_definitions()

            response = {
                "entity_types": config,
                "field_definitions": field_definitions,
                "organization_id": organization_id,
            }

            current_app.logger.debug(f"Field configuration API returning {len(config)} entity types: {list(config.keys())}")

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error getting field configuration: {str(e)}", exc_info=True)
            return jsonify({"error": "Failed to get field configuration"}), 500

    @app.route("/admin/data-quality/api/field-config", methods=["POST"])
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_field_config_update():
        """Update field configuration"""
        try:
            organization = get_current_organization()
            organization_id = None

            # For v1, use system-wide configuration
            # Future: support org-specific configuration

            # Get request data
            data = request.get_json()
            if not data:
                return jsonify({"error": "Request body must be JSON"}), 400

            # Support both single field update and batch update
            if "changes" in data:
                # Batch update
                changes = data.get("changes", [])
                if not isinstance(changes, list) or len(changes) == 0:
                    return jsonify({"error": "Invalid changes format"}), 400

                # Get current configuration
                disabled_fields = DataQualityFieldConfigService.get_disabled_fields(organization_id)
                field_definitions = DataQualityFieldConfigService.get_field_definitions()

                # Apply all changes
                updated_fields = []
                for change in changes:
                    entity_type = change.get("entity_type")
                    field_name = change.get("field_name")
                    is_enabled = change.get("is_enabled")

                    if not entity_type or not field_name or is_enabled is None:
                        continue

                    # Validate entity type and field name
                    if entity_type not in field_definitions:
                        continue
                    if field_name not in field_definitions[entity_type]:
                        continue

                    # Update configuration
                    if entity_type not in disabled_fields:
                        disabled_fields[entity_type] = []

                    if is_enabled:
                        # Remove from disabled list
                        if field_name in disabled_fields[entity_type]:
                            disabled_fields[entity_type].remove(field_name)
                    else:
                        # Add to disabled list
                        if field_name not in disabled_fields[entity_type]:
                            disabled_fields[entity_type].append(field_name)

                    updated_fields.append({"entity_type": entity_type, "field_name": field_name, "is_enabled": is_enabled})

                # Save configuration
                success = DataQualityFieldConfigService.set_disabled_fields(disabled_fields, organization_id)

                if not success:
                    return jsonify({"error": "Failed to update field configuration"}), 500

                # Clear cache for data quality metrics
                DataQualityService._clear_cache()

                # Log action
                AdminLog.log_action(
                    admin_user_id=current_user.id,
                    action="DATA_QUALITY_FIELD_CONFIG_UPDATE",
                    details=f"Updated field configuration: {len(updated_fields)} fields",
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                )

                response = {
                    "success": True,
                    "message": f"Field configuration updated: {len(updated_fields)} fields",
                    "updated_fields": updated_fields,
                }

                return jsonify(response)
            else:
                # Single field update (for backward compatibility)
                entity_type = data.get("entity_type")
                field_name = data.get("field_name")
                is_enabled = data.get("is_enabled")

                if not entity_type or not field_name or is_enabled is None:
                    return (
                        jsonify(
                            {
                                "error": "Missing required fields: entity_type, field_name, is_enabled (or 'changes' for batch update)"
                            }
                        ),
                        400,
                    )

                # Validate entity type
                field_definitions = DataQualityFieldConfigService.get_field_definitions()
                if entity_type not in field_definitions:
                    return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

                # Validate field name
                if field_name not in field_definitions[entity_type]:
                    return (
                        jsonify({"error": f"Invalid field name: {field_name} for entity type: {entity_type}"}),
                        400,
                    )

                # Get current configuration
                disabled_fields = DataQualityFieldConfigService.get_disabled_fields(organization_id)

                # Update configuration
                if entity_type not in disabled_fields:
                    disabled_fields[entity_type] = []

                if is_enabled:
                    # Remove from disabled list
                    if field_name in disabled_fields[entity_type]:
                        disabled_fields[entity_type].remove(field_name)
                else:
                    # Add to disabled list
                    if field_name not in disabled_fields[entity_type]:
                        disabled_fields[entity_type].append(field_name)

                # Save configuration
                success = DataQualityFieldConfigService.set_disabled_fields(disabled_fields, organization_id)

                if not success:
                    return jsonify({"error": "Failed to update field configuration"}), 500

                # Clear cache for data quality metrics
                DataQualityService._clear_cache()

                # Log action
                AdminLog.log_action(
                    admin_user_id=current_user.id,
                    action="DATA_QUALITY_FIELD_CONFIG_UPDATE",
                    details=f"Updated field configuration: {entity_type}.{field_name} = {is_enabled}",
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                )

                response = {
                    "success": True,
                    "message": "Field configuration updated",
                    "config": {
                        "entity_type": entity_type,
                        "field_name": field_name,
                        "is_enabled": is_enabled,
                    },
                }

                return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error updating field configuration: {str(e)}", exc_info=True)
            return jsonify({"error": "Failed to update field configuration"}), 500

    @app.route("/admin/data-quality/api/field-config/<entity_type>", methods=["GET"])
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_field_config_entity(entity_type):
        """Get field configuration for a specific entity type"""
        try:
            organization = get_current_organization()
            organization_id = None

            # For v1, use system-wide configuration
            # Future: support org-specific configuration

            # Validate entity type
            field_definitions = DataQualityFieldConfigService.get_field_definitions()
            if entity_type not in field_definitions:
                return jsonify({"error": f"Invalid entity type: {entity_type}"}), 400

            # Get field configuration for entity
            config = DataQualityFieldConfigService.get_field_config_for_display(organization_id)
            entity_config = config.get(entity_type, {})

            response = {
                "entity_type": entity_type,
                "fields": entity_config,
                "organization_id": organization_id,
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(
                f"Error getting field configuration for {entity_type}: {str(e)}", exc_info=True
            )
            return jsonify({"error": f"Failed to get field configuration for {entity_type}"}), 500

    @app.route("/admin/data-quality/api/field-definitions", methods=["GET"])
    @login_required
    @permission_required("view_users", org_context=False)
    def data_quality_field_definitions():
        """Get available field definitions"""
        try:
            entity_type = request.args.get("entity_type")

            # Get field definitions
            field_definitions = DataQualityFieldConfigService.get_field_definitions(entity_type)

            response = {
                "field_definitions": field_definitions,
            }

            return jsonify(response)
        except Exception as e:
            current_app.logger.error(f"Error getting field definitions: {str(e)}", exc_info=True)
            return jsonify({"error": "Failed to get field definitions"}), 500
