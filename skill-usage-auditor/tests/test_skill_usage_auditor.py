from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "skill_usage_auditor.py"
)
SPEC = importlib.util.spec_from_file_location("skill_usage_auditor", MODULE_PATH)
assert SPEC and SPEC.loader
auditor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = auditor
SPEC.loader.exec_module(auditor)


NOW = datetime(2026, 8, 20, 2, 0, tzinfo=timezone.utc)


def record(record_type, payload, timestamp="2026-08-20T01:00:00+00:00"):
    return {"timestamp": timestamp, "type": record_type, "payload": payload}


def session_meta(session_id="session-1", timestamp="2026-08-20T00:00:00+00:00"):
    return record("session_meta", {"id": session_id}, timestamp)


def turn_context(turn_id="turn-1"):
    return record("turn_context", {"turn_id": turn_id})


def function_call(name, arguments, call_id="call-1"):
    return record(
        "response_item",
        {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": call_id,
        },
    )


def injected_skill(skill_md: Path, name: str, message_id="msg-1", repeat=1):
    block = (
        f"<skill>\n<name>{name}</name>\n<path>{skill_md}</path>\n"
        f"---\nname: {name}\ndescription: test\n---\nbody\n</skill>"
    )
    return record(
        "response_item",
        {
            "type": "message",
            "id": message_id,
            "role": "user",
            "content": [{"type": "input_text", "text": "\n".join([block] * repeat)}],
            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-message"},
        },
    )


class AuditorTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skill_root = self.root / "skills"
        self.session_root = self.root / "sessions"
        self.skill_root.mkdir()
        self.session_root.mkdir()
        self.skill_a = self.make_skill("alpha", "Analyze alpha project workflows and reports")

    def tearDown(self):
        self.temp.cleanup()

    def make_skill(self, name, description="A sufficiently detailed unique description", parent=None):
        directory = (parent or self.skill_root) / name
        directory.mkdir(parents=True)
        skill_md = directory / "SKILL.md"
        skill_md.write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
        return skill_md

    def write_log(self, name, records, root=None):
        path = (root or self.session_root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(item) if not isinstance(item, str) else item for item in records)
            + "\n",
            encoding="utf-8",
        )
        return path

    def skills(self):
        return auditor.discover_skills([self.skill_root])

    def scan(self, roots=None):
        return auditor.scan_session_logs(roots or [self.session_root], self.skills())


