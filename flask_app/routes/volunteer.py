# flask_app/routes/volunteer.py
"""
Volunteer management routes
"""

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, desc, exists
from sqlalchemy.orm import joinedload

from flask_app.forms.volunteer import CreateVolunteerForm, UpdateVolunteerForm
from flask_app.models import (
    ClearanceStatus,
    ContactEmail,
    ContactPhone,
    ContactType,
    EducationLevel,
    EmailType,
    Gender,
    PhoneType,
    PreferredLanguage,
    RaceEthnicity,
    Salutation,
    Volunteer,
    VolunteerStatus,
    db,
)


def register_volunteer_routes(app):
    """Register volunteer management routes"""

    @app.route("/volunteers")
    @login_required
    def volunteers_list():
        """List all volunteers with search and sorting"""
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 20
            search_term = request.args.get("search", "").strip()
            sort_column = request.args.get("sort", "name")
            sort_order = request.args.get("order", "asc")

            # Base query with eager loading
            query = Volunteer.query.options(
                joinedload(Volunteer.emails),
                joinedload(Volunteer.phones)
            )

            # Apply search filter if provided
            if search_term:
                # Create subqueries for email and phone search to avoid duplicates
                email_search = exists().where(
                    db.and_(
                        ContactEmail.contact_id == Volunteer.id,
                        ContactEmail.email.ilike(f"%{search_term}%")
                    )
                )
                phone_search = exists().where(
                    db.and_(
                        ContactPhone.contact_id == Volunteer.id,
                        ContactPhone.phone_number.ilike(f"%{search_term}%")
                    )
                )
                
                search_filter = or_(
                    Volunteer.first_name.ilike(f"%{search_term}%"),
                    Volunteer.last_name.ilike(f"%{search_term}%"),
                    Volunteer.preferred_name.ilike(f"%{search_term}%"),
                    email_search,
                    phone_search,
                    Volunteer.title.ilike(f"%{search_term}%"),
                    Volunteer.industry.ilike(f"%{search_term}%"),
                )
                query = query.filter(search_filter)

            # Apply sorting
            sort_mapping = {
                "name": (Volunteer.last_name, Volunteer.first_name),
                "email": ContactEmail.email,
                "phone": ContactPhone.phone_number,
                "status": Volunteer.volunteer_status,
                "hours": Volunteer.total_volunteer_hours,
                "last_date": Volunteer.last_volunteer_date,
                "created": Volunteer.created_at,
                "last_name": Volunteer.last_name,
                "first_name": Volunteer.first_name,
            }

            if sort_column in sort_mapping:
                sort_field = sort_mapping[sort_column]
                
                # Handle multi-column sort for name
                if sort_column == "name":
                    if sort_order == "desc":
                        query = query.order_by(desc(Volunteer.last_name), desc(Volunteer.first_name))
                    else:
                        query = query.order_by(Volunteer.last_name, Volunteer.first_name)
                # Handle email/phone sorting (need to join if not already joined)
                elif sort_column in ["email", "phone"]:
                    if search_term:
                        # Already joined for search, just order
                        if sort_order == "desc":
                            query = query.order_by(desc(sort_field))
                        else:
                            query = query.order_by(sort_field)
                    else:
                        # Need to join for sorting - use subquery to get primary email/phone
                        if sort_column == "email":
                            # Join and filter for primary emails only, then order
                            query = query.outerjoin(
                                ContactEmail, 
                                db.and_(
                                    ContactEmail.contact_id == Volunteer.id,
                                    ContactEmail.is_primary == True
                                )
                            ).order_by(
                                desc(sort_field) if sort_order == "desc" else sort_field
                            )
                        else:  # phone
                            query = query.outerjoin(
                                ContactPhone,
                                db.and_(
                                    ContactPhone.contact_id == Volunteer.id,
                                    ContactPhone.is_primary == True
                                )
                            ).order_by(
                                desc(sort_field) if sort_order == "desc" else sort_field
                            )
                else:
                    # Simple column sort
                    if sort_order == "desc":
                        query = query.order_by(desc(sort_field))
                    else:
                        query = query.order_by(sort_field)
            else:
                # Default sort by name
                query = query.order_by(Volunteer.last_name, Volunteer.first_name)

            # Paginate
            volunteers = query.paginate(page=page, per_page=per_page, error_out=False)

            return render_template(
                "volunteers/list.html",
                volunteers=volunteers,
                search_term=search_term,
                sort_column=sort_column,
                sort_order=sort_order,
            )

        except Exception as e:
            current_app.logger.error(f"Error in volunteers list page: {str(e)}")
            flash("An error occurred while loading volunteers.", "danger")
            return redirect(url_for("index"))

    @app.route("/volunteers/create", methods=["GET", "POST"])
    @login_required
    def volunteers_create():
        """Create new volunteer"""
        form = CreateVolunteerForm()

        try:
            if form.validate_on_submit():
                # Create Contact record first (base for Volunteer)
                # Convert enum string values to enum objects
                salutation_enum = Salutation(form.salutation.data) if form.salutation.data else None
                gender_enum = Gender(form.gender.data) if form.gender.data else None
                race_enum = RaceEthnicity(form.race.data) if form.race.data else None
                education_enum = EducationLevel(form.education_level.data) if form.education_level.data else None
                language_enum = PreferredLanguage(form.preferred_language.data) if form.preferred_language.data else None
                clearance_enum = ClearanceStatus(form.clearance_status.data) if form.clearance_status.data else None

                contact = Volunteer(
                    contact_type=ContactType.VOLUNTEER,
                    first_name=form.first_name.data.strip(),
                    last_name=form.last_name.data.strip(),
                    salutation=salutation_enum,
                    middle_name=form.middle_name.data.strip() if form.middle_name.data else None,
                    suffix=form.suffix.data.strip() if form.suffix.data else None,
                    preferred_name=form.preferred_name.data.strip() if form.preferred_name.data else None,
                    gender=gender_enum,
                    race=race_enum,
                    birthdate=form.birthdate.data if form.birthdate.data else None,
                    education_level=education_enum,
                    is_local=form.is_local.data,
                    do_not_call=form.do_not_call.data,
                    do_not_email=form.do_not_email.data,
                    do_not_contact=form.do_not_contact.data,
                    preferred_language=language_enum,
                    notes=form.notes.data.strip() if form.notes.data else None,
                    internal_notes=form.internal_notes.data.strip() if form.internal_notes.data else None,
                    # Volunteer-specific fields
                    volunteer_status=VolunteerStatus(form.volunteer_status.data),
                    title=form.title.data.strip() if form.title.data else None,
                    industry=form.industry.data.strip() if form.industry.data else None,
                    clearance_status=clearance_enum,
                )

                db.session.add(contact)
                db.session.flush()  # Get the ID without committing

                # Create primary email if provided
                if form.email.data:
                    email = ContactEmail(
                        contact_id=contact.id,
                        email=form.email.data.strip(),
                        email_type=EmailType.PERSONAL,
                        is_primary=True,
                        is_verified=False,
                    )
                    db.session.add(email)

                # Create primary phone if provided
                if form.phone_number.data:
                    phone = ContactPhone(
                        contact_id=contact.id,
                        phone_number=form.phone_number.data.strip(),
                        phone_type=PhoneType.MOBILE,
                        is_primary=True,
                        can_text=form.can_text.data,
                    )
                    db.session.add(phone)

                # Commit all changes
                db.session.commit()

                flash(f"Volunteer {contact.get_full_name()} created successfully!", "success")
                return redirect(url_for("volunteers_list"))

            return render_template("volunteers/create.html", form=form)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating volunteer: {str(e)}")
            flash(f"An error occurred while creating volunteer: {str(e)}", "danger")
            return render_template("volunteers/create.html", form=form)

    @app.route("/volunteers/<int:volunteer_id>")
    @login_required
    def volunteers_view(volunteer_id):
        """View volunteer details"""
        try:
            from sqlalchemy.orm import joinedload
            volunteer = db.session.query(Volunteer).options(
                joinedload(Volunteer.emails),
                joinedload(Volunteer.phones),
                joinedload(Volunteer.addresses),
                joinedload(Volunteer.skills),
                joinedload(Volunteer.interests),
                joinedload(Volunteer.availability_slots),
                joinedload(Volunteer.volunteer_hours),
            ).filter_by(id=volunteer_id).first()
            if not volunteer:
                from flask import abort
                abort(404)

            return render_template("volunteers/view.html", volunteer=volunteer)

        except Exception as e:
            current_app.logger.error(f"Error viewing volunteer {volunteer_id}: {str(e)}")
            flash("An error occurred while loading volunteer details.", "danger")
            return redirect(url_for("volunteers_list"))

    @app.route("/volunteers/<int:volunteer_id>/edit", methods=["GET", "POST"])
    @login_required
    def volunteers_edit(volunteer_id):
        """Edit volunteer information"""
        from sqlalchemy.orm import joinedload
        volunteer = db.session.query(Volunteer).options(
            joinedload(Volunteer.emails),
            joinedload(Volunteer.phones),
        ).filter_by(id=volunteer_id).first()
        if not volunteer:
            from flask import abort
            abort(404)

        form = UpdateVolunteerForm(obj=volunteer)

        # Pre-populate form fields only on GET requests
        if request.method == "GET":
            # Pre-populate email and phone from primary contact info
            primary_email = volunteer.get_primary_email()
            primary_phone_obj = next((p for p in volunteer.phones if p.is_primary), None)
            if primary_email:
                form.email.data = primary_email
            if primary_phone_obj:
                form.phone_number.data = primary_phone_obj.phone_number
                form.can_text.data = primary_phone_obj.can_text

            # Pre-populate enum fields
            if volunteer.salutation:
                form.salutation.data = volunteer.salutation.value if hasattr(volunteer.salutation, 'value') else str(volunteer.salutation)
            if volunteer.gender:
                form.gender.data = volunteer.gender.value if hasattr(volunteer.gender, 'value') else str(volunteer.gender)
            if volunteer.race:
                form.race.data = volunteer.race.value if hasattr(volunteer.race, 'value') else str(volunteer.race)
            if volunteer.education_level:
                form.education_level.data = volunteer.education_level.value if hasattr(volunteer.education_level, 'value') else str(volunteer.education_level)
            if volunteer.preferred_language:
                form.preferred_language.data = volunteer.preferred_language.value if hasattr(volunteer.preferred_language, 'value') else str(volunteer.preferred_language)
            if volunteer.clearance_status:
                form.clearance_status.data = volunteer.clearance_status.value if hasattr(volunteer.clearance_status, 'value') else str(volunteer.clearance_status)

        try:
            if form.validate_on_submit():
                # Convert enum string values to enum objects
                salutation_enum = Salutation(form.salutation.data) if form.salutation.data else None
                gender_enum = Gender(form.gender.data) if form.gender.data else None
                race_enum = RaceEthnicity(form.race.data) if form.race.data else None
                education_enum = EducationLevel(form.education_level.data) if form.education_level.data else None
                language_enum = PreferredLanguage(form.preferred_language.data) if form.preferred_language.data else None
                clearance_enum = ClearanceStatus(form.clearance_status.data) if form.clearance_status.data else None

                # Update base contact fields
                volunteer.first_name = form.first_name.data.strip()
                volunteer.last_name = form.last_name.data.strip()
                volunteer.salutation = salutation_enum
                volunteer.middle_name = form.middle_name.data.strip() if form.middle_name.data else None
                volunteer.suffix = form.suffix.data.strip() if form.suffix.data else None
                volunteer.preferred_name = form.preferred_name.data.strip() if form.preferred_name.data else None
                volunteer.gender = gender_enum
                volunteer.race = race_enum
                volunteer.birthdate = form.birthdate.data if form.birthdate.data else None
                volunteer.education_level = education_enum
                # Boolean fields - check request form directly to get submitted values
                # WTForms BooleanField might use default/pre-populated values instead of submitted
                if 'is_local' in request.form:
                    volunteer.is_local = request.form.get('is_local', '').lower() in ('true', '1', 'on', 'yes')
                else:
                    volunteer.is_local = form.is_local.data
                if 'do_not_call' in request.form:
                    volunteer.do_not_call = request.form.get('do_not_call', '').lower() in ('true', '1', 'on', 'yes')
                else:
                    volunteer.do_not_call = form.do_not_call.data
                if 'do_not_email' in request.form:
                    volunteer.do_not_email = request.form.get('do_not_email', '').lower() in ('true', '1', 'on', 'yes')
                else:
                    volunteer.do_not_email = form.do_not_email.data
                if 'do_not_contact' in request.form:
                    volunteer.do_not_contact = request.form.get('do_not_contact', '').lower() in ('true', '1', 'on', 'yes')
                else:
                    volunteer.do_not_contact = form.do_not_contact.data
                volunteer.preferred_language = language_enum
                volunteer.notes = form.notes.data.strip() if form.notes.data else None
                volunteer.internal_notes = form.internal_notes.data.strip() if form.internal_notes.data else None

                # Update volunteer-specific fields
                volunteer.volunteer_status = VolunteerStatus(form.volunteer_status.data)
                volunteer.title = form.title.data.strip() if form.title.data else None
                volunteer.industry = form.industry.data.strip() if form.industry.data else None
                volunteer.clearance_status = clearance_enum

                # Update primary email if changed
                email_value = form.email.data.strip() if form.email.data else ""
                
                if email_value:
                    # Validate email first
                    try:
                        from email_validator import validate_email, EmailNotValidError
                        check_deliverability = current_app.config.get(
                            "EMAIL_VALIDATION_CHECK_DELIVERABILITY", True
                        )
                        validate_email(email_value, check_deliverability=check_deliverability)
                    except (ValueError, EmailNotValidError) as e:
                        current_app.logger.error(f"Email validation error: {str(e)}")
                        flash(f"Invalid email address: {str(e)}", "danger")
                        db.session.rollback()
                        return render_template("volunteers/edit.html", form=form, volunteer=volunteer)
                    
                    # Get primary email - always query directly to ensure fresh data
                    primary_email_obj = db.session.query(ContactEmail).filter_by(
                        contact_id=volunteer.id, is_primary=True
                    ).first()
                    
                    if primary_email_obj:
                        # Update existing primary email
                        if primary_email_obj.email != email_value:
                            current_app.logger.info(f"Updating email from '{primary_email_obj.email}' to '{email_value}' for volunteer {volunteer.id}")
                            # Get the email ID and query fresh to ensure it's in the session
                            email_id = primary_email_obj.id
                            email_to_delete = db.session.query(ContactEmail).filter_by(id=email_id).first()
                            if email_to_delete:
                                current_app.logger.info(f"Deleting email {email_id} and creating new one")
                                db.session.delete(email_to_delete)
                                db.session.flush()  # Flush delete
                                
                                # Create new primary email with updated value
                                new_email = ContactEmail(
                                    contact_id=volunteer.id,
                                    email=email_value,
                                    email_type=EmailType.PERSONAL,
                                    is_primary=True,
                                    is_verified=False,
                                )
                                db.session.add(new_email)
                                db.session.flush()  # Flush create
                                current_app.logger.info(f"Created new email with value '{new_email.email}'")
                            else:
                                current_app.logger.warning(f"Email {email_id} not found for delete")
                        else:
                            current_app.logger.debug(f"Email already set to '{email_value}', skipping update")
                    else:
                        # Create new primary email
                        current_app.logger.info(f"No primary email found, creating new one with '{email_value}'")
                        email = ContactEmail(
                            contact_id=volunteer.id,
                            email=email_value,
                            email_type=EmailType.PERSONAL,
                            is_primary=True,
                            is_verified=False,
                        )
                        db.session.add(email)
                else:
                    # Remove primary email if form is empty
                    # Always query directly to ensure fresh data
                    primary_email_obj = db.session.query(ContactEmail).filter_by(
                        contact_id=volunteer.id, is_primary=True
                    ).first()
                    if primary_email_obj:
                        # Ensure the object is in the current session before deleting
                        primary_email_obj = db.session.merge(primary_email_obj)
                        db.session.delete(primary_email_obj)

                # Update primary phone if changed
                # Query primary phone directly to ensure fresh data
                primary_phone_obj = db.session.query(ContactPhone).filter_by(
                    contact_id=volunteer.id, is_primary=True
                ).first()
                
                if form.phone_number.data:
                    if primary_phone_obj:
                        if primary_phone_obj.phone_number != form.phone_number.data.strip():
                            primary_phone_obj.phone_number = form.phone_number.data.strip()
                        primary_phone_obj.can_text = form.can_text.data
                    else:
                        # Create new primary phone
                        phone = ContactPhone(
                            contact_id=volunteer.id,
                            phone_number=form.phone_number.data.strip(),
                            phone_type=PhoneType.MOBILE,
                            is_primary=True,
                            can_text=form.can_text.data,
                        )
                        db.session.add(phone)
                elif primary_phone_obj:
                    # Remove primary phone if form is empty and one existed before
                    # Ensure the object is in the current session before deleting
                    primary_phone_obj = db.session.merge(primary_phone_obj)
                    db.session.delete(primary_phone_obj)

                # Commit all changes
                db.session.commit()
                
                # Expire the volunteer's emails relationship to ensure fresh data on next access
                db.session.expire(volunteer, ['emails'])

                flash(f"Volunteer {volunteer.get_full_name()} updated successfully!", "success")
                return redirect(url_for("volunteers_view", volunteer_id=volunteer_id))

            return render_template("volunteers/edit.html", form=form, volunteer=volunteer)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating volunteer {volunteer_id}: {str(e)}")
            flash(f"An error occurred while updating volunteer: {str(e)}", "danger")
            return render_template("volunteers/edit.html", form=form, volunteer=volunteer)

