# FOM — Universal FHIR to OMOP CDM Mapper

**Working name:** FHIR2OMOP Mapper (FOM)
**Version:** 0.1.0 (Release 0.1 Prototype) | October 2026
**Basis:** Software Requirements Specification (SRS) v1.0 Draft, IEEE 29148 structure

FOM ingests clinical data expressed as HL7 FHIR resources, transforms it according to configurable, versioned mapping specifications and terminology maps, and loads it into an OMOP Common Data Model (CDM) database. It then validates data quality and tracks lineage.

> **Release 0.1 scope:** Bundle and ndjson ingestion, Patient and Encounter mapping, PostgreSQL target, CLI, REST API (OpenAPI 3), terminology stub, structural quality checks, loader/crosswalk. See the [Release Plan](#release-plan) for what lands in 0.5 / 1.0.

---

## Table of Contents

1. [Features](#features)
2. [Architecture Overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [Quick Start with Docker](#quick-start-with-docker)
5. [Local Development Setup](#local-development-setup)
6. [Command-Line Interface (CLI)](#command-line-interface-cli)
7. [REST API](#rest-api)
8. [FHIR Ingestion](#fhir-ingestion)
9. [Declarative Mapping Specifications](#declarative-mapping-specifications)
10. [Configuration](#configuration)
11. [Running Tests](#running-tests)
12. [Project Structure](#project-structure)
13. [Data Model](#data-model)
14. [Release Plan](#release-plan)
15. [Requirements Coverage](#requirements-coverage)
16. [Limitations & Known Issues](#limitations--known-issues)
17. [License & Compliance](#license--compliance)

---

## Features

| Category | Capability (Release 0.1) | SRS Ref |
|----------|--------------------------|---------|
| **Ingestion** | FHIR Bundle (transaction/collection/searchset) JSON upload; FHIR Bulk ndjson upload; single-resource JSON | FR-010, FR-011, FR-015, FR-016 |
| **Validation** | Structural FHIR validation; invalid resources quarantined with reason codes | FR-016, FR-026 |
| **Mapping** | Declarative JSON mapping specs; FHIRPath-ish expressions; domain routing; `concept_id 0` fallback | FR-030 to FR-038 |
| **Terminology** | FHIR code-system → OMOP vocabulary translation; "Maps to" resolution; unmapped-code worklist ranked by frequency | FR-051, FR-052, FR-058, FR-059 |
| **Loader** | Persistent crosswalk (FHIR ↔ OMOP); idempotent upsert; OMOP surrogate key generation | FR-070 to FR-074 |
| **Quality** | Structural checks (dates, required fields); source-to-OMOP reconciliation | FR-090, FR-092 |
| **Operations** | Run lifecycle (create/list/summary); REST API (OpenAPI 3); CLI for automation | FR-096, FR-101, FR-102 |
| **Storage** | PostgreSQL operational store (raw, staging, crosswalk, runs, rejected) | DR-1 to DR-6 |

**Out of scope (release 1):** reverse OMOP→FHIR, ATLAS/HADES cohorts, NLP beyond NOTE storage, operating a FHIR server.

---

## Architecture Overview

```
FHIR sources (files, uploads)  -->  Ingestion service  -->  Raw store
                                                          -->  Staging service
                                                          -->  Mapping engine  -->  Loader  -->  OMOP CDM
                                                          -->  Terminology service
                                                          -->  Quality service
Web UI / REST API / CLI  -->  Orchestrator & scheduler
```

**Components**
- **Ingestion service** — source adapters, validation, quarantine, raw store
- **Staging service** — flattening and normalization (prototype: raw JSON passed through)
- **Mapping engine** — declarative rule interpreter, FHIRPath-ish expressions, domain routing
- **Terminology service** — vocabulary lookup, local maps, unmapped worklist
- **Loader** — crosswalk, idempotent writes, deletes, surrogate keys
- **Quality service** — structural checks, reconciliation
- **API gateway & Web UI** — FastAPI REST (OpenAPI 3); CLI for automation

**Indicative tech stack:** Python backend, PostgreSQL operational data, single-page Web UI (planned).

---

## Why OMOP

OMOP CDM (Observational Medical Outcomes Partnership Common Data Model) is the de facto standard for observational health data analytics, maintained by OHDSI (Observational Health Data Sciences and Informatics). Mapping FHIR to OMOP unlocks:

- **Interoperability:** Convert heterogeneous FHIR resources from multiple EHR systems into a single, analysis-ready schema.
- **Portable analytics:** Run OHDSI tools (ATLAS, Achilles, HADES, Data Quality Dashboard) against your data without site-specific ETL rework.
- **Standardized semantics:** Source codes (ICD-10, SNOMED, LOINC, RxNorm, local codes) are resolved to standard concepts via OHDSI vocabularies.
- **Derived insights:** Build observation periods, condition/drug/dose eras, and cost tables out of the box.
- **Governance & audit:** Row-level lineage tracks every OMOP row back to its source FHIR resource, rule version, and run.

FOM bridges the gap between FHIR-native source systems and the OMOP analytical world, letting sites load once and analyze with the full OHDSI toolchain.

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (reference target; SQLite used for tests)
- Docker & Docker Compose (optional, recommended)
- `pip` / `venv`

---

## Quick Start with Docker

### 1. Clone / enter the project

```bash
cd /Users/prabathjayathissa/Documents/Claude/fom-mapper
```

### 2. Start the stack

```bash
docker-compose up -d --build
```

This starts:
- `db` — PostgreSQL 16 on host port **5433**
- `app` — FOM FastAPI on host port **8000**

### 3. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","app_env":"dev"}

curl http://localhost:8000/docs   # Swagger UI (OpenAPI 3)
```

### 4. Ingest a FHIR Bundle

```bash
curl -X POST http://localhost:8000/api/v1/ingestion/bundle \
  -F "source_system=demo" \
  -F "batch_id=batch-1" \
  -F "file=@bundle.json;type=application/json"
```

Example `bundle.json`:
```json
{
  "resourceType": "Bundle",
  "type": "collection",
  "entry": [
    {
      "resource": {
        "resourceType": "Patient",
        "id": "pat-1",
        "gender": "female",
        "birthDate": "1970-05-21",
        "meta": { "status": "active", "versionId": "1" }
      }
    }
  ]
}
```

Expected response:
```json
{
  "batch_id": "batch-1",
  "resources_received": 1,
  "resources_valid": 1,
  "resources_rejected": 0,
  "message": "Ingested 1 resources (1 valid, 0 rejected)."
}
```

### 5. Stop the stack

```bash
docker-compose down
```

---

## Local Development Setup

### 1. Create a virtual environment

```bash
cd /Users/prabathjayathissa/Documents/Claude/fom-mapper
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment

Copy settings as needed. `app/config.py` reads `FOM_`-prefixed environment variables (and an optional `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `dev` | Deployment environment |
| `LOG_LEVEL` | `info` | Logging level |
| `DATABASE_URL` | `postgresql+asyncpg://fom:fom@localhost:5432/fom` | Async DB connection string |
| `DATABASE_ECHO` | `false` | Echo SQL statements |
| `RAW_STORE_PATH` | `./data/raw` | Raw file store path |
| `MAX_UPLOAD_MB` | `100` | Max upload size in MB |
| `AUTH_ENABLED` | `false` | Auth toggle (release 1) |
| `SECRET_KEY` | `dev-secret-change-me` | Secret for dev mode |

Create a `.env` file if you want to override defaults:

```ini
DATABASE_URL=postgresql+asyncpg://fom:fom@localhost:5433/fom
APP_ENV=dev
LOG_LEVEL=debug
```

### 3. Run the API server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The app creates its operational tables on startup via SQLAlchemy metadata. For production, manage schema with Alembic migrations (`alembic/` directory included).

### 4. Ingest via CLI

```bash
# Bundle
python -m app.cli.main ingest-bundle --source demo --batch batch-1 --file bundle.json

# ndjson (FHIR Bulk)
python -m app.cli.main ingest-ndjson --source demo --batch batch-2 --file export.ndjson
```

### 5. Run tests

```bash
pytest tests/ -v
# 17 passed
```

---

## Command-Line Interface (CLI)

The CLI (FR-102) supports running pipelines in automation:

```bash
python -m app.cli.main --help
```

### Commands

| Command | Description |
|---------|-------------|
| `ingest-bundle` | Ingest a FHIR Bundle JSON file |
| `ingest-ndjson` | Ingest a FHIR Bulk ndjson file |
| `run-pipeline` | Run a mapping pipeline over staged resources (Patient & Encounter) |
| `spec-add` | Register a declarative mapping spec from JSON |
| `spec-activate` | Activate a mapping spec by name and version |
| `health` | Show service health |

### Examples

```bash
# Ingest a Bundle
python -m app.cli.main ingest-bundle \
  --source hospital-a \
  --batch batch-2026-10-23 \
  --file ./data/bundle.json

# Ingest ndjson
python -m app.cli.main ingest-ndjson \
  --source hospital-a \
  --batch batch-ndjson-1 \
  --file ./data/export.ndjson

# Run mapping pipeline (default project)
python -m app.cli.main run-pipeline --project demo --source demo

# Register a mapping spec
python -m app.cli.main spec-add \
  --name "Patient to PERSON" \
  --version 1.0.0 \
  --resource-type Patient \
  --file app/mapping/patient_to_person.json

# Activate it
python -m app.cli.main spec-activate "Patient to PERSON" 1.0.0
```

---

## REST API

All functions are exposed through a documented REST API (OpenAPI 3) (FR-101, IR-9).

**Base path:** `/api/v1`

**Interactive docs:** `http://localhost:8000/docs` (Swagger) or `http://localhost:8000/redoc`

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health |
| `POST` | `/api/v1/ingestion/bundle` | Ingest FHIR Bundle JSON (multipart) |
| `POST` | `/api/v1/ingestion/ndjson` | Ingest FHIR Bulk ndjson (multipart) |
| `POST` | `/api/v1/ingestion/json` | Ingest a single FHIR resource JSON |
| `GET` | `/api/v1/mapping/specs` | List mapping specifications |
| `POST` | `/api/v1/mapping/specs` | Create a mapping specification |
| `POST` | `/api/v1/mapping/specs/{spec_id}/activate` | Activate a mapping spec |
| `POST` | `/api/v1/mapping/test` | Test a mapping against sample resources (no CDM write) |
| `POST` | `/api/v1/mapping/apply/{resource_type}` | Apply active mapping to stored resources |
| `POST` | `/api/v1/runs/` | Create a new run |
| `GET` | `/api/v1/runs/` | List runs |
| `GET` | `/api/v1/runs/{run_id}` | Get a run |
| `POST` | `/api/v1/runs/{run_id}/complete` | Mark a run complete |
| `GET` | `/api/v1/runs/{run_id}/summary` | Run summary/report (rows read/mapped/rejected, duration) |
| `POST` | `/api/v1/quality/checks/resource` | Structural checks on a FHIR resource |
| `GET` | `/api/v1/quality/reconciliation/{batch_id}` | Reconcile source vs OMOP counts |
| `GET` | `/api/v1/quality/terminology/coverage` | Terminology coverage per domain |

### Example: test a mapping without writing to CDM (FR-036)

```bash
curl -X POST http://localhost:8000/api/v1/mapping/test \
  -H "Content-Type: application/json" \
  -d '{
    "spec_json": {
      "name": "Test Patient",
      "resource_type": "Patient",
      "rules": [{
        "targetTable": "PERSON",
        "columns": {
          "person_id": "uuid",
          "person_source_value": "extract.id",
          "gender_concept_id": "lookup.gender.gender"
        }
      }]
    },
    "sample_resources": [
      { "resourceType": "Patient", "id": "p1", "gender": "male" }
    ]
  }'
```

---

## FHIR Ingestion

### Supported formats (IR-1 to IR-3)

| Format | Details |
|--------|---------|
| FHIR Bundle JSON | `transaction`, `collection`, `searchset` types; uploaded as `application/json` |
| FHIR Bulk ndjson | One FHIR resource per line; blank lines skipped |
| Single resource JSON | Any FHIR resource treated as a bundle of one |

### What is stored (FR-015, DR-1)

Each received resource is stored unchanged with:
- `resource_type`, `fhir_id`, `version_id`, `last_updated`
- `source_system`, `batch_id`
- `checksum` (SHA-256 of canonical JSON)
- `raw_format` (json / ndjson / xml)
- Full `resource_json` (unchanged resource)

### Validation & quarantine (FR-016, FR-026)

- Resources are validated against the base FHIR specification.
- Invalid resources are placed in `rejected_records` with `reason_code` and `reason_message`.
- Resources matching exclusion status rules (e.g. `entered-in-error`) are excluded and logged.

### Incremental extraction (planned)

FR-013 (`_since`, `meta.lastUpdated`, change feed) and FR-014 (Kafka/AMQP adapters) are planned for later releases.

---

## Declarative Mapping Specifications

Mapping specs are versioned JSON (YAML supported in the language design; JSON shipped in 0.1) files that describe how a source FHIR resource maps to OMOP tables (FR-030, FR-035, FR-040).

### Shipped defaults (FR-038, Release 0.1)

| File | FHIR resource | OMOP target |
|------|---------------|-------------|
| `app/mapping/patient_to_person.json` | Patient | PERSON |
| `app/mapping/encounter_to_visit_occurrence.json` | Encounter | VISIT_OCCURRENCE |

### Spec format

```json
{
  "name": "Patient to PERSON",
  "version": "1.0.0",
  "resource_type": "Patient",
  "rules": [
    {
      "targetTable": "PERSON",
      "filter": "meta.status != 'entered-in-error'",
      "columns": {
        "person_id": "uuid",
        "gender_concept_id": "lookup.gender.gender",
        "year_of_birth": "extract.birthDate",
        "person_source_value": "extract.id"
      },
      "defaults": {
        "year_of_birth": "const:0"
      }
    }
  ]
}
```

### Expression language (prototype)

| Form | Example | Meaning |
|------|---------|---------|
| `const:<value>` | `const:0` | Literal value |
| `extract.<path>` | `extract.birthDate` | Dotted-path extraction from the FHIR resource; supports `array[0]` |
| `lookup.<table>.<key>` | `lookup.gender.gender` | Terminology / value-set lookup |
| `now` | `now` | Current UTC timestamp |
| `uuid` | `uuid` | Generate a UUID |

### Filter expressions

- `path == 'value'` — equality
- `path != 'value'` — inequality
- Bare path — truthiness

### Registering and activating specs

```bash
# Register
python -m app.cli.main spec-add --name "Condition to CONDITION_OCCURRENCE" --version 1.0.0 --resource-type Condition --file my_spec.json

# Activate (deactivates other specs for the same resource type)
python -m app.cli.main spec-activate "Condition to CONDITION_OCCURRENCE" 1.0.0
```

Or via API:
```bash
POST /api/v1/mapping/specs          # create
POST /api/v1/mapping/specs/{id}/activate  # activate
```

---

## Configuration

`app/config.py` uses Pydantic Settings with `FOM_`-prefixed environment variables and an optional `.env` file.

See the [Local Development Setup](#local-development-setup) table for all variables.

Secrets must never be stored in plain-text configuration (NFR-021); for production, inject `DATABASE_URL` and `SECRET_KEY` via a secret manager or environment.

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=term-missing
```

Test files:
- `tests/test_mapping_engine.py` — mapping spec parsing, expression evaluation, OMOP row generation
- `tests/test_terminology.py` — code-system translation, concept resolution, unmapped worklist
- `tests/test_ingestion.py` — Bundle/ndjson parsing, quarantine

17 tests pass in Release 0.1.

---

## Project Structure

```
fom-mapper/
├── pyproject.toml          # Project metadata & dependencies
├── Dockerfile              # Container image
├── docker-compose.yml      # Local stack (Postgres + app)
├── alembic.ini             # Alembic migration config
├── alembic/env.py          # Alembic environment
├── alembic/versions/       # Migration revisions
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app, OpenAPI, health, startup
│   ├── config.py           # Pydantic settings
│   ├── database.py         # Async engine, session, Base
│   ├── models/
│   │   └── __init__.py     # Batch, RawResource, StagingResource, Crosswalk,
│   │                       # MappingSpec, Run, RejectedRecord
│   ├── schemas/
│   │   └── __init__.py     # Pydantic API contracts
│   ├── services/
│   │   ├── ingestion.py    # Bundle/ndjson parse, validate, quarantine
│   │   ├── mapping_engine.py # Spec interpreter, expressions, domain routing
│   │   ├── loader.py       # Crosswalk, idempotent upsert, OMOP ids
│   │   ├── terminology.py  # Vocabulary lookup, worklist
│   │   └── quality.py      # Structural checks, reconciliation
│   ├── api/
│   │   ├── __init__.py
│   │   ├── ingestion.py    # /ingestion/* endpoints
│   │   ├── mapping.py      # /mapping/* endpoints
│   │   ├── runs.py         # /runs/* endpoints
│   │   └── quality.py      # /quality/* endpoints
│   ├── cli/
│   │   └── main.py         # Typer CLI
│   └── mapping/
│       ├── patient_to_person.json
│       └── encounter_to_visit_occurrence.json
├── tests/
│   ├── conftest.py
│   ├── test_mapping_engine.py
│   ├── test_terminology.py
│   ├── test_ingestion.py
│   └── data/
│       └── openmrs/           # OpenMRS FHIR test dataset (R4)
│           ├── patients/
│           ├── encounters/
│           └── observations/
└── data/                      # Raw store at runtime (created on first ingest)
```

---

## Data Model (Operational Store)

| Table | Purpose | SRS Ref |
|-------|---------|---------|
| `batches` | Ingestion batch grouping | DR-5 |
| `raw_resources` | Unchanged FHIR resources + metadata | DR-1, FR-015 |
| `staging_resources` | Flattened typed projections | DR-2 |
| `rejected_records` | Quarantined invalid resources + reason codes | DR-5, FR-016 |
| `crosswalk` | (source, type, fhir id) → (OMOP table, OMOP id) | DR-3, FR-070 |
| `mapping_specs` | Versioned declarative mapping specs | DR-4, FR-002 |
| `runs` | ETL run records + metrics | DR-5, FR-040 |

Row-level lineage from OMOP rows to source resources (FR-093, DR-6) is captured through `crosswalk.run_id` → `runs`, and `crosswalk.<source,type,id>` → `raw_resources`. A dedicated lineage table is formalized in Release 1.0.

---

## Release Plan

| Release | Content | SRS Section 10 |
|---------|---------|----------------|
| **0.1 Prototype** (current) | Bundle & ndjson ingestion, Patient & Encounter mapping, PostgreSQL target, CLI | 0.1 |
| **0.5 Beta** | Observation (prioritized), then Condition, Procedure, Medication, and other core clinical resources; terminology service, crosswalk & incremental load, basic UI, structural checks | 0.5 |
| **1.0** | All Must requirements, derived tables (OBSERVATION_PERIOD, CONDITION/DRUG/DOSE_ERA), DQD integration, RBAC & audit, run reports, documentation | 1.0 |
| **1.x** | Mapping editor improvements, SQL Server & further platforms, profile pack library, mapping suggestions, performance scaling | 1.x |

---

## Requirements Coverage (Release 0.1)

| ID | Requirement | Status |
|----|-------------|--------|
| FR-010 | Ingest FHIR Bundles from files/uploads | ✅ |
| FR-011 | Ingest FHIR Bulk ndjson | ✅ |
| FR-012 | Read from FHIR REST API | Planned (0.5) |
| FR-013 | Incremental extraction (_since, lastUpdated) | Planned (0.5) |
| FR-014 | Message-queue adapters | Planned (1.x) |
| FR-015 | Store resources unchanged with metadata | ✅ |
| FR-016 | Validate & quarantine invalid resources | ✅ |
| FR-017 | Detect deletions / superseded versions | Planned (0.5) |
| FR-018 | Multiple FHIR sources per project | Planned (0.5) |
| FR-030 to FR-038 | Mapping language & engine (Patient, Encounter defaults) | ✅ (partial) |
| FR-051, FR-052, FR-058, FR-059 | Terminology resolution, concept_id 0, worklist | ✅ (stub) |
| FR-070 to FR-074 | Crosswalk, idempotent load, surrogate keys | ✅ |
| FR-090, FR-092 | Structural checks, reconciliation | ✅ |
| FR-096 | Run report | ✅ (summary endpoint) |
| FR-101 | REST API (OpenAPI 3) | ✅ |
| FR-102 | CLI | ✅ |
| NFR-040 | Automated tests | ✅ |

See the SRS for the full requirement list (FR-001 to FR-115, NFR-001 to NFR-052, IR-1 to IR-10, DR-1 to DR-8, CR-1 to CR-5).

---

## Limitations & Known Issues

1. **PostgreSQL only for production-like runs.** Tests use in-memory SQLite; asyncpg connects to PostgreSQL in Docker/local.
2. **Terminology service is a stub.** Athena CSV loading, SOURCE_TO_CONCEPT_MAP, and Usagi import are planned for 0.5/1.0.
3. **No dedicated OMOP CDM table writes yet.** Release 0.1 records crosswalk entries and generates OMOP row dicts; actual CDM table inserts land in 0.5/1.0 (FR-076).
4. **No RBAC/auth enforcement.** Auth models exist (FR-110, FR-111) but are disabled by default in dev (`AUTH_ENABLED=false`).
5. **No scheduling, notifications, or DQD/Achilles integration.** Planned for 1.0 (FR-103, FR-104, FR-093, FR-094).
6. **Ruff lint:** Some FastAPI `Form()`/`File()` defaults trigger B008 false positives; these are ignored in `pyproject.toml`.

---

## License & Compliance

- Open standards for interfaces: FHIR REST, OpenAPI 3, SQL, OAuth 2.0/OIDC (CR-4).
- OMOP vocabularies obtained from Athena per their license terms; some vocabularies require separate licenses (CR-1).
- Personal data processing complies with GDPR and applicable national requirements (CR-5, NFR-020 to NFR-025).
- Source-specific logic resides in configuration, not application code (CR-2).
- Deployable inside a customer network with no mandatory outbound internet access during operation (CR-3).

> This is a prototype (Release 0.1). Review the SRS and run acceptance criteria (Section 9 of the SRS) before production use.