class EventParsingTests(AuditorTestCase):
    def test_injected_skill_counts_and_mentions_do_not(self):
        mention = record(
            "response_item",
            {
                "type": "message",
                "id": "mention",
                "role": "user",
                "content": [{"type": "input_text", "text": "Use $alpha or mention alpha"}],
            },
        )
        self.write_log(
            "one.jsonl",
            [session_meta(), turn_context(), mention, injected_skill(self.skill_a, "alpha")],
        )
        scan = self.scan()
        self.assertEqual(1, len(scan.events))
        self.assertEqual("injected_skill", scan.events[0].source_type)
        self.assertEqual("msg-1", scan.events[0].source_id)
        self.assertEqual("turn-message", scan.events[0].turn_id)

    def test_every_injected_occurrence_counts(self):
        self.write_log(
            "repeat.jsonl",
            [session_meta(), injected_skill(self.skill_a, "alpha", repeat=2)],
        )
        events = self.scan().events
        self.assertEqual(2, len(events))
        self.assertEqual([0, 1], [event.occurrence_index for event in events])
        self.assertEqual(2, len({event.event_key for event in events}))

    def test_mismatched_injected_name_is_rejected(self):
        self.write_log(
            "mismatch.jsonl",
            [session_meta(), injected_skill(self.skill_a, "not-alpha")],
        )
        self.assertEqual([], self.scan().events)

    def test_direct_read_absolute_and_relative_paths(self):
        self.write_log(
            "reads.jsonl",
            [
                session_meta(),
                function_call("read_file", {"path": str(self.skill_a)}, "read-1"),
                function_call(
                    "read_text_file",
                    {"path": "alpha/SKILL.md", "workdir": str(self.skill_root)},
                    "read-2",
                ),
            ],
        )
        events = self.scan().events
        self.assertEqual(2, len(events))
        self.assertEqual({"read-1", "read-2"}, {event.source_id for event in events})

    def test_shell_call_preserves_repeated_loads_and_multiple_skills(self):
        skill_b = self.make_skill("beta", "Build beta documents and validate outputs")
        command = f"cat {self.skill_a}; sed -n 1,20p {self.skill_a}; head {skill_b}"
        self.write_log(
            "shell.jsonl",
            [session_meta(), function_call("exec_command", {"cmd": command}, "shell-1")],
        )
        events = self.scan().events
        self.assertEqual(["alpha", "alpha", "beta"], [event.skill_name for event in events])
        self.assertEqual([0, 1, 2], [event.occurrence_index for event in events])

    def test_unsafe_or_unsupported_shell_commands_are_rejected(self):
        calls = [
            function_call("exec_command", {"cmd": f"grep alpha {self.skill_a}"}, "grep"),
            function_call("exec_command", {"cmd": f"cat < {self.skill_a}"}, "redirect"),
            function_call("exec_command", {"cmd": "cat $UNKNOWN"}, "variable"),
        ]
        self.write_log("unsafe.jsonl", [session_meta(), *calls])
        self.assertEqual([], self.scan().events)

    def test_structured_skill_read_accepts_path_and_unique_name(self):
        calls = [
            function_call("skills.read", {"skill_path": str(self.skill_a)}, "structured-1"),
            function_call("skills_read", {"skill_name": "alpha"}, "structured-2"),
        ]
        self.write_log("structured.jsonl", [session_meta(), *calls])
        events = self.scan().events
        self.assertEqual(2, len(events))
        self.assertTrue(all(event.source_type == "structured_skill_read" for event in events))

    def test_structured_name_is_rejected_when_ambiguous(self):
        other_root = self.root / "other"
        other_root.mkdir()
        self.make_skill("alpha", parent=other_root)
        skills = auditor.discover_skills([self.skill_root, other_root])
        self.write_log(
            "ambiguous.jsonl",
            [session_meta(), function_call("skills.read", {"skill_name": "alpha"})],
        )
        scan = auditor.scan_session_logs([self.session_root], skills)
        self.assertEqual([], scan.events)

    def test_symlinked_skill_is_discovered_once(self):
        alias = self.skill_root / "alpha-alias"
        alias.symlink_to(self.skill_a.parent, target_is_directory=True)
        skills = self.skills()
        self.assertEqual(1, len(skills))

    def test_malformed_log_and_missing_timestamp_are_reported(self):
        payload = function_call("read_file", {"path": str(self.skill_a)})
        payload.pop("timestamp")
        self.write_log("broken.jsonl", ["{not json", payload])
        scan = self.scan()
        self.assertEqual([], scan.events)
        self.assertEqual(2, scan.warning_count)
        self.assertEqual(1, scan.supported_records)

    def test_current_and_archive_copies_are_idempotent(self):
        archive = self.root / "archive"
        archive.mkdir()
        records = [session_meta(), function_call("read_file", {"path": str(self.skill_a)}, "same")]
        self.write_log("current.jsonl", records)
        self.write_log("archived.jsonl", records, archive)
        scan = self.scan([self.session_root, archive])
        self.assertEqual(1, len(scan.events))


