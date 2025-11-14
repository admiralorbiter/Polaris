# flask_app/services/data_sampling_service.py
"""
Data Sampling Service - Intelligent sampling and statistical analysis for data exploration
"""

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Query

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
    VolunteerInterest,
    VolunteerSkill,
    db,
)
from flask_app.services.data_quality_service import DataQualityService


@dataclass
class FieldStatistics:
    """Statistical summary for a single field"""

    field_name: str
    total_count: int
    non_null_count: int
    null_count: int
    unique_values: int
    most_common_values: List[Dict[str, Any]] = field(default_factory=list)
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    avg_value: Optional[float] = None
    value_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class RecordSample:
    """A single sampled record with metadata"""

    id: int
    data: Dict[str, Any]
    completeness_score: float
    completeness_level: str  # "high", "medium", "low"
    is_edge_case: bool
    edge_case_reasons: List[str] = field(default_factory=list)


@dataclass
class SamplingResult:
    """Result of sampling operation"""

    entity_type: str
    total_records: int
    sample_size: int
    samples: List[RecordSample]
    statistics: Dict[str, FieldStatistics]
    edge_cases: List[RecordSample]
    timestamp: datetime


class DataSamplingService:
    """Service for intelligent data sampling and statistical analysis"""

    # Cache for sampling results (in-memory, simple implementation)
    _cache: Dict[str, Tuple[datetime, Any]] = {}
    _cache_ttl_seconds = 300  # 5 minutes

    # Completeness thresholds (same as DataQualityService)
    THRESHOLD_GOOD = 80.0
    THRESHOLD_WARNING = 50.0

    # Sampling configuration
    MIN_SAMPLE_SIZE = 10
    MAX_SAMPLE_SIZE = 50
    DEFAULT_SAMPLE_SIZE = 20

    # Stratification ratios
    HIGH_COMPLETENESS_RATIO = 0.3
    MEDIUM_COMPLETENESS_RATIO = 0.4
    LOW_COMPLETENESS_RATIO = 0.3

    @classmethod
    def _get_cache_key(cls, entity_type: str, sample_size: int, organization_id: Optional[int] = None) -> str:
        """Generate cache key"""
        key_parts = ["dq_samples", entity_type, str(sample_size)]
        if organization_id:
            key_parts.append(f"org_{organization_id}")
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
    def _calculate_sample_size(cls, total_records: int, requested_size: Optional[int] = None) -> int:
        """Calculate appropriate sample size based on data volume"""
        if requested_size:
            return max(cls.MIN_SAMPLE_SIZE, min(requested_size, cls.MAX_SAMPLE_SIZE))

        # Dynamic sizing: log scale
        if total_records == 0:
            return 0
        elif total_records < 100:
            return min(total_records, cls.MIN_SAMPLE_SIZE)
        elif total_records < 1000:
            # Log scale: log10(records) * 10
            size = int(math.log10(total_records) * 10)
            return max(cls.MIN_SAMPLE_SIZE, min(size, cls.MAX_SAMPLE_SIZE))
        else:
            return cls.MAX_SAMPLE_SIZE

    @classmethod
    def _calculate_record_completeness(
        cls, entity_type: str, record: Any, field_definitions: List[Tuple[str, Any]]
    ) -> float:
        """Calculate completeness score for a single record"""
        if not field_definitions:
            return 0.0

        populated_fields = 0
        for field_name, field_column in field_definitions:
            if hasattr(record, field_name):
                value = getattr(record, field_name)
                if value is not None and value != "":
                    populated_fields += 1

        # Check relationship fields
        if entity_type == "contact":
            if record.emails:
                populated_fields += 1
            if record.phones:
                populated_fields += 1
            if record.addresses:
                populated_fields += 1
        elif entity_type == "volunteer":
            if record.skills:
                populated_fields += 1
            if record.interests:
                populated_fields += 1
            if record.availability:
                populated_fields += 1
            if record.hours:
                populated_fields += 1
        elif entity_type == "organization":
            if record.addresses:
                populated_fields += 1

        total_fields = len(field_definitions) + (
            3
            if entity_type == "contact"
            else (4 if entity_type == "volunteer" else (1 if entity_type == "organization" else 0))
        )
        return (populated_fields / total_fields * 100) if total_fields > 0 else 0.0

    @classmethod
    def _get_completeness_level(cls, score: float) -> str:
        """Get completeness level string"""
        if score >= cls.THRESHOLD_GOOD:
            return "high"
        elif score >= cls.THRESHOLD_WARNING:
            return "medium"
        else:
            return "low"

    @classmethod
    def _is_edge_case(cls, entity_type: str, record: Any, completeness_score: float) -> Tuple[bool, List[str]]:
        """Detect if record is an edge case"""
        reasons = []

        if entity_type == "contact":
            # Missing both email and phone
            if not record.emails and not record.phones:
                reasons.append("Missing both email and phone")
            # Missing name
            if not record.first_name or not record.last_name:
                reasons.append("Missing required name fields")
            # Very old birthdate
            if record.birthdate and record.birthdate.year < 1900:
                reasons.append("Unusually old birthdate")
            # Future birthdate
            if record.birthdate and record.birthdate > date.today():
                reasons.append("Future birthdate")

        elif entity_type == "volunteer":
            # Missing critical contact info
            if not record.emails and not record.phones:
                reasons.append("Missing both email and phone")
            # High hours but no recent activity
            if record.total_volunteer_hours and record.total_volunteer_hours > 1000:
                if not record.last_volunteer_date or (
                    record.last_volunteer_date and (date.today() - record.last_volunteer_date).days > 365
                ):
                    reasons.append("High hours but inactive for over a year")

        elif entity_type == "event":
            # Missing location info
            if not record.location_name and not record.location_address and not record.virtual_link:
                reasons.append("Missing all location information")
            # End before start
            if record.end_date and record.start_date and record.end_date < record.start_date:
                reasons.append("End date before start date")
            # Very old events
            if record.start_date and (datetime.now() - record.start_date.replace(tzinfo=None)).days > 3650:
                reasons.append("Event over 10 years old")

        # Low completeness but has many optional fields
        if completeness_score < cls.THRESHOLD_WARNING:
            # Check if record has unusual pattern (many nulls but some populated)
            reasons.append("Low completeness score")

        return len(reasons) > 0, reasons

    @classmethod
    def _serialize_record(cls, entity_type: str, record: Any) -> Dict[str, Any]:
        """Serialize a record to dictionary"""
        data = {}

        if entity_type == "contact":
            data = {
                "id": record.id,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "middle_name": record.middle_name,
                "preferred_name": record.preferred_name,
                "email": record.emails[0].email if record.emails else None,
                "phone": record.phones[0].phone_number if record.phones else None,
                "address": record.addresses[0].get_full_address() if record.addresses else None,
                "birthdate": record.birthdate.isoformat() if record.birthdate else None,
                "gender": record.gender.value if record.gender else None,
                "status": record.status.value if record.status else None,
            }
        elif entity_type == "volunteer":
            data = {
                "id": record.id,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "email": record.emails[0].email if record.emails else None,
                "phone": record.phones[0].phone_number if record.phones else None,
                "title": record.title,
                "industry": record.industry,
                "total_volunteer_hours": float(record.total_volunteer_hours) if record.total_volunteer_hours else None,
                "first_volunteer_date": record.first_volunteer_date.isoformat()
                if record.first_volunteer_date
                else None,
                "last_volunteer_date": record.last_volunteer_date.isoformat() if record.last_volunteer_date else None,
                "skills_count": len(record.skills) if record.skills else 0,
                "interests_count": len(record.interests) if record.interests else 0,
            }
        elif entity_type == "student":
            data = {
                "id": record.id,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "grade": record.grade,
                "student_id": record.student_id,
                "enrollment_date": record.enrollment_date.isoformat() if record.enrollment_date else None,
                "graduation_date": record.graduation_date.isoformat() if record.graduation_date else None,
            }
        elif entity_type == "teacher":
            data = {
                "id": record.id,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "certification": record.certification,
                "subject_areas": record.subject_areas,
                "hire_date": record.hire_date.isoformat() if record.hire_date else None,
                "employee_id": record.employee_id,
            }
        elif entity_type == "event":
            data = {
                "id": record.id,
                "title": record.title,
                "description": record.description[:100] + "..."
                if record.description and len(record.description) > 100
                else record.description,
                "start_date": record.start_date.isoformat() if record.start_date else None,
                "end_date": record.end_date.isoformat() if record.end_date else None,
                "location_name": record.location_name,
                "location_address": record.location_address,
                "virtual_link": record.virtual_link,
                "capacity": record.capacity,
                "cost": float(record.cost) if record.cost else None,
                "event_status": record.event_status.value if record.event_status else None,
                "event_type": record.event_type.value if record.event_type else None,
            }
        elif entity_type == "organization":
            data = {
                "id": record.id,
                "name": record.name,
                "description": record.description[:100] + "..."
                if record.description and len(record.description) > 100
                else record.description,
                "website": record.website,
                "phone": record.phone,
                "email": record.email,
                "address": record.addresses[0].get_full_address() if record.addresses else None,
                "organization_type": record.organization_type.value if record.organization_type else None,
            }
        elif entity_type == "user":
            data = {
                "id": record.id,
                "username": record.username,
                "email": record.email,
                "first_name": record.first_name,
                "last_name": record.last_name,
            }

        return data

    @classmethod
    def get_samples(
        cls,
        entity_type: str,
        sample_size: Optional[int] = None,
        organization_id: Optional[int] = None,
    ) -> SamplingResult:
        """Get intelligent sample of records for an entity type"""
        cache_key = cls._get_cache_key(entity_type, sample_size or cls.DEFAULT_SAMPLE_SIZE, organization_id)
        cached = cls._get_cached(cache_key)
        if cached:
            return cached

        # Get base query and field definitions
        query, field_definitions, total_records = cls._get_entity_query(entity_type, organization_id)

        if total_records == 0:
            return SamplingResult(
                entity_type=entity_type,
                total_records=0,
                sample_size=0,
                samples=[],
                statistics={},
                edge_cases=[],
                timestamp=datetime.now(timezone.utc),
            )

        # Calculate sample size
        actual_sample_size = cls._calculate_sample_size(total_records, sample_size)

        # Get all records with completeness scores
        all_records = query.all()
        records_with_scores = []
        for record in all_records:
            score = cls._calculate_record_completeness(entity_type, record, field_definitions)
            level = cls._get_completeness_level(score)
            is_edge, edge_reasons = cls._is_edge_case(entity_type, record, score)
            records_with_scores.append((record, score, level, is_edge, edge_reasons))

        # Stratified sampling
        high_completeness = [r for r in records_with_scores if r[2] == "high"]
        medium_completeness = [r for r in records_with_scores if r[2] == "medium"]
        low_completeness = [r for r in records_with_scores if r[2] == "low"]
        edge_cases_list = [r for r in records_with_scores if r[3]]

        # Calculate sample distribution
        high_count = max(1, int(actual_sample_size * cls.HIGH_COMPLETENESS_RATIO))
        medium_count = max(1, int(actual_sample_size * cls.MEDIUM_COMPLETENESS_RATIO))
        low_count = max(1, actual_sample_size - high_count - medium_count)

        # Sample from each stratum
        sampled_high = random.sample(high_completeness, min(high_count, len(high_completeness)))
        sampled_medium = random.sample(medium_completeness, min(medium_count, len(medium_completeness)))
        sampled_low = random.sample(low_completeness, min(low_count, len(low_completeness)))

        # Combine samples
        all_sampled = sampled_high + sampled_medium + sampled_low

        # Ensure we include some edge cases (up to 20% of sample)
        edge_case_count = min(int(actual_sample_size * 0.2), len(edge_cases_list))
        if edge_case_count > 0:
            sampled_edge = random.sample(edge_cases_list, edge_case_count)
            # Merge edge cases into samples (avoid duplicates)
            existing_ids = {r[0].id for r in all_sampled}
            for edge_record in sampled_edge:
                if edge_record[0].id not in existing_ids:
                    all_sampled.append(edge_record)
                    if len(all_sampled) >= actual_sample_size:
                        break

        # Limit to sample size
        all_sampled = all_sampled[:actual_sample_size]

        # Convert to RecordSample objects
        samples = []
        for record, score, level, is_edge, edge_reasons in all_sampled:
            samples.append(
                RecordSample(
                    id=record.id,
                    data=cls._serialize_record(entity_type, record),
                    completeness_score=round(score, 2),
                    completeness_level=level,
                    is_edge_case=is_edge,
                    edge_case_reasons=edge_reasons,
                )
            )

        # Separate edge cases
        edge_cases = [s for s in samples if s.is_edge_case]

        # Calculate statistics
        statistics = cls._calculate_statistics(entity_type, all_records, field_definitions, organization_id)

        result = SamplingResult(
            entity_type=entity_type,
            total_records=total_records,
            sample_size=len(samples),
            samples=samples,
            statistics=statistics,
            edge_cases=edge_cases,
            timestamp=datetime.now(timezone.utc),
        )

        cls._set_cache(cache_key, result)
        return result

    @classmethod
    def _get_entity_query(
        cls, entity_type: str, organization_id: Optional[int] = None
    ) -> Tuple[Query, List[Tuple[str, Any]], int]:
        """Get query and field definitions for entity type"""
        if entity_type == "contact":
            query = Contact.query
            if organization_id:
                contact_ids = DataQualityService._get_contact_ids_for_organization(organization_id)
                if not contact_ids:
                    return query.filter(False), [], 0
                query = query.filter(Contact.id.in_(contact_ids))

            field_definitions = [
                ("first_name", Contact.first_name),
                ("last_name", Contact.last_name),
                ("middle_name", Contact.middle_name),
                ("preferred_name", Contact.preferred_name),
                ("birthdate", Contact.birthdate),
                ("gender", Contact.gender),
                ("race", Contact.race),
                ("education_level", Contact.education_level),
            ]
            total_records = query.count()
            return query, field_definitions, total_records

        elif entity_type == "volunteer":
            if organization_id:
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

            field_definitions = [
                ("title", Volunteer.title),
                ("industry", Volunteer.industry),
                ("clearance_status", Volunteer.clearance_status),
                ("first_volunteer_date", Volunteer.first_volunteer_date),
                ("last_volunteer_date", Volunteer.last_volunteer_date),
                ("total_volunteer_hours", Volunteer.total_volunteer_hours),
            ]
            total_records = query.count()
            return query, field_definitions, total_records

        elif entity_type == "student":
            query = Student.query
            if organization_id:
                query = query.filter(Student.organization_id == organization_id)
            field_definitions = [
                ("grade", Student.grade),
                ("enrollment_date", Student.enrollment_date),
                ("student_id", Student.student_id),
                ("graduation_date", Student.graduation_date),
            ]
            total_records = query.count()
            return query, field_definitions, total_records

        elif entity_type == "teacher":
            query = Teacher.query
            if organization_id:
                query = query.filter(Teacher.organization_id == organization_id)
            field_definitions = [
                ("certification", Teacher.certification),
                ("subject_areas", Teacher.subject_areas),
                ("hire_date", Teacher.hire_date),
                ("employee_id", Teacher.employee_id),
            ]
            total_records = query.count()
            return query, field_definitions, total_records

        elif entity_type == "event":
            query = Event.query
            if organization_id:
                from flask_app.models.event.models import EventOrganization

                event_ids = (
                    db.session.query(EventOrganization.event_id)
                    .filter(EventOrganization.organization_id == organization_id)
                    .subquery()
                )
                query = query.filter(Event.id.in_(db.session.query(event_ids)))

            field_definitions = [
                ("title", Event.title),
                ("description", Event.description),
                ("location_name", Event.location_name),
                ("location_address", Event.location_address),
                ("virtual_link", Event.virtual_link),
                ("start_date", Event.start_date),
                ("end_date", Event.end_date),
                ("duration", Event.duration),
                ("capacity", Event.capacity),
                ("cost", Event.cost),
            ]
            total_records = query.count()
            return query, field_definitions, total_records

        elif entity_type == "organization":
            query = Organization.query
            if organization_id:
                query = query.filter(Organization.id == organization_id)

            field_definitions = [
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
            total_records = query.count()
            return query, field_definitions, total_records

        elif entity_type == "user":
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

            field_definitions = [
                ("username", User.username),
                ("email", User.email),
                ("first_name", User.first_name),
                ("last_name", User.last_name),
            ]
            total_records = query.count()
            return query, field_definitions, total_records

        else:
            raise ValueError(f"Unknown entity type: {entity_type}")

    @classmethod
    def _calculate_statistics(
        cls,
        entity_type: str,
        records: List[Any],
        field_definitions: List[Tuple[str, Any]],
        organization_id: Optional[int] = None,
    ) -> Dict[str, FieldStatistics]:
        """Calculate statistical summaries for fields"""
        statistics = {}

        for field_name, field_column in field_definitions:
            values = []
            non_null_count = 0

            for record in records:
                if hasattr(record, field_name):
                    value = getattr(record, field_name)
                    if value is not None and value != "":
                        values.append(value)
                        non_null_count += 1

            # Calculate statistics
            unique_values = len(set(values))
            value_counter = Counter(values)
            most_common = [{"value": str(val), "count": count} for val, count in value_counter.most_common(10)]

            # Numeric statistics
            min_val = None
            max_val = None
            avg_val = None

            numeric_values = [v for v in values if isinstance(v, (int, float))]
            if numeric_values:
                min_val = min(numeric_values)
                max_val = max(numeric_values)
                avg_val = sum(numeric_values) / len(numeric_values)

            # Date statistics
            date_values = [v for v in values if isinstance(v, (datetime, type(datetime.now().date())))]
            if date_values:
                min_val = min(date_values)
                max_val = max(date_values)

            statistics[field_name] = FieldStatistics(
                field_name=field_name,
                total_count=len(records),
                non_null_count=non_null_count,
                null_count=len(records) - non_null_count,
                unique_values=unique_values,
                most_common_values=most_common,
                min_value=min_val,
                max_value=max_val,
                avg_value=avg_val,
                value_distribution={str(k): v for k, v in value_counter.items()},
            )

        # Add relationship field statistics
        if entity_type == "contact":
            email_count = sum(1 for r in records if r.emails)
            phone_count = sum(1 for r in records if r.phones)
            address_count = sum(1 for r in records if r.addresses)

            statistics["email"] = FieldStatistics(
                field_name="email",
                total_count=len(records),
                non_null_count=email_count,
                null_count=len(records) - email_count,
                unique_values=email_count,
                most_common_values=[],
            )

            statistics["phone"] = FieldStatistics(
                field_name="phone",
                total_count=len(records),
                non_null_count=phone_count,
                null_count=len(records) - phone_count,
                unique_values=phone_count,
                most_common_values=[],
            )

            statistics["address"] = FieldStatistics(
                field_name="address",
                total_count=len(records),
                non_null_count=address_count,
                null_count=len(records) - address_count,
                unique_values=address_count,
                most_common_values=[],
            )

        elif entity_type == "volunteer":
            skills_count = sum(1 for r in records if r.skills)
            interests_count = sum(1 for r in records if r.interests)

            statistics["skills"] = FieldStatistics(
                field_name="skills",
                total_count=len(records),
                non_null_count=skills_count,
                null_count=len(records) - skills_count,
                unique_values=skills_count,
                most_common_values=[],
            )

            statistics["interests"] = FieldStatistics(
                field_name="interests",
                total_count=len(records),
                non_null_count=interests_count,
                null_count=len(records) - interests_count,
                unique_values=interests_count,
                most_common_values=[],
            )

        elif entity_type == "organization":
            address_count = sum(1 for r in records if r.addresses)
            statistics["address"] = FieldStatistics(
                field_name="address",
                total_count=len(records),
                non_null_count=address_count,
                null_count=len(records) - address_count,
                unique_values=address_count,
                most_common_values=[],
            )

        return statistics

    @classmethod
    def get_statistics(cls, entity_type: str, organization_id: Optional[int] = None) -> Dict[str, FieldStatistics]:
        """Get statistical summaries for an entity type"""
        query, field_definitions, total_records = cls._get_entity_query(entity_type, organization_id)

        if total_records == 0:
            return {}

        all_records = query.all()
        return cls._calculate_statistics(entity_type, all_records, field_definitions, organization_id)

    @classmethod
    def get_edge_cases(
        cls,
        entity_type: str,
        limit: int = 20,
        organization_id: Optional[int] = None,
    ) -> List[RecordSample]:
        """Get edge cases for an entity type"""
        query, field_definitions, total_records = cls._get_entity_query(entity_type, organization_id)

        if total_records == 0:
            return []

        all_records = query.all()
        edge_cases = []

        for record in all_records:
            score = cls._calculate_record_completeness(entity_type, record, field_definitions)
            is_edge, edge_reasons = cls._is_edge_case(entity_type, record, score)

            if is_edge:
                level = cls._get_completeness_level(score)
                edge_cases.append(
                    RecordSample(
                        id=record.id,
                        data=cls._serialize_record(entity_type, record),
                        completeness_score=round(score, 2),
                        completeness_level=level,
                        is_edge_case=True,
                        edge_case_reasons=edge_reasons,
                    )
                )

        # Sort by number of edge case reasons (most problematic first)
        edge_cases.sort(key=lambda x: len(x.edge_case_reasons), reverse=True)

        return edge_cases[:limit]

    @classmethod
    def get_field_samples(
        cls,
        entity_type: str,
        field_name: str,
        sample_size: Optional[int] = None,
        organization_id: Optional[int] = None,
    ) -> SamplingResult:
        """Get samples filtered to only include records that have the specified field populated"""
        # Check cache
        cache_key = cls._get_cache_key(
            f"field_samples_{entity_type}_{field_name}", sample_size or cls.DEFAULT_SAMPLE_SIZE, organization_id
        )
        cached = cls._get_cached(cache_key)
        if cached:
            return cached

        # Get base query and field definitions
        query, field_definitions, total_records = cls._get_entity_query(entity_type, organization_id)

        if total_records == 0:
            result = SamplingResult(
                entity_type=entity_type,
                total_records=0,
                sample_size=0,
                samples=[],
                statistics={},
                edge_cases=[],
                timestamp=datetime.now(timezone.utc),
            )
            cls._set_cache(cache_key, result)
            return result

        # Filter query to only records with the field populated
        field_column = None
        for fname, fcol in field_definitions:
            if fname == field_name:
                field_column = fcol
                break

        if field_column:
            # Direct field - filter by non-null and non-empty
            query = query.filter(and_(field_column.isnot(None), field_column != ""))
        elif field_name == "email" and entity_type == "contact":
            # Relationship field - filter by existence
            query = query.join(ContactEmail, ContactEmail.contact_id == Contact.id).distinct()
        elif field_name == "phone" and entity_type == "contact":
            query = query.join(ContactPhone, ContactPhone.contact_id == Contact.id).distinct()
        elif field_name == "address" and entity_type == "contact":
            query = query.join(ContactAddress, ContactAddress.contact_id == Contact.id).distinct()
        elif field_name == "address" and entity_type == "organization":
            query = query.join(OrganizationAddress, OrganizationAddress.organization_id == Organization.id).distinct()
        elif field_name == "skills" and entity_type == "volunteer":
            query = query.join(VolunteerSkill, VolunteerSkill.volunteer_id == Volunteer.id).distinct()
        elif field_name == "interests" and entity_type == "volunteer":
            query = query.join(VolunteerInterest, VolunteerInterest.volunteer_id == Volunteer.id).distinct()
        else:
            # Field not found - return empty result
            result = SamplingResult(
                entity_type=entity_type,
                total_records=total_records,
                sample_size=0,
                samples=[],
                statistics={},
                edge_cases=[],
                timestamp=datetime.now(timezone.utc),
            )
            cls._set_cache(cache_key, result)
            return result

        # Get count efficiently (don't load all records)
        filtered_total = query.count()
        actual_sample_size = cls._calculate_sample_size(filtered_total, sample_size)

        if filtered_total == 0:
            result = SamplingResult(
                entity_type=entity_type,
                total_records=0,
                sample_size=0,
                samples=[],
                statistics={},
                edge_cases=[],
                timestamp=datetime.now(timezone.utc),
            )
            cls._set_cache(cache_key, result)
            return result

        # Use database-level sampling - get random sample directly from DB
        # For SQLite/Postgres, use ORDER BY RANDOM() or similar
        # Limit to reasonable number to avoid loading too much
        max_load = min(actual_sample_size * 3, 150)  # Load at most 150 records
        filtered_records = query.order_by(func.random()).limit(max_load).all()

        # Shuffle and take sample (already random from DB, but ensure diversity)
        if len(filtered_records) > actual_sample_size:
            random.shuffle(filtered_records)
            filtered_records = filtered_records[:actual_sample_size]

        # Convert to RecordSample objects (skip expensive completeness calculation for samples)
        samples = []
        for record in filtered_records:
            # Simplified - just serialize, don't calculate completeness for each sample
            samples.append(
                RecordSample(
                    id=record.id,
                    data=cls._serialize_record(entity_type, record),
                    completeness_score=0.0,  # Not calculated for performance
                    completeness_level="unknown",
                    is_edge_case=False,  # Not calculated for performance
                    edge_case_reasons=[],
                )
            )

        # Don't load statistics or edge cases here - lazy load them separately
        result = SamplingResult(
            entity_type=entity_type,
            total_records=filtered_total,
            sample_size=len(samples),
            samples=samples,
            statistics={},  # Loaded separately
            edge_cases=[],  # Loaded separately
            timestamp=datetime.now(timezone.utc),
        )

        cls._set_cache(cache_key, result)
        return result

    @classmethod
    def get_field_statistics(
        cls,
        entity_type: str,
        field_name: str,
        organization_id: Optional[int] = None,
    ) -> Optional[FieldStatistics]:
        """Get statistics for a specific field - optimized to only calculate for this field"""
        # Check cache
        cache_key = cls._get_cache_key(f"field_stats_{entity_type}_{field_name}", 0, organization_id)
        cached = cls._get_cached(cache_key)
        if cached:
            return cached

        query, field_definitions, total_records = cls._get_entity_query(entity_type, organization_id)

        if total_records == 0:
            return None

        # Find the field column
        field_column = None
        for fname, fcol in field_definitions:
            if fname == field_name:
                field_column = fcol
                break

        if not field_column:
            # Check relationship fields
            if field_name == "email" and entity_type == "contact":
                # Use SQL aggregation for efficiency
                email_query = db.session.query(func.count(func.distinct(ContactEmail.contact_id))).join(
                    Contact, ContactEmail.contact_id == Contact.id
                )
                if organization_id:
                    contact_ids = DataQualityService._get_contact_ids_for_organization(organization_id)
                    if contact_ids:
                        email_query = email_query.filter(Contact.id.in_(contact_ids))

                non_null_count = email_query.scalar() or 0
                statistics = FieldStatistics(
                    field_name=field_name,
                    total_count=total_records,
                    non_null_count=non_null_count,
                    null_count=total_records - non_null_count,
                    unique_values=non_null_count,
                    most_common_values=[],
                )
                cls._set_cache(cache_key, statistics)
                return statistics
            elif field_name == "phone" and entity_type == "contact":
                phone_query = db.session.query(func.count(func.distinct(ContactPhone.contact_id))).join(
                    Contact, ContactPhone.contact_id == Contact.id
                )
                if organization_id:
                    contact_ids = DataQualityService._get_contact_ids_for_organization(organization_id)
                    if contact_ids:
                        phone_query = phone_query.filter(Contact.id.in_(contact_ids))

                non_null_count = phone_query.scalar() or 0
                statistics = FieldStatistics(
                    field_name=field_name,
                    total_count=total_records,
                    non_null_count=non_null_count,
                    null_count=total_records - non_null_count,
                    unique_values=non_null_count,
                    most_common_values=[],
                )
                cls._set_cache(cache_key, statistics)
                return statistics
            return None

        # Use SQL aggregation for direct fields - much faster than loading all records
        # Count non-null values
        non_null_query = query.filter(and_(field_column.isnot(None), field_column != ""))
        non_null_count = non_null_query.count()

        # Get unique count using the same query
        unique_count = non_null_query.with_entities(func.count(func.distinct(field_column))).scalar() or 0

        # Get most common values using SQL aggregation (top 10) - use the base query directly
        most_common_query = (
            query.filter(and_(field_column.isnot(None), field_column != ""))
            .with_entities(field_column, func.count(field_column).label("count"))
            .group_by(field_column)
            .order_by(func.count(field_column).desc())
            .limit(10)
        )
        most_common = [{"value": str(row[0]), "count": row[1]} for row in most_common_query.all()]

        # Get min/max/avg for numeric fields
        min_val = None
        max_val = None
        avg_val = None

        # Try to get numeric stats if field is numeric
        try:
            numeric_query = query.filter(and_(field_column.isnot(None), field_column != "")).with_entities(
                func.min(field_column), func.max(field_column), func.avg(field_column)
            )
            numeric_result = numeric_query.first()
            if numeric_result and numeric_result[0] is not None:
                min_val = float(numeric_result[0]) if numeric_result[0] is not None else None
                max_val = float(numeric_result[1]) if numeric_result[1] is not None else None
                avg_val = float(numeric_result[2]) if numeric_result[2] is not None else None
        except Exception:
            # Field is not numeric, skip
            pass

        statistics = FieldStatistics(
            field_name=field_name,
            total_count=total_records,
            non_null_count=non_null_count,
            null_count=total_records - non_null_count,
            unique_values=unique_count,
            most_common_values=most_common,
            min_value=min_val,
            max_value=max_val,
            avg_value=avg_val,
            value_distribution={},  # Not calculated for performance
        )

        cls._set_cache(cache_key, statistics)
        return statistics

    @classmethod
    def get_field_edge_cases(
        cls,
        entity_type: str,
        field_name: str,
        limit: int = 20,
        organization_id: Optional[int] = None,
    ) -> List[RecordSample]:
        """Get edge cases related to a specific field (records missing this field) - optimized"""
        # Check cache
        cache_key = cls._get_cache_key(f"field_edges_{entity_type}_{field_name}", limit, organization_id)
        cached = cls._get_cached(cache_key)
        if cached:
            return cached

        query, field_definitions, total_records = cls._get_entity_query(entity_type, organization_id)

        if total_records == 0:
            return []

        # Find the field column
        field_column = None
        for fname, fcol in field_definitions:
            if fname == field_name:
                field_column = fcol
                break

        # Query directly for records missing the field (much faster than loading all)
        edge_case_query = None

        if field_column:
            # Direct field - query for records where field is null or empty
            edge_case_query = query.filter(or_(field_column.is_(None), field_column == ""))
        elif field_name == "email" and entity_type == "contact":
            # Records without emails - use NOT EXISTS subquery
            email_subquery = db.session.query(ContactEmail.contact_id).distinct()
            if organization_id:
                contact_ids = DataQualityService._get_contact_ids_for_organization(organization_id)
                if contact_ids:
                    email_subquery = email_subquery.filter(ContactEmail.contact_id.in_(contact_ids))
            edge_case_query = query.filter(~Contact.id.in_(email_subquery))
        elif field_name == "phone" and entity_type == "contact":
            phone_subquery = db.session.query(ContactPhone.contact_id).distinct()
            if organization_id:
                contact_ids = DataQualityService._get_contact_ids_for_organization(organization_id)
                if contact_ids:
                    phone_subquery = phone_subquery.filter(ContactPhone.contact_id.in_(contact_ids))
            edge_case_query = query.filter(~Contact.id.in_(phone_subquery))
        elif field_name == "address" and entity_type == "contact":
            address_subquery = db.session.query(ContactAddress.contact_id).distinct()
            if organization_id:
                contact_ids = DataQualityService._get_contact_ids_for_organization(organization_id)
                if contact_ids:
                    address_subquery = address_subquery.filter(ContactAddress.contact_id.in_(contact_ids))
            edge_case_query = query.filter(~Contact.id.in_(address_subquery))
        elif field_name == "address" and entity_type == "organization":
            address_subquery = db.session.query(OrganizationAddress.organization_id).distinct()
            if organization_id:
                address_subquery = address_subquery.filter(OrganizationAddress.organization_id == organization_id)
            edge_case_query = query.filter(~Organization.id.in_(address_subquery))

        if not edge_case_query:
            return []

        # Limit to avoid loading too many records
        edge_records = edge_case_query.limit(limit).all()

        # Convert to RecordSample objects (skip expensive completeness calculation)
        edge_cases = []
        for record in edge_records:
            edge_cases.append(
                RecordSample(
                    id=record.id,
                    data=cls._serialize_record(entity_type, record),
                    completeness_score=0.0,  # Not calculated for performance
                    completeness_level="low",
                    is_edge_case=True,
                    edge_case_reasons=[f"Missing {field_name}"],
                )
            )

        cls._set_cache(cache_key, edge_cases)
        return edge_cases
