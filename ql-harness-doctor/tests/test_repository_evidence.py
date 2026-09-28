import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import collect_evidence as collector


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        (self.root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.root / ".git/index").write_bytes(b"synthetic index")

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def scan(self):
        return collector.collect_evidence(self.root)

    def test_documents_have_original_lines_hash_scope_and_stable_output(self):
        self.put("apps/api/AGENTS.md", "# API\nRun checks before delivery.\n")
        a, b = self.scan(), self.scan()
        self.assertEqual(a, b)
        self.assertTrue(a["ok"])
        row = a["evidence"]["files"][0]
        self.assertEqual("apps/api", row["scope"])
        self.assertEqual({"line": 2, "text": "Run checks before delivery."}, row["lines"][1])
        self.assertEqual(hashlib.sha256(b"# API\nRun checks before delivery.\n").hexdigest(), row["sha256"])
        self.assertNotIn(str(self.root), json.dumps(a))

    def test_invalid_root_does_not_ascend(self):
        (self.root / "subdir").mkdir()
        result = collector.collect_evidence(self.root / "subdir")
        self.assertFalse(result["ok"])
        self.assertEqual("EVIDENCE_ROOT_INVALID", result["errors"][0]["code"])

    def test_empty_repository_returns_unknown_git_status(self):
        result = self.scan()["evidence"]
        self.assertEqual([], result["files"])
        self.assertTrue(result["scan"]["complete_within_policy"])
        self.assertEqual("unverifiable", result["repository"]["git"]["worktree_status"])

    def test_no_network_or_subprocess_and_no_application_writes(self):
        path = self.put("README.md", "Useful documentation\n")
        before = (path.read_bytes(), path.stat().st_mtime_ns,
                  sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))
        with patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
                patch.object(socket, "socket", side_effect=AssertionError("network")):
            self.assertTrue(self.scan()["ok"])
        after = (path.read_bytes(), path.stat().st_mtime_ns,
                 sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))
        self.assertEqual(before, after)

    def test_secrets_links_and_dependency_trees_are_never_read(self):
        self.put(".env", "CANARY")
        self.put("node_modules/README.md", "CANARY")
        self.put("private.key", "CANARY")
        self.put("README.md", "api_key = CANARY12345\n")
        (self.root / "AGENTS.md").symlink_to(self.root / ".env")
        with patch.object(collector, "read_at", wraps=collector.read_at) as reader:
            result = self.scan()
        names = [call.args[1] for call in reader.call_args_list]
        self.assertNotIn(".env", names)
        self.assertNotIn("AGENTS.md", names)
        self.assertNotIn("private.key", names)
        self.assertNotIn("CANARY", json.dumps(result))
        row = next(r for r in result["evidence"]["files"] if r["path"] == "README.md")
        self.assertEqual("withheld_sensitive", row["read_status"])
        self.assertIsNone(row["sha256"])

    def test_nested_repositories_and_worktree_pointers_are_not_followed(self):
        self.put("vendor/tool/.git", "gitdir: /private/CANARY\n")
        self.put("vendor/tool/README.md", "CANARY")
        result = self.scan()
        self.assertNotIn("CANARY", json.dumps(result))
        self.assertFalse(any(r["path"].startswith("vendor/tool/") for r in result["evidence"]["files"]))

    def test_static_command_names_are_not_executed(self):
        self.put("package.json", '{"scripts":{"test":"touch DO_NOT_CREATE"}}')
        self.put("Makefile", "check:\n\ttouch DO_NOT_CREATE\n")
        result = self.scan()["evidence"]
        self.assertEqual({"test", "check"}, {c["name"] for c in result["commands"]})
        self.assertTrue(all(c["executed"] is False for c in result["commands"]))
        self.assertFalse((self.root / "DO_NOT_CREATE").exists())

    def test_invalid_manifest_has_no_guessed_commands(self):
        self.put("package.json", '{"scripts":{},"scripts":{"test":"run"}}')
        result = self.scan()["evidence"]
        self.assertEqual([], result["commands"])
        self.assertTrue(any(item["code"] == "DECLARATION_UNPARSED" for item in result["limitations"]))

    def test_arbitrary_test_fixture_is_metadata_only(self):
        self.put("tests/patient_data.json", '["PRIVATE CANARY"]')
        result = self.scan()
        self.assertNotIn("PRIVATE CANARY", json.dumps(result))
        self.assertEqual("metadata_only", result["evidence"]["files"][0]["read_status"])

    def test_size_and_enumeration_limits_are_explicit(self):
        self.put("README.md", "x" * 200)
        with patch.dict(collector.LIMITS, file_bytes=100):
            result = self.scan()["evidence"]
        self.assertFalse(result["scan"]["complete_within_policy"])
        self.assertEqual([], result["files"][0]["lines"])
        with patch.dict(collector.LIMITS, entries=1):
            result = self.scan()["evidence"]
        self.assertFalse(result["scan"]["complete_within_policy"])
        self.assertEqual([], result["files"])

    def test_hardlinks_fifo_and_unsafe_filenames_are_not_opened(self):
        source = self.put("source", "CANARY")
        os.link(source, self.root / "README.md")
        os.mkfifo(self.root / "AGENTS.md")
        self.put("evil\nREADME.md", "CANARY")
        result = self.scan()
        self.assertNotIn("CANARY", json.dumps(result))
        self.assertEqual([], result["evidence"]["files"])

    def test_excerpt_budget_is_global_and_has_original_line_numbers(self):
        self.put("README.md", "1234567890\nsecond line\n")
        with patch.dict(collector.LIMITS, excerpt_chars=5):
            result = self.scan()["evidence"]
        self.assertEqual(5, result["scan"]["excerpt_chars"])
        self.assertTrue(result["files"][0]["excerpt_truncated"])

    def test_worktree_marker_does_not_expose_external_path(self):
        import shutil
        shutil.rmtree(self.root / ".git")
        self.put(".git", "gitdir: /private/CANARY/worktree\n")
        self.put("README.md", "Normal documentation\n")
        result = self.scan()
        self.assertTrue(result["ok"])
        self.assertNotIn("CANARY", json.dumps(result))
        self.assertIsNone(result["evidence"]["repository"]["git"]["head_sha256"])


if __name__ == "__main__":
    unittest.main()
