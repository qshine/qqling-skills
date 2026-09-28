"""Bounded local I/O shared by the evidence and change boundaries."""

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Tuple


class SafetyError(ValueError):
    """A stable code, never an exception containing untrusted content."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SafetyError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise SafetyError("JSON_INVALID_NUMBER")


def finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise SafetyError("JSON_INVALID_NUMBER")
    return number


def parse_json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant, parse_float=finite_float)
    except (ValueError, RecursionError) as error:
        raise SafetyError("JSON_INVALID") from error


def sensitive(text: str) -> bool:
    return bool(re.search(
        r"(?i)(-----BEGIN [\w ]*PRIVATE KEY|(?:AKIA|ASIA)[A-Z0-9]{16}|"
        r"(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}|https?://[^\s/]+:[^\s/]+@|"
        r"(?:api[_-]?key|password|secret|access[_-]?token|auth[_-]?token)\s*[\"']?\s*[:=]\s*\S+|"
        r"/(?:Users|home)/[^\s/]+/)", text))


def safe_path(value: str) -> bool:
    return (isinstance(value, str) and bool(value) and len(value) <= 1024
            and not value.startswith("/") and "\\" not in value
            and all(part not in {"", ".", ".."} for part in value.split("/"))
            and not any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF
                        or 0x202A <= ord(c) <= 0x202E for c in value)
            and not sensitive(value))


def identity(info: os.stat_result) -> Tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_directory(name: Any, parent_fd: int = None) -> int:
    if not hasattr(os, "O_NOFOLLOW") or os.name != "posix":
        raise SafetyError("PLATFORM_UNSUPPORTED")
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)


def read_at(parent_fd: int, name: str, limit: int) -> Tuple[bytes, os.stat_result]:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise SafetyError("UNSAFE_FILE")
    if before.st_size > limit:
        raise SafetyError("SIZE_LIMIT")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if identity(info) != identity(before) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SafetyError("FILE_CHANGED")
        chunks, length = [], 0
        while length <= limit:
            part = os.read(fd, min(65536, limit + 1 - length))
            if not part:
                break
            chunks.append(part)
            length += len(part)
        if length > limit:
            raise SafetyError("SIZE_LIMIT")
        if identity(info) != identity(os.fstat(fd)) or identity(info) != identity(
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)):
            raise SafetyError("FILE_CHANGED")
        return b"".join(chunks), info
    finally:
        os.close(fd)


def root_identity(root: Path, info: os.stat_result) -> str:
    return digest([str(root), info.st_dev, info.st_ino])
