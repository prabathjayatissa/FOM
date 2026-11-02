"""FOM FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ingestion, mapping, quality, runs
from app.config import settings
from app.database import Base, engine


def create_app() -> FastAPI:
    app = FastAPI(
        title="FOM - FHIR to OMOP CDM Mapper",
        description="Universal FHIR to OMOP CDM Mapping Application (Release 0.1 Prototype)",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(ingestion.router, prefix="/api/v1/ingestion", tags=["Ingestion"])
    app.include_router(mapping.router, prefix="/api/v1/mapping", tags=["Mapping"])
    app.include_router(runs.router, prefix="/api/v1/runs", tags=["Runs"])
    app.include_router(quality.router, prefix="/api/v1/quality", tags=["Quality"])

    @app.on_event("startup")
    async def startup():
        # Note: in production use Alembic migrations. Here we create tables
        # automatically for the prototype so it runs out of the box.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @app.get("/health", tags=["System"])
    async def health():
        return {"status": "ok", "version": "0.1.0", "app_env": settings.app_env}

    return app


app = create_app()
