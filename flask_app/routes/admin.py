# flask_app/routes/admin.py

from datetime import datetime, timedelta, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc
from werkzeug.security import generate_password_hash

from flask_app.forms import ChangePasswordForm, CreateUserForm, UpdateUserForm
from flask_app.models import AdminLog, SystemMetrics, User, db
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
                    active_users = User.query.filter(
                        User.id.in_(org_user_ids), User.is_active.is_(True)
                    ).count()
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
                    for uo in UserOrganization.query.filter_by(
                        organization_id=organization.id, is_active=True
                    ).all()
                ]
                recent_users = User.query.filter(
                    User.id.in_(org_user_ids), User.created_at >= thirty_days_ago
                ).count()
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
                    for uo in UserOrganization.query.filter_by(
                        organization_id=organization.id, is_active=True
                    ).all()
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
                    return render_template(
                        "admin/create_user.html", form=form, organization=organization
                    )

                # Validate organization/role only if:
                # 1. The new user is NOT a super admin, AND
                # 2. The current user creating them is NOT a super admin
                # Super admins can create users without organization assignment
                if not is_super_admin and not current_user.is_super_admin:
                    # Get organization ID from request.form (hidden field set by JS)
                    # or form field
                    org_id_raw = request.form.get("organization_id", "").strip()
                    if (
                        not org_id_raw
                        and hasattr(form, "organization_search")
                        and form.organization_search.data
                    ):
                        org_id_raw = str(form.organization_search.data)

                    # Convert to int if it's a valid number
                    try:
                        org_id = int(org_id_raw) if org_id_raw and org_id_raw.isdigit() else None
                    except (ValueError, TypeError):
                        org_id = None

                    role_id = (
                        form.role_id.data
                        if hasattr(form, "role_id") and form.role_id.data
                        else None
                    )

                    current_app.logger.debug(
                        f"Organization ID from request: {org_id_raw}, "
                        f"converted: {org_id}, Role ID: {role_id}"
                    )

                    if not org_id or org_id == 0:
                        flash(
                            "Organization is required for non-super admin users. "
                            "Please select an organization from the dropdown.",
                            "danger",
                        )
                        return render_template(
                            "admin/create_user.html", form=form, organization=organization
                        )

                    if not role_id or role_id == 0:
                        flash("Role is required when organization is selected.", "danger")
                        return render_template(
                            "admin/create_user.html", form=form, organization=organization
                        )

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
                        if (
                            "unique" in error_lower
                            or "duplicate" in error_lower
                            or "already exists" in error_lower
                        ):
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
                                    "A user with this information already exists. "
                                    "Please check username and email.",
                                    "danger",
                                )
                        else:
                            flash(f"Error creating user: {error}", "danger")
                        current_app.logger.error(f"Error creating user: {error}")
                        return render_template(
                            "admin/create_user.html", form=form, organization=organization
                        )
                except Exception as create_exception:
                    # Catch any unexpected errors during user creation
                    current_app.logger.error(
                        f"Unexpected error creating user: {str(create_exception)}", exc_info=True
                    )
                    flash(
                        "An unexpected error occurred while creating the user. Please try again.",
                        "danger",
                    )
                    return render_template(
                        "admin/create_user.html", form=form, organization=organization
                    )

                if not new_user:
                    flash("Failed to create user. Please try again.", "danger")
                    current_app.logger.error("User creation returned None without error")
                    return render_template(
                        "admin/create_user.html", form=form, organization=organization
                    )
                else:
                    # Add user to organization if organization_id is provided
                    # (for non-super-admin users)
                    # Get organization ID from request.form (hidden field set by JS)
                    # or form field
                    org_id_raw = request.form.get("organization_id", "").strip()
                    if (
                        not org_id_raw
                        and hasattr(form, "organization_search")
                        and form.organization_search.data
                    ):
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
                                    current_app.logger.error(
                                        f"Error adding user to organization: {str(commit_error)}"
                                    )
                                    # Don't fail user creation if org assignment fails
                                    flash(
                                        f"User created but failed to add to organization: "
                                        f"{str(commit_error)}",
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
                    AdminLog.query.filter_by(target_user_id=user_id)
                    .order_by(desc(AdminLog.created_at))
                    .limit(10)
                    .all()
                )
            else:
                actions = (
                    AdminLog.query.filter_by(admin_user_id=current_user.id, target_user_id=user_id)
                    .order_by(desc(AdminLog.created_at))
                    .limit(10)
                    .all()
                )

            return render_template(
                "admin/view_user.html", user=user, actions=actions, organization=organization
            )

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
                is_super_admin = (
                    form.is_super_admin.data
                    if hasattr(form, "is_super_admin")
                    else user.is_super_admin
                )
                if is_super_admin != user.is_super_admin and not current_user.is_super_admin:
                    flash("Only super admins can change super admin status.", "danger")
                    return render_template(
                        "admin/edit_user.html", form=form, user=user, organization=organization
                    )

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
                            org_id = (
                                int(org_id_raw) if org_id_raw and org_id_raw.isdigit() else None
                            )
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
                                        f"Error updating user organization membership: "
                                        f"{str(commit_error)}"
                                    )
                                    flash(
                                        f"Error updating organization membership: "
                                        f"{str(commit_error)}",
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

            return render_template(
                "admin/edit_user.html", form=form, user=user, organization=organization
            )

        except Exception as e:
            current_app.logger.error(f"Error editing user {user_id}: {str(e)}")
            flash("An error occurred while updating user.", "danger")
            return render_template(
                "admin/edit_user.html", form=form, user=user, organization=organization
            )

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
                success, error = user.safe_update(
                    password_hash=generate_password_hash(form.new_password.data)
                )

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
                    for uo in UserOrganization.query.filter_by(
                        organization_id=organization.id, is_active=True
                    ).all()
                ]
                stats = {
                    "total_users": len(org_user_ids),
                    "active_users": User.query.filter(
                        User.id.in_(org_user_ids), User.is_active.is_(True)
                    ).count(),
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
