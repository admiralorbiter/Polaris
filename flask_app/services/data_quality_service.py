# flask_app/services/data_quality_service.py
"""
Data Quality Service - Calculate field completeness metrics for all entities
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import current_app
from sqlalchemy import and_, func

from flask_app.models import (
    Contact,
    ContactAddress,
    ContactEmail,
    ContactPhone,
    Event,
    Organization,
    OrganizationAddress,
    Student,
    Teacher,
    User,
    Volunteer,
    VolunteerAvailability,
    VolunteerHours,
    VolunteerInterest,
    VolunteerSkill,
    db,
)
from flask_app.services.data_quality_field_config_service import (
    DataQualityFieldConfigService,
)


@dataclass
class FieldMetric:
    """Metric for a single field"""

    field_name: str
    total_records: int
    records_with_value: int
    records_without_value: int
    completeness_percentage: float
    status: str  # "good", "warning", "critical"


@dataclass
class EntityMetrics:
    """Metrics for an entity type"""

    entity_type: str
    total_records: int
    fields: List[FieldMetric]
    overall_completeness: float
    key_metrics: Dict[str, Any]


@dataclass
class OverallMetrics:
    """Overall system health metrics"""

    overall_health_score: float
    entity_metrics: List[EntityMetrics]
    total_entities: int
    timestamp: datetime


class DataQualityService:
    """Service for calculating data quality metrics"""

    # Cache for metrics (in-memory, simple implementation)
    _cache: Dict[str, Tuple[datetime, Any]] = {}
    _cache_ttl_seconds = 300  # 5 minutes

    # Completeness thresholds
    THRESHOLD_GOOD = 80.0
    THRESHOLD_WARNING = 50.0

    @classmethod
    def _get_cache_key(cls, entity_type: Optional[str] = None, filters: Optional[Dict] = None) -> str:
        """Generate cache key"""
        key_parts = ["dq_metrics"]
        if entity_type:
            key_parts.append(entity_type)
        if filters:
            # Sort filters for consistent keys
            filter_str = "_".join(f"{k}:{v}" for k, v in sorted(filters.items()) if v)
            if filter_str:
                key_parts.append(filter_str)
        # Include field configuration in cache key to invalidate when config changes
        # Use hash of JSON serialization for stable, short cache key
        disabled_fields = DataQualityFieldConfigService.get_disabled_fields()
        # Sort for consistent serialization
        config_str = json.dumps(
            {k: sorted(v) for k, v in sorted(disabled_fields.items())}, sort_keys=True
        )
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]
        key_parts.append(f"cfg:{config_hash}")
        return "_".join(key_parts)

    @classmethod
    def _is_cache_valid(cls, cached_time: datetime) -> bool:
        """Check if cache is still valid"""
        age = datetime.now(timezone.utc) - cached_time
        return age.total_seconds() < cls._cache_ttl_seconds

    @classmethod
    def _get_cached(cls, key: str) -> Optional[Any]:
        """Get value from cache if valid"""
        if key in cls._cache:
            cached_time, value = cls._cache[key]
            if cls._is_cache_valid(cached_time):
                return value
            else:
                del cls._cache[key]
        return None

    @classmethod
    def _set_cache(cls, key: str, value: Any) -> None:
        """Set value in cache"""
        cls._cache[key] = (datetime.now(timezone.utc), value)

    @classmethod
    def _clear_cache(cls, pattern: Optional[str] = None) -> None:
        """Clear cache, optionally by pattern"""
        if pattern:
            keys_to_remove = [k for k in cls._cache.keys() if pattern in k]
            for key in keys_to_remove:
                del cls._cache[key]
        else:
            cls._cache.clear()

    @classmethod
    def get_overall_health_score(cls, organization_id: Optional[int] = None) -> OverallMetrics:
        """Calculate overall system health score (0-100%)"""
        cache_key = cls._get_cache_key(filters={"org_id": organization_id})
        cached = cls._get_cached(cache_key)
        if cached:
            return cached

        entity_types = ["contact", "volunteer", "student", "teacher", "event", "organization", "user"]
        entity_metrics_list = []

        total_entities = 0
        weighted_sum = 0.0
        total_weight = 0.0

        for entity_type in entity_types:
            try:
                metrics = cls.get_entity_metrics(entity_type, organization_id=organization_id)
                entity_metrics_list.append(metrics)
                total_entities += metrics.total_records

                # Weight by number of records (more records = more important)
                weight = metrics.total_records
                weighted_sum += metrics.overall_completeness * weight
                total_weight += weight
            except Exception as e:
                current_app.logger.error(f"Error calculating metrics for {entity_type}: {e}")

        # Calculate overall health score (only using enabled fields, already filtered in get_entity_metrics)
        overall_health_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0

        result = OverallMetrics(
            overall_health_score=round(overall_health_score, 2),
            entity_metrics=entity_metrics_list,
            total_entities=total_entities,
            timestamp=datetime.now(timezone.utc),
        )

        cls._set_cache(cache_key, result)
        return result

    @classmethod
    def _filter_disabled_fields(
        cls, fields: List[FieldMetric], entity_type: str, organization_id: Optional[int] = None
    ) -> List[FieldMetric]:
        """
        Filter out disabled fields from metrics.

        Args:
            fields: List of field metrics
            entity_type: Entity type
            organization_id: Optional organization ID

        Returns:
            Filtered list of field metrics (only enabled fields)
        """
        disabled_fields = DataQualityFieldConfigService.get_disabled_fields(organization_id)
        disabled_for_entity: Set[str] = set(disabled_fields.get(entity_type, []))

        # Filter out disabled fields
        return [field for field in fields if field.field_name not in disabled_for_entity]

    @classmethod
    def get_entity_metrics(cls, entity_type: str, organization_id: Optional[int] = None) -> EntityMetrics:
        """Get completeness metrics for a specific entity"""
        cache_key = cls._get_cache_key(entity_type, filters={"org_id": organization_id})
        cached = cls._get_cached(cache_key)
        if cached:
            return cached

        fields = []
        total_records = 0

        if entity_type == "contact":
            fields, total_records = cls._get_contact_metrics(organization_id)
        elif entity_type == "volunteer":
            fields, total_records = cls._get_volunteer_metrics(organization_id)
        elif entity_type == "student":
            fields, total_records = cls._get_student_metrics(organization_id)
        elif entity_type == "teacher":
            fields, total_records = cls._get_teacher_metrics(organization_id)
        elif entity_type == "event":
            fields, total_records = cls._get_event_metrics(organization_id)
        elif entity_type == "organization":
            fields, total_records = cls._get_organization_metrics(organization_id)
        elif entity_type == "user":
            fields, total_records = cls._get_user_metrics(organization_id)
        else:
            raise ValueError(f"Unknown entity type: {entity_type}")

        # Filter out disabled fields
        fields = cls._filter_disabled_fields(fields, entity_type, organization_id)

        # Calculate overall completeness (only using enabled fields)
        if fields:
            overall_completeness = sum(f.completeness_percentage for f in fields) / len(fields)
        else:
            overall_completeness = 0.0

        # Extract key metrics
        key_metrics = {}
        for field in fields:
            if field.field_name in ["email", "phone", "address"]:
                key_metrics[field.field_name] = {
                    "percentage": field.completeness_percentage,
                    "count": field.records_with_value,
                }

        result = EntityMetrics(
            entity_type=entity_type,
            total_records=total_records,
            fields=fields,
            overall_completeness=round(overall_completeness, 2),
            key_metrics=key_metrics,
        )

        cls._set_cache(cache_key, result)
        return result

    @classmethod
    def _get_contact_ids_for_organization(cls, organization_id: int) -> List[int]:
        """Get all contact IDs for an organization (via organization_id or ContactOrganization)"""
        from flask_app.models.contact.relationships import ContactOrganization

        # Get contact IDs linked via ContactOrganization (current relationships only)
        org_links = ContactOrganization.query.filter_by(organization_id=organization_id, end_date=None).all()
        org_contact_ids_via_link = [link.contact_id for link in org_links]

        # Get contacts that have organization_id directly
        contact_ids_with_org = db.session.query(Contact.id).filter(Contact.organization_id == organization_id).all()
        contact_ids_direct = [c.id for c in contact_ids_with_org]

        # Combine both sets (remove duplicates)
        all_contact_ids = list(set(org_contact_ids_via_link + contact_ids_direct))
        return all_contact_ids

    @classmethod
    def _get_contact_metrics(cls, organization_id: Optional[int] = None) -> Tuple[List[FieldMetric], int]:
        """Get metrics for Contact entity"""
        # Get contact IDs if filtering by organization
        contact_ids = None
        if organization_id:
            contact_ids = cls._get_contact_ids_for_organization(organization_id)
            if not contact_ids:
                # No contacts for this organization
                return [], 0
            query = Contact.query.filter(Contact.id.in_(contact_ids))
        else:
            query = Contact.query

        total_records = query.count()
        if total_records == 0:
            return [], 0

        fields = []

        # Direct fields
        direct_fields = [
            ("first_name", Contact.first_name),
            ("last_name", Contact.last_name),
            ("middle_name", Contact.middle_name),
            ("preferred_name", Contact.preferred_name),
            ("birthdate", Contact.birthdate),
            ("gender", Contact.gender),
            ("race", Contact.race),
            ("education_level", Contact.education_level),
            ("preferred_language", Contact.preferred_language),
            ("photo_url", Contact.photo_url),
            ("notes", Contact.notes),
        ]

        for field_name, field_column in direct_fields:
            if field_name in ["first_name", "last_name"]:
                # For required fields, check for non-null and non-empty
                with_value = query.filter(and_(field_column.isnot(None), field_column != "")).count()
            else:
                # For optional fields, check for non-null
                with_value = query.filter(field_column.isnot(None)).count()

            without_value = total_records - with_value
            completeness = (with_value / total_records * 100) if total_records > 0 else 0.0
            status = cls._get_status(completeness)

            fields.append(
                FieldMetric(
                    field_name=field_name,
                    total_records=total_records,
                    records_with_value=with_value,
                    records_without_value=without_value,
                    completeness_percentage=round(completeness, 2),
                    status=status,
                )
            )

        # Relationship fields - Email
        email_query = db.session.query(func.count(func.distinct(ContactEmail.contact_id))).join(
            Contact, ContactEmail.contact_id == Contact.id
        )
        if contact_ids:
            email_query = email_query.filter(Contact.id.in_(contact_ids))
        contacts_with_email = email_query.scalar() or 0

        email_completeness = (contacts_with_email / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="email",
                total_records=total_records,
                records_with_value=contacts_with_email,
                records_without_value=total_records - contacts_with_email,
                completeness_percentage=round(email_completeness, 2),
                status=cls._get_status(email_completeness),
            )
        )

        # Relationship fields - Phone
        phone_query = db.session.query(func.count(func.distinct(ContactPhone.contact_id))).join(
            Contact, ContactPhone.contact_id == Contact.id
        )
        if contact_ids:
            phone_query = phone_query.filter(Contact.id.in_(contact_ids))
        contacts_with_phone = phone_query.scalar() or 0

        phone_completeness = (contacts_with_phone / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="phone",
                total_records=total_records,
                records_with_value=contacts_with_phone,
                records_without_value=total_records - contacts_with_phone,
                completeness_percentage=round(phone_completeness, 2),
                status=cls._get_status(phone_completeness),
            )
        )

        # Relationship fields - Address
        address_query = db.session.query(func.count(func.distinct(ContactAddress.contact_id))).join(
            Contact, ContactAddress.contact_id == Contact.id
        )
        if contact_ids:
            address_query = address_query.filter(Contact.id.in_(contact_ids))
        contacts_with_address = address_query.scalar() or 0

        address_completeness = (contacts_with_address / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="address",
                total_records=total_records,
                records_with_value=contacts_with_address,
                records_without_value=total_records - contacts_with_address,
                completeness_percentage=round(address_completeness, 2),
                status=cls._get_status(address_completeness),
            )
        )

        return fields, total_records

    @classmethod
    def _get_volunteer_metrics(cls, organization_id: Optional[int] = None) -> Tuple[List[FieldMetric], int]:
        """Get metrics for Volunteer entity"""
        if organization_id:
            # Volunteers are linked to organizations via ContactOrganization
            from flask_app.models.contact.relationships import ContactOrganization

            org_contact_ids = (
                db.session.query(ContactOrganization.contact_id)
                .filter(
                    ContactOrganization.organization_id == organization_id,
                    ContactOrganization.end_date.is_(None),
                )
                .subquery()
            )
            query = Volunteer.query.filter(Volunteer.id.in_(db.session.query(org_contact_ids)))
        else:
            query = Volunteer.query

        total_records = query.count()
        if total_records == 0:
            return [], 0

        fields = []

        # Direct fields from Volunteer table
        direct_fields = [
            ("title", Volunteer.title),
            ("industry", Volunteer.industry),
            ("clearance_status", Volunteer.clearance_status),
            ("first_volunteer_date", Volunteer.first_volunteer_date),
            ("last_volunteer_date", Volunteer.last_volunteer_date),
            ("total_volunteer_hours", Volunteer.total_volunteer_hours),
        ]

        for field_name, field_column in direct_fields:
            with_value = query.filter(and_(field_column.isnot(None), field_column != "", field_column != 0)).count()
            without_value = total_records - with_value
            completeness = (with_value / total_records * 100) if total_records > 0 else 0.0
            status = cls._get_status(completeness)

            fields.append(
                FieldMetric(
                    field_name=field_name,
                    total_records=total_records,
                    records_with_value=with_value,
                    records_without_value=without_value,
                    completeness_percentage=round(completeness, 2),
                    status=status,
                )
            )

        # Relationship fields - Skills
        # Use the same query base to ensure consistency with total_records
        volunteer_ids_subquery = query.with_entities(Volunteer.id).subquery()
        volunteers_with_skills = (
            db.session.query(func.count(func.distinct(VolunteerSkill.volunteer_id)))
            .join(volunteer_ids_subquery, VolunteerSkill.volunteer_id == volunteer_ids_subquery.c.id)
            .scalar()
            or 0
        )

        skills_completeness = (volunteers_with_skills / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="skills",
                total_records=total_records,
                records_with_value=volunteers_with_skills,
                records_without_value=total_records - volunteers_with_skills,
                completeness_percentage=round(skills_completeness, 2),
                status=cls._get_status(skills_completeness),
            )
        )

        # Relationship fields - Interests
        # Use the same query base to ensure consistency with total_records
        volunteer_ids_subquery = query.with_entities(Volunteer.id).subquery()
        volunteers_with_interests = (
            db.session.query(func.count(func.distinct(VolunteerInterest.volunteer_id)))
            .join(volunteer_ids_subquery, VolunteerInterest.volunteer_id == volunteer_ids_subquery.c.id)
            .scalar()
            or 0
        )

        interests_completeness = (volunteers_with_interests / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="interests",
                total_records=total_records,
                records_with_value=volunteers_with_interests,
                records_without_value=total_records - volunteers_with_interests,
                completeness_percentage=round(interests_completeness, 2),
                status=cls._get_status(interests_completeness),
            )
        )

        # Relationship fields - Availability
        # Use the same query base to ensure consistency with total_records
        volunteer_ids_subquery = query.with_entities(Volunteer.id).subquery()
        volunteers_with_availability = (
            db.session.query(func.count(func.distinct(VolunteerAvailability.volunteer_id)))
            .join(volunteer_ids_subquery, VolunteerAvailability.volunteer_id == volunteer_ids_subquery.c.id)
            .filter(VolunteerAvailability.is_active.is_(True))
            .scalar()
            or 0
        )

        availability_completeness = (volunteers_with_availability / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="availability",
                total_records=total_records,
                records_with_value=volunteers_with_availability,
                records_without_value=total_records - volunteers_with_availability,
                completeness_percentage=round(availability_completeness, 2),
                status=cls._get_status(availability_completeness),
            )
        )

        # Relationship fields - Hours
        # Use the same query base to ensure consistency with total_records
        volunteer_ids_subquery = query.with_entities(Volunteer.id).subquery()
        volunteers_with_hours = (
            db.session.query(func.count(func.distinct(VolunteerHours.volunteer_id)))
            .join(volunteer_ids_subquery, VolunteerHours.volunteer_id == volunteer_ids_subquery.c.id)
            .scalar()
            or 0
        )

        hours_completeness = (volunteers_with_hours / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="hours_logged",
                total_records=total_records,
                records_with_value=volunteers_with_hours,
                records_without_value=total_records - volunteers_with_hours,
                completeness_percentage=round(hours_completeness, 2),
                status=cls._get_status(hours_completeness),
            )
        )

        return fields, total_records

    @classmethod
    def _get_student_metrics(cls, organization_id: Optional[int] = None) -> Tuple[List[FieldMetric], int]:
        """Get metrics for Student entity"""
        query = Student.query
        if organization_id:
            query = query.filter(Student.organization_id == organization_id)

        total_records = query.count()
        if total_records == 0:
            return [], 0

        fields = []

        # Student-specific fields
        direct_fields = [
            ("grade", Student.grade),
            ("enrollment_date", Student.enrollment_date),
            ("student_id", Student.student_id),
            ("graduation_date", Student.graduation_date),
        ]

        for field_name, field_column in direct_fields:
            with_value = query.filter(field_column.isnot(None)).count()
            without_value = total_records - with_value
            completeness = (with_value / total_records * 100) if total_records > 0 else 0.0
            status = cls._get_status(completeness)

            fields.append(
                FieldMetric(
                    field_name=field_name,
                    total_records=total_records,
                    records_with_value=with_value,
                    records_without_value=without_value,
                    completeness_percentage=round(completeness, 2),
                    status=status,
                )
            )

        return fields, total_records

    @classmethod
    def _get_teacher_metrics(cls, organization_id: Optional[int] = None) -> Tuple[List[FieldMetric], int]:
        """Get metrics for Teacher entity"""
        query = Teacher.query
        if organization_id:
            query = query.filter(Teacher.organization_id == organization_id)

        total_records = query.count()
        if total_records == 0:
            return [], 0

        fields = []

        # Teacher-specific fields
        direct_fields = [
            ("certification", Teacher.certification),
            ("subject_areas", Teacher.subject_areas),
            ("hire_date", Teacher.hire_date),
            ("employee_id", Teacher.employee_id),
        ]

        for field_name, field_column in direct_fields:
            with_value = query.filter(field_column.isnot(None)).count()
            without_value = total_records - with_value
            completeness = (with_value / total_records * 100) if total_records > 0 else 0.0
            status = cls._get_status(completeness)

            fields.append(
                FieldMetric(
                    field_name=field_name,
                    total_records=total_records,
                    records_with_value=with_value,
                    records_without_value=without_value,
                    completeness_percentage=round(completeness, 2),
                    status=status,
                )
            )

        return fields, total_records

    @classmethod
    def _get_event_metrics(cls, organization_id: Optional[int] = None) -> Tuple[List[FieldMetric], int]:
        """Get metrics for Event entity"""
        query = Event.query
        if organization_id:
            from flask_app.models.event.models import EventOrganization

            event_ids = (
                db.session.query(EventOrganization.event_id)
                .filter(EventOrganization.organization_id == organization_id)
                .subquery()
            )
            query = query.filter(Event.id.in_(db.session.query(event_ids)))

        total_records = query.count()
        if total_records == 0:
            return [], 0

        fields = []

        # Event fields
        direct_fields = [
            ("title", Event.title),
            ("description", Event.description),
            ("location_name", Event.location_name),
            ("location_address", Event.location_address),
            ("virtual_link", Event.virtual_link),
            ("start_date", Event.start_date),
            ("end_date", Event.end_date),
            ("duration", Event.duration),
            ("capacity", Event.capacity),
            ("registration_deadline", Event.registration_deadline),
            ("cost", Event.cost),
        ]

        for field_name, field_column in direct_fields:
            with_value = query.filter(field_column.isnot(None)).count()
            without_value = total_records - with_value
            completeness = (with_value / total_records * 100) if total_records > 0 else 0.0
            status = cls._get_status(completeness)

            fields.append(
                FieldMetric(
                    field_name=field_name,
                    total_records=total_records,
                    records_with_value=with_value,
                    records_without_value=without_value,
                    completeness_percentage=round(completeness, 2),
                    status=status,
                )
            )

        return fields, total_records

    @classmethod
    def _get_organization_metrics(cls, organization_id: Optional[int] = None) -> Tuple[List[FieldMetric], int]:
        """Get metrics for Organization entity"""
        query = Organization.query
        if organization_id:
            query = query.filter(Organization.id == organization_id)

        total_records = query.count()
        if total_records == 0:
            return [], 0

        fields = []

        # Organization fields
        direct_fields = [
            ("name", Organization.name),
            ("description", Organization.description),
            ("website", Organization.website),
            ("phone", Organization.phone),
            ("email", Organization.email),
            ("tax_id", Organization.tax_id),
            ("logo_url", Organization.logo_url),
            ("contact_person_name", Organization.contact_person_name),
            ("contact_person_title", Organization.contact_person_title),
            ("founded_date", Organization.founded_date),
        ]

        for field_name, field_column in direct_fields:
            with_value = query.filter(field_column.isnot(None)).count()
            without_value = total_records - with_value
            completeness = (with_value / total_records * 100) if total_records > 0 else 0.0
            status = cls._get_status(completeness)

            fields.append(
                FieldMetric(
                    field_name=field_name,
                    total_records=total_records,
                    records_with_value=with_value,
                    records_without_value=without_value,
                    completeness_percentage=round(completeness, 2),
                    status=status,
                )
            )

        # Relationship fields - Address
        address_query = db.session.query(func.count(func.distinct(OrganizationAddress.organization_id))).join(
            Organization, OrganizationAddress.organization_id == Organization.id
        )
        if organization_id:
            address_query = address_query.filter(Organization.id == organization_id)
        orgs_with_address = address_query.scalar() or 0

        address_completeness = (orgs_with_address / total_records * 100) if total_records > 0 else 0.0
        fields.append(
            FieldMetric(
                field_name="address",
                total_records=total_records,
                records_with_value=orgs_with_address,
                records_without_value=total_records - orgs_with_address,
                completeness_percentage=round(address_completeness, 2),
                status=cls._get_status(address_completeness),
            )
        )

        return fields, total_records

    @classmethod
    def _get_user_metrics(cls, organization_id: Optional[int] = None) -> Tuple[List[FieldMetric], int]:
        """Get metrics for User entity"""
        query = User.query
        if organization_id:
            from flask_app.models import UserOrganization

            user_ids = (
                db.session.query(UserOrganization.user_id)
                .filter(
                    UserOrganization.organization_id == organization_id,
                    UserOrganization.is_active.is_(True),
                )
                .subquery()
            )
            query = query.filter(User.id.in_(db.session.query(user_ids)))

        total_records = query.count()
        if total_records == 0:
            return [], 0

        fields = []

        # User fields
        direct_fields = [
            ("username", User.username),
            ("email", User.email),
            ("first_name", User.first_name),
            ("last_name", User.last_name),
        ]

        for field_name, field_column in direct_fields:
            with_value = query.filter(and_(field_column.isnot(None), field_column != "")).count()
            without_value = total_records - with_value
            completeness = (with_value / total_records * 100) if total_records > 0 else 0.0
            status = cls._get_status(completeness)

            fields.append(
                FieldMetric(
                    field_name=field_name,
                    total_records=total_records,
                    records_with_value=with_value,
                    records_without_value=without_value,
                    completeness_percentage=round(completeness, 2),
                    status=status,
                )
            )

        return fields, total_records

    @classmethod
    def _get_status(cls, completeness: float) -> str:
        """Get status based on completeness percentage"""
        if completeness >= cls.THRESHOLD_GOOD:
            return "good"
        elif completeness >= cls.THRESHOLD_WARNING:
            return "warning"
        else:
            return "critical"
