#!/usr/bin/env python3
"""Validate the Harness Doctor control catalog without modifying it."""

import argparse
import json
import re
import stat
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_DIR = SKILL_ROOT / "references" / "catalog"
BOUNDARY_ERROR_CODES = {
    "CATALOG_FILE_MISSING",
    "CATALOG_FILE_UNREADABLE",
    "CATALOG_JSON_INVALID",
    "CATALOG_USAGE_INVALID",
}
SUPPORTED_SCHEMA_MAJOR = 1
DOMAIN_ID_PATTERN = r"HD-[A-Z]{3}"
ALLOWED_DOMAIN_IDS = {f"HD-{name}" for name in (
    "FND", "KNW", "INS", "BST", "SCP", "STA", "VER", "ARC", "OBS", "HYG", "AUT", "GRF"
)}
CONTROL_ID_PATTERN = r"HD-[A-Z]{3}-[0-9]{3}"
CANDIDATE_ID_PATTERN = r"L(?:0[1-9]|1[0-4])-C[0-9]{2}"
SOURCE_ID_PATTERN = r"[a-z0-9][a-z0-9-]*@[A-Za-z0-9][A-Za-z0-9._-]*"
DOCUMENT_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"
SEMVER_PATTERN = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
BOOK_SOURCE_ID = "walkinglabs-he@77e7a3e"
BOOK_REVISION = "77e7a3e21469dcbece2558086c8d91657abeaa40"
BOOK_CANDIDATE_COUNTS = (4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 6, 7, 7)
EXPECTED_STATUS_IDS = (
    "satisfied",
    "partial",
    "missing",
    "conflict",
    "unverifiable",
    "not_applicable",
)
EXPECTED_COVERAGE_POLICY = {
    "numerator_statuses": ["satisfied"],
    "excluded_from_denominator": ["not_applicable"],
    "zero_denominator_result": "N/A",
    "is_weighted": False,
}
EXPECTED_MATURITY_IDS = ("L0", "L1", "L2", "L3", "L4")
MATURITY_RANK = {level_id: index for index, level_id in enumerate(EXPECTED_MATURITY_IDS)}
ALLOWED_LIFECYCLE_STATUSES = {"active", "deprecated"}
ALLOWED_REMEDIATION_RISKS = {"low", "medium", "high"}
ALLOWED_REVISION_KINDS = {"git_commit", "published_at", "archived_snapshot"}


@dataclass(frozen=True)
class ValidationError:
    code: str
    path: str
    message: str


Shape = Dict[str, Any]


def object_shape(fields: Mapping[str, Shape]) -> Shape:
    return {"kind": "object", "fields": dict(fields)}


def array_shape(item: Shape) -> Shape:
    return {"kind": "array", "item": item}


STRING = {"kind": "string"}
INTEGER = {"kind": "integer"}
BOOLEAN = {"kind": "boolean"}
NULLABLE_STRING = {"kind": "nullable_string"}
STRING_ARRAY = array_shape(STRING)

DOMAIN_SHAPE = object_shape(
    {
        "id": STRING,
        "title": STRING,
        "description": STRING,
        "display_order": INTEGER,
    }
)
DIAGNOSTIC_STATUS_SHAPE = object_shape(
    {"id": STRING, "label": STRING, "definition": STRING}
)
COVERAGE_POLICY_SHAPE = object_shape(
    {
        "numerator_statuses": STRING_ARRAY,
        "excluded_from_denominator": STRING_ARRAY,
        "zero_denominator_result": STRING,
        "is_weighted": BOOLEAN,
    }
)
MATURITY_LEVEL_SHAPE = object_shape(
    {
        "id": STRING,
        "title": STRING,
        "description": STRING,
        "requires_lower_levels": BOOLEAN,
        "activation": STRING,
        "gate_control_ids": STRING_ARRAY,
    }
)
APPLICABILITY_SHAPE = object_shape(
    {"applies_when": STRING_ARRAY, "not_applicable_when": STRING_ARRAY}
)
EVIDENCE_SHAPE = object_shape(
    {"positive": STRING_ARRAY, "partial": STRING_ARRAY, "conflict": STRING_ARRAY, "minimum_level": STRING}
)
REMEDIATION_SHAPE = object_shape(
    {"summary": STRING, "artifact_types": STRING_ARRAY, "risk": STRING}
)
SOURCE_REF_SHAPE = object_shape(
    {
        "source_id": STRING,
        "document_id": STRING,
        "locator": STRING,
        "note": STRING,
    }
)
LIFECYCLE_SHAPE = object_shape(
    {
        "status": STRING,
        "introduced_in": STRING,
        "changed_in": STRING,
        "deprecated_in": NULLABLE_STRING,
        "superseded_by": NULLABLE_STRING,
    }
)
CONTROL_SHAPE = object_shape(
    {
        "id": STRING,
        "title": STRING,
        "domain": STRING,
        "maturity": STRING,
        "is_gate": BOOLEAN,
        "requirement": STRING,
        "applicability": APPLICABILITY_SHAPE,
        "evidence": EVIDENCE_SHAPE,
        "remediation": REMEDIATION_SHAPE,
        "dependencies": STRING_ARRAY,
        "conflicts_with": STRING_ARRAY,
        "alternatives": STRING_ARRAY,
        "source_refs": array_shape(SOURCE_REF_SHAPE),
        "source_aliases": STRING_ARRAY,
        "lifecycle": LIFECYCLE_SHAPE,
    }
)
EXCLUDED_CANDIDATE_SHAPE = object_shape(
    {"id": STRING, "rationale": STRING, "decision": STRING}
)
CONTROLS_DOCUMENT_SHAPE = object_shape(
    {
        "schema_version": STRING,
        "catalog_version": STRING,
        "domains": array_shape(DOMAIN_SHAPE),
        "diagnostic_statuses": array_shape(DIAGNOSTIC_STATUS_SHAPE),
        "coverage_policy": COVERAGE_POLICY_SHAPE,
        "maturity_levels": array_shape(MATURITY_LEVEL_SHAPE),
        "controls": array_shape(CONTROL_SHAPE),
        "excluded_candidates": array_shape(EXCLUDED_CANDIDATE_SHAPE),
    }
)

