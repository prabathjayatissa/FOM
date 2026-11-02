"""Mapping engine: declarative mapping specifications, FHIRPath-ish expressions,
domain routing, and OMOP row generation (prototype).

Release 0.1 implements a compact declarative JSON mapping language and an
interpreter for Patient -> PERSON and Encounter -> VISIT_OCCURRENCE.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.models import MappingSpec

# ---------------------------------------------------------------------------
# Mapping spec data structures
# ---------------------------------------------------------------------------

class ColumnMap:
    """A single target column expression."""

    def __init__(self, name: str, expression: str, default: Any = None):
        self.name = name
        self.expression = expression  # e.g. "extract.birthDate.year" or "const:1970"
        self.default = default


class MappingRule:
    """One rule: source filter + target table + column expressions."""

    def __init__(
        self,
        target_table: str,
        filter_expr: str | None,
        columns: list[ColumnMap],
        order: int = 0,
    ):
        self.target_table = target_table
        self.filter_expr = filter_expr
        self.columns = columns
        self.order = order


class MappingSpecDef:
    """Parsed mapping specification."""

    def __init__(self, name: str, resource_type: str, rules: list[MappingRule]):
        self.name = name
        self.resource_type = resource_type
        self.rules = sorted(rules, key=lambda r: r.order)


# ---------------------------------------------------------------------------
# Expression evaluator (mini FHIRPath / expression language)
# ---------------------------------------------------------------------------

class ExpressionError(Exception):
    pass


class Evaluator:
    """Evaluate column expressions against a FHIR resource context.

    Supported expression forms:
      - const:<value>            literal
      - extract.<fhirpath>       value from resource (simple dotted path, array index [0])
      - lookup.<table>.<key>     terminology / value-set lookup
      - now                      current UTC timestamp
      - uuid                     generate a uuid4 string
    """

    def __init__(self, resource: dict[str, Any], context: dict[str, Any] | None = None):
        self.resource = resource
        self.context = context or {}

    def evaluate(self, expression: str) -> Any:
        expression = expression.strip()
        if not expression:
            return None

        if expression.startswith("const:"):
            return expression[len("const:"):]

        if expression == "now":
            return datetime.now(UTC).isoformat().replace("+00:00", "Z")

        if expression == "uuid":
            import uuid as _uuid
            return str(_uuid.uuid4())

        if expression.startswith("extract."):
            path = expression[len("extract."):]
            return self._extract(path)

        if expression.startswith("lookup."):
            path = expression[len("lookup."):]
            return self._lookup(path)

        raise ExpressionError(f"unsupported expression: {expression}")

    def _extract(self, path: str) -> Any:
        """Simple dotted-path extraction with optional [index] and .field."""
        node: Any = self.resource
        for token in re.split(r"(?<!\\)\.", path):
            token = token.strip()
            if not token:
                continue
            # Handle array index: patients[0]
            m = re.match(r"^([^\[]+)(?:\[(\d+)\])?$", token)
            if not m:
                raise ExpressionError(f"bad path token: {token}")
            key, index = m.group(1), m.group(2)
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return None
            if index is not None:
                if isinstance(node, list) and 0 <= int(index) < len(node):
                    node = node[int(index)]
                else:
                    return None
        return node

    def _lookup(self, path: str) -> Any:
        """Terminology/value-set lookup. Placeholder for release 0.1.

        Supports lookup.gender.<value>, lookup.<table>.<key>.
        """
        parts = path.split(".")
        if len(parts) < 2:
            return None
        table, key = parts[0], parts[1]
        value = self.context.get(key)
        lookups = {
            "gender": {
                "male": 8507,      # OMOP MALE
                "female": 8532,    # OMOP FEMALE
                "other": 0,
                "unknown": 0,
            },
        }
        table_map = lookups.get(table, {})
        if value is None:
            # Fall back to extracting the key from the resource itself.
            value = self._extract(key)
        return table_map.get(value, 0)


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------

def parse_spec(spec_json: dict[str, Any]) -> MappingSpecDef:
    """Parse a declarative mapping spec JSON into a MappingSpecDef."""
    name = spec_json.get("name", "unnamed")
    resource_type = spec_json.get("resourceType") or spec_json.get("resource_type", "Unknown")
    rules: list[MappingRule] = []

    for idx, rule in enumerate(spec_json.get("rules", [])):
        target_table = rule.get("targetTable", "UNKNOWN")
        filter_expr = rule.get("filter")
        columns: list[ColumnMap] = []
        for col_name, expr in rule.get("columns", {}).items():
            default = rule.get("defaults", {}).get(col_name)
            columns.append(ColumnMap(name=col_name, expression=expr, default=default))
        rules.append(
            MappingRule(
                target_table=target_table,
                filter_expr=filter_expr,
                columns=columns,
                order=idx,
            )
        )

    return MappingSpecDef(name=name, resource_type=resource_type, rules=rules)


# ---------------------------------------------------------------------------
# Rule application / OMOP row generation
# ---------------------------------------------------------------------------

def _match_filter(resource: dict[str, Any], filter_expr: str | None) -> bool:
    """Evaluate a simple boolean filter.

    Prototype supports: <path> == <value>, <path> != <value>, and truthiness.
    """
    if not filter_expr:
        return True
    filter_expr = filter_expr.strip()

    # Equality: path == value
    m = re.match(r"^(.+?)\s==\s['\"](.+)['\"]\s*$", filter_expr)
    if m:
        path, value = m.group(1).strip(), m.group(2)
        node: Any = resource
        for token in path.split("."):
            if isinstance(node, dict) and token in node:
                node = node[token]
            else:
                return False
        return str(node) == value

    # Inequality
    m = re.match(r"^(.+?)\s!=\s['\"](.+)['\"]\s*$", filter_expr)
    if m:
        path, value = m.group(1).strip(), m.group(2)
        node: Any = resource
        for token in path.split("."):
            if isinstance(node, dict) and token in node:
                node = node[token]
            else:
                return True
        return str(node) != value

    # Truthiness of path
    node: Any = resource
    for token in filter_expr.split("."):
        if isinstance(node, dict) and token in node:
            node = node[token]
        else:
            return False
    return bool(node)


def apply_spec(
    spec_def: MappingSpecDef,
    resource: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply a mapping spec to one FHIR resource, returning OMOP row dicts."""
    context = context or {}
    rows: list[dict[str, Any]] = []

    for rule in spec_def.rules:
        if not _match_filter(resource, rule.filter_expr):
            continue

        row: dict[str, Any] = {"target_table": rule.target_table}
        for col in rule.columns:
            try:
                value = Evaluator(resource, context).evaluate(col.expression)
            except ExpressionError:
                value = None
            if value is None and col.default is not None:
                value = col.default
            row[col.name] = value

        rows.append(row)

    return rows


def generate_omop_rows(
    spec_def: MappingSpecDef,
    resources: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a mapping spec over many resources, returning all OMOP rows."""
    context = context or {}
    all_rows: list[dict[str, Any]] = []
    for resource in resources:
        if resource.get("resourceType") != spec_def.resource_type:
            continue
        all_rows.extend(apply_spec(spec_def, resource, context))
    return all_rows


# ---------------------------------------------------------------------------
# Database-backed spec resolution
# ---------------------------------------------------------------------------

async def get_active_spec_for_resource(
    db, resource_type: str
) -> MappingSpecDef | None:
    """Load the active MappingSpec for a resource type from the config store."""
    from sqlalchemy import select

    result = await db.execute(
        select(MappingSpec).where(
            MappingSpec.resource_type == resource_type,
            MappingSpec.is_active == True,
        )
    )
    spec = result.scalar_one_or_none()
    if spec is None:
        return None
    return parse_spec(spec.spec_json)