class StateAndStatsTests(AuditorTestCase):
    def test_sync_is_idempotent(self):
        self.write_log(
            "sync.jsonl",
            [session_meta(), function_call("read_file", {"path": str(self.skill_a)})],
        )
        store = auditor.StateStore(self.root / "state.sqlite3")
        events = self.scan().events
        self.assertEqual(1, store.add_events(events))
        self.assertEqual(0, store.add_events(events))

    def test_legacy_schema_migrates_and_legacy_events_are_excluded(self):
        state = self.root / "legacy.sqlite3"
        with sqlite3.connect(state) as connection:
            connection.execute(
                "CREATE TABLE usage_events (event_key TEXT PRIMARY KEY, skill_path TEXT NOT NULL, "
                "skill_name TEXT NOT NULL, used_at TEXT NOT NULL, source TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO usage_events VALUES (?, ?, ?, ?, ?)",
                ("old", str(self.skill_a.parent), "alpha", NOW.isoformat(), "function_call"),
            )
        store = auditor.StateStore(state)
        with sqlite3.connect(state) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(usage_events)")}
            source_type = connection.execute(
                "SELECT source_type FROM usage_events WHERE event_key='old'"
            ).fetchone()[0]
        self.assertIn("parser_version", columns)
        self.assertEqual("legacy_observed", source_type)
        self.assertEqual([], store.events_between(NOW - timedelta(days=1), NOW + timedelta(days=1)))

    def test_resync_after_legacy_migration_counts_only_new_exact_event(self):
        state = self.root / "legacy-resync.sqlite3"
        with sqlite3.connect(state) as connection:
            connection.execute(
                "CREATE TABLE usage_events (event_key TEXT PRIMARY KEY, skill_path TEXT NOT NULL, "
                "skill_name TEXT NOT NULL, used_at TEXT NOT NULL, source TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO usage_events VALUES (?, ?, ?, ?, ?)",
                ("old", str(self.skill_a.parent), "alpha", NOW.isoformat(), "function_call"),
            )
        self.write_log(
            "resync.jsonl",
            [session_meta(), function_call("read_file", {"path": str(self.skill_a)}, "new-call")],
        )
        store = auditor.StateStore(state)
        self.assertEqual(1, store.add_events(self.scan().events))
        stats = auditor.collect_stats(store, self.skills(), now=NOW, window_days=30)
        self.assertEqual(1, stats[0].uses)

    def test_manual_records_are_excluded_unless_requested(self):
        store = auditor.StateStore(self.root / "state.sqlite3")
        skill = self.skills()[0]
        auditor.record_manual_use(store, skill, used_at=NOW, event_id="manual-1")
        start, end = NOW - timedelta(days=1), NOW + timedelta(days=1)
        self.assertEqual([], store.events_between(start, end))
        self.assertEqual(1, len(store.events_between(start, end, include_manual=True)))

    def test_stats_include_tasks_sources_latest_and_trend(self):
        store = auditor.StateStore(self.root / "state.sqlite3")
        path = str(self.skill_a.parent.resolve())
        events = [
            auditor.UsageEvent("one", path, "alpha", (NOW - timedelta(days=1)).isoformat(), "injected_skill", "m1", "s1", "t1"),
            auditor.UsageEvent("two", path, "alpha", NOW.isoformat(), "skill_file_read", "c1", "s2", "t2"),
        ]
        store.add_events(events)
        stats = auditor.collect_stats(store, self.skills(), now=NOW, window_days=7)
        self.assertEqual(2, stats[0].uses)
        self.assertEqual(2, stats[0].tasks)
        self.assertEqual({"injected_skill": 1, "skill_file_read": 1}, stats[0].source_counts)
        self.assertEqual(NOW.isoformat(), stats[0].latest_observed_at)
        self.assertEqual("keep", stats[0].recommendation)
        self.assertEqual(7, len(stats[0].daily_counts))

    def test_window_boundary_is_inclusive_and_normalized_to_utc(self):
        store = auditor.StateStore(self.root / "state.sqlite3")
        path = str(self.skill_a.parent.resolve())
        start = NOW - timedelta(days=7)
        events = [
            auditor.UsageEvent("inside", path, "alpha", start.isoformat(), "skill_file_read", "c1", "s1", "t1"),
            auditor.UsageEvent("outside", path, "alpha", (start - timedelta(microseconds=1)).isoformat(), "skill_file_read", "c2", "s2", "t2"),
        ]
        store.add_events(events)
        stats = auditor.collect_stats(store, self.skills(), now=NOW.isoformat(), window_days=7)
        self.assertEqual(1, stats[0].uses)
        self.assertEqual(NOW, auditor._as_datetime("2026-08-20T10:00:00+08:00"))

    def test_report_round_trip_preserves_coverage_and_advice(self):
        store = auditor.StateStore(self.root / "state.sqlite3")
        report = auditor.create_audit(
            store, self.skills(), now=NOW, coverage_status="partial",
            supported_records=3, warning_count=1,
        )
        loaded = store.load_report(report.report_id)
        self.assertEqual("partial", loaded.coverage_status)
        self.assertEqual(3, loaded.supported_records)
        self.assertEqual("observe", loaded.candidates[0].recommendation)

    def test_recommendations_respect_coverage_and_protection(self):
        skill = self.skills()[0]
        self.assertEqual("consider_remove", auditor._recommendation(skill, 0, coverage_status="complete", overlaps_with=[])[0])
        self.assertEqual("observe", auditor._recommendation(skill, 0, coverage_status="partial", overlaps_with=[])[0])
        self.assertEqual("observe", auditor._recommendation(skill, 1, coverage_status="complete", overlaps_with=[])[0])
        self.assertEqual("keep", auditor._recommendation(skill, 2, coverage_status="complete", overlaps_with=[])[0])
        protected_md = self.make_skill("system-one", parent=self.skill_root / ".system")
        protected = next(
            skill for skill in auditor.discover_skills([self.skill_root])
            if skill.name == "system-one"
        )
        self.assertTrue(protected_md.exists())
        self.assertEqual("keep", auditor._recommendation(protected, 0, coverage_status="complete", overlaps_with=[])[0])

    def test_similar_descriptions_become_merge_check(self):
        self.make_skill("beta", "Analyze alpha project workflows and reports")
        skills = self.skills()
        overlaps = auditor._overlap_map(skills)
        alpha = next(skill for skill in skills if skill.name == "alpha")
        recommendation = auditor._recommendation(
            alpha, 0, coverage_status="complete", overlaps_with=overlaps[str(alpha.path)]
        )
        self.assertEqual("merge_check", recommendation[0])
        self.assertIn("beta", recommendation[1])

    def test_chart_and_sparkline_are_deterministic(self):
        skill = self.skills()[0]
        stats = [auditor.SkillStats(skill, 4, tasks=2, daily_counts=[0, 1, 4])]
        self.assertEqual("▁▃█", auditor._sparkline([0, 1, 4]))
        chart = auditor._bar_chart(stats, width=4)
        self.assertEqual("alpha  ████ 4", chart)

    def test_coverage_status(self):
        scan = auditor.ScanResult([], 0, 1, supported_records=2)
        self.assertEqual("complete", auditor._coverage_status(scan, []))
        self.assertEqual("partial", auditor._coverage_status(scan, [self.root / "missing"]))
        self.assertEqual("none", auditor._coverage_status(auditor.ScanResult([], 0, 0), []))


