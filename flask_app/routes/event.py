# flask_app/routes/event.py
"""
Event management routes
"""

from datetime import timedelta

# Import Decimal for cost handling
from decimal import Decimal

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc, or_
from sqlalchemy.orm import joinedload

from flask_app.forms.event import CreateEventForm, UpdateEventForm
from flask_app.models import (
    CancellationReason,
    Event,
    EventFormat,
    EventOrganization,
    EventStatus,
    EventType,
    EventVolunteer,
    Organization,
    db,
)


def register_event_routes(app):
    """Register event management routes"""

    @app.route("/events")
    @login_required
    def events_list():
        """List all events with search and sorting"""
        try:
            page = request.args.get("page", 1, type=int)
            per_page = 20
            search_term = request.args.get("search", "").strip()
            sort_column = request.args.get("sort", "start_date")
            sort_order = request.args.get("order", "desc")

            # Base query with eager loading
            query = Event.query.options(joinedload(Event.organizations).joinedload(EventOrganization.organization))

            # Apply search filter if provided
            if search_term:
                search_filter = or_(
                    Event.title.ilike(f"%{search_term}%"),
                    Event.description.ilike(f"%{search_term}%"),
                    Event.location_name.ilike(f"%{search_term}%"),
                    Event.location_address.ilike(f"%{search_term}%"),
                )
                query = query.filter(search_filter)

            # Apply sorting
            sort_mapping = {
                "title": Event.title,
                "start_date": Event.start_date,
                "status": Event.event_status,
                "type": Event.event_type,
                "format": Event.event_format,
                "created": Event.created_at,
            }

            if sort_column in sort_mapping:
                sort_field = sort_mapping[sort_column]
                if sort_order == "desc":
                    query = query.order_by(desc(sort_field))
                else:
                    query = query.order_by(sort_field)
            else:
                # Default sort by start_date descending (upcoming first)
                query = query.order_by(desc(Event.start_date))

            # Paginate
            events = query.paginate(page=page, per_page=per_page, error_out=False)

            return render_template(
                "events/list.html",
                events=events,
                search_term=search_term,
                sort_column=sort_column,
                sort_order=sort_order,
            )

        except Exception as e:
            current_app.logger.error(f"Error in events list page: {str(e)}")
            flash("An error occurred while loading events.", "danger")
            return redirect(url_for("index"))

    @app.route("/events/create", methods=["GET", "POST"])
    @login_required
    def events_create():
        """Create new event"""
        form = CreateEventForm()

        try:
            if form.validate_on_submit():
                # Convert enum string values to enum objects
                event_type_enum = EventType(form.event_type.data)
                event_status_enum = EventStatus(form.event_status.data)
                event_format_enum = EventFormat(form.event_format.data)
                cancellation_reason_enum = (
                    CancellationReason(form.cancellation_reason.data) if form.cancellation_reason.data else None
                )

                # Parse cost
                cost_value = None
                if form.cost.data:
                    try:
                        cost_value = Decimal(form.cost.data.strip())
                    except (ValueError, TypeError):
                        flash("Invalid cost value.", "danger")
                        return render_template("events/create.html", form=form)

                # Create new event
                new_event, error = Event.safe_create(
                    title=form.title.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    event_type=event_type_enum,
                    event_status=event_status_enum,
                    event_format=event_format_enum,
                    cancellation_reason=cancellation_reason_enum,
                    start_date=form.start_date.data,
                    start_time=form.start_time.data if form.start_time.data else None,
                    duration=form.duration.data if form.duration.data else None,
                    location_name=form.location_name.data.strip() if form.location_name.data else None,
                    location_address=form.location_address.data.strip() if form.location_address.data else None,
                    virtual_link=form.virtual_link.data.strip() if form.virtual_link.data else None,
                    capacity=form.capacity.data if form.capacity.data else None,
                    registration_deadline=form.registration_deadline.data if form.registration_deadline.data else None,
                    cost=cost_value,
                    created_by_user_id=current_user.id,
                )

                if error:
                    flash(f"Error creating event: {error}", "danger")
                else:
                    # Calculate end_date if duration is provided
                    if new_event.duration and new_event.start_date:
                        new_event.end_date = new_event.start_date + timedelta(minutes=new_event.duration)
                        db.session.commit()

                    # Link to organization
                    organization = Organization.query.get(form.organization_id.data)
                    if organization:
                        event_org = EventOrganization(
                            event_id=new_event.id,
                            organization_id=organization.id,
                            is_primary=True,
                        )
                        db.session.add(event_org)
                        db.session.commit()

                    flash(f"Event {new_event.title} created successfully!", "success")
                    return redirect(url_for("events_list"))

            return render_template("events/create.html", form=form)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating event: {str(e)}")
            flash(f"An error occurred while creating event: {str(e)}", "danger")
            return render_template("events/create.html", form=form)

    @app.route("/events/<int:event_id>")
    @login_required
    def events_view(event_id):
        """View event details"""
        try:
            event = (
                db.session.query(Event)
                .options(
                    joinedload(Event.organizations).joinedload(EventOrganization.organization),
                    joinedload(Event.volunteers).joinedload(EventVolunteer.contact),
                )
                .filter_by(id=event_id)
                .first()
            )

            if not event:
                from flask import abort

                abort(404)

            # Get statistics
            attendance_count = event.get_attendance_count()
            primary_org = event.get_primary_organization()
            capacity_usage = None
            if event.capacity:
                capacity_usage = {
                    "current": attendance_count,
                    "max": event.capacity,
                    "percentage": round((attendance_count / event.capacity) * 100, 1) if event.capacity > 0 else 0,
                }

            stats = {
                "attendance_count": attendance_count,
                "capacity_usage": capacity_usage,
            }

            return render_template(
                "events/view.html",
                event=event,
                stats=stats,
                primary_org=primary_org,
            )

        except Exception as e:
            current_app.logger.error(f"Error viewing event {event_id}: {str(e)}", exc_info=True)
            flash(f"An error occurred while loading event details: {str(e)}", "danger")
            return redirect(url_for("events_list"))

    @app.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
    @login_required
    def events_edit(event_id):
        """Edit event information"""
        event = (
            db.session.query(Event)
            .options(joinedload(Event.organizations).joinedload(EventOrganization.organization))
            .filter_by(id=event_id)
            .first()
        )

        if not event:
            from flask import abort

            abort(404)

        form = UpdateEventForm(event=event)

        # Pre-populate form fields only on GET requests
        if request.method == "GET":
            form.title.data = event.title
            form.slug.data = event.slug
            form.description.data = event.description
            form.event_type.data = event.event_type.value if event.event_type else EventType.OTHER.value
            form.event_status.data = event.event_status.value if event.event_status else EventStatus.DRAFT.value
            form.event_format.data = event.event_format.value if event.event_format else EventFormat.IN_PERSON.value
            form.cancellation_reason.data = event.cancellation_reason.value if event.cancellation_reason else ""
            form.start_date.data = event.start_date
            form.start_time.data = event.start_time
            form.duration.data = event.duration
            form.registration_deadline.data = event.registration_deadline
            form.location_name.data = event.location_name
            form.location_address.data = event.location_address
            form.virtual_link.data = event.virtual_link
            form.capacity.data = event.capacity
            form.cost.data = str(event.cost) if event.cost else None

            # Pre-populate organization from primary organization
            primary_org = event.get_primary_organization()
            if primary_org:
                form.organization_id.data = primary_org.id

        try:
            if form.validate_on_submit():
                # Convert enum string values to enum objects
                event_type_enum = EventType(form.event_type.data)
                event_status_enum = EventStatus(form.event_status.data)
                event_format_enum = EventFormat(form.event_format.data)
                cancellation_reason_enum = (
                    CancellationReason(form.cancellation_reason.data) if form.cancellation_reason.data else None
                )

                # Parse cost
                cost_value = None
                if form.cost.data:
                    try:
                        cost_value = Decimal(form.cost.data.strip())
                    except (ValueError, TypeError):
                        flash("Invalid cost value.", "danger")
                        return render_template("events/edit.html", form=form, event=event)

                # Update event
                success, error = event.safe_update(
                    title=form.title.data.strip(),
                    slug=form.slug.data.strip().lower(),
                    description=form.description.data.strip() if form.description.data else None,
                    event_type=event_type_enum,
                    event_status=event_status_enum,
                    event_format=event_format_enum,
                    cancellation_reason=cancellation_reason_enum,
                    start_date=form.start_date.data,
                    start_time=form.start_time.data if form.start_time.data else None,
                    duration=form.duration.data if form.duration.data else None,
                    location_name=form.location_name.data.strip() if form.location_name.data else None,
                    location_address=form.location_address.data.strip() if form.location_address.data else None,
                    virtual_link=form.virtual_link.data.strip() if form.virtual_link.data else None,
                    capacity=form.capacity.data if form.capacity.data else None,
                    registration_deadline=form.registration_deadline.data if form.registration_deadline.data else None,
                    cost=cost_value,
                )

                if error:
                    flash(f"Error updating event: {error}", "danger")
                else:
                    # Calculate end_date if duration is provided
                    if event.duration and event.start_date:
                        event.end_date = event.start_date + timedelta(minutes=event.duration)
                    else:
                        event.end_date = None
                    db.session.commit()

                    # Update organization link if changed
                    primary_org = event.get_primary_organization()
                    new_org_id = form.organization_id.data

                    if not primary_org or primary_org.id != new_org_id:
                        # Remove old primary link
                        if primary_org:
                            old_link = EventOrganization.query.filter_by(
                                event_id=event.id, organization_id=primary_org.id
                            ).first()
                            if old_link:
                                db.session.delete(old_link)

                        # Create or update new primary link
                        new_org = Organization.query.get(new_org_id)
                        if new_org:
                            existing_link = EventOrganization.query.filter_by(
                                event_id=event.id, organization_id=new_org_id
                            ).first()
                            if existing_link:
                                existing_link.is_primary = True
                            else:
                                event_org = EventOrganization(
                                    event_id=event.id,
                                    organization_id=new_org_id,
                                    is_primary=True,
                                )
                                db.session.add(event_org)
                            db.session.commit()

                    flash(f"Event {event.title} updated successfully!", "success")
                    return redirect(url_for("events_view", event_id=event_id))

            return render_template("events/edit.html", form=form, event=event)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating event {event_id}: {str(e)}")
            flash(f"An error occurred while updating event: {str(e)}", "danger")
            return render_template("events/edit.html", form=form, event=event)
