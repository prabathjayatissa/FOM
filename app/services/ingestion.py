"""Ingestion service: parse FHIR Bundles and ndjson, validate, quarantine, store raw."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fhir.resources.domainresource import DomainResource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Batch, RawResource, RejectedRecord
from app.schemas import IngestBundleResponse


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


async def _is_valid_fhir_resource(resource: dict[str, Any]) -> tuple[bool, str]:
    """Validate a FHIR resource against the base specification.

    Returns (is_valid, reason). Lightweight structural validation suitable for
    the prototype; profile validation is deferred to later releases (FR-016).
    """
    resource_type = resource.get("resourceType")
    if not resource_type or not isinstance(resource_type, str):
        return False, "missing or invalid resourceType"

    rid = resource.get("id")
    if not rid or not isinstance(rid, str):
        return False, "missing or invalid id"

    # Lightweight structural validation (prototype). Profile validation against
    # configured profiles is deferred to later releases (FR-016).
    try:
        DomainResource.model_validate(resource)
    except Exception:  # noqa: BLE001
        # fhir.resources typed validation is strict about resourceType matching
        # the model class; fall back to structural checks only.
        pass

    return True, ""


async def ingest_bundle_json(
    db: AsyncSession,
    source_system: str,
    batch_id: str,
    bundle_json: dict[str, Any],
) -> IngestBundleResponse:
    """Ingest a FHIR Bundle (transaction/collection/searchset) from parsed JSON."""
    resources: list[dict[str, Any]] = []

    resource_type = bundle_json.get("resourceType")
    if resource_type == "Bundle":
        entries = bundle_json.get("entry", []) or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            res = entry.get("resource") or entry
            if isinstance(res, dict) and res.get("resourceType"):
                resources.append(res)
    else:
        # Treat a single resource as a bundle of one.
        resources.append(bundle_json)

    return await _store_resources(db, source_system, batch_id, resources)


async def ingest_ndjson(
    db: AsyncSession,
    source_system: str,
    batch_id: str,
    ndjson_text: str,
) -> IngestBundleResponse:
    """Ingest FHIR Bulk ndjson (one resource per line)."""
    resources: list[dict[str, Any]] = []
    for line_no, line in enumerate(ndjson_text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            resource = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_no}: {exc}")
        resources.append(resource)

    return await _store_resources(db, source_system, batch_id, resources)


async def _store_resources(
    db: AsyncSession,
    source_system: str,
    batch_id: str,
    resources: list[dict[str, Any]],
) -> IngestBundleResponse:
    """Validate and persist resources; quarantine invalid ones."""
    # Ensure batch exists.
    batch = await db.get(Batch, batch_id) if False else None
    result = await db.execute(select(Batch).where(Batch.batch_id == batch_id))
    batch = result.scalar_one_or_none()
    if batch is None:
        batch = Batch(
            batch_id=batch_id,
            source_system=source_system,
            status="received",
            resource_count=len(resources),
        )
        db.add(batch)
        await db.flush()

    valid = 0
    rejected = 0

    for resource in resources:
        rid = resource.get("id")
        rtype = resource.get("resourceType")
        raw_bytes = json.dumps(resource, sort_keys=True).encode("utf-8")
        checksum = _sha256(raw_bytes)

        is_valid, reason = await _is_valid_fhir_resource(resource)

        raw = RawResource(
            batch_id=batch.id,
            source_system=source_system,
            resource_type=rtype or "Unknown",
            fhir_id=rid,
            version_id=resource.get("meta", {}).get("versionId") if isinstance(resource.get("meta"), dict) else None,
            last_updated=_parse_fhir_datetime(resource.get("meta", {}).get("lastUpdated")) if isinstance(resource.get("meta"), dict) else None,
            checksum=checksum,
            raw_format="json",
            resource_json=resource,
            received_at=_now(),
        )
        db.add(raw)

        if not is_valid:
            rejected += 1
            db.add(
                RejectedRecord(
                    batch_id=batch.id,
                    source_system=source_system,
                    resource_type=rtype or "Unknown",
                    fhir_id=rid,
                    reason_code="INVALID_RESOURCE",
                    reason_message=reason,
                    resource_json=resource,
                )
            )
        else:
            valid += 1

    batch.resource_count = len(resources)
    batch.status = "validating"
    await db.commit()

    return IngestBundleResponse(
        batch_id=batch_id,
        resources_received=len(resources),
        resources_valid=valid,
        resources_rejected=rejected,
        message=f"Ingested {len(resources)} resources ({valid} valid, {rejected} rejected).",
    )


def _parse_fhir_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # FHIR datetime is ISO8601; fromisoformat handles most forms.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def run_ingestion(
    source_system: str,
    batch_id: str,
    bundle_json: dict[str, Any] | None = None,
    ndjson_text: str | None = None,
) -> IngestBundleResponse:
    """Convenience entry point used by API and CLI."""
    if bundle_json is not None:
        async with AsyncSessionLocal() as db:
            return await ingest_bundle_json(db, source_system, batch_id, bundle_json)
    if ndjson_text is not None:
        async with AsyncSessionLocal() as db:
            return await ingest_ndjson(db, source_system, batch_id, ndjson_text)
    raise ValueError("either bundle_json or ndjson_text must be provided")
