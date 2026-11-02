"""Tests for terminology service (FR-050 to FR-058)."""

from app.services.terminology import TerminologyService


class FakeDB:
    pass


def test_translate_code_system():
    ts = TerminologyService(FakeDB())
    assert ts.translate_code_system("http://loinc.org") == "LOINC"
    assert ts.translate_code_system("http://snomed.info/sct") == "SNOMED"
    assert ts.translate_code_system("http://unknown.org") is None


def test_resolve_mapped_code():
    ts = TerminologyService(FakeDB())
    ts.add_map("http://loinc.org", "1234-5", 42)
    concept_id, source_concept_id, vocab_id = ts.resolve_code("http://loinc.org", "1234-5")
    assert concept_id == 42
    assert vocab_id != 0


def test_resolve_unmapped_code_returns_zero_and_keeps_record():
    ts = TerminologyService(FakeDB())
    concept_id, source_concept_id, vocab_id = ts.resolve_code("http://loinc.org", "UNKNOWN-CODE")
    assert concept_id == 0  # concept_id 0 for unmapped (FR-058)
    assert source_concept_id == 0


def test_map_codeable_concept_prefers_mapped():
    ts = TerminologyService(FakeDB())
    ts.add_map("http://loinc.org", "GOOD", 77)
    cc = {
        "coding": [
            {"system": "http://loinc.org", "code": "BAD"},
            {"system": "http://loinc.org", "code": "GOOD"},
        ]
    }
    result = ts.map_codeable_concept(cc)
    assert result["concept_id"] == 77  # fallback to next coded value (FR-053)


def test_map_codeable_concept_all_unmapped_returns_zero():
    ts = TerminologyService(FakeDB())
    cc = {"coding": [{"system": "http://loinc.org", "code": "BAD"}]}
    result = ts.map_codeable_concept(cc)
    assert result["concept_id"] == 0  # never discard (FR-058)


def test_unmapped_worklist_ranked():
    ts = TerminologyService(FakeDB())
    ts.resolve_code("http://loinc.org", "A")  # freq 1
    ts.resolve_code("http://loinc.org", "A")  # freq 2
    ts.resolve_code("http://loinc.org", "B")  # freq 1
    wl = ts.get_unmapped_worklist()
    assert wl[0]["code"] == "A"
    assert wl[0]["frequency"] == 2
    assert wl[1]["code"] == "B"
    assert wl[1]["frequency"] == 1
