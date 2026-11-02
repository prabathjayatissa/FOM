"""Quality endpoints: structural checks, reconciliation, terminology coverage (FR-090 to FR-092)."""

from typing import Any

from fastapi import APIRouter

from app.database import AsyncSessionLocal
from app.services.quality import QualityService

router = APIRouter()


@router.post("/checks/resource", summary="Run structural checks on a FHIR resource (FR-090)")
async def check_resource(resource: dict[str, Any]) -> Any:
    async with AsyncSessionLocal() as db:
        qs = QualityService(db)
        findings = await qs.structural_checks(resource)
        return {"resourceType": resource.get("resourceType"), "findings": findings}


@router.get("/reconciliation/{batch_id}", summary="Reconcile source vs OMOP counts for a batch (FR-092)")
async def reconciliation(batch_id: str) -> Any:
    async with AsyncSessionLocal() as db:
        qs = QualityService(db)
        return await qs.reconciliation_report(batch_id)


@router.get("/terminology/coverage", summary="Terminology coverage per domain (FR-091)")
async def terminology_coverage() -> Any:
    async with AsyncSessionLocal() as db:
        qs = QualityService(db)
        return await qs.terminology_coverage()
