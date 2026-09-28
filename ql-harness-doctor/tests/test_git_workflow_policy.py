import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from collect_evidence import collect_evidence
from diagnostic import assess
from safe_io import SafetyError
from selection import recommend, select
from evidence_fixtures import synthetic_trace


class GitWorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(
            (ROOT / "references/catalog/controls.json").read_text(encoding="utf-8")
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / ".git").mkdir()
        (root / "AGENTS.md").write_text(
            "# Repository workflow\nTask isolation and checkpoints.\nSynthetic record.\nSynthetic observation.\n",
            encoding="utf-8"
        )
        self.evidence = collect_evidence(root)["evidence"]
        file_id = self.evidence["files"][0]["id"]
        # Synthetic judgments exercise the deterministic pipeline, not real Git compliance.
        refs, trace = synthetic_trace(file_id, first_line=2)
        self.judgments = [
            dict(
                control_id=control["id"],
                status="satisfied",
                rationale="Synthetic policy evidence",
                evidence=copy.deepcopy(refs), evidence_trace=copy.deepcopy(trace),
            )
            for control in self.catalog["controls"]
        ]

    def test_confirmed_checks_are_versioned_without_duplicate_book_scoring(self):
        self.assertEqual("0.4.0", self.catalog["catalog_version"])
        self.assertEqual(46, len(self.catalog["controls"]))
        controls = {c["id"]: c for c in self.catalog["controls"]}
        for control_id, term in (("HD-SCP-001", "Worktree"), ("HD-STA-004", "Git 提交")):
            control = controls[control_id]
            self.assertIn(term, control["requirement"])
            self.assertIn("2026-09-09", control["requirement"])
            self.assertEqual("0.4.0", control["lifecycle"]["changed_in"])
        self.assertEqual(74, len({a for c in controls.values() for a in c["source_aliases"]}))

    def test_worktree_gap_blocks_l2_and_is_selectable_without_autonomy(self):
        row = next(j for j in self.judgments if j["control_id"] == "HD-SCP-001")
        row.update(status="partial", rationale="Only reuses an existing workspace; no per-task creation policy")
        report = assess(self.catalog, self.evidence, self.judgments)
        self.assertEqual("L1", report["maturity"]["level"])
        choice = select(self.catalog, report, ["HD-SCP-001"])
        self.assertTrue(choice["ready"])

    def test_commit_gap_blocks_l3_and_is_recommended(self):
        row = next(j for j in self.judgments if j["control_id"] == "HD-STA-004")
        row.update(status="partial", rationale="Progress notes exist but no completed-change commit evidence")
        report = assess(self.catalog, self.evidence, self.judgments)
        self.assertEqual("L2", report["maturity"]["level"])
        gaps = recommend(self.catalog, report)
        self.assertEqual(["HD-STA-004"], [i["control_id"] for g in gaps for i in g["items"]])
        self.assertEqual(["AGENTS.md"], [f["path"] for f in self.evidence["files"]])

    def test_old_catalog_report_cannot_reuse_previous_acceptance(self):
        old = copy.deepcopy(self.catalog)
        old["catalog_version"] = "0.1.0"
        old_report = assess(old, self.evidence, self.judgments)
        with self.assertRaises(SafetyError):
            select(self.catalog, old_report, [])


if __name__ == "__main__":
    unittest.main()
