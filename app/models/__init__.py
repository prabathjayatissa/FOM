"""SQLAlchemy ORM models for FOM operational data store."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.database import Base


class Batch(Base):
    """Ingestion batch - groups resources received together (DR-5 operational store)."""

    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    source_system: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="received", nullable=False)  # received/validating/staged/loaded/failed
    resource_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    raw_resources: Mapped[list["RawResource"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class RawResource(Base):
    """Raw store: unchanged FHIR resource with metadata (DR-1, FR-015)."""

    __tablename__ = "raw_resources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fhir_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_format: Mapped[str] = mapped_column(String(20), default="json", nullable=False)  # json/ndjson/xml
    resource_json: Mapped[dict] = mapped_column(JSONB, nullable=False)  # unchanged resource
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    batch: Mapped["Batch"] = relationship(back_populates="raw_resources")
    staging: Mapped[Optional["StagingResource"]] = relationship(back_populates="raw_resource", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_raw_resources_source_type_id", "source_system", "resource_type", "fhir_id"),
        Index("ix_raw_resources_checksum", "checksum"),
    )


class StagingResource(Base):
    """Staging store: flattened, typed projection per resource type (DR-2, FR-021)."""

    __tablename__ = "staging_resources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_resources.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fhir_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    staging_json: Mapped[dict] = mapped_column(JSONB, nullable=False)  # flattened projection (FHIRPath)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    raw_resource: Mapped["RawResource"] = relationship(back_populates="staging")


class RejectedRecord(Base):
    """Quarantine: invalid resources with reason codes (FR-016, FR-026)."""

    __tablename__ = "rejected_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True)
    source_system: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    fhir_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_message: Mapped[str] = mapped_column(Text, nullable=False)
    resource_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class Crosswalk(Base):
    """Persistent crosswalk: (source, type, fhir id, version) -> (OMOP table, OMOP id) (DR-3, FR-070).

    Stores spec_name/spec_version so every loaded record carries the mapping
    specification version that produced it (FR-040, DR-6 lineage).
    """

    __tablename__ = "crosswalk"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_system: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fhir_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fhir_version: Mapped[str] = mapped_column(String(20), default="R4", nullable=False)
    omop_table: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    omop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    spec_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)  # active/retired/deleted
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_system", "resource_type", "fhir_id", "fhir_version", name="uq_crosswalk_source"),
    )


class Lineage(Base):
    """Row-level lineage: OMOP row -> source resource + rule version (DR-6, FR-093).

    Brings lineage forward so every CDM row can be traced to the exact source
    resource, mapping spec version, and run that produced it.
    """

    __tablename__ = "lineage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    omop_table: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    omop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fhir_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fhir_version: Mapped[str] = mapped_column(String(20), default="R4", nullable=False)
    spec_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_lineage_omop", "omop_table", "omop_id"),
        Index("ix_lineage_source", "source_system", "resource_type", "fhir_id"),
    )


class MappingSpec(Base):
    """Versioned declarative mapping specification (DR-4, FR-002, FR-030)."""

    __tablename__ = "mapping_specs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    spec_json: Mapped[dict] = mapped_column(JSONB, nullable=False)  # declarative mapping language (YAML/JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_mapping_spec_name_version"),
    )


class Run(Base):
    """Operational run record (DR-5, FR-040)."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    project: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", nullable=False)  # queued/running/completed/failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_mapped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
