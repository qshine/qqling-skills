"""Discover installed Skills and reconstruct observed usage from session logs."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import sys
from typing import Any, Iterable, Sequence
from uuid import uuid4


COVERAGE_NOTICE = (
    "Counts include only verifiable Skill loads in retained, parseable logs; "
    "ordinary mentions are excluded and zero is not evidence of lifetime non-use."
)
PARSER_VERSION = "2"


@dataclass(frozen=True)
class SkillInfo:
    name: str
    path: Path
    skill_md: Path
    managed_root: Path
    protected: bool
    protection_reason: str | None
    fingerprint: str
    description: str = ""


@dataclass(frozen=True)
class UsageEvent:
    event_key: str
    skill_path: str
    skill_name: str
    used_at: str
    source_type: str
    source_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    parser_version: str = PARSER_VERSION
    occurrence_index: int = 0


@dataclass(frozen=True)
class ScanResult:
    events: list[UsageEvent]
    warning_count: int
    files_scanned: int
    supported_records: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillStats:
    skill: SkillInfo
    uses: int
    latest_observed_at: str | None = None
    tasks: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)
    daily_counts: list[int] = field(default_factory=list)
    recommendation: str = "observe"
    recommendation_reason: str = ""
    overlaps_with: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditCandidate:
    candidate_id: str
    name: str
    path: str
    uses: int
    latest_observed_at: str | None = None
    fingerprint: str = ""
    protected: bool = False
    protection_reason: str | None = None
    recommendation: str = "observe"
    recommendation_reason: str = ""
    overlaps_with: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditReport:
    report_id: str
    created_at: str
    expires_at: str
    candidates: list[AuditCandidate]
    window_days: int = 30
    max_uses: int = 1
    expiry_days: int = 7
    skill_roots: list[str] = field(default_factory=list)
    scanned_skill_roots: list[str] = field(default_factory=list)
    session_roots: list[str] = field(default_factory=list)
    scanned_session_roots: list[str] = field(default_factory=list)
    skipped_default_roots: list[str] = field(default_factory=list)
    files_scanned: int = 0
    warning_count: int = 0
    supported_records: int = 0
    coverage_status: str = "none"
    coverage_notice: str = COVERAGE_NOTICE


@dataclass(frozen=True)
class RemovalRecord:
    report_id: str
    candidate_id: str
    original_path: str
    quarantine_path: str
    removed_at: str
    restored_at: str | None


class StateStore:
    """SQLite-backed event and frozen-audit storage."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    event_key TEXT PRIMARY KEY,
                    skill_path TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    parser_version TEXT NOT NULL DEFAULT '',
                    occurrence_index INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._migrate_usage_events(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_reports (
                    report_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS removals (
                    report_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    quarantine_path TEXT NOT NULL,
                    removed_at TEXT NOT NULL,
                    restored_at TEXT,
                    PRIMARY KEY (report_id, candidate_id)
                )
                """
            )

    def add_events(self, events: Sequence[UsageEvent]) -> int:
        inserted = 0
        with self._connect() as connection:
            for event in events:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO usage_events
                        (event_key, skill_path, skill_name, used_at, source,
                         source_type, source_id, session_id, turn_id,
                         parser_version, occurrence_index)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_key,
                        event.skill_path,
                        event.skill_name,
                        event.used_at,
                        event.source_type,
                        event.source_type,
                        event.source_id,
                        event.session_id,
                        event.turn_id,
                        event.parser_version,
                        event.occurrence_index,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def save_report(self, report: AuditReport) -> None:
        payload = {
            "report_id": report.report_id,
            "created_at": report.created_at,
            "expires_at": report.expires_at,
            "window_days": report.window_days,
            "max_uses": report.max_uses,
            "expiry_days": report.expiry_days,
            "skill_roots": report.skill_roots,
            "scanned_skill_roots": report.scanned_skill_roots,
            "session_roots": report.session_roots,
            "scanned_session_roots": report.scanned_session_roots,
            "skipped_default_roots": report.skipped_default_roots,
            "files_scanned": report.files_scanned,
            "warning_count": report.warning_count,
            "supported_records": report.supported_records,
            "coverage_status": report.coverage_status,
            "coverage_notice": report.coverage_notice,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "name": candidate.name,
                    "path": candidate.path,
                    "uses": candidate.uses,
                    "latest_observed_at": candidate.latest_observed_at,
                    "fingerprint": candidate.fingerprint,
                    "protected": candidate.protected,
                    "protection_reason": candidate.protection_reason,
                    "recommendation": candidate.recommendation,
                    "recommendation_reason": candidate.recommendation_reason,
                    "overlaps_with": candidate.overlaps_with,
                }
                for candidate in report.candidates
            ],
        }
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO audit_reports (report_id, payload) VALUES (?, ?)",
                (report.report_id, json.dumps(payload, sort_keys=True)),
            )

    def load_report(self, report_id: str) -> AuditReport:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM audit_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        if row is None:
            raise KeyError(report_id)
        payload = json.loads(row[0])
        return AuditReport(
            report_id=payload["report_id"],
            created_at=payload["created_at"],
            expires_at=payload["expires_at"],
            candidates=[
                AuditCandidate(
                    candidate_id=candidate["candidate_id"],
                    name=candidate["name"],
                    path=candidate["path"],
                    uses=candidate["uses"],
                    latest_observed_at=candidate.get("latest_observed_at"),
                    fingerprint=candidate.get("fingerprint", ""),
                    protected=candidate.get("protected", False),
                    protection_reason=candidate.get("protection_reason"),
                    recommendation=candidate.get("recommendation", "observe"),
                    recommendation_reason=candidate.get(
                        "recommendation_reason", ""
                    ),
                    overlaps_with=list(candidate.get("overlaps_with", [])),
                )
                for candidate in payload["candidates"]
            ],
            window_days=payload.get("window_days", 30),
            max_uses=payload.get("max_uses", 1),
            expiry_days=payload.get("expiry_days", 7),
            skill_roots=list(payload.get("skill_roots", [])),
            scanned_skill_roots=list(payload.get("scanned_skill_roots", [])),
            session_roots=list(payload.get("session_roots", [])),
            scanned_session_roots=list(payload.get("scanned_session_roots", [])),
            skipped_default_roots=list(payload.get("skipped_default_roots", [])),
            files_scanned=payload.get("files_scanned", 0),
            warning_count=payload.get("warning_count", 0),
            supported_records=payload.get("supported_records", 0),
            coverage_status=payload.get("coverage_status", "none"),
            coverage_notice=payload.get("coverage_notice", COVERAGE_NOTICE),
        )

    def save_removals(self, records: Sequence[RemovalRecord]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO removals
                    (report_id, candidate_id, original_path, quarantine_path,
                     removed_at, restored_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.report_id,
                        record.candidate_id,
                        record.original_path,
                        record.quarantine_path,
                        record.removed_at,
                        record.restored_at,
                    )
                    for record in records
                ],
            )

    def load_removal(self, report_id: str, candidate_id: str) -> RemovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT report_id, candidate_id, original_path, quarantine_path,
                       removed_at, restored_at
                FROM removals
                WHERE report_id = ? AND candidate_id = ?
                """,
                (report_id, candidate_id),
            ).fetchone()
        if row is None:
            raise KeyError((report_id, candidate_id))
        return RemovalRecord(*row)

    def mark_restored(
        self, report_id: str, candidate_id: str, restored_at: str
    ) -> RemovalRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE removals
                SET restored_at = ?
                WHERE report_id = ? AND candidate_id = ? AND restored_at IS NULL
                """,
                (restored_at, report_id, candidate_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("candidate is not available to restore")
            row = connection.execute(
                """
                SELECT report_id, candidate_id, original_path, quarantine_path,
                       removed_at, restored_at
                FROM removals
                WHERE report_id = ? AND candidate_id = ?
                """,
                (report_id, candidate_id),
            ).fetchone()
            if row is None:
                raise KeyError((report_id, candidate_id))
            return RemovalRecord(*row)

    def events_between(
        self,
        start: datetime,
        end: datetime,
        *,
        include_manual: bool = False,
    ) -> list[UsageEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, skill_path, skill_name, used_at,
                       COALESCE(NULLIF(source_type, ''), source), source_id,
                       session_id, turn_id, parser_version, occurrence_index
                FROM usage_events
                WHERE COALESCE(NULLIF(source_type, ''), source) != 'legacy_observed'
                """
            ).fetchall()
        events: list[UsageEvent] = []
        for row in rows:
            event = UsageEvent(*row)
            if event.source_type == "manual" and not include_manual:
                continue
            try:
                used_at = _as_datetime(event.used_at)
            except (TypeError, ValueError):
                continue
            if start <= used_at <= end:
                events.append(event)
        return events

    @staticmethod
    def _migrate_usage_events(connection: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(usage_events)")
        }
        additions = {
            "source_type": "TEXT NOT NULL DEFAULT ''",
            "source_id": "TEXT NOT NULL DEFAULT ''",
            "session_id": "TEXT NOT NULL DEFAULT ''",
            "turn_id": "TEXT NOT NULL DEFAULT ''",
            "parser_version": "TEXT NOT NULL DEFAULT ''",
            "occurrence_index": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE usage_events ADD COLUMN {name} {declaration}"
                )
        connection.execute(
            """
            UPDATE usage_events
            SET source_type = CASE
                WHEN source = 'manual' THEN 'manual'
                ELSE 'legacy_observed'
            END,
                parser_version = CASE
                    WHEN source = 'manual' THEN 'manual'
                    ELSE '1'
                END
            WHERE source_type = ''
            """
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def record_manual_use(
    store: StateStore,
    skill: SkillInfo,
    *,
    used_at: datetime | str,
    event_id: str | None = None,
) -> bool:
    """Record a manually supplied use and return whether it was new."""
    if not isinstance(skill, SkillInfo):
        raise TypeError("skill must be a SkillInfo")
    skill_path = str(skill.path)
    skill_name = skill.name
    used_at_text = _as_datetime(used_at).isoformat()
    if event_id is None:
        event_id = sha256(
            "\0".join(("manual", skill_path, skill_name, used_at_text)).encode("utf-8")
        ).hexdigest()
    event = UsageEvent(
        event_key=str(event_id),
        skill_path=skill_path,
        skill_name=skill_name,
        used_at=used_at_text,
        source_type="manual",
        source_id=str(event_id),
        session_id=f"manual:{event_id}",
        turn_id=f"manual:{event_id}",
        parser_version="manual",
    )
    return store.add_events([event]) == 1


def collect_stats(
    store,
    skills,
    *,
    now,
    window_days,
    include_manual: bool = False,
    coverage_status: str = "complete",
) -> list[SkillStats]:
    """Return observed rolling-window usage for each supplied Skill."""
    ending_at = _as_datetime(now)
    starting_at = ending_at - timedelta(days=window_days)
    events = store.events_between(
        datetime.min.replace(tzinfo=timezone.utc),
        ending_at,
        include_manual=include_manual,
    )
    uses_by_path: dict[str, int] = {}
    latest_by_path: dict[str, datetime] = {}
    tasks_by_path: dict[str, set[str]] = {}
    sources_by_path: dict[str, Counter[str]] = {}
    daily_by_path: dict[str, Counter[str]] = {}
    for event in events:
        observed_at = _as_datetime(event.used_at)
        if observed_at >= starting_at:
            uses_by_path[event.skill_path] = uses_by_path.get(event.skill_path, 0) + 1
            tasks_by_path.setdefault(event.skill_path, set()).add(
                event.session_id or event.source_id
            )
            sources_by_path.setdefault(event.skill_path, Counter()).update(
                [event.source_type]
            )
            daily_by_path.setdefault(event.skill_path, Counter()).update(
                [observed_at.date().isoformat()]
            )
        if observed_at > latest_by_path.get(event.skill_path, datetime.min.replace(tzinfo=timezone.utc)):
            latest_by_path[event.skill_path] = observed_at
    overlaps = _overlap_map(skills)
    day_keys = [
        (ending_at.date() - timedelta(days=offset)).isoformat()
        for offset in reversed(range(min(window_days, 14)))
    ]
    stats_rows: list[SkillStats] = []
    for skill in skills:
        path = str(skill.path)
        recommendation, reason = _recommendation(
            skill,
            uses_by_path.get(path, 0),
            coverage_status=coverage_status,
            overlaps_with=overlaps.get(path, []),
        )
        stats_rows.append(SkillStats(
            skill=skill,
            uses=uses_by_path.get(path, 0),
            latest_observed_at=(
                latest_by_path[path].isoformat()
                if path in latest_by_path
                else None
            ),
            tasks=len(tasks_by_path.get(path, set())),
            source_counts=dict(sorted(sources_by_path.get(path, Counter()).items())),
            daily_counts=[daily_by_path.get(path, Counter()).get(day, 0) for day in day_keys],
            recommendation=recommendation,
            recommendation_reason=reason,
            overlaps_with=overlaps.get(path, []),
        ))
    return stats_rows


def _coverage_status(scan: ScanResult, skipped_roots: Sequence[Path]) -> str:
    if scan.files_scanned == 0 or scan.supported_records == 0:
        return "none"
    if scan.warning_count or skipped_roots:
        return "partial"
    return "complete"


def _overlap_map(skills: Sequence[SkillInfo]) -> dict[str, list[str]]:
    overlaps: dict[str, set[str]] = {str(skill.path): set() for skill in skills}
    eligible = [skill for skill in skills if not skill.protected and skill.description]
    for index, skill in enumerate(eligible):
        for other in eligible[index + 1 :]:
            if _description_similarity(skill.description, other.description) < 0.82:
                continue
            overlaps[str(skill.path)].add(other.name)
            overlaps[str(other.path)].add(skill.name)
    return {path: sorted(names) for path, names in overlaps.items() if names}


def _description_similarity(left: str, right: str) -> float:
    def normalize(value: str) -> str:
        return " ".join(value.lower().split())

    normalized_left = normalize(left)
    normalized_right = normalize(right)
    if min(len(normalized_left), len(normalized_right)) < 24:
        return 0.0
    sequence = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    left_tokens = set(re.findall(r"[\w-]{3,}", normalized_left))
    right_tokens = set(re.findall(r"[\w-]{3,}", normalized_right))
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    return max(sequence, jaccard)


def _recommendation(
    skill: SkillInfo,
    uses: int,
    *,
    coverage_status: str,
    overlaps_with: Sequence[str],
) -> tuple[str, str]:
    if skill.protected:
        return "keep", skill.protection_reason or "protected Skill"
    if overlaps_with and uses <= 1:
        return "merge_check", "similar scope: " + ", ".join(overlaps_with)
    if uses >= 2:
        return "keep", "repeated verifiable loads in the selected window"
    if uses == 1:
        return "observe", "one verifiable load in the selected window"
    if coverage_status != "complete":
        return "observe", "no observed loads, but log coverage is incomplete"
    return "consider_remove", "no observed loads in the complete scanned window"


def _sparkline(values: Sequence[int]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not values or max(values) == 0:
        return blocks[0] * max(1, len(values))
    maximum = max(values)
    return "".join(blocks[round(value * (len(blocks) - 1) / maximum)] for value in values)


def _bar_chart(stats: Sequence[SkillStats], *, width: int = 24) -> str:
    rows = [item for item in stats if item.uses > 0]
    if not rows:
        return "No verifiable Skill loads observed in this window."
    maximum = max(item.uses for item in rows)
    name_width = min(32, max(len(item.skill.name) for item in rows))
    lines = []
    for item in rows:
        bar_width = max(1, round(item.uses * width / maximum))
        name = item.skill.name[:name_width].ljust(name_width)
        lines.append(f"{name}  {'█' * bar_width} {item.uses}")
    return "\n".join(lines)


def create_audit(
    store,
    skills,
    *,
    now,
    window_days=30,
    max_uses=1,
    expiry_days=7,
    skill_roots: Sequence[Path] = (),
    scanned_skill_roots: Sequence[Path] = (),
    session_roots: Sequence[Path] = (),
    scanned_session_roots: Sequence[Path] = (),
    skipped_default_roots: Sequence[Path] = (),
    files_scanned: int = 0,
    warning_count: int = 0,
    supported_records: int = 0,
    coverage_status: str = "complete",
    coverage_notice: str = COVERAGE_NOTICE,
) -> AuditReport:
    """Freeze the current low-use, unprotected Skill candidates in SQLite."""
    created_at = _as_datetime(now)
    stats_rows = collect_stats(
        store,
        skills,
        now=created_at,
        window_days=window_days,
        coverage_status=coverage_status,
    )
    candidates = [
        AuditCandidate(
            candidate_id=_candidate_id(stats.skill),
            name=stats.skill.name,
            path=str(stats.skill.path),
            uses=stats.uses,
            latest_observed_at=stats.latest_observed_at,
            fingerprint=stats.skill.fingerprint,
            protected=stats.skill.protected,
            protection_reason=stats.skill.protection_reason,
            recommendation=stats.recommendation,
            recommendation_reason=stats.recommendation_reason,
            overlaps_with=stats.overlaps_with,
        )
        for stats in stats_rows
        if not stats.skill.protected and stats.uses <= max_uses
    ]
    candidates.sort(key=lambda candidate: (candidate.uses, candidate.name, candidate.path))
    report = AuditReport(
        report_id=uuid4().hex,
        created_at=created_at.isoformat(),
        expires_at=(created_at + timedelta(days=expiry_days)).isoformat(),
        candidates=candidates,
        window_days=window_days,
        max_uses=max_uses,
        expiry_days=expiry_days,
        skill_roots=[str(Path(path)) for path in skill_roots],
        scanned_skill_roots=[str(Path(path)) for path in scanned_skill_roots],
        session_roots=[str(Path(path)) for path in session_roots],
        scanned_session_roots=[str(Path(path)) for path in scanned_session_roots],
        skipped_default_roots=[str(Path(path)) for path in skipped_default_roots],
        files_scanned=files_scanned,
        warning_count=warning_count,
        supported_records=supported_records,
        coverage_status=coverage_status,
        coverage_notice=coverage_notice,
    )
    store.save_report(report)
    return report


def expected_confirmation(report_id: str, candidate_ids: Sequence[str]) -> str:
    return " ".join(("CONFIRM SKILL REMOVAL", report_id, *sorted(candidate_ids)))


def remove_candidates(
    store: StateStore,
    report_id: str,
    candidate_ids: Sequence[str],
    confirmation: str,
    *,
    managed_roots: Sequence[Path],
    now: datetime,
) -> list[RemovalRecord]:
    """Move exactly confirmed report candidates out of active Skill roots."""
    selected_ids = list(candidate_ids)
    if not selected_ids:
        raise ValueError("at least one candidate must be selected")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("duplicate candidate IDs are not allowed")
    if selected_ids != sorted(selected_ids):
        raise ValueError("candidate IDs must be sorted")
    if not _valid_report_id(report_id):
        raise ValueError("report ID must be a 32-character lowercase hexadecimal token")

    report = store.load_report(report_id)
    if report.report_id != report_id:
        raise ValueError("report ID does not match persisted report")
    if _as_datetime(now) >= _as_datetime(report.expires_at):
        raise ValueError("audit report has expired")
    if confirmation != expected_confirmation(report_id, selected_ids):
        raise ValueError("exact confirmation does not match the selected candidates")

    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in report.candidates
    }
    if len(candidates_by_id) != len(report.candidates):
        raise ValueError("audit report contains duplicate candidate IDs")

    canonical_roots = [Path(root).resolve() for root in managed_roots]
    preflighted: list[tuple[AuditCandidate, Path, Path]] = []
    for candidate_id in selected_ids:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {candidate_id}")
        if candidate.protected:
            raise ValueError(f"candidate is protected: {candidate_id}")
        try:
            store.load_removal(report_id, candidate_id)
        except KeyError:
            pass
        else:
            raise ValueError(f"candidate already removed: {candidate_id}")

        reported_path = Path(candidate.path)
        try:
            skill_path = reported_path.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"candidate fingerprint changed: {candidate_id}") from error
        if str(skill_path) != candidate.path:
            raise ValueError(f"candidate path changed: {candidate_id}")
        if not any(_is_within(skill_path, root) for root in canonical_roots):
            raise ValueError(f"candidate is outside every managed root: {candidate_id}")
        protected, _ = _protection_for(skill_path, candidate.name)
        if protected:
            raise ValueError(f"candidate is protected: {candidate_id}")

        skill_md = skill_path / "SKILL.md"
        if not skill_path.is_dir() or not skill_md.is_file():
            raise ValueError(f"candidate fingerprint changed: {candidate_id}")
        current_skill = SkillInfo(
            name=candidate.name,
            path=skill_path,
            skill_md=skill_md,
            managed_root=skill_path,
            protected=False,
            protection_reason=None,
            fingerprint=_fingerprint(skill_md),
        )
        if candidate.fingerprint and candidate.fingerprint != current_skill.fingerprint:
            raise ValueError(f"candidate fingerprint changed: {candidate_id}")
        if _candidate_id(current_skill) != candidate_id:
            raise ValueError(f"candidate fingerprint changed: {candidate_id}")

        destination = _quarantine_destination(store, report_id, candidate_id)
        preflighted.append((candidate, skill_path, destination))

    selected_paths = [source for _, source, _ in preflighted]
    for index, source in enumerate(selected_paths):
        for other in selected_paths[index + 1 :]:
            if _is_within(source, other) or _is_within(other, source):
                raise ValueError(f"selected candidate paths overlap: {source} and {other}")
    for candidate, source, _ in preflighted:
        own_skill_md = source / "SKILL.md"
        if any(path != own_skill_md for path in source.rglob("SKILL.md")):
            raise ValueError(
                f"candidate contains a nested Skill and cannot be removed: "
                f"{candidate.candidate_id}"
            )

    removed_at = _as_datetime(now).isoformat()
    records = [
        RemovalRecord(
            report_id=report_id,
            candidate_id=candidate.candidate_id,
            original_path=str(source),
            quarantine_path=str(destination),
            removed_at=removed_at,
            restored_at=None,
        )
        for candidate, source, destination in preflighted
    ]
    moved: list[tuple[Path, Path]] = []
    try:
        for _, source, destination in preflighted:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append((source, destination))
        store.save_removals(records)
    except BaseException:
        rollback_error = _rollback_moves(moved)
        if rollback_error is not None:
            raise RuntimeError(
                f"removal failed and rollback was incomplete: {rollback_error}"
            ) from rollback_error
        raise
    return records