REVISION_SHAPE = object_shape({"kind": STRING, "value": STRING})
SOURCE_DOCUMENT_SHAPE = object_shape(
    {"id": STRING, "title": STRING, "page_url": STRING, "source_path": STRING}
)
SOURCE_SNAPSHOT_SHAPE = object_shape(
    {
        "id": STRING,
        "title": STRING,
        "publisher": STRING,
        "canonical_url": STRING,
        "revision": REVISION_SHAPE,
        "accessed_on": STRING,
        "language": STRING,
        "documents": array_shape(SOURCE_DOCUMENT_SHAPE),
    }
)
SOURCES_DOCUMENT_SHAPE = object_shape(
    {
        "schema_version": STRING,
        "registry_version": STRING,
        "source_snapshots": array_shape(SOURCE_SNAPSHOT_SHAPE),
    }
)


def _matches_kind(value: Any, kind: str) -> bool:
    if kind == "object":
        return type(value) is dict
    if kind == "array":
        return type(value) is list
    if kind == "string":
        return type(value) is str
    if kind == "integer":
        return type(value) is int
    if kind == "boolean":
        return type(value) is bool
    if kind == "nullable_string":
        return value is None or type(value) is str
    raise ValueError(f"unknown shape kind: {kind}")


def _expected_kind_label(kind: str) -> str:
    return {
        "object": "object",
        "array": "array",
        "string": "string",
        "integer": "integer",
        "boolean": "boolean",
        "nullable_string": "string or null",
    }[kind]


def validate_shape(value: Any, shape: Shape, path: str, errors: List[ValidationError]) -> None:
    """Validate required fields and primitive/container types without cascading."""
    kind = shape["kind"]
    if not _matches_kind(value, kind):
        errors.append(
            ValidationError(
                code="CATALOG_TYPE_INVALID",
                path=path,
                message=f"expected {_expected_kind_label(kind)}",
            )
        )
        return

    if kind == "object":
        fields = shape["fields"]
        for field_name in sorted(set(fields) - set(value)):
            errors.append(
                ValidationError(
                    code="CATALOG_FIELD_MISSING",
                    path=f"{path}.{field_name}",
                    message="required field is missing",
                )
            )
        for index, field_name in enumerate(sorted(set(value) - set(fields))):
            errors.append(
                ValidationError(
                    code="CATALOG_FIELD_UNKNOWN",
                    path=f"{path}.<unknown[{index}]>",
                    message="field is not allowed",
                )
            )
        for field_name in sorted(set(fields) & set(value)):
            validate_shape(value[field_name], fields[field_name], f"{path}.{field_name}", errors)
    elif kind == "array":
        for index, item in enumerate(value):
            validate_shape(item, shape["item"], f"{path}[{index}]", errors)


def validate_schema_version(
    document: Any, display_name: str, errors: List[ValidationError]
) -> None:
    if type(document) is not dict:
        return
    version = document.get("schema_version")
    if type(version) is not str or not re.fullmatch(SEMVER_PATTERN, version):
        return
    if int(version.split(".", 1)[0]) != SUPPORTED_SCHEMA_MAJOR:
        errors.append(
            ValidationError(
                code="CATALOG_VERSION_UNSUPPORTED",
                path=f"{display_name}.schema_version",
                message=f"schema major version must be {SUPPORTED_SCHEMA_MAJOR}",
            )
        )


def validate_id_format(
    value: str,
    pattern: str,
    path: str,
    identity_name: str,
    errors: List[ValidationError],
) -> bool:
    if re.fullmatch(pattern, value):
        return True
    errors.append(
        ValidationError(
            code="CATALOG_ID_INVALID",
            path=path,
            message=f"invalid {identity_name} id",
        )
    )
    return False


def validate_unique_ids(
    entries: Sequence[Mapping[str, Any]],
    path: str,
    identity_name: str,
    errors: List[ValidationError],
) -> None:
    seen = set()
    for index, entry in enumerate(entries):
        identity = entry["id"]
        if identity in seen:
            errors.append(
                ValidationError(
                    code="CATALOG_DUPLICATE_ID",
                    path=f"{path}[{index}].id",
                    message=f"duplicate {identity_name} id",
                )
            )
        seen.add(identity)


