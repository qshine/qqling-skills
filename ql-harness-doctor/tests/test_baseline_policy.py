"""R02 catalog integration; judgments are synthetic, not an Agent behavior eval."""

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

SOURCE_ID = "anthropic-long-running@2025-11-26"


class BaselinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(
            (ROOT / "references/catalog/controls.json").read_text(encoding="utf-8")
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / ".git").mkdir()
        (root / "AGENTS.md").write_text(
            "Synthetic baseline rule.\nSynthetic execution record.\nSynthetic observation.\n", encoding="utf-8")
        self.evidence = collect_evidence(root)["evidence"]
        file_id = self.evidence["files"][0]["id"]
        refs, trace = synthetic_trace(file_id)
        self.judgments = [
            dict(control_id=c["id"], status="satisfied", rationale="Synthetic evidence",
                 evidence=copy.deepcopy(refs), evidence_trace=copy.deepcopy(trace))
            for c in self.catalog["controls"]
        ]

    def test_r02_reuses_l2_gate_without_duplicating_chapter_scoring(self):
        self.assertEqual("0.4.0", self.catalog["catalog_version"])
        self.assertEqual(46, len(self.catalog["controls"]))
        control = next(c for c in self.catalog["controls"] if c["id"] == "HD-BST-002")
        self.assertEqual(("L2", True, ["L06-C02"]),
                         (control["maturity"], control["is_gate"], control["source_aliases"]))
        self.assertEqual("0.4.0", control["lifecycle"]["changed_in"])
        self.assertEqual({SOURCE_ID, "walkinglabs-he@77e7a3e"},
                         {ref["source_id"] for ref in control["source_refs"]})

    def test_only_selected_article_and_control_gain_new_provenance(self):
        sources = json.loads(
            (ROOT / "references/catalog/sources.json").read_text(encoding="utf-8")
        )
        self.assertEqual("0.2.0", sources["registry_version"])
        by_id = {s["id"]: s for s in sources["source_snapshots"]}
        self.assertEqual({SOURCE_ID, "walkinglabs-he@77e7a3e"}, set(by_id))
        source = by_id[SOURCE_ID]
        self.assertEqual({"kind": "published_at", "value": "2025-11-26"}, source["revision"])
        self.assertEqual("2026-09-09", source["accessed_on"])
        references = [(c["id"], ref["document_id"]) for c in self.catalog["controls"]
                      for ref in c["source_refs"] if ref["source_id"] == SOURCE_ID]
        self.assertEqual([("HD-BST-002", "anthropic-long-running-agents")], references)
        self.assertEqual([references[0][1]], [d["id"] for d in source["documents"]])

    def test_baseline_states_feed_existing_coverage_and_recommendation_flow(self):
        for status in ("satisfied", "partial", "missing", "conflict", "unverifiable", "not_applicable"):
            with self.subTest(status=status):
                row = next(j for j in self.judgments if j["control_id"] == "HD-BST-002")
                row["status"] = status
                report = assess(self.catalog, self.evidence, self.judgments)
                self.assertEqual(46 if status == "satisfied" else 45, report["coverage"]["satisfied"])
                self.assertEqual(45 if status == "not_applicable" else 46, report["coverage"]["applicable"])
                applicable_gap = status not in {"satisfied", "not_applicable"}
                self.assertEqual("L1" if applicable_gap else "L3", report["maturity"]["level"])
                items = [item for group in recommend(self.catalog, report) for item in group["items"]]
                self.assertEqual(["HD-BST-002"] if applicable_gap else [],
                                 [item["control_id"] for item in items])
                if items:
                    self.assertEqual(status != "conflict", items[0]["automatic_changes"])
                if status == "partial":
                    self.assertTrue(select(self.catalog, report, ["HD-BST-002"])["ready"])

    def test_previous_catalog_report_cannot_skip_new_baseline_judgment(self):
        old_catalog = copy.deepcopy(self.catalog)
        old_catalog["catalog_version"] = "0.2.0"
        old_report = assess(old_catalog, self.evidence, self.judgments)
        with self.assertRaisesRegex(SafetyError, "REPORT_VERSION_MISMATCH"):
            recommend(self.catalog, old_report)


if __name__ == "__main__":
    unittest.main()
