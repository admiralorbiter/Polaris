# flask_app/routes/organization.py

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc, or_
from sqlalchemy.orm import joinedload

from flask_app.forms.organization import CreateOrganizationForm, UpdateOrganizationForm
from flask_app.models import (
    AddressType,
    AdminLog,
    Organization,
    OrganizationAddress,
    OrganizationType,
    UserOrganization,
    db,
)
from flask_app.utils.permissions import super_admin_required


def register_organization_routes(app):
    """Register organization management routes"""

    # Public routes (accessible to all authenticated users)
    @app.route("/organizations")
    @login_required
    def organizations_list():
        """List all organizations with search and sorting"""
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 20
            search_term = request.args.get("search", "").strip()
            sort_column = request.args.get("sort", "name")
            sort_order = request.args.get("order", "asc")

            # Base query with eager loading
            query = Organization.query.options(joinedload(Organization.addresses))

            # Apply search filter if provided
            if search_term:
                search_filter = or_(
                    Organization.name.ilike(f"%{search_term}%"),
                    Organization.description.ilike(f"%{search_term}%"),
                    Organization.organization_type.ilike(f"%{search_term}%"),
                    Organization.website.ilike(f"%{search_term}%"),
                    Organization.email.ilike(f"%{search_term}%"),
                    Organization.phone.ilike(f"%{search_term}%"),
                )
                query = query.filter(search_filter)

            # Apply sorting
            sort_mapping = {
                "name": Organization.name,
                "type": Organization.organization_type,
                "created": Organization.created_at,
                "status": Organization.is_active,
            }

            if sort_column in sort_mapping:
                sort_field = sort_mapping[sort_column]
                if sort_order == "desc":
                    query = query.order_by(desc(sort_field))
                else:
                    query = query.order_by(sort_field)
            else:
                # Default sort by name
                query = query.order_by(Organization.name)

            # Paginate
            organizations = query.paginate(page=page, per_page=per_page, error_out=False)

            return render_template(
                "organizations/list.html",
                organizations=organizations,
                search_term=search_term,
                sort_column=sort_column,
                sort_order=sort_order,
            )

        except Exception as e:
            current_app.logger.error(f"Error in organizations list page: {str(e)}")
            flash("An error occurred while loading organizations.", "danger")
            return redirect(url_for("index"))

    @app.route("/organizations/create", methods=["GET", "POST"])
    @login_required
    def organizations_create():
        """Create new organization"""
        form = CreateOrganizationForm()

        try:
            if form.validate_on_submit():
                # Convert enum string values to enum objects
                org_type_enum = OrganizationType(form.organization_type.data)

                # Create new organization
                new_org, error = Organization.safe_create(
                    name=form.name.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    organization_type=org_type_enum,
                    website=form.website.data.strip() if form.website.data else None,
                    phone=form.phone.data.strip() if form.phone.data else None,
                    email=form.email.data.strip() if form.email.data else None,
                    tax_id=form.tax_id.data.strip() if form.tax_id.data else None,
                    logo_url=form.logo_url.data.strip() if form.logo_url.data else None,
                    contact_person_name=form.contact_person_name.data.strip()
                    if form.contact_person_name.data
                    else None,
                    contact_person_title=form.contact_person_title.data.strip()
                    if form.contact_person_title.data
                    else None,
                    founded_date=form.founded_date.data if form.founded_date.data else None,
                    is_active=form.is_active.data,
                )

                if error:
                    flash(f"Error creating organization: {error}", "danger")
                else:
                    # Create address if provided
                    if form.street_address_1.data and form.city.data and form.state.data:
                        try:
                            address_type_enum = AddressType(form.address_type.data)
                            address = OrganizationAddress(
                                organization_id=new_org.id,
                                address_type=address_type_enum,
                                street_address_1=form.street_address_1.data.strip(),
                                street_address_2=form.street_address_2.data.strip()
                                if form.street_address_2.data
                                else None,
                                city=form.city.data.strip(),
                                state=form.state.data.strip(),
                                postal_code=form.postal_code.data.strip(),
                                country=form.country.data.strip() if form.country.data else "US",
                                is_primary=True,
                            )
                            db.session.add(address)
                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            current_app.logger.error(f"Error creating address for organization {new_org.id}: {str(e)}")

                    flash(f"Organization {new_org.name} created successfully!", "success")
                    return redirect(url_for("organizations_list"))

            return render_template("organizations/create.html", form=form)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating organization: {str(e)}")
            flash(f"An error occurred while creating organization: {str(e)}", "danger")
            return render_template("organizations/create.html", form=form)

    @app.route("/organizations/<int:org_id>")
    @login_required
    def organizations_view(org_id):
        """View organization details"""
        try:
            organization = (
                db.session.query(Organization)
                .options(
                    joinedload(Organization.addresses),
                    joinedload(Organization.users),
                )
                .filter_by(id=org_id)
                .first()
            )

            if not organization:
                from flask import abort

                abort(404)

            # Get statistics using helper methods
            active_volunteers = organization.get_active_volunteers()
            total_hours = organization.get_total_volunteer_hours()
            primary_address = organization.get_primary_address()

            stats = {
                "active_volunteers_count": len(active_volunteers),
                "total_volunteer_hours": total_hours,
            }

            return render_template(
                "organizations/view.html",
                organization=organization,
                stats=stats,
                primary_address=primary_address,
            )

        except Exception as e:
            current_app.logger.error(f"Error viewing organization {org_id}: {str(e)}")
            flash("An error occurred while loading organization details.", "danger")
            return redirect(url_for("organizations_list"))

    @app.route("/organizations/<int:org_id>/edit", methods=["GET", "POST"])
    @login_required
    def organizations_edit(org_id):
        """Edit organization information"""
        organization = (
            db.session.query(Organization).options(joinedload(Organization.addresses)).filter_by(id=org_id).first()
        )

        if not organization:
            from flask import abort

            abort(404)

        form = UpdateOrganizationForm()

        # Pre-populate form fields only on GET requests
        if request.method == "GET":
            form.name.data = organization.name
            form.slug.data = organization.slug
            form.description.data = organization.description
            form.organization_type.data = (
                organization.organization_type.value if organization.organization_type else OrganizationType.OTHER.value
            )
            form.is_active.data = organization.is_active
            form.website.data = organization.website
            form.phone.data = organization.phone
            form.email.data = organization.email
            form.tax_id.data = organization.tax_id
            form.logo_url.data = organization.logo_url
            form.contact_person_name.data = organization.contact_person_name
            form.contact_person_title.data = organization.contact_person_title
            form.founded_date.data = organization.founded_date

            # Pre-populate address fields from primary address
            primary_address = organization.get_primary_address()
            if primary_address:
                form.street_address_1.data = primary_address.street_address_1
                form.street_address_2.data = primary_address.street_address_2
                form.city.data = primary_address.city
                form.state.data = primary_address.state
                form.postal_code.data = primary_address.postal_code
                form.country.data = primary_address.country
                form.address_type.data = primary_address.address_type.value

        try:
            if form.validate_on_submit():
                # Convert enum string values to enum objects
                org_type_enum = OrganizationType(form.organization_type.data)

                # Update organization
                success, error = organization.safe_update(
                    name=form.name.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    organization_type=org_type_enum,
                    website=form.website.data.strip() if form.website.data else None,
                    phone=form.phone.data.strip() if form.phone.data else None,
                    email=form.email.data.strip() if form.email.data else None,
                    tax_id=form.tax_id.data.strip() if form.tax_id.data else None,
                    logo_url=form.logo_url.data.strip() if form.logo_url.data else None,
                    contact_person_name=form.contact_person_name.data.strip()
                    if form.contact_person_name.data
                    else None,
                    contact_person_title=form.contact_person_title.data.strip()
                    if form.contact_person_title.data
                    else None,
                    founded_date=form.founded_date.data if form.founded_date.data else None,
                    is_active=form.is_active.data,
                )

                if error:
                    flash(f"Error updating organization: {error}", "danger")
                else:
                    # Update or create address
                    if form.street_address_1.data and form.city.data and form.state.data:
                        try:
                            address_type_enum = AddressType(form.address_type.data)
                            primary_address = organization.get_primary_address()

                            if primary_address:
                                # Update existing primary address
                                primary_address.street_address_1 = form.street_address_1.data.strip()
                                primary_address.street_address_2 = (
                                    form.street_address_2.data.strip() if form.street_address_2.data else None
                                )
                                primary_address.city = form.city.data.strip()
                                primary_address.state = form.state.data.strip()
                                primary_address.postal_code = form.postal_code.data.strip()
                                primary_address.country = form.country.data.strip() if form.country.data else "US"
                                primary_address.address_type = address_type_enum
                            else:
                                # Create new primary address
                                address = OrganizationAddress(
                                    organization_id=organization.id,
                                    address_type=address_type_enum,
                                    street_address_1=form.street_address_1.data.strip(),
                                    street_address_2=form.street_address_2.data.strip()
                                    if form.street_address_2.data
                                    else None,
                                    city=form.city.data.strip(),
                                    state=form.state.data.strip(),
                                    postal_code=form.postal_code.data.strip(),
                                    country=form.country.data.strip() if form.country.data else "US",
                                    is_primary=True,
                                )
                                db.session.add(address)

                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            current_app.logger.error(
                                f"Error updating address for organization {organization.id}: {str(e)}"
                            )

                    flash(f"Organization {organization.name} updated successfully!", "success")
                    return redirect(url_for("organizations_view", org_id=org_id))

            return render_template("organizations/edit.html", form=form, organization=organization)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating organization {org_id}: {str(e)}")
            flash(f"An error occurred while updating organization: {str(e)}", "danger")
            return render_template("organizations/edit.html", form=form, organization=organization)

    # Admin routes (keep existing admin routes)
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
                org.user_count = UserOrganization.query.filter_by(organization_id=org.id, is_active=True).count()

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
                # Convert enum string values to enum objects
                org_type_enum = OrganizationType(form.organization_type.data)

                # Create new organization
                new_org, error = Organization.safe_create(
                    name=form.name.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    organization_type=org_type_enum,
                    website=form.website.data.strip() if form.website.data else None,
                    phone=form.phone.data.strip() if form.phone.data else None,
                    email=form.email.data.strip() if form.email.data else None,
                    tax_id=form.tax_id.data.strip() if form.tax_id.data else None,
                    logo_url=form.logo_url.data.strip() if form.logo_url.data else None,
                    contact_person_name=form.contact_person_name.data.strip()
                    if form.contact_person_name.data
                    else None,
                    contact_person_title=form.contact_person_title.data.strip()
                    if form.contact_person_title.data
                    else None,
                    founded_date=form.founded_date.data if form.founded_date.data else None,
                    is_active=form.is_active.data,
                )

                if error:
                    flash(f"Error creating organization: {error}", "danger")
                else:
                    # Create address if provided
                    if form.street_address_1.data and form.city.data and form.state.data:
                        try:
                            address_type_enum = AddressType(form.address_type.data)
                            address = OrganizationAddress(
                                organization_id=new_org.id,
                                address_type=address_type_enum,
                                street_address_1=form.street_address_1.data.strip(),
                                street_address_2=form.street_address_2.data.strip()
                                if form.street_address_2.data
                                else None,
                                city=form.city.data.strip(),
                                state=form.state.data.strip(),
                                postal_code=form.postal_code.data.strip(),
                                country=form.country.data.strip() if form.country.data else "US",
                                is_primary=True,
                            )
                            db.session.add(address)
                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            current_app.logger.error(f"Error creating address for organization {new_org.id}: {str(e)}")

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

            total_users = UserOrganization.query.filter_by(organization_id=org_id, is_active=True).count()

            # Count active users in organization
            user_org_ids = [
                uo.user_id for uo in UserOrganization.query.filter_by(organization_id=org_id, is_active=True).all()
            ]
            active_users = (
                User.query.filter(User.id.in_(user_org_ids), User.is_active.is_(True)).count() if user_org_ids else 0
            )

            # Get users in organization
            user_orgs = UserOrganization.query.filter_by(organization_id=org_id, is_active=True).all()

            stats = {"total_users": total_users, "active_users": active_users, "users": user_orgs}

            return render_template("admin/view_organization.html", organization=organization, stats=stats)

        except Exception as e:
            current_app.logger.error(f"Error viewing organization {org_id}: {str(e)}")
            flash("Organization not found.", "danger")
            return redirect(url_for("admin_organizations"))

    @app.route("/admin/organizations/<int:org_id>/edit", methods=["GET", "POST"])
    @login_required
    @super_admin_required
    def admin_edit_organization(org_id):
        """Edit organization information"""
        organization = (
            db.session.query(Organization).options(joinedload(Organization.addresses)).filter_by(id=org_id).first()
        )
        if not organization:
            from flask import abort

            abort(404)
        form = UpdateOrganizationForm()

        # Pre-populate form fields only on GET requests
        if request.method == "GET":
            form.name.data = organization.name
            form.slug.data = organization.slug
            form.description.data = organization.description
            form.organization_type.data = (
                organization.organization_type.value if organization.organization_type else OrganizationType.OTHER.value
            )
            form.is_active.data = organization.is_active
            form.website.data = organization.website
            form.phone.data = organization.phone
            form.email.data = organization.email
            form.tax_id.data = organization.tax_id
            form.logo_url.data = organization.logo_url
            form.contact_person_name.data = organization.contact_person_name
            form.contact_person_title.data = organization.contact_person_title
            form.founded_date.data = organization.founded_date

            # Pre-populate address fields from primary address
            primary_address = organization.get_primary_address()
            if primary_address:
                form.street_address_1.data = primary_address.street_address_1
                form.street_address_2.data = primary_address.street_address_2
                form.city.data = primary_address.city
                form.state.data = primary_address.state
                form.postal_code.data = primary_address.postal_code
                form.country.data = primary_address.country
                form.address_type.data = primary_address.address_type.value

        try:
            if form.validate_on_submit():
                # Convert enum string values to enum objects
                org_type_enum = OrganizationType(form.organization_type.data)

                # Update organization
                success, error = organization.safe_update(
                    name=form.name.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    organization_type=org_type_enum,
                    website=form.website.data.strip() if form.website.data else None,
                    phone=form.phone.data.strip() if form.phone.data else None,
                    email=form.email.data.strip() if form.email.data else None,
                    tax_id=form.tax_id.data.strip() if form.tax_id.data else None,
                    logo_url=form.logo_url.data.strip() if form.logo_url.data else None,
                    contact_person_name=form.contact_person_name.data.strip()
                    if form.contact_person_name.data
                    else None,
                    contact_person_title=form.contact_person_title.data.strip()
                    if form.contact_person_title.data
                    else None,
                    founded_date=form.founded_date.data if form.founded_date.data else None,
                    is_active=form.is_active.data,
                )

                if error:
                    flash(f"Error updating organization: {error}", "danger")
                else:
                    # Update or create address
                    if form.street_address_1.data and form.city.data and form.state.data:
                        try:
                            address_type_enum = AddressType(form.address_type.data)
                            primary_address = organization.get_primary_address()

                            if primary_address:
                                # Update existing primary address
                                primary_address.street_address_1 = form.street_address_1.data.strip()
                                primary_address.street_address_2 = (
                                    form.street_address_2.data.strip() if form.street_address_2.data else None
                                )
                                primary_address.city = form.city.data.strip()
                                primary_address.state = form.state.data.strip()
                                primary_address.postal_code = form.postal_code.data.strip()
                                primary_address.country = form.country.data.strip() if form.country.data else "US"
                                primary_address.address_type = address_type_enum
                            else:
                                # Create new primary address
                                address = OrganizationAddress(
                                    organization_id=organization.id,
                                    address_type=address_type_enum,
                                    street_address_1=form.street_address_1.data.strip(),
                                    street_address_2=form.street_address_2.data.strip()
                                    if form.street_address_2.data
                                    else None,
                                    city=form.city.data.strip(),
                                    state=form.state.data.strip(),
                                    postal_code=form.postal_code.data.strip(),
                                    country=form.country.data.strip() if form.country.data else "US",
                                    is_primary=True,
                                )
                                db.session.add(address)

                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            current_app.logger.error(
                                f"Error updating address for organization {organization.id}: {str(e)}"
                            )

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

            return render_template("admin/edit_organization.html", form=form, organization=organization)

        except Exception as e:
            current_app.logger.error(f"Error editing organization {org_id}: {str(e)}")
            flash("An error occurred while updating organization.", "danger")
            return render_template("admin/edit_organization.html", form=form, organization=organization)

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