def validate_canonical_order(
    values: Sequence[Any], expected: Sequence[Any], path: str, errors: List[ValidationError]
) -> None:
    if list(values) != list(expected):
        errors.append(
            ValidationError(
                code="CATALOG_ORDER_INVALID",
                path=path,
                message="entries are not in canonical order",
            )
        )


def validate_controls_identity(controls: Mapping[str, Any], errors: List[ValidationError]) -> None:
    domains = controls["domains"]
    control_entries = controls["controls"]
    excluded_candidates = controls["excluded_candidates"]

    validate_unique_ids(domains, "controls.json.domains", "domain", errors)
    validate_unique_ids(control_entries, "controls.json.controls", "control", errors)
    validate_unique_ids(
        excluded_candidates,
        "controls.json.excluded_candidates",
        "candidate",
        errors,
    )

    valid_domain_ids = set()
    for index, domain in enumerate(domains):
        path = f"controls.json.domains[{index}].id"
        if validate_id_format(domain["id"], DOMAIN_ID_PATTERN, path, "domain", errors):
            if domain["id"] in ALLOWED_DOMAIN_IDS:
                valid_domain_ids.add(domain["id"])
            else:
                errors.append(ValidationError("CATALOG_ID_INVALID", path,
                                              "domain is not in the supported schema"))

    validate_canonical_order(
        [(domain["display_order"], domain["id"]) for domain in domains],
        sorted((domain["display_order"], domain["id"]) for domain in domains),
        "controls.json.domains",
        errors,
    )

    control_ids = {control["id"] for control in control_entries}
    maturity_ids = {level["id"] for level in controls["maturity_levels"]}
    for index, control in enumerate(control_entries):
        control_path = f"controls.json.controls[{index}]"
        control_id_is_valid = validate_id_format(
            control["id"], CONTROL_ID_PATTERN, f"{control_path}.id", "control", errors
        )
        domain = control["domain"]
        if domain not in valid_domain_ids:
            errors.append(
                ValidationError(
                    code="CATALOG_REFERENCE_UNKNOWN",
                    path=f"{control_path}.domain",
                    message="unknown domain id",
                )
            )
        if control_id_is_valid and domain != control["id"].rsplit("-", 1)[0]:
            errors.append(
                ValidationError(
                    code="CATALOG_DOMAIN_MISMATCH",
                    path=f"{control_path}.domain",
                    message="domain does not match control id",
                )
            )
        if control["maturity"] not in maturity_ids:
            errors.append(
                ValidationError(
                    code="CATALOG_REFERENCE_UNKNOWN",
                    path=f"{control_path}.maturity",
                    message="unknown maturity id",
                )
            )

        for relation_name in ("dependencies", "conflicts_with", "alternatives"):
            for relation_index, related_id in enumerate(control[relation_name]):
                if related_id not in control_ids:
                    errors.append(
                        ValidationError(
                            code="CATALOG_REFERENCE_UNKNOWN",
                            path=f"{control_path}.{relation_name}[{relation_index}]",
                            message="unknown control id",
                        )
                    )

        for alias_index, alias in enumerate(control["source_aliases"]):
            validate_id_format(
                alias,
                CANDIDATE_ID_PATTERN,
                f"{control_path}.source_aliases[{alias_index}]",
                "candidate",
                errors,
            )

    validate_canonical_order(
        [(control["domain"], control["id"]) for control in control_entries],
        sorted((control["domain"], control["id"]) for control in control_entries),
        "controls.json.controls",
        errors,
    )

    for level_index, level in enumerate(controls["maturity_levels"]):
        for gate_index, gate_id in enumerate(level["gate_control_ids"]):
            if gate_id not in control_ids:
                errors.append(
                    ValidationError(
                        code="CATALOG_REFERENCE_UNKNOWN",
                        path=(
                            f"controls.json.maturity_levels[{level_index}]"
                            f".gate_control_ids[{gate_index}]"
                        ),
                        message="unknown control id",
                    )
                )

    for index, candidate in enumerate(excluded_candidates):
        validate_id_format(
            candidate["id"],
            CANDIDATE_ID_PATTERN,
            f"controls.json.excluded_candidates[{index}].id",
            "candidate",
            errors,
        )


def validate_sources_identity(sources: Mapping[str, Any], errors: List[ValidationError]) -> None:
    snapshots = sources["source_snapshots"]
    validate_unique_ids(snapshots, "sources.json.source_snapshots", "source", errors)
    validate_canonical_order(
        [snapshot["id"] for snapshot in snapshots],
        sorted(snapshot["id"] for snapshot in snapshots),
        "sources.json.source_snapshots",
        errors,
    )

    for snapshot_index, snapshot in enumerate(snapshots):
        snapshot_path = f"sources.json.source_snapshots[{snapshot_index}]"
        validate_id_format(
            snapshot["id"], SOURCE_ID_PATTERN, f"{snapshot_path}.id", "source", errors
        )
        documents = snapshot["documents"]
        validate_unique_ids(documents, f"{snapshot_path}.documents", "document", errors)
        validate_canonical_order(
            [document["id"] for document in documents],
            sorted(document["id"] for document in documents),
            f"{snapshot_path}.documents",
            errors,
        )
        for document_index, document in enumerate(documents):
            validate_id_format(
                document["id"],
                DOCUMENT_ID_PATTERN,
                f"{snapshot_path}.documents[{document_index}].id",
                "document",
                errors,
            )