def restore_candidate(
    store: StateStore,
    report_id: str,
    candidate_id: str,
) -> RemovalRecord:
    """Restore one quarantined candidate without overwriting its original path."""
    if not _valid_report_id(report_id):
        raise ValueError("report ID must be a 32-character lowercase hexadecimal token")
    if not _valid_candidate_id(candidate_id):
        raise ValueError("candidate ID must be a 64-character lowercase hexadecimal token")

    report = store.load_report(report_id)
    if report.report_id != report_id:
        raise ValueError("report ID does not match persisted report")
    candidates = [
        candidate for candidate in report.candidates
        if candidate.candidate_id == candidate_id
    ]
    if len(candidates) != 1:
        raise ValueError("candidate is unknown or duplicated in the persisted report")
    candidate = candidates[0]

    record = store.load_removal(report_id, candidate_id)
    if record.restored_at is not None:
        raise ValueError("candidate has already been restored")

    source = _expected_quarantine_source(store, report_id, candidate_id)
    destination = Path(candidate.path)
    if (
        record.quarantine_path != str(source)
        or record.original_path != str(destination)
    ):
        raise ValueError("persisted removal paths do not match the audit report")
    _require_real_directory_ancestry(destination.parent, "original parent")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"restore target exists: {destination}")

    shutil.move(str(source), str(destination))
    try:
        return store.mark_restored(
            report_id,
            candidate_id,
            datetime.now(timezone.utc).isoformat(),
        )
    except BaseException:
        rollback_error = _rollback_moves([(source, destination)])
        if rollback_error is not None:
            raise RuntimeError(
                f"restore failed and rollback was incomplete: {rollback_error}"
            ) from rollback_error
        raise


