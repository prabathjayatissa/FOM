"""FOM command-line interface (FR-102)."""


import typer
from rich import print as rprint

from app.database import AsyncSessionLocal
from app.services.ingestion import run_ingestion
from app.services.loader import complete_run, create_run
from app.services.mapping_engine import generate_omop_rows, get_active_spec_for_resource

app = typer.Typer(help="FOM - FHIR to OMOP CDM Mapper CLI (Release 0.1 Prototype)")


@app.command()
def ingest_bundle(
    source_system: str = typer.Option(..., "--source", help="Source system identifier"),
    batch_id: str = typer.Option(..., "--batch", help="Batch identifier"),
    file: str = typer.Option(..., "--file", help="Path to FHIR Bundle JSON file"),
) -> None:
    """Ingest a FHIR Bundle JSON file."""
    import asyncio
    import json

    with open(file, encoding="utf-8") as f:
        bundle_json = json.load(f)

    result = asyncio.run(run_ingestion(source_system=source_system, batch_id=batch_id, bundle_json=bundle_json))
    rprint(f"[green]Ingested {result.resources_received} resources[/green] "
           f"({result.resources_valid} valid, {result.resources_rejected} rejected).")
    rprint(result.message)


@app.command()
def ingest_ndjson(
    source_system: str = typer.Option(..., "--source", help="Source system identifier"),
    batch_id: str = typer.Option(..., "--batch", help="Batch identifier"),
    file: str = typer.Option(..., "--file", help="Path to ndjson file"),
) -> None:
    """Ingest a FHIR Bulk ndjson file."""
    import asyncio

    with open(file, encoding="utf-8") as f:
        text = f.read()

    result = asyncio.run(run_ingestion(source_system=source_system, batch_id=batch_id, ndjson_text=text))
    rprint(f"[green]Ingested {result.resources_received} resources[/green] "
           f"({result.resources_valid} valid, {result.resources_rejected} rejected).")
    rprint(result.message)


@app.command()
def run_pipeline(
    project: str = typer.Option("default", "--project", help="Project name"),
    run_id: str | None = typer.Option(None, "--run-id", help="Run identifier (auto-generated if omitted)"),
    source_system: str = typer.Option("demo", "--source", help="Source system to map"),
    batch_id: str | None = typer.Option(None, "--batch", help="Optional batch to map"),
) -> None:
    """Run a mapping pipeline over staged resources (prototype)."""
    import asyncio

    from sqlalchemy import select

    from app.models import RawResource

    async def _run():
        async with AsyncSessionLocal() as db:
            run = await create_run(db, project, run_id or f"cli-{project}")

            # Map Patient and Encounter using active specs
            total_mapped = 0
            for rtype in ("Patient", "Encounter"):
                spec_def = await get_active_spec_for_resource(db, rtype)
                if not spec_def:
                    continue
                q = select(RawResource).where(RawResource.resource_type == rtype)
                if batch_id:
                    from app.models import Batch
                    br = await db.execute(select(Batch).where(Batch.batch_id == batch_id))
                    batch = br.scalar_one_or_none()
                    if batch:
                        q = q.where(RawResource.batch_id == batch.id)
                res = await db.execute(q.limit(5000))
                resources = [r.resource_json for r in res.scalars().all()]
                rows = generate_omop_rows(spec_def, resources)
                total_mapped += len(rows)
                rprint(f"[cyan]{rtype}: {len(rows)} OMOP row(s) generated[/cyan]")

            await complete_run(db, run, "completed", rows_read=0, rows_mapped=total_mapped, rows_rejected=0)
            rprint(f"[green]Run {run.run_id} completed: {total_mapped} rows mapped[/green]")

    asyncio.run(_run())


@app.command()
def spec_add(
    name: str = typer.Option(..., "--name", help="Mapping spec name"),
    version: str = typer.Option("1.0", "--version", help="Mapping spec version"),
    resource_type: str = typer.Option("Patient", "--resource-type", help="FHIR resource type"),
    file: str = typer.Option(..., "--file", help="Path to mapping spec JSON file"),
) -> None:
    """Register a declarative mapping specification from a JSON file."""
    import asyncio
    import json

    from sqlalchemy import select

    from app.models import MappingSpec

    with open(file, encoding="utf-8") as f:
        spec_json = json.load(f)

    async def _add():
        async with AsyncSessionLocal() as db:
            exists = await db.execute(
                select(MappingSpec).where(MappingSpec.name == name, MappingSpec.version == version)
            )
            if exists.scalar_one_or_none():
                rprint("[yellow]Spec already exists[/yellow]")
                return
            row = MappingSpec(
                name=name,
                version=version,
                resource_type=resource_type,
                spec_json=spec_json,
                is_active=False,
                created_by="cli",
            )
            db.add(row)
            await db.commit()
            rprint(f"[green]Mapping spec {name}@{version} registered[/green]")

    asyncio.run(_add())


@app.command()
def spec_activate(
    name: str,
    version: str,
) -> None:
    """Activate a mapping spec by name and version."""
    import asyncio

    from sqlalchemy import select

    from app.models import MappingSpec

    async def _activate():
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(MappingSpec).where(MappingSpec.name == name, MappingSpec.version == version))
            spec = res.scalar_one_or_none()
            if not spec:
                rprint("[red]Spec not found[/red]")
                return
            # deactivate siblings
            sibs = await db.execute(select(MappingSpec).where(MappingSpec.resource_type == spec.resource_type))
            for s in sibs.scalars().all():
                s.is_active = False
            spec.is_active = True
            await db.commit()
            rprint(f"[green]Activated {name}@{version} for {spec.resource_type}[/green]")

    asyncio.run(_activate())


@app.command()
def health() -> None:
    """Show service health."""
    rprint({"status": "ok", "version": "0.1.0"})


if __name__ == "__main__":
    app()
