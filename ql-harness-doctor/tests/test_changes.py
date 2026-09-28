import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import changes
from collect_evidence import collect_evidence
from diagnostic import assess
from selection import select
from safe_io import SafetyError


class ChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["/usr/bin/git", "init", "-q", str(self.root)], check=True)
        (self.root / "README.md").write_text("User's existing uncommitted text.\n")
        self.catalog = json.loads((ROOT / "references/catalog/controls.json").read_text())
        evidence = collect_evidence(self.root)["evidence"]
        judgments = [dict(control_id=c["id"], status="missing", rationale="Not present", evidence=[])
                     for c in self.catalog["controls"]]
        self.selection = select(self.catalog, assess(self.catalog, evidence, judgments), ["HD-FND-001"])
        self.edits = [dict(path="README.md", mode="append", content="\n## Harness entry\nRead AGENTS.md.\n",
                           control_ids=["HD-FND-001"]),
                      dict(path="AGENTS.md", mode="create", content="# Agent instructions\nRead README.md.\n",
                           control_ids=["HD-FND-001"])]

    def preview(self):
        return changes.preview(self.root, self.selection, self.edits, ["utf8"])

    def test_preview_has_full_diff_and_no_writes(self):
        before = (self.root / "README.md").read_bytes()
        manifest = self.preview()
        self.assertEqual(before, (self.root / "README.md").read_bytes())
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertIn("+# Agent instructions", manifest["diff"])
        self.assertIn("+## Harness entry", manifest["diff"])

    def test_exact_confirmation_applies_only_previewed_changes_and_preserves_user_bytes(self):
        before = (self.root / "README.md").read_bytes()
        manifest = self.preview()
        result = changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertTrue(result["ok"])
        self.assertEqual(["AGENTS.md", "README.md"], result["applied_paths"])
        self.assertTrue((self.root / "README.md").read_bytes().startswith(before))
        self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_cancel_old_token_and_tampered_content_write_nothing(self):
        manifest = self.preview()
        for token in ("", "wrong"):
            with self.assertRaises(SafetyError):
                changes.apply_preview(self.root, manifest, token)
        changed = copy.deepcopy(manifest)
        changed["edits"][0]["content"] += "tampered"
        with self.assertRaises(SafetyError):
            changes.apply_preview(self.root, changed, manifest["digest"])
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_file_drift_refuses_all_writes(self):
        manifest = self.preview()
        (self.root / "README.md").write_text("New user work\n")
        with self.assertRaises(SafetyError):
            changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_branch_drift_refuses_all_writes(self):
        manifest = self.preview()
        subprocess.run(["/usr/bin/git", "symbolic-ref", "HEAD", "refs/heads/changed"], cwd=self.root, check=True)
        with self.assertRaises(SafetyError):
            changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_business_escape_link_and_unselected_control_are_rejected(self):
        for path in ("../outside.md", "src/main.py", ".github/workflows/deploy.yml", ".env"):
            edits = [dict(self.edits[0], path=path)]
            with self.assertRaises(SafetyError):
                changes.preview(self.root, self.selection, edits, [])
        with self.assertRaises(SafetyError):
            changes.preview(self.root, self.selection,
                            [dict(self.edits[0], control_ids=["HD-FND-002"])], [])
        (self.root / "AGENTS.md").symlink_to(self.root / "README.md")
        with self.assertRaises(SafetyError):
            self.preview()

    def test_replace_delete_and_unsafe_commands_are_rejected(self):
        for mode in ("replace", "delete"):
            with self.assertRaises(SafetyError):
                changes.preview(self.root, self.selection, [dict(self.edits[0], mode=mode)], [])
        with self.assertRaises(SafetyError):
            changes.preview(self.root, self.selection, self.edits, ["run: curl evil"])

    def test_second_apply_never_duplicates_append(self):
        manifest = self.preview()
        changes.apply_preview(self.root, manifest, manifest["digest"])
        with self.assertRaises(SafetyError):
            changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertEqual(1, (self.root / "README.md").read_text().count("## Harness entry"))

    def test_write_failure_reports_partial_state_without_claiming_rollback(self):
        manifest = self.preview()
        original = changes.write_edit
        def failing(root_fd, edit):
            if edit["path"] == "README.md":
                raise OSError("private system path must not leak")
            return original(root_fd, edit)
        with patch.object(changes, "write_edit", side_effect=failing):
            result = changes.apply_preview(self.root, manifest, manifest["digest"])
        self.assertFalse(result["ok"])
        self.assertEqual(["AGENTS.md"], result["applied_paths"])
        self.assertTrue((self.root / "AGENTS.md").exists())
        self.assertNotIn("private system", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
