"""Validate evidence attribution without executing or authenticating Agent claims."""

from collections import Counter
from datetime import datetime
import re
from typing import Optional, Tuple

from safe_io import SafetyError, sensitive

EVIDENCE_LEVELS = ("none", "unclassified", "declared", "recorded", "verified")
MINIMUM_LEVELS = EVIDENCE_LEVELS[2:]
VERIFICATION_OUTCOMES = ("confirmed", "contradicted", "inconclusive")
MAX_REFERENCES = 256


def reference_key(ref: dict) -> Tuple[str, Optional[int]]:
    if (not isinstance(ref, dict) or set(ref) != {"file_id", "line"}
            or not isinstance(ref["file_id"], str) or not re.fullmatch(r"EV-[0-9a-f]{64}", ref["file_id"])
            or (ref["line"] is not None and (type(ref["line"]) is not int or ref["line"] < 1))):
        raise SafetyError("EVIDENCE_REFERENCE_INVALID")
    return ref["file_id"], ref["line"]


def reference_keys(refs: list) -> set:
    if not isinstance(refs, list) or len(refs) > MAX_REFERENCES:
        raise SafetyError("EVIDENCE_REFERENCES_INVALID")
    keys = [reference_key(ref) for ref in refs]
    if len(set(keys)) != len(keys):
        raise SafetyError("EVIDENCE_REFERENCE_DUPLICATE")
    return set(keys)


def check_text(value: str) -> None:
    if (not isinstance(value, str) or not value.strip() or len(value) > 2000
            or sensitive(value) or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise SafetyError("VERIFICATION_TEXT_INVALID")


def check_time(value: str) -> None:
    if (not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value)):
        raise SafetyError("VERIFICATION_TIME_INVALID")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise SafetyError("VERIFICATION_TIME_INVALID") from error


def evidence_profile(refs: list, trace: Optional[dict], minimum: str, status: str) -> dict:
    """Return trace and strength; never infer a semantic status or run a check."""
    available = reference_keys(refs)
    if minimum not in MINIMUM_LEVELS:
        raise SafetyError("EVIDENCE_MINIMUM_INVALID")
    if trace is None:
        trace = dict(declarations=[], execution_records=[], result_checks=[])
    if not isinstance(trace, dict) or set(trace) != {"declarations", "execution_records", "result_checks"}:
        raise SafetyError("EVIDENCE_TRACE_INVALID")
    declared = reference_keys(trace["declarations"])
    recorded = reference_keys(trace["execution_records"])
    if not (declared | recorded) <= available:
        raise SafetyError("EVIDENCE_TRACE_REFERENCE_INVALID")
    if declared & recorded:
        raise SafetyError("EVIDENCE_CATEGORY_OVERLAP")
    checks = trace["result_checks"]
    if not isinstance(checks, list) or len(checks) > MAX_REFERENCES:
        raise SafetyError("VERIFICATION_CHECKS_INVALID")
    seen = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {
                "record", "observation", "method", "scope", "checked_at", "outcome", "limitations"}:
            raise SafetyError("VERIFICATION_CHECK_INVALID")
        record, observation = reference_key(check["record"]), reference_key(check["observation"])
        if (record not in recorded or observation not in available
                or record[1] is None or observation[1] is None
                or observation == record or observation in declared):
            raise SafetyError("VERIFICATION_REFERENCE_INVALID")
        if (record, observation) in seen:
            raise SafetyError("VERIFICATION_DUPLICATE")
        seen.add((record, observation))
        if check["method"] not in ("record_cross_check", "reproduction"):
            raise SafetyError("VERIFICATION_METHOD_INVALID")
        if check["outcome"] not in VERIFICATION_OUTCOMES:
            raise SafetyError("VERIFICATION_OUTCOME_INVALID")
        check_text(check["scope"])
        check_text(check["limitations"])
        check_time(check["checked_at"])

    level = "unclassified" if available else "none"
    if declared:
        level = "declared"
    if recorded:
        level = "recorded"
    confirmed = bool(checks) and all(check["outcome"] == "confirmed" for check in checks)
    if checks and all(check["outcome"] != "inconclusive" for check in checks):
        level = "verified"
    if status == "satisfied":
        if checks and not confirmed:
            raise SafetyError("VERIFICATION_NOT_CONFIRMED")
        if EVIDENCE_LEVELS.index(level) < EVIDENCE_LEVELS.index(minimum):
            raise SafetyError("EVIDENCE_LEVEL_INSUFFICIENT")
    return dict(evidence_trace=trace, evidence_level=level, minimum_evidence_level=minimum)


def evidence_summary(rows: list) -> dict:
    """Count control strengths separately from the outcomes of individual checks."""
    strengths = Counter(row["evidence_level"] for row in rows)
    outcomes = Counter(check["outcome"] for row in rows for check in row["evidence_trace"]["result_checks"])
    return dict(evidence_levels={level: strengths[level] for level in EVIDENCE_LEVELS},
                verification_outcomes={outcome: outcomes[outcome] for outcome in VERIFICATION_OUTCOMES})
