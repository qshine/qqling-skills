import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from diagnostic import assess
from collect_evidence import collect_evidence
from selection import recommend, select
from safe_io import SafetyError
from evidence_fixtures import synthetic_trace


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "references/catalog/controls.json").read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / ".git").mkdir()
        (root / "AGENTS.md").write_text("Synthetic rule\nSynthetic record\nSynthetic observation\n")
        self.evidence = collect_evidence(root)["evidence"]
        self.file_id = self.evidence["files"][0]["id"]
        self.judgments = [{"control_id": c["id"], "status": "missing", "rationale": "No relevant evidence",
                           "evidence": []} for c in self.catalog["controls"]]

    def set_status(self, control_id, status):
        row = next(j for j in self.judgments if j["control_id"] == control_id)
        row["status"] = status
        if status in {"satisfied", "partial"}:
            row["evidence"], row["evidence_trace"] = synthetic_trace(self.file_id)
        else:
            row["evidence"] = []
            row.pop("evidence_trace", None)

    def report(self, enabled=False):
        return assess(self.catalog, self.evidence, self.judgments, enabled)

    def test_only_satisfied_is_numerator_and_na_excluded(self):
        statuses = ["satisfied", "partial", "missing", "conflict", "unverifiable", "not_applicable"]
        for index, row in enumerate(self.judgments):
            self.set_status(row["control_id"], statuses[index % 6])
        report = self.report()
        self.assertEqual(8, report["coverage"]["satisfied"])
        self.assertEqual(39, report["coverage"]["applicable"])
        self.assertEqual(round(800 / 39, 2), report["coverage"]["percent"])

    def test_zero_denominator_never_awards_l4(self):
        for row in self.judgments:
            self.set_status(row["control_id"], "not_applicable")
        report = self.report(True)
        self.assertIsNone(report["coverage"]["percent"])
        self.assertNotEqual("L4", report["maturity"]["level"])

    def test_lower_gates_and_l4_activation_are_required(self):
        for row in self.judgments:
            self.set_status(row["control_id"], "satisfied")
        self.assertEqual("L3", self.report()["maturity"]["level"])
        self.assertEqual("L4", self.report(True)["maturity"]["level"])
        self.set_status("HD-FND-001", "partial")
        self.assertEqual("L0", self.report(True)["maturity"]["level"])

    def test_missing_duplicate_or_unknown_judgments_rejected(self):
        for changed in (self.judgments[:-1], self.judgments + [self.judgments[0]],
                        self.judgments + [{"control_id": "not-a-control"}]):
            with self.assertRaises(SafetyError):
                assess(self.catalog, self.evidence, changed)

    def test_satisfied_requires_readable_real_reference_and_line(self):
        self.set_status("HD-FND-001", "satisfied")
        row = next(j for j in self.judgments if j["control_id"] == "HD-FND-001")
        for refs in ([], [{"file_id": "foreign", "line": 1}], [{"file_id": self.file_id, "line": 99}]):
            row["evidence"] = refs
            with self.assertRaises(SafetyError):
                self.report()

    def test_groups_do_not_auto_select_dependencies(self):
        report = self.report()
        groups = recommend(self.catalog, report)
        self.assertEqual(46, sum(len(g["items"]) for g in groups))
        selection = select(self.catalog, report, ["HD-INS-001"])
        self.assertEqual(["HD-INS-001"], selection["selected_ids"])
        self.assertEqual(["HD-FND-001"], selection["required_ids"])
        self.assertFalse(selection["ready"])
        resolved = select(self.catalog, report, ["HD-FND-001", "HD-INS-001"])
        self.assertTrue(resolved["ready"])

    def test_l4_cannot_be_selected_for_automatic_changes(self):
        with self.assertRaises(SafetyError):
            select(self.catalog, self.report(), ["HD-AUT-001"])

    def test_tampered_report_is_rejected(self):
        report = self.report()
        report["coverage"]["percent"] = 100
        with self.assertRaises(SafetyError):
            select(self.catalog, report, [])

    def test_empty_duplicate_unknown_and_symmetric_conflict_selections(self):
        self.assertFalse(select(self.catalog, self.report(), [])["ready"])
        for selected in (["HD-FND-001", "HD-FND-001"], ["HD-NOT-001"]):
            with self.assertRaises(SafetyError):
                select(self.catalog, self.report(), selected)
        for control in self.catalog["controls"]:
            if control["id"] == "HD-FND-001":
                control["conflicts_with"] = ["HD-KNW-001"]
            if control["id"] == "HD-KNW-001":
                control["conflicts_with"] = ["HD-FND-001"]
        result = select(self.catalog, self.report(), ["HD-FND-001", "HD-KNW-001"])
        self.assertFalse(result["ready"])
        self.assertEqual([["HD-FND-001", "HD-KNW-001"]], result["conflicts"])

    def test_optional_missing_control_does_not_block_l3(self):
        for control in self.catalog["controls"]:
            status = "satisfied" if control["is_gate"] and control["maturity"] != "L4" else "not_applicable"
            self.set_status(control["id"], status)
        self.set_status("HD-FND-002", "missing")
        self.assertEqual("L3", self.report()["maturity"]["level"])


if __name__ == "__main__":
    unittest.main()
