"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Ingestion ----------

class BatchCreate(BaseModel):
    batch_id: str = Field(..., max_length=100)
    source_system: str = Field(..., max_length=200)


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: str
    source_system: str
    status: str
    resource_count: int
    created_at: datetime


class RawResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    source_system: str
    resource_type: str
    fhir_id: str | None
    version_id: str | None
    last_updated: datetime | None
    checksum: str
    raw_format: str
    received_at: datetime


class IngestBundleResponse(BaseModel):
    batch_id: str
    resources_received: int
    resources_valid: int
    resources_rejected: int
    message: str


# ---------- Mapping ----------

class MappingSpecCreate(BaseModel):
    name: str = Field(..., max_length=200)
    version: str = Field(..., max_length=50)
    resource_type: str = Field(..., max_length=100)
    spec_json: dict[str, Any]


class MappingSpecOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: str
    resource_type: str
    spec_json: dict[str, Any]
    is_active: bool
    created_by: str
    created_at: datetime


class MappingTestRequest(BaseModel):
    spec_json: dict[str, Any]
    sample_resources: list[dict[str, Any]]


class MappingTestResponse(BaseModel):
    rows_generated: int
    omop_rows: list[dict[str, Any]]
    warnings: list[str] = []


# ---------- Crosswalk ----------

class CrosswalkEntry(BaseModel):
    source_system: str
    resource_type: str
    fhir_id: str
    fhir_version: str = "R4"
    omop_table: str
    omop_id: int


# ---------- Runs ----------

class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: str
    project: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    rows_read: int
    rows_mapped: int
    rows_rejected: int
    error: str | None


class RunSummary(BaseModel):
    run_id: str
    status: str
    rows_read: int
    rows_mapped: int
    rows_rejected: int
    duration_ms: int | None


# ---------- Rejected / Quarantine ----------

class RejectedRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_system: str
    resource_type: str
    fhir_id: str | None
    reason_code: str
    reason_message: str
    created_at: datetime


# ---------- Health ----------

class HealthOut(BaseModel):
    status: str
    version: str
    app_env: str
