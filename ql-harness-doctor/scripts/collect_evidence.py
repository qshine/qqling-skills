#!/usr/bin/env python3
"""Single-repository static evidence. No subprocesses, network, or application writes."""

import argparse
import itertools
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict

sys.dont_write_bytecode = True

from safe_io import (SafetyError, identity, open_directory, parse_json, read_at,
                     root_identity, safe_path, sensitive, sha)

LIMITS = dict(entries=10000, files=256, depth=12, file_bytes=65536, total_bytes=2097152,
              lines=120, line_chars=400, excerpt_chars=64000, git_bytes=8388608)
EXCLUDED_NAMES = {".git", "node_modules", "vendor", "dist", "build", "target", ".venv",
                  "venv", "__pycache__", ".cache", ".next", "coverage", "logs",
                  ".ssh", ".aws", ".azure", ".secrets", "secrets", "credentials",
                  ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519"}


def excluded(name: str) -> bool:
    lower = name.lower()
    return (lower in EXCLUDED_NAMES or lower.startswith(".env") or
            bool(re.search(r"(?:secret|credential|private[-_]?key)", lower)) or
            lower.endswith((".pem", ".key", ".p12", ".pfx", ".log", ".db", ".sqlite")))


def classify(path: str) -> tuple:
    p = Path(path)
    name, lower = p.name, p.name.lower()
    parts = {part.lower() for part in p.parts[:-1]}
    categories = set()
    text = p.suffix.lower() in {".md", ".mdx", ".rst", ".txt"}
    if lower in {"agents.md", "claude.md", ".cursorrules"} or parts & {"rules", ".agents", ".claude"}:
        categories.add("agent_instruction")
        text |= lower == ".cursorrules" or p.suffix.lower() == ".mdc"
    if lower.startswith(("readme", "contributing")) or "docs" in parts:
        categories.add("project_documentation")
    if re.search(r"architect|adr|decision", lower) or parts & {"adr", "decisions"}:
        categories.add("architecture_decision")
    if re.search(r"^(spec|plan|todo|progress|handoff|feature_list|constraints)", lower) or parts & {"tasks", ".harness"}:
        categories.add("task_state")
        text |= p.suffix.lower() == ".json"
    if name in {"package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "Gemfile"}:
        categories.add("package_manifest")
        text = True
    if lower in {".python-version", ".node-version", ".nvmrc", ".tool-versions", "rust-toolchain.toml"}:
        categories.add("toolchain")
        text = True
    if lower in {"makefile", "justfile", "taskfile.yml"}:
        categories.add("task_runner")
        text = True
    if re.search(r"test|pytest|eslint|ruff|mypy|tsconfig|check", lower) or parts & {"tests", "test", "checks"}:
        categories.add("verification")
        if lower in {"pytest.ini", "tox.ini", "ruff.toml", "mypy.ini", "tsconfig.json", ".eslintrc.json"}:
            text = True
    if ".github" in parts and "workflows" in parts:
        categories.add("ci_configuration")
        text = p.suffix.lower() in {".yml", ".yaml"}
    if re.search(r"automat|workflow|schedule|workspace", lower):
        categories.add("automation")
    if re.search(r"observ|telemetry|logging|metric", lower):
        categories.add("observability")
    if re.search(r"maintenan|cleanup|hygiene", lower):
        categories.add("maintenance")
    if lower in {"automation.yaml", "automation.yml", "workspace.json", "schedule.yaml", "schedule.yml",
                 "logging.yaml", "logging.yml", "observability.yaml", "observability.yml", "telemetry.json",
                 "maintenance.yaml", "maintenance.yml", "hygiene.json"}:
        text = True
    return sorted(categories), text


def command_declarations(name: str, text: str, file_id: str) -> list:
    declarations = []
    if name == "package.json":
        data = parse_json(text)
        if not isinstance(data, dict) or not isinstance(data.get("scripts", {}), dict):
            raise SafetyError("DECLARATION_UNPARSED")
        candidates = [(key, None, "package_script") for key, value in data.get("scripts", {}).items()
                      if isinstance(value, str)]
    elif name.lower() in {"makefile", "justfile"}:
        candidates = []
        for number, line in enumerate(text.splitlines(), 1):
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*:(?![=:])[^=]*", line)
            if match:
                candidates.append((match[1], number, "static_target"))
    else:
        return []
    for key, number, kind in candidates:
        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", key) and not sensitive(key):
            declarations.append(dict(file_id=file_id, name=key, line=number, kind=kind, executed=False))
    return declarations


def git_metadata(fd: int, kind: str) -> dict:
    result = dict(marker_kind=kind, metadata_status="unverifiable", head_sha256=None,
                  index_sha256=None, worktree_status="unverifiable", reason="GIT_STATUS_NOT_EXECUTED")
    if kind == "directory":
        try:
            git_fd = open_directory(".git", fd)
            try:
                for name, key in (("HEAD", "head_sha256"), ("index", "index_sha256")):
                    try:
                        result[key] = sha(read_at(git_fd, name, LIMITS["git_bytes"])[0])
                    except (OSError, SafetyError):
                        pass  # Null and metadata_status explicitly represent unavailable metadata.
            finally:
                os.close(git_fd)
        except OSError:
            pass
        if result["head_sha256"] and result["index_sha256"]:
            result["metadata_status"] = "available"
    else:
        result["reason"] = "EXTERNAL_GIT_METADATA_NOT_FOLLOWED"
    return result


def collect_evidence(repository_root: Path) -> Dict[str, Any]:
    try:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise SafetyError("PLATFORM_UNSUPPORTED")
        root = repository_root.resolve(strict=True)
        if root in {Path(root.anchor), Path.home()}:
            raise SafetyError("ROOT_INVALID")
        fd = open_directory(root)
    except (OSError, ValueError, RuntimeError) as error:
        code = str(error) if isinstance(error, SafetyError) else (
            "ROOT_UNREADABLE" if isinstance(error, PermissionError) else "ROOT_INVALID")
        return {"ok": False, "evidence": None, "errors": [
            dict(code="EVIDENCE_" + code, path="repo", message="Cannot safely open repository root.")]}
    try:
        root_info = os.fstat(fd)
        try:
            marker = os.stat(".git", dir_fd=fd, follow_symlinks=False)
            if not (stat.S_ISDIR(marker.st_mode) or stat.S_ISREG(marker.st_mode)):
                raise SafetyError("ROOT_INVALID")
        except (OSError, SafetyError):
            return {"ok": False, "evidence": None, "errors": [dict(
                code="EVIDENCE_ROOT_INVALID", path="repo", message="Expected an explicit worktree root.")]}
        bundle = dict(schema_version="1.0.0", collector_version="0.1.0", policy_version="0.1.0",
                      trust="untrusted_repository_data", repository=dict(
                          root=".", root_id=root_identity(root, root_info),
                          git=git_metadata(fd, "directory" if stat.S_ISDIR(marker.st_mode) else "file")),
                      scan=dict(scope=".", complete_within_policy=True, limits=dict(LIMITS),
                                entries_seen=0, files_reported=0, bytes_read=0, excerpt_chars=0,
                                excluded_counts={}), files=[], commands=[], limitations=[])
        scan = bundle["scan"]

        def limitation(code, path, impact="policy_exclusion"):
            counts = scan["excluded_counts"]
            counts[code] = counts.get(code, 0) + 1
            if impact == "scan_incomplete":
                scan["complete_within_policy"] = False
            bundle["limitations"].append(dict(code=code, path=path, impact=impact, message=code))

        def file_entry(directory, name, path, info):
            categories, with_text = classify(path)
            if not categories:
                return
            if len(bundle["files"]) >= LIMITS["files"]:
                limitation("FILE_COUNT_LIMIT", path, "scan_incomplete")
                return
            row = dict(id="EV-" + sha(path.encode()), path=path, scope=str(Path(path).parent),
                       categories=categories, read_status="metadata_only", size_bytes=info.st_size,
                       mtime_ns=info.st_mtime_ns, sha256=None, lines=[], excerpt_truncated=False)
            bundle["files"].append(row)
            if not with_text:
                return
            try:
                remaining = min(LIMITS["file_bytes"], LIMITS["total_bytes"] - scan["bytes_read"])
                data, _ = read_at(directory, name, remaining)
                scan["bytes_read"] += len(data)
                text = data.decode("utf-8")
                if "\x00" in text:
                    raise UnicodeError()
                if sensitive(text):
                    row["read_status"] = "withheld_sensitive"
                    limitation("SENSITIVE_CONTENT", path, "content_unavailable")
                    return
                row.update(read_status="read", sha256=sha(data))
                try:
                    bundle["commands"].extend(command_declarations(name, text, row["id"]))
                except SafetyError:
                    limitation("DECLARATION_UNPARSED", path, "content_unavailable")
                lines = text.splitlines()
                for number, line in enumerate(lines[:LIMITS["lines"]], 1):
                    available = max(0, LIMITS["excerpt_chars"] - scan["excerpt_chars"])
                    cleaned = "".join(c if ord(c) >= 32 and ord(c) != 127 else " " for c in line)
                    shown = cleaned[:min(LIMITS["line_chars"], available)]
                    if shown or not line:
                        row["lines"].append(dict(line=number, text=shown))
                    scan["excerpt_chars"] += len(shown)
                    row["excerpt_truncated"] |= len(shown) != len(line)
                row["excerpt_truncated"] |= len(lines) > LIMITS["lines"]
            except (OSError, UnicodeError, SafetyError) as error:
                row["read_status"] = "unreadable"
                code = str(error) if isinstance(error, SafetyError) else "CONTENT_UNREADABLE"
                limitation(code, path, "scan_incomplete")

        def walk(directory, prefix, depth):
            try:
                with os.scandir(directory) as entries:
                    remaining = LIMITS["entries"] - scan["entries_seen"]
                    names = [entry.name for entry in itertools.islice(entries, remaining + 1)]
                if len(names) > remaining:
                    limitation("ENTRY_LIMIT", prefix or ".", "scan_incomplete")
                    return
                scan["entries_seen"] += len(names)
                for name in sorted(names):
                    path = prefix + name
                    if not safe_path(path):
                        limitation("UNSAFE_NAME", None)
                        continue
                    if excluded(name):
                        limitation("EXCLUDED_NAME", path)
                        continue
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or info.st_dev != root_info.st_dev:
                        limitation("LINK_OR_DEVICE_BOUNDARY", path)
                    elif stat.S_ISDIR(info.st_mode):
                        if depth >= LIMITS["depth"]:
                            limitation("DEPTH_LIMIT", path, "scan_incomplete")
                            continue
                        child = open_directory(name, directory)
                        try:
                            try:
                                os.stat(".git", dir_fd=child, follow_symlinks=False)
                            except FileNotFoundError:
                                walk(child, path + "/", depth + 1)
                            else:
                                limitation("NESTED_REPOSITORY", path)
                            if (os.fstat(child).st_ino != info.st_ino or
                                    os.stat(name, dir_fd=directory, follow_symlinks=False).st_ino != info.st_ino):
                                limitation("DIRECTORY_CHANGED", path, "scan_incomplete")
                        finally:
                            os.close(child)
                    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        file_entry(directory, name, path, info)
                    else:
                        limitation("SPECIAL_OR_HARDLINK", path)
            except OSError:
                limitation("DIRECTORY_UNREADABLE", prefix or ".", "scan_incomplete")

        walk(fd, "", 0)
        try:
            if os.stat(root).st_ino != root_info.st_ino:
                limitation("ROOT_CHANGED", ".", "scan_incomplete")
        except OSError:
            limitation("ROOT_CHANGED", ".", "scan_incomplete")
        scan["files_reported"] = len(bundle["files"])
        bundle["files"].sort(key=lambda row: row["path"])
        bundle["commands"].sort(key=lambda row: (row["file_id"], row["name"], row["line"] or 0))
        bundle["limitations"].sort(key=lambda item: (item["path"] or "", item["code"]))
        return dict(ok=True, evidence=bundle, errors=[])
    finally:
        os.close(fd)


class EvidenceArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SafetyError("EVIDENCE_USAGE_INVALID")


def main() -> int:
    parser = EvidenceArgumentParser(prog="collect_evidence.py", description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args()
    except SafetyError:
        result = dict(ok=False, evidence=None, errors=[dict(code="EVIDENCE_USAGE_INVALID",
                      path="arguments", message="Invalid arguments; use --help.")])
        print(json.dumps(result) if "--json" in sys.argv else "Invalid arguments; use --help.")
        return 2
    result = collect_evidence(args.repo)
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        if result["ok"]:
            print("Scope: .; evidence files: " + str(len(result["evidence"]["files"])) +
                  "; complete within policy: " + str(result["evidence"]["scan"]["complete_within_policy"]))
            print("Limitations: " + ", ".join(sorted({item["code"] for item in result["evidence"]["limitations"]})))
        else:
            print("Repository unavailable: " + result["errors"][0]["code"])
    return 2 if not result["ok"] else (0 if result["evidence"]["scan"]["complete_within_policy"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
