"""
SQLAlchemy models for the importer base schema (IMP-2).

These tables remain lightweight until future importer work layers on
additional behavior. They are created alongside the rest of the app so
environments that choose to enable the importer have the schema ready.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel, db


class ImportRunStatus(str, enum.Enum):
    """Lifecycle states for an import run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportRun(BaseModel):
    """Metadata describing a single importer execution."""

    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    adapter: Mapped[str | None] = mapped_column(db.String(100), nullable=True)
    status: Mapped[ImportRunStatus] = mapped_column(
        Enum(ImportRunStatus, name="import_run_status_enum"),
        nullable=False,
        default=ImportRunStatus.PENDING,
        index=True,
    )
    dry_run: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    triggered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    counts_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    metrics_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    anomaly_flags: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    ingest_params_json: Mapped[dict | None] = mapped_column(
        db.JSON,
        nullable=True,
        comment="Stored parameters for retry support (file_path, source_system, dry_run, keep_file)",
    )
    adapter_health_json: Mapped[dict | None] = mapped_column(
        db.JSON,
        nullable=True,
        comment="Snapshot of adapter readiness metadata when the run was created.",
    )
    max_source_updated_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
        comment="Latest source updated-at observed during the run for freshness tracking.",
    )

    triggered_by_user = relationship("User", foreign_keys=[triggered_by_user_id])
    staging_rows = relationship(
        "StagingVolunteer",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    staging_organizations = relationship(
        "StagingOrganization",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    staging_affiliations = relationship(
        "StagingAffiliation",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    staging_events = relationship(
        "StagingEvent",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    dq_violations = relationship(
        "DataQualityViolation",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_volunteers = relationship(
        "CleanVolunteer",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_organizations = relationship(
        "CleanOrganization",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_affiliations = relationship(
        "CleanAffiliation",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_events = relationship(
        "CleanEvent",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    dedupe_suggestions = relationship(
        "DedupeSuggestion",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    external_ids = relationship(
        "ExternalIdMap",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    merge_events = relationship(
        "MergeLog",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    change_events = relationship(
        "ChangeLogEntry",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    import_skips = relationship(
        "ImportSkip",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (Index("idx_import_runs_source_status", "source", "status"),)


class StagingRecordStatus(str, enum.Enum):
    """High-level processing state for a staging row."""

    LANDED = "landed"
    VALIDATED = "validated"
    QUARANTINED = "quarantined"
    LOADED = "loaded"


class StagingVolunteer(BaseModel):
    """
    Raw volunteer payloads staged during an import run.

    Rows contain both the original payload and optional normalized data. DQ
    processing moves rows from `LANDED` to `VALIDATED`/`QUARANTINED`.
    """

    __tablename__ = "staging_volunteers"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    normalized_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    status: Mapped[StagingRecordStatus] = mapped_column(
        Enum(StagingRecordStatus, name="staging_volunteer_status_enum"),
        default=StagingRecordStatus.LANDED,
        nullable=False,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    landed_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))

    import_run = relationship("ImportRun", back_populates="staging_rows")
    dq_violations = relationship(
        "DataQualityViolation",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_record = relationship(
        "CleanVolunteer",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    dedupe_suggestions = relationship(
        "DedupeSuggestion",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    import_skips = relationship(
        "ImportSkip",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "idx_staging_volunteers_external_key",
            "external_system",
            "external_id",
        ),
        UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_staging_volunteers_run_sequence",
        ),
    )


class StagingOrganization(BaseModel):
    """
    Raw organization payloads staged during an import run.

    Rows contain both the original payload and optional normalized data. DQ
    processing moves rows from `LANDED` to `VALIDATED`/`QUARANTINED`.
    """

    __tablename__ = "staging_organizations"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    normalized_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    status: Mapped[StagingRecordStatus] = mapped_column(
        Enum(StagingRecordStatus, name="staging_organization_status_enum"),
        default=StagingRecordStatus.LANDED,
        nullable=False,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    landed_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))

    import_run = relationship("ImportRun", back_populates="staging_organizations")
    dq_violations = relationship(
        "DataQualityViolation",
        back_populates="staging_organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_record = relationship(
        "CleanOrganization",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    import_skips = relationship(
        "ImportSkip",
        back_populates="staging_organization",
        primaryjoin="StagingOrganization.id == ImportSkip.staging_organization_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "idx_staging_organizations_external_key",
            "external_system",
            "external_id",
        ),
        UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_staging_organizations_run_sequence",
        ),
    )


class StagingAffiliation(BaseModel):
    """
    Raw affiliation payloads staged during an import run.

    Rows contain both the original payload and optional normalized data. DQ
    processing moves rows from `LANDED` to `VALIDATED`/`QUARANTINED`.
    """

    __tablename__ = "staging_affiliations"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    normalized_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    status: Mapped[StagingRecordStatus] = mapped_column(
        Enum(StagingRecordStatus, name="staging_affiliation_status_enum"),
        default=StagingRecordStatus.LANDED,
        nullable=False,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    landed_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))

    import_run = relationship("ImportRun", back_populates="staging_affiliations")
    dq_violations = relationship(
        "DataQualityViolation",
        back_populates="staging_affiliation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_record = relationship(
        "CleanAffiliation",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    import_skips = relationship(
        "ImportSkip",
        back_populates="staging_affiliation",
        primaryjoin="StagingAffiliation.id == ImportSkip.staging_affiliation_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "idx_staging_affiliations_external_key",
            "external_system",
            "external_id",
        ),
        UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_staging_affiliations_run_sequence",
        ),
    )


class StagingEvent(BaseModel):
    """
    Raw event payloads staged during an import run.

    Rows contain both the original payload and optional normalized data. DQ
    processing moves rows from `LANDED` to `VALIDATED`/`QUARANTINED`.
    """

    __tablename__ = "staging_events"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    normalized_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    status: Mapped[StagingRecordStatus] = mapped_column(
        Enum(StagingRecordStatus, name="staging_event_status_enum"),
        default=StagingRecordStatus.LANDED,
        nullable=False,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    landed_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))

    import_run = relationship("ImportRun", back_populates="staging_events")
    dq_violations = relationship(
        "DataQualityViolation",
        back_populates="staging_event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    clean_record = relationship(
        "CleanEvent",
        back_populates="staging_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    import_skips = relationship(
        "ImportSkip",
        back_populates="staging_event",
        primaryjoin="StagingEvent.id == ImportSkip.staging_event_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "idx_staging_events_external_key",
            "external_system",
            "external_id",
        ),
        UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_staging_events_run_sequence",
        ),
    )


class DataQualitySeverity(str, enum.Enum):
    """Severity tier for data quality rules."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DataQualityStatus(str, enum.Enum):
    """Resolution state for a DQ violation."""

    OPEN = "open"
    FIXED = "fixed"
    SUPPRESSED = "suppressed"


class DataQualityViolation(BaseModel):
    """Quarantined issues that block or warn on data movement."""

    __tablename__ = "dq_violations"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_volunteer_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_volunteers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    staging_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    staging_affiliation_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_affiliations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    staging_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(db.String(50), nullable=False, default="volunteer")
    record_key: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    rule_code: Mapped[str] = mapped_column(db.String(50), nullable=False)
    severity: Mapped[DataQualitySeverity] = mapped_column(
        Enum(DataQualitySeverity, name="dq_violation_severity_enum"),
        nullable=False,
    )
    status: Mapped[DataQualityStatus] = mapped_column(
        Enum(DataQualityStatus, name="dq_violation_status_enum"),
        nullable=False,
        default=DataQualityStatus.OPEN,
        index=True,
    )
    message: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    remediation_notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    edited_payload_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    edited_fields_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    remediation_audit_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    remediated_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    remediated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    import_run = relationship("ImportRun", back_populates="dq_violations")
    staging_row = relationship("StagingVolunteer", back_populates="dq_violations", foreign_keys=[staging_volunteer_id])
    staging_organization = relationship(
        "StagingOrganization", back_populates="dq_violations", foreign_keys=[staging_organization_id]
    )
    staging_affiliation = relationship(
        "StagingAffiliation", back_populates="dq_violations", foreign_keys=[staging_affiliation_id]
    )
    staging_event = relationship("StagingEvent", back_populates="dq_violations", foreign_keys=[staging_event_id])
    remediated_by_user = relationship("User", foreign_keys=[remediated_by_user_id])

    __table_args__ = (Index("idx_dq_violations_run_rule", "run_id", "rule_code"),)


class ImportSkipType(str, enum.Enum):
    """Types of reasons why a record was skipped during core load."""

    DUPLICATE_EMAIL = "duplicate_email"
    DUPLICATE_NAME = "duplicate_name"
    DUPLICATE_FUZZY = "duplicate_fuzzy"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    MISSING_REFERENCE = "missing_reference"
    VALIDATION_ERROR = "validation_error"
    OTHER = "other"


class ImportSkip(BaseModel):
    """Records that passed DQ validation but were skipped during core load."""

    __tablename__ = "import_skips"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_volunteer_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_volunteers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    staging_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    staging_affiliation_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_affiliations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    staging_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    clean_volunteer_id: Mapped[int | None] = mapped_column(
        ForeignKey("clean_volunteers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    clean_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("clean_organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    clean_affiliation_id: Mapped[int | None] = mapped_column(
        ForeignKey("clean_affiliations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    clean_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("clean_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(db.String(50), nullable=False, default="volunteer")
    skip_type: Mapped[ImportSkipType] = mapped_column(
        Enum(ImportSkipType, name="import_skip_type_enum"),
        nullable=False,
        index=True,
    )
    skip_reason: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    record_key: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    import_run = relationship("ImportRun", back_populates="import_skips")
    staging_row = relationship("StagingVolunteer", back_populates="import_skips", foreign_keys=[staging_volunteer_id])
    staging_organization = relationship(
        "StagingOrganization", back_populates="import_skips", foreign_keys=[staging_organization_id]
    )
    staging_affiliation = relationship(
        "StagingAffiliation", back_populates="import_skips", foreign_keys=[staging_affiliation_id]
    )
    staging_event = relationship("StagingEvent", back_populates="import_skips", foreign_keys=[staging_event_id])
    clean_row = relationship("CleanVolunteer", back_populates="import_skips", foreign_keys=[clean_volunteer_id])
    clean_organization = relationship(
        "CleanOrganization", back_populates="import_skips", foreign_keys=[clean_organization_id]
    )
    clean_affiliation = relationship(
        "CleanAffiliation", back_populates="import_skips", foreign_keys=[clean_affiliation_id]
    )
    clean_event = relationship("CleanEvent", back_populates="import_skips", foreign_keys=[clean_event_id])

    __table_args__ = (
        Index("idx_import_skips_run_type", "run_id", "skip_type"),
        Index("idx_import_skips_entity_type", "entity_type"),
    )


class CleanVolunteer(BaseModel):
    """Normalized volunteer rows promoted from staging prior to core load."""

    __tablename__ = "clean_volunteers"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_volunteer_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_volunteers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(db.String(320), nullable=True, index=True)
    phone_e164: Mapped[str | None] = mapped_column(db.String(20), nullable=True, index=True)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    load_action: Mapped[str | None] = mapped_column(db.String(50), nullable=True)
    core_contact_id: Mapped[int | None] = mapped_column(db.Integer, nullable=True, index=True)
    core_volunteer_id: Mapped[int | None] = mapped_column(db.Integer, nullable=True, index=True)

    import_run = relationship("ImportRun", back_populates="clean_volunteers")
    staging_row = relationship("StagingVolunteer", back_populates="clean_record")
    import_skips = relationship(
        "ImportSkip",
        back_populates="clean_row",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "staging_volunteer_id",
            name="uq_clean_volunteers_run_staging",
        ),
    )


class CleanOrganization(BaseModel):
    """Normalized organization rows promoted from staging prior to core load."""

    __tablename__ = "clean_organizations"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    load_action: Mapped[str | None] = mapped_column(db.String(50), nullable=True)
    core_organization_id: Mapped[int | None] = mapped_column(db.Integer, nullable=True, index=True)

    import_run = relationship("ImportRun", back_populates="clean_organizations")
    staging_row = relationship("StagingOrganization", back_populates="clean_record")
    import_skips = relationship(
        "ImportSkip",
        back_populates="clean_organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "staging_organization_id",
            name="uq_clean_organizations_run_staging",
        ),
    )


class CleanAffiliation(BaseModel):
    """Normalized affiliation rows promoted from staging prior to core load."""

    __tablename__ = "clean_affiliations"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_affiliation_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_affiliations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True, index=True)
    contact_external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True, index=True)
    organization_external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True, index=True)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    load_action: Mapped[str | None] = mapped_column(db.String(50), nullable=True)
    core_contact_organization_id: Mapped[int | None] = mapped_column(db.Integer, nullable=True, index=True)

    import_run = relationship("ImportRun", back_populates="clean_affiliations")
    staging_row = relationship("StagingAffiliation", back_populates="clean_record")
    import_skips = relationship(
        "ImportSkip",
        back_populates="clean_affiliation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "staging_affiliation_id",
            name="uq_clean_affiliations_run_staging",
        ),
    )


class CleanEvent(BaseModel):
    """Normalized event rows promoted from staging prior to core load."""

    __tablename__ = "clean_events"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(db.String(255), nullable=True, index=True)
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    checksum: Mapped[str | None] = mapped_column(db.String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    load_action: Mapped[str | None] = mapped_column(db.String(50), nullable=True)
    core_event_id: Mapped[int | None] = mapped_column(db.Integer, nullable=True, index=True)

    import_run = relationship("ImportRun", back_populates="clean_events")
    staging_row = relationship("StagingEvent", back_populates="clean_record")
    import_skips = relationship(
        "ImportSkip",
        back_populates="clean_event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "staging_event_id",
            name="uq_clean_events_run_staging",
        ),
    )


class DedupeDecision(str, enum.Enum):
    """Decision outcome for a dedupe suggestion."""

    PENDING = "pending"
    AUTO_MERGED = "auto_merged"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class DedupeSuggestion(BaseModel):
    """Candidate duplicate matches surfaced during imports."""

    __tablename__ = "dedupe_suggestions"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staging_volunteer_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_volunteers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    staging_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    primary_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    candidate_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    score: Mapped[float | None] = mapped_column(db.Numeric(5, 4), nullable=True)
    match_type: Mapped[str | None] = mapped_column(db.String(32), nullable=True, index=True)
    confidence_score: Mapped[float | None] = mapped_column(db.Numeric(5, 4), nullable=True)
    features_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    decision: Mapped[DedupeDecision] = mapped_column(
        Enum(DedupeDecision, name="dedupe_decision_enum"),
        nullable=False,
        default=DedupeDecision.PENDING,
        index=True,
    )
    decision_notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    import_run = relationship("ImportRun", back_populates="dedupe_suggestions")
    staging_row = relationship("StagingVolunteer", back_populates="dedupe_suggestions")
    primary_contact = relationship("Contact", foreign_keys=[primary_contact_id])
    candidate_contact = relationship("Contact", foreign_keys=[candidate_contact_id])
    decided_by_user = relationship("User", foreign_keys=[decided_by_user_id])

    __table_args__ = (
        Index("idx_dedupe_suggestions_run_decision", "run_id", "decision"),
        UniqueConstraint(
            "run_id",
            "primary_contact_id",
            "candidate_contact_id",
            name="uq_dedupe_suggestions_run_contact_pair",
        ),
    )


class ExternalIdMap(BaseModel):
    """Maps external IDs to internal entities to support idempotency."""

    __tablename__ = "external_id_map"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(db.String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(db.Integer, nullable=False)
    external_system: Mapped[str] = mapped_column(db.String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(db.String(255), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id"), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    upstream_deleted_reason: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)

    import_run = relationship("ImportRun", back_populates="external_ids")

    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "external_system",
            "external_id",
            name="uq_external_id_map_entity",
        ),
        Index(
            "idx_external_id_map_external_key",
            "external_system",
            "external_id",
        ),
        Index(
            "idx_external_id_map_active_entity",
            "entity_type",
            "entity_id",
            "is_active",
        ),
    )

    def mark_seen(
        self,
        *,
        run_id: int | None = None,
        seen_at: datetime | None = None,
    ) -> None:
        """
        Update bookkeeping for an external identifier that was observed again.

        If the identifier had been soft-deleted previously, it is automatically
        reactivated so downstream consumers do not treat the record as removed.
        """

        now = seen_at or datetime.now(timezone.utc)
        self.last_seen_at = now
        if run_id is not None:
            self.run_id = run_id
        if not self.is_active:
            self.is_active = True
            self.deactivated_at = None
            self.upstream_deleted_reason = None

    def soft_delete(
        self,
        *,
        reason: str | None = None,
        deactivated_at: datetime | None = None,
    ) -> None:
        """
        Mark the external identifier as inactive without removing history.
        """

        if self.is_active:
            self.is_active = False
            self.deactivated_at = deactivated_at or datetime.now(timezone.utc)
        else:
            self.deactivated_at = self.deactivated_at or datetime.now(timezone.utc)
        self.upstream_deleted_reason = reason


class MergeLog(BaseModel):
    """Auditable record of merge operations performed during imports."""

    __tablename__ = "merge_log"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    primary_contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merged_contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    performed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    decision_type: Mapped[str] = mapped_column(db.String(50), nullable=False, default="manual")
    reason: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    snapshot_before: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    snapshot_after: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    undo_payload: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(
        db.JSON,
        nullable=True,
        comment="Merge metadata (score, match_type, features_json, survivorship_decisions, field_overrides).",
    )

    import_run = relationship("ImportRun", back_populates="merge_events")
    primary_contact = relationship("Contact", foreign_keys=[primary_contact_id])
    merged_contact = relationship("Contact", foreign_keys=[merged_contact_id])
    performed_by_user = relationship("User", foreign_keys=[performed_by_user_id])

    __table_args__ = (
        Index("idx_merge_log_primary_contact", "primary_contact_id"),
        Index("idx_merge_log_run", "run_id"),
    )


class ChangeLogEntry(BaseModel):
    """Field-level change history for importer-driven updates."""

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(db.String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(db.Integer, nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    old_value: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    change_source: Mapped[str] = mapped_column(db.String(50), nullable=False, default="importer")
    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)

    import_run = relationship("ImportRun", back_populates="change_events")
    changed_by_user = relationship("User", foreign_keys=[changed_by_user_id])

    __table_args__ = (
        Index("idx_change_log_entity", "entity_type", "entity_id"),
        CheckConstraint("field_name <> ''", name="ck_change_log_field_non_empty"),
    )


class ImporterWatermark(BaseModel):
    """Track the last successful watermark for each adapter/object pair."""

    __tablename__ = "importer_watermarks"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    adapter: Mapped[str] = mapped_column(db.String(64), nullable=False)
    object_name: Mapped[str] = mapped_column(db.String(128), nullable=False)
    last_successful_modstamp: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
        comment="Most recent SystemModstamp processed successfully.",
    )
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        db.JSON,
        nullable=True,
        comment="Adapter-specific metadata (e.g., batch counts, cursor hints).",
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    last_run = relationship("ImportRun", foreign_keys=[last_run_id])

    __table_args__ = (
        UniqueConstraint(
            "adapter",
            "object_name",
            name="uq_importer_watermarks_adapter_object",
        ),
        Index("idx_importer_watermarks_adapter", "adapter"),
    )
