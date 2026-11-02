"""Run endpoints: run lifecycle, progress, reports (FR-096, FR-103)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Run
from app.schemas import RunOut, RunSummary
from app.services.loader import complete_run, create_run

router = APIRouter()


@router.post("/", response_model=RunOut, summary="Create a new run")
async def create_run_endpoint(project: str, run_id: str | None = None) -> Any:
    import uuid as _uuid
    rid = run_id or str(_uuid.uuid4())
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(Run).where(Run.run_id == rid))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="run_id already exists")
        run = await create_run(db, project, rid)
        return run


@router.get("/", response_model=list[RunOut], summary="List runs")
async def list_runs(project: str | None = None) -> Any:
    async with AsyncSessionLocal() as db:
        query = select(Run).order_by(Run.started_at.desc())
        if project:
            query = query.where(Run.project == project)
        result = await db.execute(query)
        return result.scalars().all()


@router.get("/{run_id}", response_model=RunOut, summary="Get a run")
async def get_run(run_id: str) -> Any:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Run).where(Run.run_id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return run


@router.post("/{run_id}/complete", response_model=RunOut, summary="Mark a run complete (CLI/internal)")
async def complete_run_endpoint(
    run_id: str,
    status: str = "completed",
    rows_read: int = 0,
    rows_mapped: int = 0,
    rows_rejected: int = 0,
    error: str | None = None,
) -> Any:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Run).where(Run.run_id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        run = await complete_run(db, run, status, rows_read, rows_mapped, rows_rejected, error)
        return run


@router.get("/{run_id}/summary", response_model=RunSummary, summary="Run summary / report (FR-096)")
async def run_summary(run_id: str) -> Any:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Run).where(Run.run_id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        duration_ms = None
        if run.completed_at and run.started_at:
            duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
        return RunSummary(
            run_id=run.run_id,
            status=run.status,
            rows_read=run.rows_read,
            rows_mapped=run.rows_mapped,
            rows_rejected=run.rows_rejected,
            duration_ms=duration_ms,
        )