def validate_cross_file_references(
    controls: Mapping[str, Any], sources: Mapping[str, Any], errors: List[ValidationError]
) -> None:
    documents_by_source = {
        snapshot["id"]: {document["id"] for document in snapshot["documents"]}
        for snapshot in sources["source_snapshots"]
    }
    for control_index, control in enumerate(controls["controls"]):
        for ref_index, source_ref in enumerate(control["source_refs"]):
            ref_path = f"controls.json.controls[{control_index}].source_refs[{ref_index}]"
            source_id = source_ref["source_id"]
            if source_id not in documents_by_source:
                errors.append(
                    ValidationError(
                        code="CATALOG_REFERENCE_UNKNOWN",
                        path=f"{ref_path}.source_id",
                        message="unknown source id",
                    )
                )
                continue
            document_id = source_ref["document_id"]
            if document_id not in documents_by_source[source_id]:
                errors.append(
                    ValidationError(
                        code="CATALOG_REFERENCE_UNKNOWN",
                        path=f"{ref_path}.document_id",
                        message="document does not belong to the referenced source",
                    )
                )


def validate_semver(value: str, path: str, errors: List[ValidationError]) -> bool:
    if re.fullmatch(SEMVER_PATTERN, value):
        return True
    errors.append(
        ValidationError(
            code="CATALOG_VERSION_INVALID",
            path=path,
            message="version must use MAJOR.MINOR.PATCH without leading zeros",
        )
    )
    return False


def validate_controls_policy(controls: Mapping[str, Any], errors: List[ValidationError]) -> None:
    status_ids = tuple(status["id"] for status in controls["diagnostic_statuses"])
    if status_ids != EXPECTED_STATUS_IDS:
        errors.append(
            ValidationError(
                code="CATALOG_POLICY_INVALID",
                path="controls.json.diagnostic_statuses",
                message="diagnostic status ids or order do not match the approved policy",
            )
        )

    if controls["coverage_policy"] != EXPECTED_COVERAGE_POLICY:
        errors.append(
            ValidationError(
                code="CATALOG_POLICY_INVALID",
                path="controls.json.coverage_policy",
                message="coverage policy does not match the approved unweighted formula",
            )
        )

    maturity_levels = controls["maturity_levels"]
    maturity_ids = tuple(level["id"] for level in maturity_levels)
    if maturity_ids != EXPECTED_MATURITY_IDS:
        errors.append(
            ValidationError(
                code="CATALOG_MATURITY_INVALID",
                path="controls.json.maturity_levels",
                message="maturity levels must be ordered L0 through L4",
            )
        )

    for level_index, level in enumerate(maturity_levels):
        level_path = f"controls.json.maturity_levels[{level_index}]"
        level_id = level["id"]
        expected_activation = "explicit_autonomy" if level_id == "L4" else "default"
        if level["activation"] != expected_activation:
            errors.append(
                ValidationError(
                    code="CATALOG_MATURITY_INVALID",
                    path=f"{level_path}.activation",
                    message=f"activation must be {expected_activation}",
                )
            )
        expected_requires_lower = level_id != "L0"
        if level["requires_lower_levels"] is not expected_requires_lower:
            errors.append(
                ValidationError(
                    code="CATALOG_MATURITY_INVALID",
                    path=f"{level_path}.requires_lower_levels",
                    message=(
                        "requires_lower_levels must be "
                        f"{str(expected_requires_lower).lower()}"
                    ),
                )
            )
        if level_id == "L0" and level["gate_control_ids"]:
            errors.append(
                ValidationError(
                    code="CATALOG_MATURITY_GATE_INVALID",
                    path=f"{level_path}.gate_control_ids",
                    message="L0 cannot declare gate controls",
                )
            )

    control_entries = controls["controls"]
    control_by_id = {control["id"]: control for control in control_entries}
    gate_occurrences = set()
    for level_index, level in enumerate(maturity_levels):
        level_rank = MATURITY_RANK.get(level["id"])
        for gate_index, gate_id in enumerate(level["gate_control_ids"]):
            if gate_id not in control_by_id:
                continue
            gate_occurrences.add(gate_id)
            gate = control_by_id[gate_id]
            gate_path = (
                f"controls.json.maturity_levels[{level_index}].gate_control_ids[{gate_index}]"
            )
            gate_rank = MATURITY_RANK.get(gate["maturity"])
            if not gate["is_gate"]:
                errors.append(
                    ValidationError(
                        code="CATALOG_MATURITY_GATE_INVALID",
                        path=gate_path,
                        message="control is not marked as a gate",
                    )
                )
            elif gate["lifecycle"]["status"] != "active":
                errors.append(
                    ValidationError(
                        code="CATALOG_MATURITY_GATE_INVALID",
                        path=gate_path,
                        message="gate control is not active",
                    )
                )
            elif level_rank is not None and gate_rank is not None and gate_rank > level_rank:
                errors.append(
                    ValidationError(
                        code="CATALOG_MATURITY_GATE_INVALID",
                        path=gate_path,
                        message="gate control is above the containing maturity level",
                    )
                )

    for control_index, control in enumerate(control_entries):
        control_path = f"controls.json.controls[{control_index}]"
        if control["maturity"] not in {"L1", "L2", "L3", "L4"}:
            errors.append(
                ValidationError(
                    code="CATALOG_MATURITY_INVALID",
                    path=f"{control_path}.maturity",
                    message="controls must use maturity L1 through L4",
                )
            )
        if control["is_gate"] and control["id"] not in gate_occurrences:
            errors.append(
                ValidationError(
                    code="CATALOG_MATURITY_GATE_INVALID",
                    path=f"{control_path}.is_gate",
                    message="gate control is absent from every maturity gate list",
                )
            )


