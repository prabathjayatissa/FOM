"""Loader service: crosswalk management, idempotent OMOP writes, deletes (FR-070 to FR-079)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Crosswalk, Lineage, RawResource, Run


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Loader:
    """Idempotent loader that maintains the crosswalk between FHIR resources
    and OMOP identifiers.

    Release 0.1 writes OMOP rows into a staging/results representation and
    records crosswalk entries. Full CDM table DDL and bulk-load adapters are
    added for SQL Server / other platforms in later releases (FR-076).
    """

    def __init__(self, db: AsyncSession, run: Run):
        self.db = db
        self.run = run

    async def upsert_resource(
        self,
        source_system: str,
        resource_type: str,
        fhir_id: str,
        fhir_version: str,
        omop_table: str,
        omop_id: int,
        spec_name: Optional[str] = None,
        spec_version: Optional[str] = None,
    ) -> Crosswalk:
        """Insert or update a crosswalk entry idempotently (FR-073).

        Re-processing the same resource version must not create duplicates.
        Stores spec_name/spec_version so every loaded record carries the
        mapping specification version that produced it (FR-040).
        """
        result = await self.db.execute(
            select(Crosswalk).where(
                Crosswalk.source_system == source_system,
                Crosswalk.resource_type == resource_type,
                Crosswalk.fhir_id == fhir_id,
                Crosswalk.fhir_version == fhir_version,
                Crosswalk.omop_table == omop_table,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.omop_id = omop_id
            existing.status = "active"
            existing.run_id = self.run.id
            existing.spec_name = spec_name
            existing.spec_version = spec_version
            await self.db.flush()
            return existing

        entry = Crosswalk(
            source_system=source_system,
            resource_type=resource_type,
            fhir_id=fhir_id,
            fhir_version=fhir_version,
            omop_table=omop_table,
            omop_id=omop_id,
            spec_name=spec_name,
            spec_version=spec_version,
            status="active",
            run_id=self.run.id,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def record_lineage(
        self,
        omop_table: str,
        omop_id: int,
        raw_resource: RawResource,
        spec_name: Optional[str],
        spec_version: Optional[str],
    ) -> Lineage:
        """Row-level lineage from OMOP row to source resource (FR-093, DR-6).

        Creates a Lineage record linking the OMOP row to the source resource,
        mapping spec version, and run. Brings lineage forward so every CDM
        row can be traced to its origin.
        """
        lineage = Lineage(
            omop_table=omop_table,
            omop_id=omop_id,
            source_system=raw_resource.source_system,
            resource_type=raw_resource.resource_type,
            fhir_id=raw_resource.fhir_id or "",
            fhir_version=raw_resource.resource_json.get("meta", {}).get("versionId", "R4") if isinstance(raw_resource.resource_json, dict) else "R4",
            spec_name=spec_name,
            spec_version=spec_version,
            run_id=self.run.id,
        )
        self.db.add(lineage)
        await self.db.flush()
        return lineage

    async def retire_resource(
        self,
        source_system: str,
        resource_type: str,
        fhir_id: str,
        fhir_version: str,
        omop_table: str,
    ) -> int:
        """Mark crosswalk entries retired when a source resource is deleted
        or superseded (FR-017, FR-074). Returns number of rows retired."""
        result = await self.db.execute(
            select(Crosswalk).where(
                Crosswalk.source_system == source_system,
                Crosswalk.resource_type == resource_type,
                Crosswalk.fhir_id == fhir_id,
                Crosswalk.fhir_version == fhir_version,
                Crosswalk.omop_table == omop_table,
                Crosswalk.status == "active",
            )
        )
        entries = result.scalars().all()
        for entry in entries:
            entry.status = "retired"
            entry.run_id = self.run.id
        await self.db.flush()
        return len(entries)

    async def get_crosswalk(
        self,
        source_system: str,
        resource_type: str,
        fhir_id: str,
        fhir_version: str,
        omop_table: str,
    ) -> Optional[Crosswalk]:
        result = await self.db.execute(
            select(Crosswalk).where(
                Crosswalk.source_system == source_system,
                Crosswalk.resource_type == resource_type,
                Crosswalk.fhir_id == fhir_id,
                Crosswalk.fhir_version == fhir_version,
                Crosswalk.omop_table == omop_table,
                Crosswalk.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def generate_omop_id(self, table: str) -> int:
        """Generate a unique OMOP surrogate key across runs and workers
        (FR-071). Uses a UUID-derived high bucket plus a per-table sequence."""
        shard = int(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.run.run_id}:{table}").int % 100000)
        result = await self.db.execute(
            select(Crosswalk.omop_id).where(Crosswalk.omop_table == table).order_by(Crosswalk.omop_id.desc()).limit(1)
        )
        max_id = result.scalar_one_or_none() or 0
        next_id = max_id + 1
        return shard * 1000000 + next_id

    async def commit(self) -> None:
        await self.db.commit()


async def create_run(db: AsyncSession, project: str, run_id: str) -> Run:
    run = Run(run_id=run_id, project=project, status="running", rows_read=0, rows_mapped=0, rows_rejected=0)
    db.add(run)
    await db.flush()
    await db.commit()
    await db.refresh(run)
    return run


async def complete_run(
    db: AsyncSession,
    run: Run,
    status: str,
    rows_read: int = 0,
    rows_mapped: int = 0,
    rows_rejected: int = 0,
    error: Optional[str] = None,
) -> Run:
    run.status = status
    run.completed_at = _now()
    run.rows_read = rows_read
    run.rows_mapped = rows_mapped
    run.rows_rejected = rows_rejected
    run.error = error
    await db.commit()
    await db.refresh(run)
    return run
