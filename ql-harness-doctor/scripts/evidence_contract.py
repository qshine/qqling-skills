"""Validate the bundled evidence schema subset and cross-field provenance invariants."""

import re
from pathlib import Path
from typing import Any

from safe_io import SafetyError, digest, parse_json, safe_path, sensitive, sha

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "references/evidence.schema.json"


def check_schema(value: Any, schema: dict, document: dict) -> None:
    """Only the keywords used by our bundled schema; not a general JSON Schema engine."""
    if "$ref" in schema:
        check_schema(value, document["$defs"][schema["$ref"].split("/")[-1]], document)
        return
    types = dict(object=dict, array=list, string=str, integer=int, boolean=bool, null=type(None))
    wanted = schema.get("type", [])
    wanted = [wanted] if isinstance(wanted, str) else wanted
    if wanted and not any(type(value) is types[name] for name in wanted):
        raise SafetyError("EVIDENCE_SHAPE_INVALID")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise SafetyError("EVIDENCE_CONSTANT_INVALID")
    if "enum" in schema and value not in schema["enum"]:
        raise SafetyError("EVIDENCE_ENUM_INVALID")
    if type(value) is int and value < schema.get("minimum", value):
        raise SafetyError("EVIDENCE_RANGE_INVALID")
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)):
            raise SafetyError("EVIDENCE_RANGE_INVALID")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise SafetyError("EVIDENCE_PATTERN_INVALID")
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", len(value)):
            raise SafetyError("EVIDENCE_RANGE_INVALID")
        if schema.get("uniqueItems") and len({digest(item) for item in value}) != len(value):
            raise SafetyError("EVIDENCE_DUPLICATE")
        for item in value:
            check_schema(item, schema["items"], document)
    if isinstance(value, dict):
        if not set(schema.get("required", [])) <= set(value):
            raise SafetyError("EVIDENCE_FIELDS_INVALID")
        for key, item in value.items():
            child = schema.get("properties", {}).get(key, schema.get("additionalProperties", True))
            if child is False:
                raise SafetyError("EVIDENCE_FIELDS_INVALID")
            if isinstance(child, dict):
                check_schema(item, child, document)


def validate_evidence(evidence: dict) -> None:
    schema = parse_json(SCHEMA_PATH.read_text(encoding="utf-8"))
    check_schema(evidence, schema, schema)
    files = {}
    for row in evidence["files"]:
        if (not safe_path(row["path"]) or row["scope"] != str(Path(row["path"]).parent)
                or row["id"] != "EV-" + sha(row["path"].encode()) or row["id"] in files):
            raise SafetyError("EVIDENCE_IDENTITY_INVALID")
        files[row["id"]] = row
        numbers = [line["line"] for line in row["lines"]]
        if numbers != sorted(set(numbers)) or any(sensitive(line["text"]) for line in row["lines"]):
            raise SafetyError("EVIDENCE_LINES_INVALID")
        if row["read_status"] == "read":
            if row["sha256"] is None:
                raise SafetyError("EVIDENCE_HASH_REQUIRED")
        elif row["lines"] or row["sha256"] is not None:
            raise SafetyError("EVIDENCE_UNREAD_CONTENT")
    if len(files) != evidence["scan"]["files_reported"]:
        raise SafetyError("EVIDENCE_COUNT_MISMATCH")
    for command in evidence["commands"]:
        if command["file_id"] not in files or files[command["file_id"]]["read_status"] != "read":
            raise SafetyError("EVIDENCE_COMMAND_INVALID")
    for limitation in evidence["limitations"]:
        if limitation["path"] not in {None, "."} and not safe_path(limitation["path"]):
            raise SafetyError("EVIDENCE_LIMITATION_INVALID")