def validate_dependency_graph(
    control_entries: Sequence[Mapping[str, Any]], errors: List[ValidationError]
) -> None:
    index_by_id = {control["id"]: index for index, control in enumerate(control_entries)}
    control_by_id = {control["id"]: control for control in control_entries}
    state = {control_id: 0 for control_id in control_by_id}
    # Explicit DFS frames avoid Python's recursion limit on long valid chains.
    for root_id in sorted(control_by_id):
        if state[root_id] != 0:
            continue
        state[root_id] = 1
        frames = [(root_id, iter(enumerate(control_by_id[root_id]["dependencies"])))]
        while frames:
            control_id, edges = frames[-1]
            edge = next(edges, None)
            if edge is None:
                state[control_id] = 2
                frames.pop()
                continue
            dependency_index, dependency_id = edge
            if dependency_id not in control_by_id:
                continue
            if state[dependency_id] == 0:
                state[dependency_id] = 1
                frames.append((dependency_id, iter(enumerate(
                    control_by_id[dependency_id]["dependencies"]))))
            elif state[dependency_id] == 1:
                errors.append(ValidationError(
                    "CATALOG_DEPENDENCY_CYCLE",
                    f"controls.json.controls[{index_by_id[control_id]}]"
                    f".dependencies[{dependency_index}]",
                    "dependency edge closes a cycle",
                ))


def validate_control_semantics(
    controls: Mapping[str, Any], errors: List[ValidationError]
) -> None:
    validate_semver(controls["schema_version"], "controls.json.schema_version", errors)
    validate_semver(controls["catalog_version"], "controls.json.catalog_version", errors)

    control_entries = controls["controls"]
    control_by_id = {control["id"]: control for control in control_entries}
    mapped_candidates = set()
    for control_index, control in enumerate(control_entries):
        control_path = f"controls.json.controls[{control_index}]"
        lifecycle = control["lifecycle"]
        status = lifecycle["status"]

        if control["evidence"]["minimum_level"] not in {"declared", "recorded", "verified"}:
            errors.append(ValidationError(
                code="CATALOG_ENUM_INVALID", path=f"{control_path}.evidence.minimum_level",
                message="minimum evidence must be declared, recorded, or verified",
            ))
        if control["remediation"]["risk"] not in ALLOWED_REMEDIATION_RISKS:
            errors.append(
                ValidationError(
                    code="CATALOG_ENUM_INVALID",
                    path=f"{control_path}.remediation.risk",
                    message="risk must be low, medium, or high",
                )
            )
        if status not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(
                ValidationError(
                    code="CATALOG_ENUM_INVALID",
                    path=f"{control_path}.lifecycle.status",
                    message="lifecycle status must be active or deprecated",
                )
            )

        for version_field in ("introduced_in", "changed_in"):
            validate_semver(
                lifecycle[version_field], f"{control_path}.lifecycle.{version_field}", errors
            )
        if lifecycle["deprecated_in"] is not None:
            validate_semver(
                lifecycle["deprecated_in"],
                f"{control_path}.lifecycle.deprecated_in",
                errors,
            )

        if status == "active":
            if lifecycle["deprecated_in"] is not None:
                errors.append(
                    ValidationError(
                        code="CATALOG_LIFECYCLE_INVALID",
                        path=f"{control_path}.lifecycle.deprecated_in",
                        message="active controls cannot have deprecated_in",
                    )
                )
            if lifecycle["superseded_by"] is not None:
                errors.append(
                    ValidationError(
                        code="CATALOG_LIFECYCLE_INVALID",
                        path=f"{control_path}.lifecycle.superseded_by",
                        message="active controls cannot have superseded_by",
                    )
                )
            if not control["source_refs"]:
                errors.append(
                    ValidationError(
                        code="CATALOG_PROVENANCE_MISSING",
                        path=f"{control_path}.source_refs",
                        message="active controls require at least one source reference",
                    )
                )
            if not control["source_aliases"]:
                errors.append(
                    ValidationError(
                        code="CATALOG_PROVENANCE_MISSING",
                        path=f"{control_path}.source_aliases",
                        message="active controls require at least one candidate alias",
                    )
                )
        elif status == "deprecated":
            if lifecycle["deprecated_in"] is None:
                errors.append(
                    ValidationError(
                        code="CATALOG_LIFECYCLE_INVALID",
                        path=f"{control_path}.lifecycle.deprecated_in",
                        message="deprecated controls require deprecated_in",
                    )
                )
            successor_id = lifecycle["superseded_by"]
            if successor_id is not None:
                successor = control_by_id.get(successor_id)
                if (
                    successor is None
                    or successor_id == control["id"]
                    or successor["lifecycle"]["status"] != "active"
                ):
                    errors.append(
                        ValidationError(
                            code="CATALOG_LIFECYCLE_INVALID",
                            path=f"{control_path}.lifecycle.superseded_by",
                            message="superseded_by must resolve to a different active control",
                        )
                    )

        for dependency_index, dependency_id in enumerate(control["dependencies"]):
            dependency = control_by_id.get(dependency_id)
            if dependency is not None and dependency["lifecycle"]["status"] != "active":
                errors.append(
                    ValidationError(
                        code="CATALOG_REFERENCE_INACTIVE",
                        path=f"{control_path}.dependencies[{dependency_index}]",
                        message="dependency control is not active",
                    )
                )

        for conflict_index, conflict_id in enumerate(control["conflicts_with"]):
            other = control_by_id.get(conflict_id)
            if other is not None and control["id"] not in other["conflicts_with"]:
                errors.append(
                    ValidationError(
                        code="CATALOG_CONFLICT_ASYMMETRIC",
                        path=f"{control_path}.conflicts_with[{conflict_index}]",
                        message="control does not declare the reverse conflict",
                    )
                )

        for alias_index, alias in enumerate(control["source_aliases"]):
            if alias in mapped_candidates:
                errors.append(
                    ValidationError(
                        code="CATALOG_CANDIDATE_DUPLICATE",
                        path=f"{control_path}.source_aliases[{alias_index}]",
                        message="candidate is mapped more than once",
                    )
                )
            mapped_candidates.add(alias)

    validate_dependency_graph(control_entries, errors)

    for candidate_index, candidate in enumerate(controls["excluded_candidates"]):
        candidate_path = f"controls.json.excluded_candidates[{candidate_index}]"
        if candidate["decision"] != "not_adopted":
            errors.append(
                ValidationError(
                    code="CATALOG_ENUM_INVALID",
                    path=f"{candidate_path}.decision",
                    message="excluded candidate decision must be not_adopted",
                )
            )
        if not candidate["rationale"].strip():
            errors.append(
                ValidationError(
                    code="CATALOG_PROVENANCE_MISSING",
                    path=f"{candidate_path}.rationale",
                    message="excluded candidates require a concrete rationale",
                )
            )
        if candidate["id"] in mapped_candidates:
            errors.append(
                ValidationError(
                    code="CATALOG_CANDIDATE_OVERLAP",
                    path=f"{candidate_path}.id",
                    message="candidate is both mapped and excluded",
                )
            )


