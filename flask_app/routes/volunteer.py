# flask_app/routes/volunteer.py
"""
Volunteer management routes
"""

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from flask_app.forms.volunteer import CreateVolunteerForm
from flask_app.models import (
    ContactEmail,
    ContactPhone,
    ContactType,
    EmailType,
    PhoneType,
    Volunteer,
    VolunteerStatus,
    db,
)


def register_volunteer_routes(app):
    """Register volunteer management routes"""

    @app.route("/volunteers")
    @login_required
    def volunteers_list():
        """List all volunteers"""
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 20

            # Query all volunteers, ordered by name
            volunteers = (
                Volunteer.query.order_by(Volunteer.last_name, Volunteer.first_name)
                .paginate(page=page, per_page=per_page, error_out=False)
            )

            return render_template("volunteers/list.html", volunteers=volunteers)

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
                contact = Volunteer(
                    contact_type=ContactType.VOLUNTEER,
                    first_name=form.first_name.data.strip(),
                    last_name=form.last_name.data.strip(),
                    salutation=form.salutation.data.strip() if form.salutation.data else None,
                    middle_name=form.middle_name.data.strip() if form.middle_name.data else None,
                    suffix=form.suffix.data.strip() if form.suffix.data else None,
                    preferred_name=form.preferred_name.data.strip() if form.preferred_name.data else None,
                    gender=form.gender.data.strip() if form.gender.data else None,
                    race=form.race.data.strip() if form.race.data else None,
                    birthdate=form.birthdate.data if form.birthdate.data else None,
                    education_level=form.education_level.data.strip() if form.education_level.data else None,
                    is_local=form.is_local.data,
                    do_not_call=form.do_not_call.data,
                    do_not_email=form.do_not_email.data,
                    do_not_contact=form.do_not_contact.data,
                    preferred_language=form.preferred_language.data.strip() if form.preferred_language.data else None,
                    notes=form.notes.data.strip() if form.notes.data else None,
                    internal_notes=form.internal_notes.data.strip() if form.internal_notes.data else None,
                    # Volunteer-specific fields
                    volunteer_status=VolunteerStatus(form.volunteer_status.data),
                    title=form.title.data.strip() if form.title.data else None,
                    industry=form.industry.data.strip() if form.industry.data else None,
                    clearance_status=form.clearance_status.data.strip() if form.clearance_status.data else None,
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