def _rollback_moves(moved: Sequence[tuple[Path, Path]]) -> BaseException | None:
    rollback_error: BaseException | None = None
    for source, destination in reversed(moved):
        try:
            if source.exists() or source.is_symlink():
                raise FileExistsError(f"rollback target is occupied: {source}")
            if not destination.exists() or destination.is_symlink():
                raise FileNotFoundError(f"rollback source is not a real path: {destination}")
            shutil.move(str(destination), str(source))
            if (
                not source.exists()
                or source.is_symlink()
                or source.resolve(strict=True) != source
                or destination.exists()
                or destination.is_symlink()
            ):
                raise RuntimeError(
                    f"rollback postcondition failed for {destination} -> {source}"
                )
        except BaseException as error:
            if rollback_error is None:
                rollback_error = error
    return rollback_error


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _valid_report_id(report_id: str) -> bool:
    return (
        isinstance(report_id, str)
        and len(report_id) == 32
        and all(character in "0123456789abcdef" for character in report_id)
    )


def _valid_candidate_id(candidate_id: str) -> bool:
    return (
        isinstance(candidate_id, str)
        and len(candidate_id) == 64
        and all(character in "0123456789abcdef" for character in candidate_id)
    )


def _quarantine_destination(
    store: StateStore, report_id: str, candidate_id: str
) -> Path:
    state_parent = store.path.parent.resolve(strict=True)
    quarantine_root = state_parent / "quarantine"
    report_root = quarantine_root / report_id
    destination = report_root / candidate_id
    for ancestor in (quarantine_root, report_root):
        if ancestor.is_symlink():
            raise ValueError(f"quarantine ancestry contains a symlink: {ancestor}")
        if ancestor.exists() and not ancestor.is_dir():
            raise FileExistsError(f"quarantine ancestor is not a directory: {ancestor}")
    if destination.is_symlink():
        raise ValueError(f"quarantine destination is a symlink: {destination}")
    if destination.exists():
        raise FileExistsError(f"quarantine destination exists: {destination}")
    return destination


