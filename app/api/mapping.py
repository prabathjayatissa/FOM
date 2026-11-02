"""Mapping endpoints: spec CRUD, test mode, apply mapping (FR-030 to FR-036, FR-038)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import MappingSpec
from app.schemas import MappingSpecCreate, MappingSpecOut, MappingTestRequest, MappingTestResponse
from app.services.mapping_engine import (
    generate_omop_rows,
    get_active_spec_for_resource,
    parse_spec,
)

router = APIRouter()


@router.post("/specs", response_model=MappingSpecOut, summary="Create a mapping specification")
async def create_spec(spec: MappingSpecCreate) -> Any:
    async with AsyncSessionLocal() as db:
        exists = await db.execute(
            select(MappingSpec).where(
                MappingSpec.name == spec.name,
                MappingSpec.version == spec.version,
            )
        )
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="mapping spec name/version already exists")
        row = MappingSpec(
            name=spec.name,
            version=spec.version,
            resource_type=spec.resource_type,
            spec_json=spec.spec_json,
            is_active=False,
            created_by="api-user",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


@router.get("/specs", response_model=list[MappingSpecOut], summary="List mapping specifications")
async def list_specs(resource_type: str | None = None) -> Any:
    async with AsyncSessionLocal() as db:
        query = select(MappingSpec)
        if resource_type:
            query = query.where(MappingSpec.resource_type == resource_type)
        result = await db.execute(query)
        return result.scalars().all()


@router.post("/specs/{spec_id}/activate", response_model=MappingSpecOut, summary="Activate a mapping spec")
async def activate_spec(spec_id: str) -> Any:
    async with AsyncSessionLocal() as db:
        # Deactivate all specs for the same resource type
        target = await db.get(MappingSpec, spec_id)
        if not target:
            raise HTTPException(status_code=404, detail="mapping spec not found")
        await db.execute(
            select(MappingSpec)  # placeholder to load type
        )
        # Deactivate siblings
        result = await db.execute(select(MappingSpec).where(MappingSpec.resource_type == target.resource_type))
        for sib in result.scalars().all():
            sib.is_active = False
        target.is_active = True
        await db.commit()
        await db.refresh(target)
        return target


@router.post("/test", response_model=MappingTestResponse, summary="Test a mapping against sample resources (FR-036)")
async def test_mapping(req: MappingTestRequest) -> Any:
    """Run a mapping rule against sample resources and show generated OMOP rows without writing to CDM."""
    try:
        spec_def = parse_spec(req.spec_json)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid mapping spec: {exc}")

    rows = generate_omop_rows(spec_def, req.sample_resources)
    warnings: list[str] = []
    unmapped = [r for r in rows if r.get("concept_id") == 0]
    if unmapped:
        warnings.append(f"{len(unmapped)} row(s) contain unmapped concept_id 0")

    return MappingTestResponse(
        rows_generated=len(rows),
        omop_rows=rows,
        warnings=warnings,
    )


@router.post("/apply/{resource_type}", summary="Apply active mapping spec to stored resources (prototype)")
async def apply_mapping(resource_type: str, batch_id: str | None = None) -> Any:
    """Apply the active mapping spec for a resource type to staged resources.

    Release 0.1 generates OMOP rows in memory; full CDM loader integration in 0.5/1.0.
    """
    async with AsyncSessionLocal() as db:
        spec_def = await get_active_spec_for_resource(db, resource_type)
        if not spec_def:
            raise HTTPException(status_code=404, detail=f"no active mapping spec for {resource_type}")

        query = select(__import__("app.models", fromlist=["RawResource"]).RawResource).where(
            __import__("app.models", fromlist=["RawResource"]).RawResource.resource_type == resource_type
        )
        if batch_id:
            from app.models import Batch
            br = await db.execute(select(Batch).where(Batch.batch_id == batch_id))
            batch = br.scalar_one_or_none()
            if batch:
                query = query.where(__import__("app.models", fromlist=["RawResource"]).RawResource.batch_id == batch.id)
        result = await db.execute(query.limit(1000))
        resources = [r.resource_json for r in result.scalars().all()]

    rows = generate_omop_rows(spec_def, resources)
    return {"resource_type": resource_type, "rows_generated": len(rows), "omop_rows": rows}
