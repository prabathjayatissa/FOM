"""Tests for the mapping engine (FR-030 to FR-036)."""


from app.services.mapping_engine import (
    ColumnMap,
    MappingRule,
    MappingSpecDef,
    generate_omop_rows,
    parse_spec,
)


def _spec() -> MappingSpecDef:
    return MappingSpecDef(
        name="Patient to PERSON",
        resource_type="Patient",
        rules=[
            MappingRule(
                target_table="PERSON",
                filter_expr=None,
                columns=[
                    ColumnMap("person_id", "uuid"),
                    ColumnMap("gender_concept_id", "lookup.gender.gender"),
                    ColumnMap("year_of_birth", "extract.birthDate"),
                    ColumnMap("person_source_value", "extract.id"),
                ],
            )
        ],
    )


def test_generate_person_row_male():
    spec = _spec()
    resource = {
        "resourceType": "Patient",
        "id": "pat-1",
        "gender": "male",
        "birthDate": "1970-05-21",
    }
    rows = generate_omop_rows(spec, [resource])
    assert len(rows) == 1
    row = rows[0]
    assert row["target_table"] == "PERSON"
    assert row["person_source_value"] == "pat-1"
    assert row["gender_concept_id"] == 8507  # OMOP MALE
    assert row["year_of_birth"] == "1970-05-21"


def test_generate_person_row_unmapped_gender_returns_zero():
    spec = _spec()
    resource = {
        "resourceType": "Patient",
        "id": "pat-2",
        "gender": "other",
        "birthDate": "1980-01-01",
    }
    rows = generate_omop_rows(spec, [resource])
    assert rows[0]["gender_concept_id"] == 0  # concept_id 0 for unmapped (FR-058)


def test_filter_excludes_entered_in_error():
    spec = MappingSpecDef(
        name="Patient",
        resource_type="Patient",
        rules=[
            MappingRule(
                target_table="PERSON",
                filter_expr="meta.status != 'entered-in-error'",
                columns=[ColumnMap("person_id", "uuid")],
            )
        ],
    )
    bad = {
        "resourceType": "Patient",
        "id": "pat-bad",
        "meta": {"status": "entered-in-error"},
    }
    good = {
        "resourceType": "Patient",
        "id": "pat-good",
        "meta": {"status": "active"},
    }
    rows = generate_omop_rows(spec, [bad, good])
    assert len(rows) == 1
    assert rows[0]["person_id"]  # only the good one mapped


def test_single_resource_zero_one_many_rows():
    spec = _spec()
    # Not a Patient -> zero rows
    rows = generate_omop_rows(spec, [{"resourceType": "Observation", "id": "obs-1"}])
    assert rows == []
    # One Patient -> one row
    rows = generate_omop_rows(spec, [{"resourceType": "Patient", "id": "p1"}])
    assert len(rows) == 1
    # Two Patients -> two rows
    rows = generate_omop_rows(spec, [
        {"resourceType": "Patient", "id": "p1"},
        {"resourceType": "Patient", "id": "p2"},
    ])
    assert len(rows) == 2  # FR-032: zero, one, or many


def test_parse_spec_from_json_dict():
    spec_json = {
        "name": "Test",
        "resource_type": "Patient",
        "rules": [
            {
                "targetTable": "PERSON",
                "filter": None,
                "columns": {"person_id": "uuid"},
            }
        ],
    }
    spec_def = parse_spec(spec_json)
    assert spec_def.name == "Test"
    assert spec_def.resource_type == "Patient"
    assert len(spec_def.rules) == 1
    assert spec_def.rules[0].target_table == "PERSON"
    assert spec_def.rules[0].columns[0].name == "person_id"


def test_evaluator_const_and_lookup():
    from app.services.mapping_engine import Evaluator
    ev = Evaluator({"gender": "female"}, {})
    assert ev.evaluate("const:hello") == "hello"
    assert ev.evaluate("lookup.gender.gender") == 8532  # OMOP FEMALE
    assert ev.evaluate("uuid") is not None


def test_extract_path():
    from app.services.mapping_engine import Evaluator
    ev = Evaluator({"id": "p1", "birthDate": "1970-01-01"}, {})
    assert ev.evaluate("extract.id") == "p1"
    assert ev.evaluate("extract.birthDate") == "1970-01-01"
    assert ev.evaluate("extract.missing") is None
