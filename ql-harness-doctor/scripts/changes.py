"""Preview and apply bounded, additive Harness changes after explicit confirmation."""

import ast
import difflib
import json
import os
import selectors
import stat
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from collect_evidence import collect_evidence, excluded
from diagnostic import active_controls, seal, verify_seal
from safe_io import (SafetyError, digest, identity, open_directory, parse_json,
                     read_at, root_identity, safe_path, sensitive, sha)

MAX_BYTES = 65536
MAX_PREVIEW_BYTES = 3145728
CHECKS = {"utf8", "json", "python_ast"}


def git_read(root: Path, arguments: list) -> tuple:
    """Fixed builtin metadata queries only; bound output and disable executable extensions."""
    env = dict(PATH="/usr/bin:/bin", LANG="C", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_OPTIONAL_LOCKS="0",
               GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")
    command = ["/usr/bin/git", "--no-optional-locks", "--no-replace-objects",
               "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"] + arguments
    with subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        chunks, length, deadline = [], 0, time.monotonic() + 5
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise SafetyError("GIT_SNAPSHOT_TIMEOUT")
                    for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                        part = os.read(key.fileobj.fileno(), 65536)
                        if not part:
                            selector.unregister(key.fileobj)
                            continue
                        length += len(part)
                        if length > 8388608:
                            raise SafetyError("GIT_SNAPSHOT_TOO_LARGE")
                        chunks.append(part)
                return process.wait(timeout=max(0.01, deadline - time.monotonic())), b"".join(chunks)
        except (OSError, SafetyError, subprocess.TimeoutExpired):
            process.kill()
            process.wait()
            raise SafetyError("GIT_SNAPSHOT_UNAVAILABLE") from None


def git_snapshot(root: Path) -> str:
    code, top = git_read(root, ["rev-parse", "--show-toplevel"])
    if code or top.rstrip(b"\n") != os.fsencode(str(root)):
        raise SafetyError("GIT_ROOT_MISMATCH")
    branch_code, branch = git_read(root, ["symbolic-ref", "--quiet", "HEAD"])
    head_code, head = git_read(root, ["rev-parse", "--verify", "HEAD"])
    index_code, index = git_read(root, ["ls-files", "--stage", "-z"])
    if index_code or branch_code not in {0, 1} or (head_code and (head_code != 128 or branch_code)):
        raise SafetyError("GIT_SNAPSHOT_UNAVAILABLE")
    return digest([branch_code, sha(branch), head_code, sha(head), sha(index)])


def allowed_target(path: str) -> bool:
    if not safe_path(path) or any(excluded(part) for part in path.split("/")):
        return False
    if path in {"AGENTS.md", "CLAUDE.md", "README.md", "CONSTRAINTS.md"}:
        return True
    parts = path.split("/")
    return (len(parts) > 1 and parts[0] in {"docs", "tasks", ".harness"}
            and (path.endswith(".md") or (parts[0] in {"tasks", ".harness"} and path.endswith(".json"))
                 or (len(parts) == 3 and parts[:2] == [".harness", "checks"] and path.endswith(".py"))))


@contextmanager
def parent_directory(root_fd: int, path: str, create: bool = False):
    fd = os.dup(root_fd)
    try:
        for part in path.split("/")[:-1]:
            try:
                child = open_directory(part, fd)
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                os.mkdir(part, 0o755, dir_fd=fd)
                child = open_directory(part, fd)
            if os.fstat(child).st_dev != os.fstat(root_fd).st_dev:
                os.close(child)
                raise SafetyError("CROSS_DEVICE_TARGET")
            try:
                os.stat(".git", dir_fd=child, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                os.close(child)
                raise SafetyError("NESTED_REPOSITORY_TARGET")
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def before_bytes(root_fd: int, path: str) -> bytes:
    with parent_directory(root_fd, path) as parent:
        if parent is None:
            return None
        try:
            data, _ = read_at(parent, path.split("/")[-1], MAX_BYTES)
        except FileNotFoundError:
            return None
        if sensitive(data.decode("utf-8", errors="replace")):
            raise SafetyError("SENSITIVE_TARGET")
        return data


def check_bytes(path: str, data: bytes, checks: list) -> list:
    text = data.decode("utf-8")
    if "\x00" in text or sensitive(text):
        raise SafetyError("CONTENT_UNSAFE")
    result = [dict(path=path, kind="utf8", passed=True)]
    if path.endswith(".json") and "json" in checks:
        parse_json(text)
        result.append(dict(path=path, kind="json", passed=True))
    if path.endswith(".py") and "python_ast" in checks:
        ast.parse(text, filename="<proposed-check>")
        result.append(dict(path=path, kind="python_ast", passed=True))
    return result


def full_diff(path: str, before: bytes, after: bytes) -> str:
    old = before.decode("utf-8").splitlines(keepends=True) if before is not None else []
    lines = difflib.unified_diff(old, after.decode("utf-8").splitlines(keepends=True),
                                 fromfile="a/" + path if before is not None else "/dev/null",
                                 tofile="b/" + path)
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                   for line in lines)


def preview(root: Path, selection: dict, edits: list, checks: list) -> dict:
    verify_seal(selection)
    catalog = parse_json((Path(__file__).resolve().parents[1] / "references/catalog/controls.json").read_text())
    controls = active_controls(catalog)
    ids = selection.get("selected_ids")
    if (selection.get("schema_version") != "1.0.0" or selection.get("catalog_version") != catalog["catalog_version"]
            or selection.get("ready") is not True or selection.get("required_ids") or selection.get("conflicts")
            or not isinstance(ids, list) or not ids or any(not isinstance(key, str) or key not in controls
                or controls[key]["maturity"] == "L4" for key in ids) or len(ids) != len(set(ids))):
        raise SafetyError("SELECTION_NOT_READY")
    if any(value == "conflict" for value in selection.get("selected_statuses", {}).values()):
        raise SafetyError("CONFLICT_REQUIRES_MANUAL_RESOLUTION")
    if (not isinstance(edits, list) or not 1 <= len(edits) <= 64 or not isinstance(checks, list)
            or any(not isinstance(check, str) or check not in CHECKS for check in checks)):
        raise SafetyError("PREVIEW_INPUT_INVALID")
    checks = sorted(set(checks) | {"utf8"} | {"json" for edit in edits if isinstance(edit, dict)
                                           and str(edit.get("path", "")).endswith(".json")}
                    | {"python_ast" for edit in edits if isinstance(edit, dict)
                       and str(edit.get("path", "")).endswith(".py")})
    try:
        root = root.resolve(strict=True)
        bundle = collect_evidence(root)
        if not bundle["ok"] or not bundle["evidence"]["scan"]["complete_within_policy"]:
            raise SafetyError("BASELINE_INCOMPLETE")
        evidence = bundle["evidence"]
        if (selection.get("root_id") != evidence["repository"]["root_id"]
                or selection.get("evidence_digest") != digest(evidence)):
            raise SafetyError("BASELINE_CHANGED")
        baseline = dict(evidence_digest=digest(evidence), git=git_snapshot(root))
        fd = open_directory(root)
        normalized, seen, covered, diffs = [], set(), set(), []
        try:
            for edit in edits:
                if not isinstance(edit, dict) or set(edit) != {"path", "mode", "content", "control_ids"}:
                    raise SafetyError("EDIT_INVALID")
                path, mode, content, mapped = (edit[key] for key in ("path", "mode", "content", "control_ids"))
                if (not allowed_target(path) or path in seen or mode not in ("create", "append")
                        or not isinstance(content, str) or not content or len(content.encode("utf-8")) > MAX_BYTES
                        or not isinstance(mapped, list) or not mapped or any(not isinstance(key, str) for key in mapped)
                        or len(mapped) != len(set(mapped)) or not set(mapped) <= set(ids)):
                    raise SafetyError("EDIT_OUT_OF_SCOPE")
                before = before_bytes(fd, path)
                if (mode == "create") != (before is None) or (mode == "append" and path.endswith(".py")):
                    raise SafetyError("EDIT_MODE_MISMATCH")
                after = (before or b"") + content.encode("utf-8")
                if len(after) > MAX_BYTES:
                    raise SafetyError("SIZE_LIMIT")
                check_bytes(path, after, checks)
                normalized.append(dict(edit, control_ids=sorted(mapped),
                                       before_sha256=sha(before) if before is not None else None,
                                       after_sha256=sha(after)))
                diffs.append((path, full_diff(path, before, after)))
                seen.add(path)
                covered.update(mapped)
            if covered != set(ids):
                raise SafetyError("SELECTED_CONTROL_UNMAPPED")
        finally:
            os.close(fd)
        manifest = seal(dict(schema_version="1.0.0", catalog_version=catalog["catalog_version"],
                             root_id=selection["root_id"], selection=selection, baseline=baseline,
                             edits=sorted(normalized, key=lambda edit: edit["path"]), checks=checks,
                             diff="".join(diff for _, diff in sorted(diffs))))
        # Leave headroom under the CLI's input budget for the subsequent apply request.
        if len(json.dumps(manifest, ensure_ascii=True).encode()) > MAX_PREVIEW_BYTES:
            raise SafetyError("PREVIEW_TOO_LARGE")
        return manifest
    except (OSError, UnicodeError, SyntaxError):
        raise SafetyError("PREVIEW_UNSAFE_OR_UNAVAILABLE") from None


def write_edit(root_fd: int, edit: dict) -> None:
    path = edit["path"]
    with parent_directory(root_fd, path, create=True) as parent:
        name = path.split("/")[-1]
        before = before_bytes(root_fd, path)
        if (sha(before) if before is not None else None) != edit["before_sha256"]:
            raise SafetyError("TARGET_CHANGED")
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        flags |= os.O_CREAT | os.O_EXCL if edit["mode"] == "create" else os.O_APPEND
        fd = os.open(name, flags, 0o644, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SafetyError("UNSAFE_FILE")
            if edit["mode"] == "append":
                data = os.read(fd, MAX_BYTES + 1)
                if sha(data) != edit["before_sha256"]:
                    raise SafetyError("TARGET_CHANGED")
            if identity(info) != identity(os.stat(name, dir_fd=parent, follow_symlinks=False)):
                raise SafetyError("TARGET_CHANGED")
            data = edit["content"].encode("utf-8")
            while data:
                written = os.write(fd, data)
                if written <= 0:
                    raise SafetyError("WRITE_INCOMPLETE")
                data = data[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        after = before_bytes(root_fd, path)
        if after is None or sha(after) != edit["after_sha256"]:
            raise SafetyError("WRITE_VERIFICATION_FAILED")


def apply_preview(root: Path, manifest: dict, confirmed_digest: str) -> dict:
    verify_seal(manifest)
    if not confirmed_digest or confirmed_digest != manifest["digest"]:
        raise SafetyError("CONFIRMATION_REQUIRED")
    try:
        edits = [{key: edit[key] for key in ("path", "mode", "content", "control_ids")}
                 for edit in manifest["edits"]]
        fresh = preview(root, manifest["selection"], edits, manifest["checks"])
        if fresh != manifest:
            raise SafetyError("PREVIEW_STALE")
    except (KeyError, TypeError):
        raise SafetyError("PREVIEW_INVALID") from None
    root = root.resolve(strict=True)
    fd = open_directory(root)
    applied, checks = [], []
    try:
        if root_identity(root, os.fstat(fd)) != manifest["root_id"]:
            raise SafetyError("ROOT_CHANGED")
        for edit in manifest["edits"]:
            try:
                write_edit(fd, edit)
                applied.append(edit["path"])
                checks.extend(check_bytes(edit["path"], before_bytes(fd, edit["path"]), manifest["checks"]))
            except (OSError, SafetyError, UnicodeError, SyntaxError):
                return dict(ok=False, applied_paths=applied, failed_path=edit["path"], checks=checks,
                            errors=["APPLY_PARTIAL_FAILURE"],
                            recovery="Stop. Inspect applied paths and the failed path (possibly partially written), "
                                     "including any new parent directories. No automatic rollback was performed.")
    finally:
        os.close(fd)
    return dict(ok=True, applied_paths=applied, checks=checks, errors=[],
                recovery="No rollback performed. Rescan and reassess; static checks do not establish compliance.")