def validate_source_semantics(
    sources: Mapping[str, Any], errors: List[ValidationError]
) -> None:
    validate_semver(sources["schema_version"], "sources.json.schema_version", errors)
    validate_semver(sources["registry_version"], "sources.json.registry_version", errors)

    for snapshot_index, snapshot in enumerate(sources["source_snapshots"]):
        snapshot_path = f"sources.json.source_snapshots[{snapshot_index}]"
        if not is_iso_date(snapshot["accessed_on"]):
            errors.append(ValidationError("CATALOG_VALUE_INVALID", f"{snapshot_path}.accessed_on",
                                          "access date must be an ISO calendar date"))
        validate_public_url(snapshot["canonical_url"], f"{snapshot_path}.canonical_url", errors)
        for index, document in enumerate(snapshot["documents"]):
            document_path = f"{snapshot_path}.documents[{index}]"
            validate_public_url(document["page_url"], f"{document_path}.page_url", errors)
            source_path = document["source_path"]
            if (source_path.startswith("/") or "\\" in source_path or ":" in source_path
                    or any(part in {"", ".", ".."} for part in source_path.split("/"))
                    or any(ord(char) < 32 for char in source_path)):
                errors.append(ValidationError("CATALOG_VALUE_INVALID", f"{document_path}.source_path",
                                              "source path must be repository-relative POSIX text"))
        revision = snapshot["revision"]
        kind = revision["kind"]
        value = revision["value"]
        is_valid = kind in ALLOWED_REVISION_KINDS and bool(value.strip())
        if value.strip().lower() == "latest":
            is_valid = False
        if kind == "git_commit" and not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", value):
            is_valid = False
        if kind == "published_at" and not is_iso_date(value):
            is_valid = False
        # An archive identity must be content-addressed or a timestamped archive URL.
        if kind == "archived_snapshot" and not re.fullmatch(
            r"(?:sha256:[0-9a-f]{64}|https://web\.archive\.org/web/[0-9]{14}/https?://\S+)",
            value,
        ):
            is_valid = False
        if not is_valid:
            errors.append(
                ValidationError(
                    code="CATALOG_SOURCE_REVISION_INVALID",
                    path=f"sources.json.source_snapshots[{snapshot_index}].revision",
                    message="source revision must be immutable and reproducible",
                )
            )


