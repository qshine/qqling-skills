import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DoctorCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repository"
        self.root.mkdir()
        subprocess.run(["/usr/bin/git", "init", "-q", str(self.root)], check=True)
        (self.root / "README.md").write_text("# Example project\n")
        self.script = ROOT / "scripts/doctor.py"
        self.catalog = json.loads((ROOT / "references/catalog/controls.json").read_text())

    def cli(self, command, payload=None, extra=()):
        result = subprocess.run([sys.executable, "-B", str(self.script), command, "--repo", str(self.root),
                                 *extra], input=json.dumps(payload) if payload is not None else "",
                                text=True, capture_output=True, cwd=self.root, timeout=20)
        self.assertEqual("", result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_complete_flow_and_reassessment_use_real_new_evidence(self):
        code, scan = self.cli("scan")
        self.assertEqual(0, code)
        judgments = [dict(control_id=c["id"], status="missing", rationale="Not evidenced", evidence=[])
                     for c in self.catalog["controls"]]
        code, assessment = self.cli("assess", dict(evidence=scan["evidence"], judgments=judgments))
        self.assertEqual(0, code)
        report = assessment["result"]
        self.assertEqual(0, report["coverage"]["satisfied"])
        self.assertEqual(0, self.cli("recommend", dict(report=report))[0])
        _, selection = self.cli("select", dict(report=report, selected_ids=["HD-FND-001"]))
        _, preview = self.cli("preview", dict(selection=selection["result"], checks=["utf8"], edits=[dict(
            path="AGENTS.md", mode="create", content="# Harness entry\nRead README.md.\n",
            control_ids=["HD-FND-001"])]))
        self.assertFalse((self.root / "AGENTS.md").exists())
        code, denied = self.cli("apply", dict(manifest=preview["result"]))
        self.assertEqual(2, code)
        self.assertFalse(denied["ok"])
        code, applied = self.cli("apply", dict(manifest=preview["result"]),
                                 ["--confirm", preview["result"]["digest"]])
        self.assertEqual(0, code)
        self.assertTrue(applied["result"]["ok"])
        _, rescan = self.cli("scan")
        file = next(f for f in rescan["evidence"]["files"] if f["path"] == "AGENTS.md")
        next(j for j in judgments if j["control_id"] == "HD-FND-001").update(
            status="satisfied", rationale="The fixture has the expected entry and route.",
            evidence=[dict(file_id=file["id"], line=2)],
            evidence_trace=dict(declarations=[dict(file_id=file["id"], line=2)],
                                execution_records=[], result_checks=[]))
        code, reassessed = self.cli("assess", dict(evidence=rescan["evidence"], judgments=judgments))
        self.assertEqual(0, code)
        self.assertEqual(1, reassessed["result"]["coverage"]["satisfied"])
        self.assertNotEqual(report["evidence_digest"], reassessed["result"]["evidence_digest"])

    def test_invalid_arguments_and_requests_never_echo_values(self):
        for args, raw in [(["unknown-private-value"], ""), (["assess"], '{"private-value":NaN}'),
                          (["assess"], '{"a":1,"a":2}'), (["assess"], '[]'),
                          (["assess"], '{"evidence":{},"judgments":[]}')]:
            result = subprocess.run([sys.executable, "-B", str(self.script), *args], input=raw,
                                    text=True, capture_output=True, timeout=20)
            self.assertEqual(2, result.returncode)
            self.assertNotIn("private-value", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])

    def test_package_is_self_contained_when_copied_and_called_elsewhere(self):
        copied = Path(self.temp.name) / "ql-harness-doctor"
        shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns("__pycache__"))
        self.script = copied / "scripts/doctor.py"
        code, result = self.cli("scan")
        self.assertEqual(0, code)
        self.assertTrue(result["ok"])
        self.assertFalse((self.root / ".harness").exists())

    def test_report_cannot_be_selected_in_another_repository(self):
        _, scan = self.cli("scan")
        judgments = [dict(control_id=c["id"], status="missing", rationale="Not evidenced", evidence=[])
                     for c in self.catalog["controls"]]
        _, assessment = self.cli("assess", dict(evidence=scan["evidence"], judgments=judgments))
        self.root = Path(self.temp.name).resolve() / "other"
        self.root.mkdir()
        subprocess.run(["/usr/bin/git", "init", "-q", str(self.root)], check=True)
        code, result = self.cli("select", dict(report=assessment["result"], selected_ids=["HD-FND-001"]))
        self.assertEqual(2, code)
        self.assertFalse(result["ok"])

    def test_skill_metadata_routes_to_real_resources(self):
        skill = (ROOT / "SKILL.md").read_text()
        self.assertTrue(skill.startswith("---\nname: ql-harness-doctor\n"))
        metadata = (ROOT / "agents/openai.yaml").read_text()
        self.assertIn("$ql-harness-doctor", metadata)
        for path in ("references/workflow.md", "references/collection-policy.md", "references/evidence.schema.json"):
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertIn("最终确认", skill)


if __name__ == "__main__":
    unittest.main()
