#!/usr/bin/env python3
"""Harness Doctor: deterministic boundaries for an Agent-guided single-repository workflow."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

# Imports remain read-only even when callers omit Python's -B flag.
sys.dont_write_bytecode = True

from changes import apply_preview, preview
from collect_evidence import collect_evidence
from diagnostic import assess
from safe_io import SafetyError, open_directory, parse_json, read_at, root_identity
from selection import recommend, select
from validate_catalog import validate_catalog

MAX_REQUEST_BYTES = 4194304
CATALOG_DIR = Path(__file__).resolve().parents[1] / "references/catalog"


class DoctorArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SafetyError("USAGE_INVALID")


def read_request(name: str, root: Path) -> dict:
    if name == "-":
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    else:
        path = Path(name)
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise SafetyError("REQUEST_MUST_BE_OUTSIDE_TARGET")
        fd = open_directory(path.absolute().parent)
        try:
            raw, _ = read_at(fd, path.name, MAX_REQUEST_BYTES)
        finally:
            os.close(fd)
    if len(raw) > MAX_REQUEST_BYTES:
        raise SafetyError("REQUEST_TOO_LARGE")
    value = parse_json(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise SafetyError("REQUEST_OBJECT_REQUIRED")
    return value


def require_fields(value: dict, required: set, optional: set = frozenset()) -> None:
    if not required <= set(value) or not set(value) <= required | optional:
        raise SafetyError("REQUEST_FIELDS_INVALID")


def require_root(root: Path, bound_id: str) -> None:
    resolved = root.resolve(strict=True)
    fd = open_directory(resolved)
    try:
        if bound_id != root_identity(resolved, os.fstat(fd)):
            raise SafetyError("REPOSITORY_MISMATCH")
    finally:
        os.close(fd)


def dispatch(command: str, root: Path, request: dict, confirmation: str = "") -> dict:
    if validate_catalog(CATALOG_DIR):
        raise SafetyError("CATALOG_INVALID")
    catalog = parse_json((CATALOG_DIR / "controls.json").read_text(encoding="utf-8"))
    if command == "assess":
        require_fields(request, {"evidence", "judgments"}, {"autonomy_enabled"})
        evidence = request["evidence"]
        require_root(root, evidence["repository"]["root_id"])
        return assess(catalog, evidence, request["judgments"], request.get("autonomy_enabled", False))
    if command == "recommend":
        require_fields(request, {"report"})
        require_root(root, request["report"]["root_id"])
        return recommend(catalog, request["report"])
    if command == "select":
        require_fields(request, {"report", "selected_ids"})
        require_root(root, request["report"]["root_id"])
        return select(catalog, request["report"], request["selected_ids"])
    if command == "preview":
        require_fields(request, {"selection", "edits", "checks"})
        return preview(root, request["selection"], request["edits"], request["checks"])
    if command == "apply":
        require_fields(request, {"manifest"})
        return apply_preview(root, request["manifest"], confirmation)
    raise SafetyError("USAGE_INVALID")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = DoctorArgumentParser(prog="doctor.py", description=__doc__)
    parser.add_argument("command", choices=["scan", "assess", "recommend", "select", "preview", "apply"])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="one explicit Git worktree root")
    parser.add_argument("--request", default="-", help="JSON on stdin (-), or a file outside the target repository")
    parser.add_argument("--confirm", default="", help="apply only: digest of the preview explicitly approved by the user")
    parser.add_argument("--json", action="store_true", help="compatibility flag; output is always JSON")
    try:
        args = parser.parse_args(argv)
        if args.command != "apply" and args.confirm:
            raise SafetyError("USAGE_INVALID")
        if args.command == "scan":
            if args.request != "-":
                raise SafetyError("USAGE_INVALID")
            result = collect_evidence(args.repo)
            code = 2 if not result["ok"] else (0 if result["evidence"]["scan"]["complete_within_policy"] else 1)
        else:
            output = dispatch(args.command, args.repo, read_request(args.request, args.repo), args.confirm)
            ok = args.command != "apply" or output["ok"]
            result = dict(ok=ok, result=output, errors=[] if ok else output["errors"])
            code = 0 if ok else 1
    except SafetyError as error:
        result, code = dict(ok=False, result=None, errors=[str(error)]), 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        # Boundary errors must never echo a path, input content, or OS exception.
        result, code = dict(ok=False, result=None, errors=["INPUT_INVALID_OR_UNAVAILABLE"]), 2
    print(json.dumps(result, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
