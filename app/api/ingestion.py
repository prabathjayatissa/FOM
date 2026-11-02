"""Ingestion endpoints: FHIR Bundle and ndjson upload/ingest (FR-010, FR-011, FR-015, FR-016)."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.schemas import IngestBundleResponse
from app.services.ingestion import run_ingestion

router = APIRouter()


@router.post("/bundle", response_model=IngestBundleResponse, summary="Ingest a FHIR Bundle JSON")
async def ingest_bundle(
    background_tasks: BackgroundTasks,
    source_system: str = Form(..., description="Source system identifier"),
    batch_id: str = Form(..., description="Batch identifier"),
    file: UploadFile = File(..., description="FHIR Bundle JSON file"),
) -> Any:
    """Upload and ingest a FHIR Bundle (transaction/collection/searchset) from a JSON file."""
    if file.content_type not in ("application/json", "text/json", None):
        raise HTTPException(status_code=400, detail="file must be application/json")

    content = await file.read()
    try:
        bundle_json = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")

    return await run_ingestion(source_system=source_system, batch_id=batch_id, bundle_json=bundle_json)


@router.post("/ndjson", response_model=IngestBundleResponse, summary="Ingest FHIR Bulk ndjson")
async def ingest_ndjson(
    source_system: str = Form(..., description="Source system identifier"),
    batch_id: str = Form(..., description="Batch identifier"),
    file: UploadFile = File(..., description="ndjson file (one FHIR resource per line)"),
) -> Any:
    """Upload and ingest FHIR Bulk Data ndjson export."""
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"file must be UTF-8: {exc}")

    return await run_ingestion(source_system=source_system, batch_id=batch_id, ndjson_text=text)


@router.post("/json", response_model=IngestBundleResponse, summary="Ingest a single FHIR resource JSON")
async def ingest_single(
    source_system: str = Form(..., description="Source system identifier"),
    batch_id: str = Form(..., description="Batch identifier"),
    resource: dict[str, Any] = Form(..., description="FHIR resource JSON object"),
) -> Any:
    """Ingest a single FHIR resource (useful for REST-pull staging)."""
    return await run_ingestion(source_system=source_system, batch_id=batch_id, bundle_json=resource)


# json imported above
import json
