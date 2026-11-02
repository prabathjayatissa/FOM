"""Terminology service: OHDSI vocabulary loading, code resolution, worklist (FR-050 to FR-061).

Release 0.1 provides an in-memory / DB-backed stub that:
- translates FHIR code-system URIs to OMOP vocabulary_id (FR-051)
- resolves a source code to a standard concept via "Maps to" (FR-052)
- writes concept_id 0 for unmapped codes and never discards the record (FR-058)
- produces an unmapped-code worklist (FR-059)

Full Athena CSV loading and SOURCE_TO_CONCEPT_MAP support come in release 0.5/1.0.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class TerminologyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # In-memory code-system translation table (FHIR URI -> OMOP vocabulary_id)
        self.code_system_translations: dict[str, str] = {
            "http://hl7.org/fhir/sid/icd-10": "ICD10",
            "http://hl7.org/fhir/sid/icd-10-cm": "ICD10CM",
            "http://hl7.org/fhir/sid/icd-9": "ICD9",
            "http://hl7.org/fhir/sid/icd-9-cm": "ICD9CM",
            "http://loinc.org": "LOINC",
            "http://snomed.info/sct": "SNOMED",
            "http://rxnorm.nlm.nih.gov": "RxNorm",
            "http://hl7.org/fhir/administrative-gender": "Gender",
            "http://hl7.org/fhir/marital-status": "MaritalStatus",
            "urn:oid:2.16.840.1.113883.6.1": "LOINC",
        }
        # Stub "Maps to" table: (vocabulary_id, source_code) -> standard concept_id
        self.maps_to: dict[tuple, int] = {}
        # Unmapped worklist: source_code -> frequency
        self.unmapped_counts: dict[str, int] = {}

    def translate_code_system(self, fhir_uri: str) -> str | None:
        """FR-051: translate FHIR code-system URI to OMOP vocabulary_id."""
        return self.code_system_translations.get(fhir_uri)

    def resolve_code(
        self,
        fhir_uri: str,
        code: str,
    ) -> tuple:
        """FR-052/FR-058: resolve source code to standard concept.

        Returns (concept_id, source_concept_id, vocabulary_id).
        Unmapped -> (0, source_concept_id or 0, vocabulary_id or 0), record kept.
        """
        vocab_id = self.translate_code_system(fhir_uri)
        key = (vocab_id, code) if vocab_id else None
        concept_id = self.maps_to.get(key, 0) if key else 0

        if concept_id == 0:
            key = (fhir_uri, code)
            self.unmapped_counts[key] = self.unmapped_counts.get(key, 0) + 1

        source_concept_id = concept_id if concept_id != 0 else 0
        vocab_int = self._vocab_to_int(vocab_id) if vocab_id else 0
        return concept_id, source_concept_id, vocab_int

    def _vocab_to_int(self, vocab_id: str) -> int:
        return sum(ord(c) for c in vocab_id) % 100000

    def add_map(self, fhir_uri: str, code: str, concept_id: int) -> None:
        """Add or override a source-to-standard concept mapping."""
        vocab_id = self.translate_code_system(fhir_uri)
        if vocab_id:
            self.maps_to[(vocab_id, code)] = concept_id
            self.unmapped_counts.pop(f"{fhir_uri}|{code}", None)

    def get_unmapped_worklist(self) -> list[dict[str, Any]]:
        """FR-059: unmapped-code worklist ranked by frequency."""
        return [
            {"code_system_uri": uri, "code": code, "frequency": freq}
            for (uri, code), freq in sorted(
                self.unmapped_counts.items(), key=lambda item: item[1], reverse=True
            )
        ]

    def map_coding(self, coding: dict[str, Any]) -> dict[str, Any]:
        """Resolve a single FHIR Coding to OMOP concept fields."""
        system = coding.get("system")
        code = coding.get("code")
        concept_id, source_concept_id, vocab_id = self.resolve_code(system or "", code or "")
        return {
            "concept_id": concept_id,
            "source_concept_id": source_concept_id,
            "source_code": code,
            "source_vocab_id": vocab_id,
            "mapped": concept_id != 0,
        }

    def map_codeable_concept(self, codeable_concept: dict[str, Any]) -> dict[str, Any]:
        """FR-053/FR-058: resolve all codings, prefer first mapped, fallback.

        Returns best mapping plus concept_id 0 fallback if none mapped.
        """
        codings = codeable_concept.get("coding", []) if isinstance(codeable_concept, dict) else []
        best = None
        for coding in codings:
            resolved = self.map_coding(coding)
            if resolved["mapped"]:
                best = resolved
                break
        if best is None:
            # Use first coding source info, concept_id 0 (FR-058)
            first = codings[0] if codings else {}
            best = {
                "concept_id": 0,
                "source_concept_id": 0,
                "source_code": first.get("code"),
                "source_vocab_id": self._vocab_to_int(self.translate_code_system(first.get("system", "")) or "") if first.get("system") else 0,
                "mapped": False,
            }
        return best
