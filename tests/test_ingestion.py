"""Tests for ingestion parsing (Bundle and ndjson) without a database."""


from app.services.ingestion import ingest_bundle_json, ingest_ndjson


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeBatch:
    def __init__(self):
        self.id = "batch-1"
        self.batch_id = "b1"
        self.source_system = "demo"
        self.status = "received"
        self.resource_count = 0


class FakeDB:
    def __init__(self):
        self.added = []
        self.committed = False

    async def execute(self, stmt):
        return FakeResult([FakeBatch()])

    async def get(self, model, ident):
        return FakeBatch()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True


import asyncio


def test_ingest_bundle_collection():
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "p1", "gender": "male"}},
            {"resource": {"resourceType": "Encounter", "id": "e1", "status": "finished"}},
        ],
    }
    db = FakeDB()
    result = asyncio.run(ingest_bundle_json(db, "demo", "b1", bundle))
    assert result.resources_received == 2
    assert result.resources_valid == 2
    assert result.resources_rejected == 0


def test_ingest_invalid_resource_quarantined():
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient"}},  # missing id -> invalid
        ],
    }
    db = FakeDB()
    result = asyncio.run(ingest_bundle_json(db, "demo", "b1", bundle))
    assert result.resources_received == 1
    assert result.resources_valid == 0
    assert result.resources_rejected == 1


def test_ingest_ndjson():
    ndjson = '{"resourceType":"Patient","id":"p1"}\n{"resourceType":"Encounter","id":"e1"}\n'
    db = FakeDB()
    result = asyncio.run(ingest_ndjson(db, "demo", "b1", ndjson))
    assert result.resources_received == 2
    assert result.resources_valid == 2


def test_ingest_ndjson_skips_blank_lines():
    ndjson = '{"resourceType":"Patient","id":"p1"}\n\n{"resourceType":"Encounter","id":"e1"}\n'
    db = FakeDB()
    result = asyncio.run(ingest_ndjson(db, "demo", "b1", ndjson))
    assert result.resources_received == 2
