# OpenMRS FHIR Test Dataset

This directory contains sample FHIR R4 resources from an OpenMRS instance,
suitable for testing the FOM ingestion, mapping, and loader pipeline.

## Contents

| Path | Resource | Description |
|------|----------|-------------|
| `patients/patient-001.json` | Patient | Grace Mwangi, female, born 1985-03-15, Nairobi, Kenya |
| `patients/patient-002.json` | Patient | Peter Omondi, male, born 1972-07-22, Kisumu, Kenya |
| `encounters/encounter-001.json` | Encounter | Ambulatory visit for patient-001 on 2026-10-21 |
| `observations/observation-001.json` | Observation | Heart rate 72 bpm (LOINC 8867-4) |
| `observations/observation-002.json` | Observation | Body weight 68.5 kg (LOINC 2711-3) |
| `bundle-001.json` | Bundle | Collection of all 5 resources above |

## Usage

Ingest the bundle via the REST API:

```bash
curl -X POST http://localhost:8000/api/v1/ingestion/bundle \
  -F "source_system=openmrs-demo" \
  -F "batch_id=openmrs-batch-1" \
  -F "file=@tests/data/openmrs/bundle-001.json;type=application/json"
```

Or ingest individual resources via ndjson:

```bash
cat tests/data/openmrs/patients/*.json tests/data/openmrs/encounters/*.json tests/data/openmrs/observations/*.json > openmrs.ndjson
curl -X POST http://localhost:8000/api/v1/ingestion/ndjson \
  -F "source_system=openmrs-demo" \
  -F "batch_id=openmrs-batch-2" \
  -F "file=@openmrs.ndjson;type=application/json"
```

## Source

Synthetic data modeled on OpenMRS (https://openmrs.org) FHIR R4 resources.
Names and identifiers are fictional; no real patient data is included.