def _expected_quarantine_source(
    store: StateStore, report_id: str, candidate_id: str
) -> Path:
    state_parent = store.path.parent.resolve(strict=True)
    quarantine_root = state_parent / "quarantine"
    report_root = quarantine_root / report_id
    source = report_root / candidate_id
    _require_real_directory_ancestry(report_root, "quarantine")
    if source.is_symlink():
        raise ValueError(f"quarantine source is a symlink: {source}")
    if not source.is_dir() or source.resolve(strict=True) != source:
        raise ValueError(f"quarantine source is not the expected real directory: {source}")
    return source


def _require_real_directory_ancestry(path: Path, label: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute: {path}")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"{label} ancestry contains a symlink: {current}")
        if not current.is_dir():
            raise ValueError(f"{label} ancestry is not a real directory: {current}")
    if path.resolve(strict=True) != path:
        raise ValueError(f"{label} ancestry is not canonical: {path}")


def _candidate_id(skill: SkillInfo) -> str:
    material = "\0".join((str(skill.path), skill.fingerprint))
    return sha256(material.encode("utf-8")).hexdigest()


def _as_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _valid_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        _as_datetime(value)
    except (TypeError, ValueError):
        return None
    return value


def discover_skills(roots: Sequence[Path]) -> list[SkillInfo]:
    """Return every directory containing SKILL.md beneath the supplied roots."""
    discovered: list[SkillInfo] = []
    seen_paths: set[Path] = set()
    for supplied_root in roots:
        root = Path(supplied_root).resolve()
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md"), key=lambda path: str(path)):
            if not skill_md.is_file():
                continue
            skill_path = skill_md.parent.resolve()
            if skill_path in seen_paths:
                continue
            seen_paths.add(skill_path)
            canonical_skill_md = skill_path / "SKILL.md"
            name, description = _skill_metadata(canonical_skill_md)
            name = name or skill_path.name
            protected, protection_reason = _protection_for(skill_path, name)
            discovered.append(
                SkillInfo(
                    name=name,
                    path=skill_path,
                    skill_md=canonical_skill_md,
                    managed_root=root,
                    protected=protected,
                    protection_reason=protection_reason,
                    fingerprint=_fingerprint(canonical_skill_md),
                    description=description,
                )
            )
    return discovered


def scan_session_logs(
    session_roots: Sequence[Path], skills: Sequence[SkillInfo]
) -> ScanResult:
    """Find every verifiable Skill load in retained session logs."""
    events: list[UsageEvent] = []
    event_keys: set[str] = set()
    warning_count = 0
    files_scanned = 0
    supported_records = 0
    source_counts: Counter[str] = Counter()
    skills_by_skill_md = {str(skill.skill_md.resolve()): skill for skill in skills}

    for log_path in _session_log_files(session_roots):
        files_scanned += 1
        session_id = ""
        turn_id = ""
        session_timestamp = ""
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            warning_count += 1
            continue

        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                warning_count += 1
                continue
            if not isinstance(record, dict):
                continue

            record_type, payload = _record_type_and_payload(record)
            if record_type == "session_meta" and isinstance(payload, dict):
                session_timestamp = ""
                identifier = payload.get("id")
                if isinstance(identifier, str):
                    session_id = identifier
                    turn_id = identifier
                timestamp = _valid_timestamp(record.get("timestamp"))
                if timestamp is not None:
                    session_timestamp = timestamp
                continue
            if record_type == "turn_context" and isinstance(payload, dict):
                active_turn = payload.get("turn_id")
                if isinstance(active_turn, str):
                    turn_id = active_turn
                continue
            if record_type != "response_item" or not isinstance(payload, dict):
                continue

            payload_type = payload.get("type")
            if payload_type == "message" and payload.get("role") == "user":
                supported_records += 1
                observed = [
                    (path, "injected_skill")
                    for path in _injected_skill_loads(payload, skills_by_skill_md)
                ]
            elif payload_type in {"function_call", "custom_tool_call"}:
                supported_records += 1
                observed = _classified_skill_loads(payload, skills_by_skill_md)
            else:
                continue
            if not observed:
                continue

            active_session = session_id or log_path.stem
            active_turn = _payload_turn_id(payload) or turn_id or active_session
            timestamp = _valid_timestamp(record.get("timestamp"))
            used_at = timestamp if timestamp is not None else session_timestamp
            source_id = _payload_source_id(payload, timestamp)
            for occurrence_index, (skill_md_path, source_type) in enumerate(observed):
                skill = skills_by_skill_md[skill_md_path]
                if not used_at:
                    warning_count += 1
                    continue
                event_key = _event_key(
                    active_session,
                    active_turn,
                    source_id,
                    skill_md_path,
                    occurrence_index,
                )
                if event_key in event_keys:
                    continue
                event_keys.add(event_key)
                source_counts[source_type] += 1
                events.append(
                    UsageEvent(
                        event_key=event_key,
                        skill_path=str(skill.path),
                        skill_name=skill.name,
                        used_at=used_at,
                        source_type=source_type,
                        source_id=source_id,
                        session_id=active_session,
                        turn_id=active_turn,
                        parser_version=PARSER_VERSION,
                        occurrence_index=occurrence_index,
                    )
                )

    return ScanResult(
        events=events,
        warning_count=warning_count,
        files_scanned=files_scanned,
        supported_records=supported_records,
        source_counts=dict(sorted(source_counts.items())),
    )


_DIRECT_READ_TOOLS = {"read_file", "read_text_file"}
_SHELL_TOOLS = {"exec_command", "run_command", "shell"}
_SHELL_READ_COMMANDS = {"cat", "sed", "head", "tail", "less", "more", "bat"}
_SKILL_BLOCK = re.compile(
    r"<skill>\s*<name>(?P<name>[^<]+)</name>\s*"
    r"<path>(?P<path>[^<]+)</path>.*?</skill>",
    re.DOTALL,
)


def _injected_skill_loads(
    payload: dict[str, Any], skills_by_skill_md: dict[str, SkillInfo]
) -> list[str]:
    content = payload.get("content")
    if not isinstance(content, list):
        return []
    observed: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "input_text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        for match in _SKILL_BLOCK.finditer(text):
            skill_md_path = _match_skill_path(
                match.group("path").strip(), None, skills_by_skill_md
            )
            if skill_md_path is None:
                continue
            skill = skills_by_skill_md[skill_md_path]
            if match.group("name").strip() == skill.name:
                observed.append(skill_md_path)
    return observed


def _classified_skill_loads(
    payload: dict[str, Any], skills_by_skill_md: dict[str, SkillInfo]
) -> list[tuple[str, str]]:
    """Return exact installed SKILL.md paths read by a recognized tool call."""
    source = payload.get("type")
    if source not in {"function_call", "custom_tool_call"}:
        return []
    field_name = "arguments" if source == "function_call" else "input"
    call_input = payload.get(field_name)
    if not isinstance(call_input, (str, dict)):
        return []
    tool_name = payload.get("name")
    if not isinstance(tool_name, str):
        return []
    normalized_name = tool_name.rsplit(".", 1)[-1].replace("-", "_")

    if normalized_name in _DIRECT_READ_TOOLS:
        arguments = _json_object(call_input)
        if arguments is None:
            return []
        workdir = arguments.get("workdir")
        for key in ("path", "file_path", "filepath"):
            matched = _match_skill_path(arguments.get(key), workdir, skills_by_skill_md)
            if matched is not None:
                return [(matched, "skill_file_read")]
        return []

    structured = _structured_skill_read(
        tool_name, call_input, skills_by_skill_md
    )
    if structured is not None:
        return [(structured, "structured_skill_read")]

    command_objects: list[dict[str, Any]] = []
    if normalized_name in _SHELL_TOOLS:
        arguments = _json_object(call_input)
        if arguments is not None:
            command_objects.append(arguments)
    elif normalized_name == "exec" and isinstance(call_input, str):
        command_objects.extend(_exec_command_objects(call_input))
    else:
        return []

    observed: list[tuple[str, str]] = []
    for arguments in command_objects:
        command = arguments.get("cmd")
        workdir = arguments.get("workdir")
        if not isinstance(command, str):
            continue
        observed.extend(
            (path, "skill_file_read")
            for path in _shell_skill_reads(command, workdir, skills_by_skill_md)
        )
    return observed


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _structured_skill_read(
    tool_name: str,
    call_input: str | dict[str, Any],
    skills_by_skill_md: dict[str, SkillInfo],
) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", tool_name.lower()).strip("_")
    if "skill" not in normalized or not normalized.endswith("read"):
        return None
    arguments = _json_object(call_input)
    if arguments is None:
        return None
    workdir = arguments.get("workdir")
    for key in ("skill_path", "path", "file_path", "main_resource", "resource"):
        matched = _match_skill_path(arguments.get(key), workdir, skills_by_skill_md)
        if matched is not None:
            return matched
    supplied_name = arguments.get("skill_name") or arguments.get("name")
    if not isinstance(supplied_name, str):
        return None
    matches = [
        path for path, skill in skills_by_skill_md.items()
        if skill.name == supplied_name
    ]
    return matches[0] if len(matches) == 1 else None


def _payload_turn_id(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    if isinstance(metadata, dict) and isinstance(metadata.get("turn_id"), str):
        return metadata["turn_id"]
    turn_id = payload.get("turn_id")
    return turn_id if isinstance(turn_id, str) else None


def _payload_source_id(payload: dict[str, Any], timestamp: str | None) -> str:
    for key in ("call_id", "id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return sha256(f"{timestamp or ''}\0{material}".encode("utf-8")).hexdigest()


def _exec_command_objects(call_input: str) -> list[dict[str, Any]]:
    """Extract only straight-line top-level exec_command statements."""
    objects: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    marker = "tools.exec_command("
    direct_prefix = re.compile(
        r"\s*(?:(?:const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*)?"
        r"(?:await\s+)?"
    )
    cursor = 0
    statement_start = 0
    brace_depth = 0
    bracket_depth = 0
    parenthesis_depth = 0
    while cursor < len(call_input):
        character = call_input[cursor]
        if character in {"'", '"', "`"}:
            cursor = _skip_quoted_text(call_input, cursor, character)
            continue
        if call_input.startswith("//", cursor):
            newline = call_input.find("\n", cursor + 2)
            if not call_input[statement_start:cursor].strip():
                statement_start = len(call_input) if newline < 0 else newline + 1
            cursor = len(call_input) if newline < 0 else newline + 1
            continue
        if call_input.startswith("/*", cursor):
            closing = call_input.find("*/", cursor + 2)
            cursor = len(call_input) if closing < 0 else closing + 2
            continue
        if character == "{" and not call_input.startswith(marker, cursor):
            brace_depth += 1
            cursor += 1
            continue
        if character == "}":
            brace_depth = max(0, brace_depth - 1)
            cursor += 1
            continue
        if character == "[":
            bracket_depth += 1
            cursor += 1
            continue
        if character == "]":
            bracket_depth = max(0, bracket_depth - 1)
            cursor += 1
            continue
        if character == "(":
            parenthesis_depth += 1
            cursor += 1
            continue
        if character == ")":
            parenthesis_depth = max(0, parenthesis_depth - 1)
            cursor += 1
            continue
        if (
            character == ";"
            and brace_depth == 0
            and bracket_depth == 0
            and parenthesis_depth == 0
        ):
            statement_start = cursor + 1
            cursor += 1
            continue
        if not call_input.startswith(marker, cursor):
            cursor += 1
            continue
        if (
            brace_depth != 0
            or bracket_depth != 0
            or parenthesis_depth != 0
            or direct_prefix.fullmatch(call_input[statement_start:cursor]) is None
        ):
            cursor += 1
            continue
        object_at = cursor + len(marker)
        while object_at < len(call_input) and call_input[object_at].isspace():
            object_at += 1
        if object_at >= len(call_input) or call_input[object_at] != "{":
            cursor += len(marker)
            continue
        try:
            decoded, consumed = decoder.raw_decode(call_input[object_at:])
        except json.JSONDecodeError:
            cursor = object_at + 1
            continue
        closing_at = object_at + consumed
        while closing_at < len(call_input) and call_input[closing_at].isspace():
            closing_at += 1
        if isinstance(decoded, dict) and call_input.startswith(")", closing_at):
            objects.append(decoded)
        cursor = closing_at + 1
    return objects


def _skip_quoted_text(text: str, opening_at: int, quote: str) -> int:
    cursor = opening_at + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
        elif text[cursor] == quote:
            return cursor + 1
        else:
            cursor += 1
    return len(text)


def _shell_skill_reads(
    command: str,
    workdir: Any,
    skills_by_skill_md: dict[str, SkillInfo],
) -> list[str]:
    try:
        lexer = shlex.shlex(
            command.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>"
        )
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(character in ";&|" for character in token):
            segments.append([])
        else:
            segments[-1].append(token)

    observed: list[str] = []
    assignment = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    for segment in segments:
        if not segment or any(token.startswith(("<", ">")) for token in segment):
            continue
        command_index = 0
        while command_index < len(segment) and assignment.match(segment[command_index]):
            command_index += 1
        if command_index >= len(segment):
            continue
        executable = Path(segment[command_index]).name
        if executable not in _SHELL_READ_COMMANDS:
            continue
        arguments = segment[command_index + 1 :]
        if executable == "sed" and any(
            argument.startswith("-i") or argument.startswith("--in-place")
            for argument in arguments
        ):
            continue
        file_operands = _shell_file_operands(executable, arguments)
        if file_operands is None:
            continue
        for argument in file_operands:
            matched = _match_skill_path(argument, workdir, skills_by_skill_md)
            if matched is not None:
                observed.append(matched)
    return observed


def _shell_file_operands(
    executable: str, arguments: Sequence[str]
) -> list[str] | None:
    if executable == "sed":
        return _sed_file_operands(arguments)
    flags: set[str]
    options_with_values: set[str]
    if executable == "cat":
        flags = {
            "-A", "--show-all", "-b", "--number-nonblank", "-e", "-E",
            "--show-ends", "-n", "--number", "-s", "--squeeze-blank", "-t",
            "-T", "--show-tabs", "-u", "-v", "--show-nonprinting",
        }
        options_with_values = set()
    elif executable == "head":
        flags = {"-q", "--quiet", "--silent", "-v", "--verbose", "-z", "--zero-terminated"}
        options_with_values = {"-c", "--bytes", "-n", "--lines"}
    elif executable == "tail":
        flags = {
            "-f", "--follow", "-F", "-q", "--quiet", "--silent", "--retry",
            "-v", "--verbose", "-z", "--zero-terminated",
        }
        options_with_values = {
            "-c", "--bytes", "-n", "--lines", "--max-unchanged-stats",
            "--pid", "-s", "--sleep-interval",
        }
    elif executable == "less":
        flags = {"-E", "-F", "-K", "-M", "-N", "-Q", "-R", "-S", "-X"}
        options_with_values = {"-P", "-p", "-T", "-t", "-x", "-y", "-z"}
    elif executable == "more":
        flags = {"-c", "-d", "-f", "-l", "-s", "-u"}
        options_with_values = {"-n", "-p"}
    else:
        flags = {"-A", "--show-all", "-H", "--binary", "-L", "--list-languages", "--list-themes", "-n", "--number", "-p", "--plain"}
        options_with_values = {
            "--file-name", "--highlight-line", "--language", "--line-range",
            "--map-syntax", "--pager", "--paging", "--style", "--tabs",
            "--terminal-width", "--theme", "--wrap",
        }
    return _known_positional_operands(arguments, flags, options_with_values)


def _known_positional_operands(
    arguments: Sequence[str], flags: set[str], options_with_values: set[str]
) -> list[str] | None:
    operands: list[str] = []
    cursor = 0
    options_done = False
    while cursor < len(arguments):
        argument = arguments[cursor]
        if not options_done and argument == "--":
            options_done = True
            cursor += 1
            continue
        if not options_done and argument in options_with_values:
            if cursor + 1 >= len(arguments):
                return None
            cursor += 2
            continue
        if not options_done and any(
            argument.startswith(option + "=") for option in options_with_values
            if option.startswith("--")
        ):
            cursor += 1
            continue
        if not options_done and any(
            len(option) == 2 and argument.startswith(option) and len(argument) > 2
            for option in options_with_values
        ):
            cursor += 1
            continue
        if not options_done and argument in flags:
            cursor += 1
            continue
        if not options_done and argument.startswith("-"):
            return None
        operands.append(argument)
        cursor += 1
    return operands


def _sed_file_operands(arguments: Sequence[str]) -> list[str] | None:
    positionals: list[str] = []
    program_option_seen = False
    cursor = 0
    options_done = False
    while cursor < len(arguments):
        argument = arguments[cursor]
        if not options_done and argument == "--":
            options_done = True
            cursor += 1
            continue
        if not options_done and argument in {"-e", "--expression", "-f", "--file"}:
            if cursor + 1 >= len(arguments):
                return None
            program_option_seen = True
            cursor += 2
            continue
        if not options_done and (
            (argument.startswith("-e") and argument != "-e")
            or (argument.startswith("-f") and argument != "-f")
            or argument.startswith("--expression=")
            or argument.startswith("--file=")
        ):
            program_option_seen = True
            cursor += 1
            continue
        if not options_done and argument in {
            "-n", "--quiet", "--silent", "-E", "-r", "--regexp-extended",
            "-u", "--unbuffered", "-z", "--null-data",
        }:
            cursor += 1
            continue
        if not options_done and argument.startswith("-"):
            return None
        positionals.append(argument)
        cursor += 1
    return positionals if program_option_seen else positionals[1:]


def _match_skill_path(
    supplied_path: Any,
    workdir: Any,
    skills_by_skill_md: dict[str, SkillInfo],
) -> str | None:
    if not isinstance(supplied_path, str) or not supplied_path:
        return None
    path = Path(supplied_path).expanduser()
    if not path.is_absolute():
        if not isinstance(workdir, str) or not workdir:
            return None
        path = Path(workdir).expanduser() / path
    try:
        canonical = str(path.resolve())
    except OSError:
        return None
    return canonical if canonical in skills_by_skill_md else None


def _skill_metadata(skill_md: Path) -> tuple[str | None, str]:
    try:
        lines = skill_md.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, ""
    if not lines or lines[0].strip() != "---":
        return None, ""
    name: str | None = None
    description = ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            value = line.partition(":")[2].strip().strip("\"'")
            name = value or None
        elif line.startswith("description:"):
            description = line.partition(":")[2].strip().strip("\"'")
    return name, description


def _skill_name(skill_md: Path) -> str | None:
    return _skill_metadata(skill_md)[0]


def _protection_for(path: Path, name: str) -> tuple[bool, str | None]:
    parts = path.parts
    if ".system" in parts:
        return True, "system-managed"
    if "plugins" in parts or "plugin" in parts:
        return True, "plugin-managed"
    if name == "skill-usage-auditor" or path.name == "skill-usage-auditor":
        return True, "auditor-owned"
    return False, None


def _fingerprint(skill_md: Path) -> str:
    return sha256(skill_md.read_bytes()).hexdigest()


def _session_log_files(session_roots: Sequence[Path]) -> Iterable[Path]:
    paths: set[Path] = set()
    for supplied_root in session_roots:
        root = Path(supplied_root)
        if root.is_file() and root.suffix == ".jsonl":
            paths.add(root)
        elif root.is_dir():
            paths.update(root.rglob("*.jsonl"))
    return sorted(paths, key=lambda path: str(path))


def _record_type_and_payload(record: dict[str, Any]) -> tuple[Any, Any]:
    if "type" in record:
        return record.get("type"), record.get("payload")
    for record_type in ("session_meta", "turn_context", "response_item"):
        if record_type in record:
            wrapped_payload = record[record_type]
            if isinstance(wrapped_payload, dict):
                return record_type, wrapped_payload.get("payload")
            return record_type, wrapped_payload
    if len(record) == 1:
        record_type, payload = next(iter(record.items()))
        return record_type, payload.get("payload") if isinstance(payload, dict) else payload
    return None, None


def _event_key(
    session_id: str,
    turn_id: str,
    source_id: str,
    canonical_skill_path: str,
    occurrence_index: int,
) -> str:
    material = "\0".join(
        (
            session_id,
            turn_id,
            source_id,
            canonical_skill_path,
            str(occurrence_index),
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def automation_prompt() -> str:
    """Return the audit-only prompt intended for a weekly Codex automation."""
    return (
        "Use $skill-usage-auditor. Run only the audit command for the last 30 days and "
        "present a complete candidate review. Include each candidate ID, Skill name, "
        "verifiable load count, recommendation, reason, latest load, and path. Show the coverage "
        "status and explain that zero means only no observed loads in the retained logs. "
        "Ask the user to review the candidates. Make no changes to installed Skills, and never "
        "treat silence as approval."
    )


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _default_skill_roots() -> list[Path]:
    return [_codex_home() / "skills", Path.home() / ".agents" / "skills"]


def _default_session_roots() -> list[Path]:
    return [_codex_home() / "sessions", _codex_home() / "archived_sessions"]


def _default_state_path() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    state_home = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    return state_home / "skill-usage-auditor" / "usage.sqlite3"


def _resolve_roots(
    supplied: Sequence[Path] | None,
    defaults: Sequence[Path],
    *,
    kind: str,
) -> tuple[list[Path], list[Path], list[Path]]:
    explicit = supplied is not None
    requested = [Path(path).expanduser().resolve() for path in (supplied or defaults)]
    scanned: list[Path] = []
    skipped: list[Path] = []
    for path in requested:
        if kind == "Skill":
            valid = path.is_dir()
        else:
            valid = path.is_dir() or (path.is_file() and path.suffix == ".jsonl")
        if valid:
            scanned.append(path)
        elif explicit:
            expected = "a directory" if kind == "Skill" else "a directory or JSONL file"
            raise ValueError(f"explicit {kind} root must be {expected}: {path}")
        else:
            skipped.append(path)
    return requested, scanned, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Track verifiable Skill loads and safely review low-use installs."
    )
    parser.add_argument(
        "--skill-root",
        action="append",
        type=Path,
        dest="skill_roots",
        metavar="PATH",
        help="managed Skill root (repeatable; defaults to user Skill directories)",
    )
    parser.add_argument(
        "--session-root",
        action="append",
        type=Path,
        dest="session_roots",
        metavar="PATH",
        help=(
            "defaults to CODEX_HOME/sessions and archived_sessions; accepts a session "
            "directory or JSONL file (repeatable)"
        ),
    )
    parser.add_argument(
        "--state",
        type=Path,
        help="SQLite state path (defaults under XDG_STATE_HOME or ~/.local/state)",
    )
    parser.add_argument(
        "--now",
        help="current ISO-8601 time (primarily for reproducible runs)",
    )
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync", help="scan session logs and store verifiable loads")

    record_parser = subparsers.add_parser("record", help="record one manual Skill use")
    record_parser.add_argument("skill", help="unique Skill name or absolute path")
    record_parser.add_argument("--used-at", help="ISO-8601 use time (defaults to --now/current time)")
    record_parser.add_argument("--event-id", help="optional idempotency key")

    stats_parser = subparsers.add_parser("stats", help="show rolling verifiable-load counts")
    stats_parser.add_argument("--window-days", type=_positive_int, default=30)
    stats_parser.add_argument(
        "--include-manual",
        action="store_true",
        help="include separately labeled manual records in stats",
    )

    audit_parser = subparsers.add_parser("audit", help="freeze a low-use candidate review")
    audit_parser.add_argument("--window-days", type=_positive_int, default=30)
    audit_parser.add_argument("--max-uses", type=_nonnegative_int, default=1)
    audit_parser.add_argument("--expiry-days", type=_positive_int, default=7)

    remove_parser = subparsers.add_parser("remove", help="quarantine confirmed candidates")
    remove_parser.add_argument("report_id")
    remove_parser.add_argument("candidate_ids", nargs="+")
    remove_parser.add_argument("--confirmation", required=True)

    restore_parser = subparsers.add_parser("restore", help="restore one quarantined candidate")
    restore_parser.add_argument("report_id")
    restore_parser.add_argument("candidate_id")

    subparsers.add_parser(
        "automation-prompt", help="print the audit-only weekly automation prompt"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.now and arguments.command in {"audit", "remove", "restore"}:
        parser.error(f"--now cannot be used with {arguments.command}; freshness uses real UTC time")
    if arguments.command == "automation-prompt":
        prompt = automation_prompt()
        if arguments.json:
            print(json.dumps({"prompt": prompt}, indent=2, sort_keys=True))
        else:
            print(prompt)
        return 0

    try:
        skill_roots, scanned_skill_roots, skipped_skill_roots = _resolve_roots(
            arguments.skill_roots, _default_skill_roots(), kind="Skill"
        )
        session_roots, scanned_session_roots, skipped_session_roots = _resolve_roots(
            arguments.session_roots, _default_session_roots(), kind="session"
        )
        skipped_default_roots = skipped_skill_roots + skipped_session_roots
        state_path = (arguments.state or _default_state_path()).expanduser()
        if arguments.command in {"audit", "remove", "restore"}:
            now = datetime.now(timezone.utc)
        else:
            now = _as_datetime(arguments.now) if arguments.now else datetime.now(timezone.utc)
        store = StateStore(state_path)
        skills = discover_skills(scanned_skill_roots)
        payload = _run_command(
            arguments,
            store,
            skills,
            scanned_skill_roots,
            session_roots,
            scanned_session_roots,
            skill_roots,
            skipped_default_roots,
            now,
        )
    except (KeyError, OSError, sqlite3.OperationalError, ValueError) as error:
        message = error.args[0] if isinstance(error, KeyError) and error.args else str(error)
        print(f"error: {message}", file=sys.stderr)
        return 2

    if arguments.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_markdown(arguments.command, payload))
    return 0


def _run_command(
    arguments,
    store,
    skills,
    managed_roots,
    session_roots,
    scanned_session_roots,
    skill_roots,
    skipped_default_roots,
    now,
):
    if arguments.command == "sync":
        scan = scan_session_logs(scanned_session_roots, skills)
        coverage_status = _coverage_status(scan, skipped_default_roots)
        return {
            "events_found": len(scan.events),
            "events_inserted": store.add_events(scan.events),
            "files_scanned": scan.files_scanned,
            "skill_roots": [str(path) for path in skill_roots],
            "scanned_skill_roots": [str(path) for path in managed_roots],
            "session_roots": [str(path) for path in session_roots],
            "scanned_session_roots": [str(path) for path in scanned_session_roots],
            "skipped_default_roots": [str(path) for path in skipped_default_roots],
            "skills_discovered": len(skills),
            "warnings": scan.warning_count,
            "supported_records": scan.supported_records,
            "source_counts": scan.source_counts,
            "coverage_status": coverage_status,
        }
    if arguments.command == "record":
        skill = _select_skill(skills, arguments.skill)
        inserted = record_manual_use(
            store,
            skill,
            used_at=arguments.used_at or now,
            event_id=arguments.event_id,
        )
        return {"inserted": inserted, "skill": _skill_payload(skill)}
    if arguments.command == "stats":
        scan = scan_session_logs(scanned_session_roots, skills)
        inserted = store.add_events(scan.events)
        coverage_status = _coverage_status(scan, skipped_default_roots)
        stats = collect_stats(
            store,
            skills,
            now=now,
            window_days=arguments.window_days,
            include_manual=arguments.include_manual,
            coverage_status=coverage_status,
        )
        stats = sorted(
            stats,
            key=lambda item: (
                -item.uses,
                -item.tasks,
                item.skill.name,
                str(item.skill.path),
            ),
        )
        return {
            "coverage_notice": COVERAGE_NOTICE,
            "coverage_status": coverage_status,
            "files_scanned": scan.files_scanned,
            "generated_at": now.isoformat(),
            "events_found": len(scan.events),
            "events_inserted": inserted,
            "include_manual": arguments.include_manual,
            "parse_warnings": scan.warning_count,
            "supported_records": scan.supported_records,
            "scanned_session_roots": [str(path) for path in scanned_session_roots],
            "scanned_skill_roots": [str(path) for path in managed_roots],
            "session_roots": [str(path) for path in session_roots],
            "skill_roots": [str(path) for path in skill_roots],
            "skills": [
                dict(
                    _skill_payload(item.skill),
                    uses=item.uses,
                    tasks=item.tasks,
                    latest_observed_at=item.latest_observed_at,
                    source_counts=item.source_counts,
                    trend=_sparkline(item.daily_counts),
                    recommendation=item.recommendation,
                    recommendation_reason=item.recommendation_reason,
                    overlaps_with=item.overlaps_with,
                )
                for item in stats
            ],
            "chart": _bar_chart(stats),
            "skipped_default_roots": [str(path) for path in skipped_default_roots],
            "window_days": arguments.window_days,
        }
    if arguments.command == "audit":
        scan = scan_session_logs(scanned_session_roots, skills)
        inserted = store.add_events(scan.events)
        coverage_status = _coverage_status(scan, skipped_default_roots)
        if coverage_status == "none":
            raise ValueError(
                "no supported Skill-load records were found; refusing to rank removal candidates"
            )
        report = create_audit(
            store,
            skills,
            now=now,
            window_days=arguments.window_days,
            max_uses=arguments.max_uses,
            expiry_days=arguments.expiry_days,
            skill_roots=skill_roots,
            scanned_skill_roots=managed_roots,
            session_roots=session_roots,
            scanned_session_roots=scanned_session_roots,
            skipped_default_roots=skipped_default_roots,
            files_scanned=scan.files_scanned,
            warning_count=scan.warning_count,
            supported_records=scan.supported_records,
            coverage_status=coverage_status,
            coverage_notice=COVERAGE_NOTICE,
        )
        payload = _audit_payload(report)
        payload["events_found"] = len(scan.events)
        payload["events_inserted"] = inserted
        payload["confirmation_instruction"] = (
            "Use this template only after explicit selection; replace the placeholder with "
            "the selected candidate IDs in sorted order, separated by single spaces."
        )
        payload["confirmation_template"] = (
            f"CONFIRM SKILL REMOVAL {report.report_id} "
            "<candidate-id-1> <candidate-id-2> ..."
        )
        return payload
    if arguments.command == "remove":
        records = remove_candidates(
            store,
            arguments.report_id,
            arguments.candidate_ids,
            arguments.confirmation,
            managed_roots=managed_roots,
            now=now,
        )
        return {"removed": [_removal_payload(record) for record in records]}
    if arguments.command == "restore":
        record = restore_candidate(store, arguments.report_id, arguments.candidate_id)
        return {"restored": _removal_payload(record)}
    raise ValueError(f"unsupported command: {arguments.command}")


def _select_skill(skills: Sequence[SkillInfo], selector: str) -> SkillInfo:
    supplied_path = Path(selector).expanduser()
    path_matches = [skill for skill in skills if skill.path == supplied_path.resolve()]
    matches = path_matches or [skill for skill in skills if skill.name == selector]
    if not matches:
        raise ValueError(f"Skill not found: {selector}")
    if len(matches) != 1:
        raise ValueError(f"Skill selector is ambiguous; use an absolute path: {selector}")
    return matches[0]


def _skill_payload(skill: SkillInfo) -> dict[str, Any]:
    return {
        "name": skill.name,
        "path": str(skill.path),
        "protected": skill.protected,
        "protection_reason": skill.protection_reason,
    }


def _audit_payload(report: AuditReport) -> dict[str, Any]:
    warnings = [report.coverage_notice]
    if report.skipped_default_roots:
        warnings.append(
            "Skipped missing default roots: " + ", ".join(report.skipped_default_roots)
        )
    if report.warning_count:
        warnings.append(f"Session log parse warnings: {report.warning_count}")
    return {
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "fingerprint": candidate.fingerprint,
                "latest_observed_at": candidate.latest_observed_at,
                "name": candidate.name,
                "path": candidate.path,
                "protected": candidate.protected,
                "protection_reason": candidate.protection_reason,
                "recommendation": candidate.recommendation,
                "recommendation_reason": candidate.recommendation_reason,
                "overlaps_with": candidate.overlaps_with,
                "uses": candidate.uses,
            }
            for candidate in report.candidates
        ],
        "coverage_notice": report.coverage_notice,
        "created_at": report.created_at,
        "expiry_days": report.expiry_days,
        "expires_at": report.expires_at,
        "files_scanned": report.files_scanned,
        "supported_records": report.supported_records,
        "coverage_status": report.coverage_status,
        "max_uses": report.max_uses,
        "report_id": report.report_id,
        "scanned_session_roots": report.scanned_session_roots,
        "scanned_skill_roots": report.scanned_skill_roots,
        "session_roots": report.session_roots,
        "skill_roots": report.skill_roots,
        "skipped_default_roots": report.skipped_default_roots,
        "warning_count": report.warning_count,
        "warnings": warnings,
        "window_days": report.window_days,
    }


def _removal_payload(record: RemovalRecord) -> dict[str, Any]:
    return {
        "candidate_id": record.candidate_id,
        "original_path": record.original_path,
        "quarantine_path": record.quarantine_path,
        "removed_at": record.removed_at,
        "report_id": record.report_id,
        "restored_at": record.restored_at,
    }


def _markdown(command: str, payload: dict[str, Any]) -> str:
    if command == "stats":
        lines = [
            "# Skill usage stats",
            "",
            f"Window: {payload['window_days']} days",
            "Requested Skill roots: "
            + (", ".join(payload["skill_roots"]) or "none"),
            "Scanned Skill roots: "
            + (", ".join(payload["scanned_skill_roots"]) or "none"),
            "Requested session roots: "
            + (", ".join(payload["session_roots"]) or "none"),
            "Scanned session roots: "
            + (", ".join(payload["scanned_session_roots"]) or "none"),
            "Skipped default roots: "
            + (", ".join(payload["skipped_default_roots"]) or "none"),
            f"Files scanned: {payload['files_scanned']}",
            f"Supported records: {payload['supported_records']}",
            f"Parse warnings: {payload['parse_warnings']}",
            f"Coverage status: {payload['coverage_status']}",
            f"Coverage: {payload['coverage_notice']}",
            "",
            "## Verifiable loads",
            "",
            "```text",
            payload["chart"],
            "```",
            "",
            "| Skill | Loads | Tasks | Latest | Sources | Trend | Recommendation | Path |",
            "| --- | ---: | ---: | --- | --- | --- | --- | --- |",
        ]
        lines.extend(
            f"| {_cell(skill['name'])} | {skill['uses']} | {skill['tasks']} | "
            f"{_cell(skill['latest_observed_at'] or '—')} | "
            f"{_cell(', '.join(f'{key}:{value}' for key, value in skill['source_counts'].items()) or '—')} | "
            f"{skill['trend']} | {_cell(skill['recommendation'])}: "
            f"{_cell(skill['recommendation_reason'])} | {_cell(skill['path'])} |"
            for skill in payload["skills"]
        )
        return "\n".join(lines)
    if command == "audit":
        lines = [
            "# Skill usage audit",
            "",
            f"Report: `{payload['report_id']}`",
            "",
            f"Window: {payload['window_days']} days",
            f"Maximum verifiable loads: {payload['max_uses']}",
            f"Expires: {payload['expires_at']} ({payload['expiry_days']} days)",
            f"Files scanned: {payload['files_scanned']}",
            f"Parse warnings: {payload['warning_count']}",
            f"Supported records: {payload['supported_records']}",
            f"Coverage status: {payload['coverage_status']}",
            "Requested Skill roots: "
            + (", ".join(payload["skill_roots"]) or "none"),
            "Scanned Skill roots: "
            + (", ".join(payload["scanned_skill_roots"]) or "none"),
            "Requested session roots: "
            + (", ".join(payload["session_roots"]) or "none"),
            "Scanned session roots: "
            + (", ".join(payload["scanned_session_roots"]) or "none"),
            "Skipped default roots: "
            + (", ".join(payload["skipped_default_roots"]) or "none"),
            f"Coverage: {payload['coverage_notice']}",
            "Warnings:",
            *[f"- {warning}" for warning in payload["warnings"]],
            "",
            "| Candidate ID | Skill | Loads | Latest | Recommendation | Reason | "
            "Protected | Fingerprint | Path |",
            "| --- | --- | ---: | --- | --- | --- | :---: | --- | --- |",
        ]
        lines.extend(
            f"| `{candidate['candidate_id']}` | {_cell(candidate['name'])} | "
            f"{candidate['uses']} | {_cell(candidate['latest_observed_at'] or '—')} | "
            f"{_cell(candidate['recommendation'])} | "
            f"{_cell(candidate['recommendation_reason'])} | "
            f"{'yes' if candidate['protected'] else 'no'} | "
            f"`{candidate['fingerprint']}` | {_cell(candidate['path'])} |"
            for candidate in payload["candidates"]
        )
        lines.extend(
            [
                "",
                "Confirmation template (use only after explicit selection):",
                "",
                f"`{payload['confirmation_template']}`",
                "",
                payload["confirmation_instruction"],
            ]
        )
        return "\n".join(lines)
    if command == "sync":
        rows = [(key.replace("_", " ").title(), payload[key]) for key in sorted(payload)]
    elif command == "record":
        rows = [
            ("Skill", payload["skill"]["name"]),
            ("Path", payload["skill"]["path"]),
            ("Inserted", "yes" if payload["inserted"] else "no"),
        ]
    elif command == "remove":
        rows = [
            (record["candidate_id"], record["quarantine_path"])
            for record in payload["removed"]
        ]
    elif command == "restore":
        record = payload["restored"]
        rows = [(record["candidate_id"], record["original_path"])]
    else:
        rows = []
    return "\n".join(
        ["| Item | Value |", "| --- | --- |"]
        + [f"| {_cell(label)} | {_cell(value)} |" for label, value in rows]
    )


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