class SafetyAndCliTests(AuditorTestCase):
    def make_report(self, *, coverage="complete"):
        store = auditor.StateStore(self.root / "state.sqlite3")
        report = auditor.create_audit(
            store,
            self.skills(),
            now=NOW,
            coverage_status=coverage,
            supported_records=1,
        )
        return store, report

    def test_remove_requires_exact_confirmation_and_restores(self):
        store, report = self.make_report()
        candidate = report.candidates[0]
        with self.assertRaises(ValueError):
            auditor.remove_candidates(
                store, report.report_id, [candidate.candidate_id], "yes",
                managed_roots=[self.skill_root], now=NOW,
            )
        confirmation = auditor.expected_confirmation(report.report_id, [candidate.candidate_id])
        records = auditor.remove_candidates(
            store, report.report_id, [candidate.candidate_id], confirmation,
            managed_roots=[self.skill_root], now=NOW,
        )
        self.assertFalse(self.skill_a.parent.exists())
        self.assertTrue(Path(records[0].quarantine_path).exists())
        auditor.restore_candidate(store, report.report_id, candidate.candidate_id)
        self.assertTrue(self.skill_a.parent.exists())

    def test_expired_report_is_rejected(self):
        store, report = self.make_report()
        candidate = report.candidates[0]
        confirmation = auditor.expected_confirmation(report.report_id, [candidate.candidate_id])
        with self.assertRaisesRegex(ValueError, "expired"):
            auditor.remove_candidates(
                store, report.report_id, [candidate.candidate_id], confirmation,
                managed_roots=[self.skill_root], now=NOW + timedelta(days=8),
            )

    def test_duplicate_candidate_selection_is_rejected(self):
        store, report = self.make_report()
        candidate = report.candidates[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            auditor.remove_candidates(
                store,
                report.report_id,
                [candidate.candidate_id, candidate.candidate_id],
                "unused",
                managed_roots=[self.skill_root],
                now=NOW,
            )

    def test_changed_fingerprint_is_rejected(self):
        store, report = self.make_report()
        candidate = report.candidates[0]
        self.skill_a.write_text(self.skill_a.read_text() + "changed\n", encoding="utf-8")
        confirmation = auditor.expected_confirmation(report.report_id, [candidate.candidate_id])
        with self.assertRaisesRegex(ValueError, "fingerprint changed"):
            auditor.remove_candidates(
                store, report.report_id, [candidate.candidate_id], confirmation,
                managed_roots=[self.skill_root], now=NOW,
            )

    def test_restore_refuses_occupied_destination(self):
        store, report = self.make_report()
        candidate = report.candidates[0]
        confirmation = auditor.expected_confirmation(report.report_id, [candidate.candidate_id])
        auditor.remove_candidates(
            store, report.report_id, [candidate.candidate_id], confirmation,
            managed_roots=[self.skill_root], now=NOW,
        )
        self.skill_a.parent.mkdir()
        with self.assertRaises(FileExistsError):
            auditor.restore_candidate(store, report.report_id, candidate.candidate_id)

    def test_incomplete_coverage_never_recommends_removal(self):
        _, report = self.make_report(coverage="partial")
        self.assertEqual("observe", report.candidates[0].recommendation)

    def test_protected_skills_are_excluded_from_audit(self):
        protected_root = self.skill_root / ".system"
        self.make_skill("protected", parent=protected_root)
        store = auditor.StateStore(self.root / "state.sqlite3")
        report = auditor.create_audit(
            store, auditor.discover_skills([self.skill_root]), now=NOW,
            coverage_status="complete", supported_records=1,
        )
        self.assertEqual(["alpha"], [candidate.name for candidate in report.candidates])

    def test_markdown_contains_visual_and_strict_language(self):
        payload = {
            "window_days": 7,
            "skill_roots": [str(self.skill_root)],
            "scanned_skill_roots": [str(self.skill_root)],
            "session_roots": [str(self.session_root)],
            "scanned_session_roots": [str(self.session_root)],
            "skipped_default_roots": [],
            "files_scanned": 1,
            "supported_records": 1,
            "parse_warnings": 0,
            "coverage_status": "complete",
            "coverage_notice": auditor.COVERAGE_NOTICE,
            "chart": "alpha █ 1",
            "skills": [{
                "name": "alpha", "uses": 1, "tasks": 1,
                "latest_observed_at": NOW.isoformat(),
                "source_counts": {"injected_skill": 1}, "trend": "▁█",
                "recommendation": "observe", "recommendation_reason": "one load",
                "path": str(self.skill_a.parent),
            }],
        }
        rendered = auditor._markdown("stats", payload)
        self.assertIn("## Verifiable loads", rendered)
        self.assertIn("Coverage status: complete", rendered)
        self.assertNotIn("never used", rendered.lower())

    def test_cli_rejects_invalid_window(self):
        with self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                auditor.main(["stats", "--window-days", "0"])

    def test_cli_audit_refuses_empty_unsupported_logs(self):
        empty_log = self.session_root / "empty.jsonl"
        empty_log.write_text("", encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = auditor.main([
                "--skill-root", str(self.skill_root),
                "--session-root", str(self.session_root),
                "--state", str(self.root / "cli.sqlite3"),
                "--json", "audit",
            ])
        self.assertEqual(2, code)
        self.assertIn("no supported Skill-load records", stderr.getvalue())

    def test_cli_json_stats_are_ranked_and_traceable(self):
        self.write_log(
            "cli.jsonl",
            [session_meta(), function_call("read_file", {"path": str(self.skill_a)}, "trace-call")],
        )
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = auditor.main([
                "--skill-root", str(self.skill_root),
                "--session-root", str(self.session_root),
                "--state", str(self.root / "cli-state.sqlite3"),
                "--now", NOW.isoformat(),
                "--json", "stats", "--window-days", "30",
            ])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, code)
        self.assertEqual("alpha", payload["skills"][0]["name"])
        self.assertEqual(1, payload["skills"][0]["uses"])
        self.assertEqual({"skill_file_read": 1}, payload["skills"][0]["source_counts"])


if __name__ == "__main__":
    unittest.main()
