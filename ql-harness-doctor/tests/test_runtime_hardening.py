import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import changes
import collect_evidence as collector
import doctor
from diagnostic import assess
from safe_io import SafetyError, parse_json
from diagnostic import seal
from selection import recommend, select


class RuntimeHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["/usr/bin/git", "init", "-q", str(self.root)], check=True)
        (self.root / "README.md").write_text("User text\n")
        self.catalog = json.loads((ROOT / "references/catalog/controls.json").read_text())

    def inputs(self, status="missing"):
        evidence = collector.collect_evidence(self.root)["evidence"]
        judgments = [dict(control_id=c["id"], status=status, rationale="Fixture assessment", evidence=[])
                     for c in self.catalog["controls"]]
        report = assess(self.catalog, evidence, judgments)
        selection = select(self.catalog, report, ["HD-FND-001"])
        edit = dict(path="AGENTS.md", mode="create", content="# Instructions\n", control_ids=["HD-FND-001"])
        return evidence, judgments, selection, edit

    def test_malformed_evidence_and_references_raise_boundary_errors(self):
        evidence, judgments, _, _ = self.inputs()
        bad = copy.deepcopy(evidence)
        bad["files"][0]["path"] = "../secret"
        with self.assertRaises(SafetyError):
            assess(self.catalog, bad, judgments)
        bad = copy.deepcopy(evidence)
        bad["files"][0]["lines"][0]["line"] = True
        with self.assertRaises(SafetyError):
            assess(self.catalog, bad, judgments)
        judgments[0].update(status="satisfied", evidence=[dict(file_id=[], line=1)])
        with self.assertRaises(SafetyError):
            assess(self.catalog, evidence, judgments)

    def test_conflicting_old_instructions_cannot_be_masked_by_append(self):
        _, _, selection, edit = self.inputs("conflict")
        with self.assertRaisesRegex(SafetyError, "CONFLICT"):
            changes.preview(self.root, selection, [edit], [])

    def test_task_json_and_known_configs_are_read_but_arbitrary_fixtures_are_not(self):
        for name in ("tasks/work.json", "automation.yaml", "observability.yml", "hygiene.json", ".cursorrules"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("{}\n")
        (self.root / "tests").mkdir()
        (self.root / "tests/data.json").write_text("{}\n")
        rows = {r["path"]: r for r in collector.collect_evidence(self.root)["evidence"]["files"]}
        for name in ("tasks/work.json", "automation.yaml", "observability.yml", "hygiene.json", ".cursorrules"):
            self.assertEqual("read", rows[name]["read_status"], name)
        self.assertEqual("metadata_only", rows["tests/data.json"]["read_status"])

    def test_collector_cli_invalid_values_are_not_echoed(self):
        out = io.StringIO()
        with patch.object(sys, "argv", ["collect_evidence.py", "--json", "private-invalid"]), redirect_stdout(out):
            code = collector.main()
        self.assertEqual(2, code)
        self.assertNotIn("private-invalid", out.getvalue())
        self.assertEqual("EVIDENCE_USAGE_INVALID", json.loads(out.getvalue())["errors"][0]["code"])

    def test_root_index_commit_and_parent_link_drift_refuse_before_writing(self):
        _, _, selection, edit = self.inputs()
        manifest = changes.preview(self.root, selection, [edit], [])
        other = self.root / "other"
        other.mkdir()
        subprocess.run(["/usr/bin/git", "init", "-q", str(other)], check=True)
        with self.assertRaises(SafetyError):
            changes.apply_preview(other, manifest, manifest["digest"])
        subprocess.run(["/usr/bin/git", "add", "README.md"], cwd=self.root, check=True)
        with self.assertRaises(SafetyError):
            changes.apply_preview(self.root, manifest, manifest["digest"])
        _, _, selection, edit = self.inputs()
        manifest = changes.preview(self.root, selection, [edit], [])
        subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Fixture"], cwd=self.root, check=True)
        with self.assertRaises(SafetyError):
            changes.apply_preview(self.root, manifest, manifest["digest"])
        _, _, selection, edit = self.inputs()
        edit["path"] = "docs/guide.md"
        manifest = changes.preview(self.root, selection, [edit], [])
        (self.root / "docs").symlink_to(other, target_is_directory=True)
        with self.assertRaises(SafetyError):
            changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertFalse((other / "guide.md").exists())
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_short_writes_are_completed(self):
        _, _, selection, edit = self.inputs()
        manifest = changes.preview(self.root, selection, [edit], [])
        original = os.write
        with patch.object(changes.os, "write", side_effect=lambda fd, data: original(fd, data[:2])):
            result = changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertTrue(result["ok"])
        self.assertEqual(edit["content"], (self.root / "AGENTS.md").read_text())

    def test_post_write_verification_failure_is_reported_as_partial(self):
        _, _, selection, edit = self.inputs()
        manifest = changes.preview(self.root, selection, [edit], [])
        original = changes.check_bytes
        calls = []
        def check(path, data, checks):
            calls.append(path)
            if len(calls) == 2:
                raise SafetyError("VERIFICATION_FAILED")
            return original(path, data, checks)
        with patch.object(changes, "check_bytes", side_effect=check):
            result = changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertFalse(result["ok"])
        self.assertEqual(["AGENTS.md"], result["applied_paths"])
        self.assertEqual("AGENTS.md", result["failed_path"])

    def test_linked_worktree_preview_uses_git_metadata_without_touching_primary_files(self):
        subprocess.run(["/usr/bin/git", "add", "README.md"], cwd=self.root, check=True)
        subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Fixture"], cwd=self.root, check=True)
        worktree = self.root / "linked"
        subprocess.run(["/usr/bin/git", "worktree", "add", "-q", "-b", "linked", str(worktree)], cwd=self.root, check=True)
        primary = self.root
        self.root = worktree
        _, _, selection, edit = self.inputs()
        manifest = changes.preview(worktree, selection, [edit], [])
        result = changes.apply_preview(worktree, manifest, manifest["digest"])
        self.assertTrue(result["ok"])
        self.assertFalse((primary / "AGENTS.md").exists())

    def test_git_fsmonitor_and_hooks_are_not_executed_by_preview(self):
        hook = self.root / "malicious-hook"
        hook.write_text("#!/bin/sh\ntouch DO_NOT_CREATE\n")
        hook.chmod(0o755)
        subprocess.run(["/usr/bin/git", "config", "core.fsmonitor", str(hook)], cwd=self.root, check=True)
        subprocess.run(["/usr/bin/git", "config", "core.hooksPath", str(self.root)], cwd=self.root, check=True)
        _, _, selection, edit = self.inputs()
        manifest = changes.preview(self.root, selection, [edit], [])
        changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertFalse((self.root / "DO_NOT_CREATE").exists())

    def test_changed_report_catalog_fields_are_rejected_even_with_new_digest(self):
        evidence, judgments, _, _ = self.inputs()
        report = assess(self.catalog, evidence, judgments)
        report.pop("digest")
        report["controls"][0]["maturity"] = "L0"
        with self.assertRaises(SafetyError):
            recommend(self.catalog, seal(report))

    def test_directory_swap_to_symlink_is_not_followed(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "README.md").write_text("OUTSIDE-CANARY\n")
        (self.root / "docs").mkdir()
        (self.root / "docs/README.md").write_text("Allowed content\n")
        original = collector.open_directory
        def swapping(name, parent_fd=None):
            if name == "docs":
                (self.root / "docs").rename(self.root / "old-docs")
                (self.root / "docs").symlink_to(outside.name, target_is_directory=True)
            return original(name, parent_fd)
        with patch.object(collector, "open_directory", side_effect=swapping):
            result = collector.collect_evidence(self.root)
        self.assertFalse(result["evidence"]["scan"]["complete_within_policy"])
        self.assertNotIn("OUTSIDE-CANARY", json.dumps(result))

    def test_changed_file_content_is_discarded_after_read(self):
        original = collector.read_at
        def changing(parent, name, limit):
            if name == "README.md":
                raise SafetyError("FILE_CHANGED")
            return original(parent, name, limit)
        with patch.object(collector, "read_at", side_effect=changing):
            result = collector.collect_evidence(self.root)["evidence"]
        self.assertFalse(result["scan"]["complete_within_policy"])
        self.assertEqual([], result["files"][0]["lines"])
        self.assertIsNone(result["files"][0]["sha256"])

    def test_depth_file_count_and_total_byte_limits_report_incomplete(self):
        (self.root / "docs").mkdir()
        (self.root / "docs/guide.md").write_text("Guide\n")
        for limits in (dict(depth=0), dict(files=1), dict(total_bytes=1)):
            with patch.dict(collector.LIMITS, **limits):
                result = collector.collect_evidence(self.root)["evidence"]
            self.assertFalse(result["scan"]["complete_within_policy"])

    def test_invalid_json_python_and_sensitive_candidate_are_rejected(self):
        _, _, selection, edit = self.inputs()
        for path, content in [("tasks/state.json", '{"a":1,"a":2}'),
                              (".harness/checks/check.py", "if :"),
                              ("AGENTS.md", "password=private-canary")]:
            with self.assertRaises(SafetyError):
                changes.preview(self.root, selection, [dict(edit, path=path, content=content)], [])
        manifest = changes.preview(self.root, selection, [dict(edit, path="tasks/state.json", content="{}\n")], [])
        self.assertEqual(["json", "utf8"], manifest["checks"])

    def test_no_newline_diff_is_explicit_and_append_preserves_exact_bytes(self):
        (self.root / "README.md").write_bytes(b"no newline")
        _, _, selection, edit = self.inputs()
        edit.update(path="README.md", mode="append", content="\nnew line\n")
        manifest = changes.preview(self.root, selection, [edit], [])
        self.assertIn("\\ No newline at end of file", manifest["diff"])
        changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertEqual(b"no newline\nnew line\n", (self.root / "README.md").read_bytes())

    def test_request_file_must_be_bounded_regular_and_outside_target(self):
        inside = self.root / "request.json"
        inside.write_text("{}")
        with self.assertRaises(SafetyError):
            doctor.read_request(str(inside), self.root)
        with patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"x" * 17))), patch.object(doctor, "MAX_REQUEST_BYTES", 16):
            with self.assertRaises(SafetyError):
                doctor.read_request("-", self.root)

    def test_oversized_preview_is_rejected_before_confirmation_or_writes(self):
        _, _, selection, edit = self.inputs()
        with patch.object(changes, "MAX_PREVIEW_BYTES", 32):
            with self.assertRaisesRegex(SafetyError, "PREVIEW_TOO_LARGE"):
                changes.preview(self.root, selection, [edit], [])
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_non_finite_numbers_are_never_accepted_by_strict_json(self):
        for value in ("NaN", "Infinity", "1e9999"):
            with self.assertRaises(SafetyError):
                parse_json('{"value":' + value + '}')


if __name__ == "__main__":
    unittest.main()