def validate_public_url(value: str, path: str, errors: List[ValidationError]) -> None:
    try:
        url = urlsplit(value)
        valid = (url.scheme in {"http", "https"} and bool(url.hostname)
                 and url.username is None and url.password is None
                 and not any(char.isspace() or ord(char) < 32 for char in value))
    except ValueError:
        valid = False
    if not valid:
        errors.append(ValidationError("CATALOG_VALUE_INVALID", path,
                                      "source URL must be HTTP(S) without credentials"))


def is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_nonempty_values(value: Any, path: str, errors: List[ValidationError]) -> None:
    """Inspect only shape-trusted documents; locators and optional arrays may be empty."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key != "locator":
                validate_nonempty_values(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        if not value and path.rsplit(".", 1)[-1] in {
            "controls", "domains", "source_snapshots", "documents", "applies_when",
            "positive", "partial", "conflict", "artifact_types",
        }:
            errors.append(ValidationError("CATALOG_VALUE_INVALID", path,
                                          "at least one entry is required"))
        for index, item in enumerate(value):
            validate_nonempty_values(item, f"{path}[{index}]", errors)
    elif isinstance(value, str) and not value.strip():
        errors.append(ValidationError("CATALOG_VALUE_INVALID", path,
                                      "a non-empty value is required"))


def validate_ordered_set(values: Sequence[Any], path: str, errors: List[ValidationError]) -> None:
    if list(values) != sorted(set(values)):
        errors.append(ValidationError("CATALOG_ORDER_INVALID", path,
                                      "entries must be unique and in lexical order"))


def validate_control_details(controls: Mapping[str, Any], errors: List[ValidationError]) -> None:
    """Enforce values that shape and reference checks alone cannot establish."""
    validate_nonempty_values(controls, "controls.json", errors)
    order = [domain["display_order"] for domain in controls["domains"]]
    if len(set(order)) != len(order) or any(number < 1 for number in order):
        errors.append(ValidationError("CATALOG_VALUE_INVALID", "controls.json.domains",
                                      "display orders must be unique positive integers"))
    for index, control in enumerate(controls["controls"]):
        path = f"controls.json.controls[{index}]"
        for relation in ("dependencies", "conflicts_with", "alternatives", "source_aliases"):
            validate_ordered_set(control[relation], f"{path}.{relation}", errors)
        for relation in ("conflicts_with", "alternatives"):
            if control["id"] in control[relation]:
                errors.append(ValidationError("CATALOG_REFERENCE_INVALID", f"{path}.{relation}",
                                              "a control cannot relate to itself here"))
        validate_ordered_set(control["remediation"]["artifact_types"],
                             f"{path}.remediation.artifact_types", errors)
        validate_ordered_set([(ref["source_id"], ref["document_id"], ref["locator"])
                              for ref in control["source_refs"]], f"{path}.source_refs", errors)
        lifecycle = control["lifecycle"]
        versions = [lifecycle["introduced_in"], lifecycle["changed_in"],
                    controls["catalog_version"]]
        if lifecycle["deprecated_in"] is not None:
            versions.insert(1, lifecycle["deprecated_in"])
        if all(re.fullmatch(SEMVER_PATTERN, version) for version in versions):
            numeric = [tuple(int(part) for part in version.split(".")) for version in versions]
            if numeric != sorted(numeric):
                errors.append(ValidationError("CATALOG_LIFECYCLE_INVALID", f"{path}.lifecycle",
                                              "lifecycle versions must be chronological within the catalog"))
    for index, level in enumerate(controls["maturity_levels"]):
        validate_ordered_set(level["gate_control_ids"],
                             f"controls.json.maturity_levels[{index}].gate_control_ids", errors)
    validate_ordered_set([candidate["id"] for candidate in controls["excluded_candidates"]],
                         "controls.json.excluded_candidates", errors)


def validate_book_dispositions(
    controls: Mapping[str, Any], sources: Mapping[str, Any], errors: List[ValidationError]
) -> None:
    """The fixed research inventory is small data, never a runtime read of chapter notes."""
    snapshots = [s for s in sources["source_snapshots"] if s["id"] == BOOK_SOURCE_ID]
    if not snapshots:
        return  # Synthetic catalogs and future non-book sources have separate inventories.
    expected = {f"L{chapter:02d}-C{candidate:02d}"
                for chapter, count in enumerate(BOOK_CANDIDATE_COUNTS, 1)
                for candidate in range(1, count + 1)}
    dispositions = {alias for control in controls["controls"] for alias in control["source_aliases"]}
    dispositions.update(candidate["id"] for candidate in controls["excluded_candidates"])
    if expected - dispositions:
        errors.append(ValidationError("CATALOG_CANDIDATE_UNDISPOSED", "controls.json.controls",
                                      "fixed-book candidates are missing dispositions"))
    if dispositions - expected:
        errors.append(ValidationError("CATALOG_ID_INVALID", "controls.json.controls",
                                      "candidate is not in the fixed research inventory"))
    for index, control in enumerate(controls["controls"]):
        chapters = {ref["document_id"] for ref in control["source_refs"]
                    if ref["source_id"] == BOOK_SOURCE_ID}
        if any(f"walkinglabs-he-{alias[:3]}" not in chapters for alias in control["source_aliases"]):
            errors.append(ValidationError("CATALOG_PROVENANCE_MISSING",
                                          f"controls.json.controls[{index}].source_refs",
                                          "each book alias requires its chapter source reference"))
    expected_docs = {f"walkinglabs-he-L{chapter:02d}" for chapter in range(1, 15)}
    if (snapshots[0]["revision"] != {"kind": "git_commit", "value": BOOK_REVISION}
            or {d["id"] for d in snapshots[0]["documents"]} != expected_docs):
        errors.append(ValidationError("CATALOG_PROVENANCE_MISSING", "sources.json.source_snapshots",
                                      "the fixed book requires all fourteen documents at its pinned commit"))


def unique_json_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def reject_json_constant(value: str) -> None:
    raise ValueError("non-JSON number")


def load_json_document(path: Path, display_name: str) -> Tuple[Optional[Any], List[ValidationError]]:
    """Load one JSON document and return sanitized boundary errors."""
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise OSError("catalog input is not a regular file")
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, [
            ValidationError(
                code="CATALOG_FILE_MISSING",
                path=display_name,
                message="catalog file is missing",
            )
        ]
    except (OSError, UnicodeError, ValueError):
        return None, [
            ValidationError(
                code="CATALOG_FILE_UNREADABLE",
                path=display_name,
                message="catalog file could not be read as UTF-8",
            )
        ]

    try:
        return json.loads(content, object_pairs_hook=unique_json_object,
                          parse_constant=reject_json_constant), []
    except json.JSONDecodeError as error:
        return None, [
            ValidationError(
                code="CATALOG_JSON_INVALID",
                path=display_name,
                message=f"invalid JSON at line {error.lineno} column {error.colno}",
            )
        ]
    except (ValueError, RecursionError):
        return None, [ValidationError("CATALOG_JSON_INVALID", display_name,
                                      "invalid JSON structure, duplicate field, or non-JSON number")]


def validate_catalog(catalog_dir: Path) -> Sequence[ValidationError]:
    """Return deterministic validation findings without modifying catalog files."""
    errors: List[ValidationError] = []

    controls, controls_errors = load_json_document(catalog_dir / "controls.json", "controls.json")
    sources, sources_errors = load_json_document(catalog_dir / "sources.json", "sources.json")
    errors.extend(controls_errors)
    errors.extend(sources_errors)
    for schema_name in ("controls.schema.json", "sources.schema.json"):
        _, schema_errors = load_json_document(DEFAULT_CATALOG_DIR / schema_name, schema_name)
        errors.extend(schema_errors)

    controls_shape_errors: List[ValidationError] = []
    sources_shape_errors: List[ValidationError] = []
    if not controls_errors:
        validate_shape(controls, CONTROLS_DOCUMENT_SHAPE, "controls.json", controls_shape_errors)
        validate_schema_version(controls, "controls.json", controls_shape_errors)
        errors.extend(controls_shape_errors)
    if not sources_errors:
        validate_shape(sources, SOURCES_DOCUMENT_SHAPE, "sources.json", sources_shape_errors)
        validate_schema_version(sources, "sources.json", sources_shape_errors)
        errors.extend(sources_shape_errors)

    controls_are_trusted = not controls_errors and not controls_shape_errors
    sources_are_trusted = not sources_errors and not sources_shape_errors
    if controls_are_trusted:
        validate_controls_identity(controls, errors)
        validate_controls_policy(controls, errors)
        validate_control_semantics(controls, errors)
        validate_control_details(controls, errors)
    if sources_are_trusted:
        validate_sources_identity(sources, errors)
        validate_source_semantics(sources, errors)
        validate_nonempty_values(sources, "sources.json", errors)
    if controls_are_trusted and sources_are_trusted:
        validate_cross_file_references(controls, sources, errors)
        validate_book_dispositions(controls, sources, errors)

    return tuple(sorted(errors, key=lambda item: (item.path, item.code, item.message)))


def render_json(errors: Sequence[ValidationError]) -> str:
    payload = {
        "ok": not errors,
        "errors": [
            {"code": error.code, "path": error.path, "message": error.message}
            for error in errors
        ],
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


def render_human(errors: Sequence[ValidationError]) -> str:
    return "".join(f"{error.code} {error.path}: {error.message}\n" for error in errors)


class CatalogArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("invalid arguments; use --help for usage")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = CatalogArgumentParser(
        prog="validate_catalog.py",
        description="Validate the Harness Doctor control catalog.",
    )
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=DEFAULT_CATALOG_DIR,
        help="directory containing controls.json and sources.json",
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON result envelope")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(arguments)
    except ValueError:
        errors = [ValidationError("CATALOG_USAGE_INVALID", "arguments",
                                  "invalid arguments; use --help for usage")]
        if "--json" in arguments:
            sys.stdout.write(render_json(errors))
        else:
            sys.stderr.write(render_human(errors))
        return 2
    errors = validate_catalog(args.catalog_dir)

    if args.json:
        sys.stdout.write(render_json(errors))
    elif errors:
        sys.stderr.write(render_human(errors))
    else:
        sys.stdout.write("Catalog is valid.\n")

    if any(error.code in BOUNDARY_ERROR_CODES for error in errors):
        return 2
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
