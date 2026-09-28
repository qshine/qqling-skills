"""Validate Agent judgments; compute metrics without making semantic judgments."""

from collections import Counter
from typing import Any, Dict

from evidence_contract import validate_evidence
from evidence_quality import evidence_profile, evidence_summary
from safe_io import SafetyError, digest, sensitive

STATUSES = ("satisfied", "partial", "missing", "conflict", "unverifiable", "not_applicable")
REPORT_SCHEMA_VERSION = "1.1.0"


def seal(payload: dict) -> dict:
    return dict(payload, digest=digest(payload))


def verify_seal(payload: dict) -> None:
    if not isinstance(payload, dict) or payload.get("digest") != digest(
            {key: value for key, value in payload.items() if key != "digest"}):
        raise SafetyError("MANIFEST_CHANGED")


def active_controls(catalog: dict) -> dict:
    return {c["id"]: c for c in catalog["controls"] if c["lifecycle"]["status"] == "active"}


def coverage(rows: list) -> dict:
    counts = Counter(row["status"] for row in rows)
    applicable = len(rows) - counts["not_applicable"]
    return dict(satisfied=counts["satisfied"], applicable=applicable,
                percent=round(counts["satisfied"] * 100 / applicable, 2) if applicable else None,
                counts={status: counts[status] for status in STATUSES})


def assess(catalog: dict, evidence: dict, judgments: list,
           autonomy_enabled: bool = False) -> Dict[str, Any]:
    if (not isinstance(evidence, dict) or evidence.get("schema_version") != "1.0.0"
            or evidence.get("trust") != "untrusted_repository_data"
            or type(autonomy_enabled) is not bool or not isinstance(judgments, list)):
        raise SafetyError("ASSESSMENT_INPUT_INVALID")
    controls = active_controls(catalog)
    validate_evidence(evidence)
    files = {row["id"]: row for row in evidence["files"]}
    if len(files) != len(evidence["files"]):
        raise SafetyError("EVIDENCE_DUPLICATE")
    rows, seen = [], set()
    for judgment in judgments:
        required = {"control_id", "status", "rationale", "evidence"}
        if (not isinstance(judgment, dict) or not required <= set(judgment)
                or not set(judgment) <= required | {"evidence_trace"}
                or ("evidence_trace" in judgment and not isinstance(judgment["evidence_trace"], dict))):
            raise SafetyError("JUDGMENT_INVALID")
        control_id, status = judgment["control_id"], judgment["status"]
        if not isinstance(control_id, str) or control_id not in controls or control_id in seen:
            raise SafetyError("JUDGMENT_ID_INVALID")
        if status not in STATUSES:
            raise SafetyError("JUDGMENT_STATUS_INVALID")
        rationale = judgment["rationale"]
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 3000 or sensitive(rationale):
            raise SafetyError("JUDGMENT_RATIONALE_INVALID")
        refs = judgment["evidence"]
        if not isinstance(refs, list) or (status in {"satisfied", "partial"} and not refs):
            raise SafetyError("JUDGMENT_EVIDENCE_REQUIRED")
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"file_id", "line"}:
                raise SafetyError("EVIDENCE_REFERENCE_INVALID")
            if not isinstance(ref["file_id"], str):
                raise SafetyError("EVIDENCE_REFERENCE_INVALID")
            item = files.get(ref["file_id"])
            if item is None or item["read_status"] != "read":
                raise SafetyError("EVIDENCE_REFERENCE_INVALID")
            if ref["line"] is not None and (type(ref["line"]) is not int or ref["line"] not in
                                           {line["line"] for line in item["lines"]}):
                raise SafetyError("EVIDENCE_LINE_INVALID")
        seen.add(control_id)
        control = controls[control_id]
        profile = evidence_profile(refs, judgment.get("evidence_trace"), control["evidence"]["minimum_level"], status)
        row = dict(judgment, domain=control["domain"], maturity=control["maturity"],
                         is_gate=control["is_gate"], title=control["title"],
                         source_refs=control["source_refs"])
        row.update(profile)
        rows.append(row)
    if seen != set(controls):
        raise SafetyError("JUDGMENTS_INCOMPLETE")
    rows.sort(key=lambda row: row["control_id"])
    by_id = {row["control_id"]: row for row in rows}
    level, gates = "L0", []
    has_autonomy = any(row["domain"] in {"HD-AUT", "HD-GRF"} and row["status"] != "not_applicable"
                       for row in rows)
    for maturity in catalog["maturity_levels"][1:]:
        if maturity["id"] == "L4" and not (autonomy_enabled and has_autonomy):
            break
        applicable = [by_id[key] for key in maturity["gate_control_ids"]
                      if by_id[key]["status"] != "not_applicable"]
        blocked = [row["control_id"] for row in applicable if row["status"] != "satisfied"]
        gates.append(dict(level=maturity["id"], applicable=len(applicable), blocked_ids=blocked))
        # A wholly inapplicable repository never gets a maturity badge by vacuous truth.
        if blocked or (maturity["id"] == "L1" and not applicable):
            break
        level = maturity["id"]
    return seal(dict(schema_version=REPORT_SCHEMA_VERSION, catalog_version=catalog["catalog_version"],
                     root_id=evidence["repository"]["root_id"], evidence_digest=digest(evidence),
                     controls=rows, coverage=coverage(rows),
                     **evidence_summary(rows),
                     domains={domain: coverage([row for row in rows if row["domain"] == domain])
                              for domain in sorted({row["domain"] for row in rows})},
                     maturity=dict(level=level, autonomy_enabled=autonomy_enabled, gates=gates),
                     high_priority_ids=[row["control_id"] for row in rows if row["status"] == "conflict"
                                        or (row["maturity"] == "L4" and row["is_gate"] and row["status"]
                                            not in {"satisfied", "not_applicable"})]))
