"""Group actionable gaps and record explicit control choices, never implicit scope expansion."""

from diagnostic import REPORT_SCHEMA_VERSION, STATUSES, active_controls, seal, verify_seal
from evidence_quality import evidence_profile, evidence_summary
from safe_io import SafetyError, sensitive


def report_controls(catalog: dict, report: dict) -> dict:
    verify_seal(report)
    if report.get("schema_version") != REPORT_SCHEMA_VERSION or report.get("catalog_version") != catalog["catalog_version"]:
        raise SafetyError("REPORT_VERSION_MISMATCH")
    if not isinstance(report.get("controls"), list):
        raise SafetyError("REPORT_CONTROLS_INVALID")
    controls = active_controls(catalog)
    for row in report["controls"]:
        if (not isinstance(row, dict) or not isinstance(row.get("control_id"), str)
                or row["control_id"] not in controls or row.get("status") not in STATUSES
                or not isinstance(row.get("rationale"), str) or sensitive(row["rationale"])
                or not isinstance(row.get("evidence"), list)):
            raise SafetyError("REPORT_CONTROLS_INVALID")
        control = controls[row["control_id"]]
        if any(row.get(key) != control[key] for key in ("title", "domain", "maturity", "is_gate", "source_refs")):
            raise SafetyError("REPORT_CATALOG_MISMATCH")
        if not isinstance(row.get("evidence_trace"), dict):
            raise SafetyError("REPORT_EVIDENCE_INVALID")
        profile = evidence_profile(row["evidence"], row["evidence_trace"],
                                   control["evidence"]["minimum_level"], row["status"])
        if any(row.get(key) != value for key, value in profile.items()):
            raise SafetyError("REPORT_EVIDENCE_MISMATCH")
    rows = {row["control_id"]: row for row in report["controls"]}
    if len(rows) != len(report["controls"]) or set(rows) != set(active_controls(catalog)):
        raise SafetyError("REPORT_CONTROLS_INVALID")
    for name, expected in evidence_summary(list(rows.values())).items():
        actual = report.get(name)
        if (not isinstance(actual, dict) or actual != expected
                or any(type(value) is not int for value in actual.values())):
            raise SafetyError("REPORT_EVIDENCE_SUMMARY_INVALID")
    return rows


def recommend(catalog: dict, report: dict) -> list:
    rows = report_controls(catalog, report)
    groups = []
    for domain in catalog["domains"]:
        items = []
        for key, control in active_controls(catalog).items():
            row = rows[key]
            if control["domain"] != domain["id"] or row["status"] in {"satisfied", "not_applicable"}:
                continue
            items.append(dict(control_id=key, title=control["title"], status=row["status"],
                              rationale=row["rationale"], evidence=row["evidence"],
                              evidence_trace=row["evidence_trace"], evidence_level=row["evidence_level"],
                              minimum_evidence_level=row["minimum_evidence_level"],
                              dependencies=control["dependencies"], remediation=control["remediation"],
                              automatic_changes=control["maturity"] != "L4" and row["status"] != "conflict"))
        if items:
            groups.append(dict(domain=domain["id"], title=domain["title"], items=items))
    return groups


def select(catalog: dict, report: dict, selected_ids: list) -> dict:
    rows = report_controls(catalog, report)
    controls = active_controls(catalog)
    if (not isinstance(selected_ids, list) or any(not isinstance(key, str) for key in selected_ids)
            or len(set(selected_ids)) != len(selected_ids)):
        raise SafetyError("SELECTION_INVALID")
    selected = set(selected_ids)
    if not selected <= set(controls):
        raise SafetyError("SELECTION_UNKNOWN_CONTROL")
    required, conflicts = set(), set()
    for key in selected:
        control = controls[key]
        if control["maturity"] == "L4":
            raise SafetyError("L4_DESIGN_ONLY")
        if rows[key]["status"] in {"satisfied", "not_applicable"}:
            raise SafetyError("SELECTION_NOT_A_GAP")
        for dependency in control["dependencies"]:
            if dependency not in selected and rows[dependency]["status"] not in {"satisfied", "not_applicable"}:
                required.add(dependency)
        for other in control["conflicts_with"]:
            if other in selected or rows[other]["status"] == "satisfied":
                conflicts.add(tuple(sorted((key, other))))
    return seal(dict(schema_version="1.0.0", catalog_version=catalog["catalog_version"],
                     root_id=report["root_id"], evidence_digest=report["evidence_digest"],
                     report_digest=report["digest"], selected_ids=sorted(selected),
                     selected_statuses={key: rows[key]["status"] for key in sorted(selected)},
                     required_ids=sorted(required), conflicts=[list(pair) for pair in sorted(conflicts)],
                     ready=bool(selected) and not required and not conflicts))
