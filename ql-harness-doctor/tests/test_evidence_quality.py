"""Evidence strength is a bounded Agent assertion, not authenticated execution."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from collect_evidence import collect_evidence
from diagnostic import assess, seal
from evidence_fixtures import synthetic_trace
from safe_io import SafetyError
from selection import recommend, select


class EvidenceQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        (self.root / "AGENTS.md").write_text(
            "Rule: record task state before implementation.\n"
            "Record: synthetic task was marked active before editing.\n"
            "Observation: synthetic event sequence matches the recorded transition.\n"
        )
        self.catalog = json.loads((ROOT / "references/catalog/controls.json").read_text())
        self.evidence = collect_evidence(self.root)["evidence"]
        file_id = self.evidence["files"][0]["id"]
        self.refs, self.trace = synthetic_trace(file_id)
        self.judgments = [dict(control_id=c["id"], status="missing", rationale="No task evidence",
                               evidence=[]) for c in self.catalog["controls"]]
        self.row = next(j for j in self.judgments if j["control_id"] == "HD-STA-003")
        self.row.update(status="partial", evidence=self.refs, evidence_trace=self.trace)

    def report(self):
        return assess(self.catalog, self.evidence, self.judgments)

    def result_row(self, report=None):
        return next(r for r in (report or self.report())["controls"]
                    if r["control_id"] == self.row["control_id"])

    def test_three_evidence_stages_and_limitations_survive_recommendations(self):
        for expected, executions, checks in (("declared", [], []),
                                              ("recorded", [self.refs[1]], []),
                                              ("verified", [self.refs[1]], self.trace["result_checks"])):
            self.row["evidence_trace"] = dict(declarations=[self.refs[0]],
                                               execution_records=executions, result_checks=checks)
            report = self.report()
            row = self.result_row(report)
            self.assertEqual(expected, row["evidence_level"])
            self.assertEqual("verified", row["minimum_evidence_level"])
            self.assertEqual(1, report["evidence_levels"][expected])
            item = next(i for group in recommend(self.catalog, report) for i in group["items"]
                        if i["control_id"] == self.row["control_id"])
            self.assertEqual(row["evidence_trace"], item["evidence_trace"])
            self.assertEqual(expected, item["evidence_level"])

    def test_rules_and_unverified_records_cannot_satisfy_execution_controls(self):
        self.row["status"] = "satisfied"
        self.row["evidence_trace"]["result_checks"] = []
        for executions in ([], [self.refs[1]]):
            self.row["evidence_trace"]["execution_records"] = executions
            with self.assertRaisesRegex(SafetyError, "EVIDENCE_LEVEL_INSUFFICIENT"):
                self.report()

    def test_verified_result_can_satisfy_but_never_auto_promotes_status(self):
        report = self.report()
        self.assertEqual(0, report["coverage"]["satisfied"])
        self.row["status"] = "satisfied"
        self.assertEqual(1, self.report()["coverage"]["satisfied"])

    def test_static_instruction_can_be_satisfied_by_declaration(self):
        self.row.update(control_id="HD-INS-002", status="satisfied", evidence=[self.refs[0]],
                        evidence_trace=dict(declarations=[self.refs[0]], execution_records=[], result_checks=[]))
        self.judgments = [j for j in self.judgments if j is self.row or j["control_id"] != "HD-INS-002"]
        self.judgments.append(dict(control_id="HD-STA-003", status="missing", rationale="Not present", evidence=[]))
        self.assertEqual("declared", self.result_row()["evidence_level"])

    def test_legacy_references_stay_unclassified_and_cannot_claim_satisfied(self):
        del self.row["evidence_trace"]
        self.assertEqual("unclassified", self.result_row()["evidence_level"])
        self.row["status"] = "satisfied"
        with self.assertRaisesRegex(SafetyError, "EVIDENCE_LEVEL_INSUFFICIENT"):
            self.report()

    def test_contradicted_or_inconclusive_check_prevents_satisfied(self):
        for outcome in ("contradicted", "inconclusive"):
            with self.subTest(outcome=outcome):
                self.row["status"] = "partial"
                self.trace["result_checks"][0]["outcome"] = outcome
                report = self.report()
                self.assertEqual("verified" if outcome == "contradicted" else "recorded",
                                 self.result_row(report)["evidence_level"])
                self.assertEqual(1, report["verification_outcomes"][outcome])
                self.row["status"] = "satisfied"
                with self.assertRaisesRegex(SafetyError, "VERIFICATION_NOT_CONFIRMED"):
                    self.report()

    def test_invalid_or_self_confirming_trace_is_rejected(self):
        variants = [
            lambda t: t.update(unknown=[]),
            lambda t: t.update(declarations=None),
            lambda t: t["execution_records"].append(t["execution_records"][0]),
            lambda t: t.update(execution_records=[self.refs[0]]),
            lambda t: t["result_checks"][0].update(observation=self.refs[1]),
            lambda t: t["result_checks"][0].update(observation=self.refs[0]),
            lambda t: t["result_checks"][0].update(record=self.refs[2]),
            lambda t: t["result_checks"][0].update(observation=dict(file_id="foreign", line=1)),
            lambda t: t["result_checks"][0].update(observation=dict(file_id=self.refs[0]["file_id"], line=None)),
            lambda t: t["result_checks"][0].update(method="trust_me"),
            lambda t: t["result_checks"][0].update(outcome="passed"),
            lambda t: t["result_checks"][0].update(scope=""),
            lambda t: t["result_checks"][0].update(checked_at="yesterday"),
            lambda t: t["result_checks"][0].update(checked_at="2026-09-13T10:00:00"),
            lambda t: t["result_checks"][0].update(checked_at="2026-09-13T10:00:00+00:99"),
            lambda t: t["result_checks"][0].update(checked_at="2026-02-30T10:00:00Z"),
            lambda t: t["result_checks"][0].update(scope="x" * 2001),
            lambda t: t["result_checks"][0].update(limitations="password=fixture"),
            lambda t: t["result_checks"].append(t["result_checks"][0]),
        ]
        for change in variants:
            trace = copy.deepcopy(self.trace)
            change(trace)
            self.row["evidence_trace"] = trace
            with self.subTest(trace=trace), self.assertRaises(SafetyError):
                self.report()

    def test_metadata_and_unseen_lines_cannot_back_verification(self):
        for line in (True, 99):
            ref = dict(file_id=self.refs[0]["file_id"], line=line)
            self.row["evidence"] = self.refs + [ref]
            self.row["evidence_trace"]["result_checks"][0]["observation"] = ref
            with self.assertRaises(SafetyError):
                self.report()
        self.row["evidence"] = self.refs
        self.evidence["files"][0]["read_status"] = "metadata_only"
        with self.assertRaises(SafetyError):
            self.report()

    def test_resealed_reports_cannot_bypass_strength_or_version_checks(self):
        report = self.report()
        for mutate in (
            lambda r: r.update(schema_version="1.0.0"),
            lambda r: r["evidence_levels"].update(verified=46),
            lambda r: r["verification_outcomes"].update(confirmed=46),
            lambda r: self.result_row(r).update(status="satisfied", evidence_level="declared"),
            lambda r: self.result_row(r).update(minimum_evidence_level="declared"),
            lambda r: self.result_row(r).update(evidence_level="declared"),
        ):
            changed = copy.deepcopy(report)
            mutate(changed)
            changed = seal({k: v for k, v in changed.items() if k != "digest"})
            for action in (lambda: recommend(self.catalog, changed),
                           lambda: select(self.catalog, changed, ["HD-STA-003"])):
                with self.assertRaises(SafetyError):
                    action()

    def test_cli_assessment_exposes_strength_without_writing_target(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/doctor.py"), "assess", "--repo", str(self.root)],
            input=json.dumps(dict(evidence=self.evidence, judgments=self.judgments)),
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(0, result.returncode, result.stdout)
        report = json.loads(result.stdout)["result"]
        self.assertEqual("1.1.0", report["schema_version"])
        self.assertEqual("verified", self.result_row(report)["evidence_level"])
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_all_task_state_controls_require_verified_evidence(self):
        for control_id in ("HD-STA-001", "HD-STA-003", "HD-STA-005"):
            judgments = [dict(control_id=c["id"], status="missing", rationale="Not inspected", evidence=[])
                         for c in self.catalog["controls"]]
            row = next(j for j in judgments if j["control_id"] == control_id)
            row.update(status="satisfied", evidence=self.refs,
                       evidence_trace=dict(declarations=[self.refs[0]], execution_records=[], result_checks=[]))
            with self.subTest(control_id=control_id), self.assertRaisesRegex(
                    SafetyError, "EVIDENCE_LEVEL_INSUFFICIENT"):
                assess(self.catalog, self.evidence, judgments)
            row["evidence_trace"] = self.trace
            self.assertEqual(1, assess(self.catalog, self.evidence, judgments)["coverage"]["satisfied"])

    def test_distinct_execution_events_can_be_cross_checked_without_hiding_their_category(self):
        self.trace["execution_records"].append(self.refs[2])
        self.trace["result_checks"][0]["outcome"] = "contradicted"
        self.row["status"] = "conflict"
        report = self.report()
        self.assertEqual("verified", self.result_row(report)["evidence_level"])
        self.assertEqual(self.refs[1:], self.result_row(report)["evidence_trace"]["execution_records"])
        self.assertEqual(0, report["coverage"]["satisfied"])
        self.assertEqual(1, report["verification_outcomes"]["contradicted"])

    def test_one_confirmed_check_cannot_hide_an_inconclusive_check(self):
        (self.root / "tasks").mkdir()
        (self.root / "tasks/observation.md").write_text("An additional observation is inconclusive.\n")
        self.evidence = collect_evidence(self.root)["evidence"]
        file = next(f for f in self.evidence["files"] if f["path"] == "tasks/observation.md")
        ref = dict(file_id=file["id"], line=1)
        self.row["evidence"] = self.refs + [ref]
        check = dict(self.trace["result_checks"][0], observation=ref, outcome="inconclusive")
        self.trace["result_checks"].append(check)
        self.assertEqual("recorded", self.result_row()["evidence_level"])
        self.row["status"] = "satisfied"
        with self.assertRaisesRegex(SafetyError, "VERIFICATION_NOT_CONFIRMED"):
            self.report()

    def test_cli_rejects_sensitive_check_without_echoing_contents(self):
        self.trace["result_checks"][0]["limitations"] = "password=EVIDENCE_CANARY"
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/doctor.py"), "assess", "--repo", str(self.root)],
            input=json.dumps(dict(evidence=self.evidence, judgments=self.judgments)),
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(2, result.returncode)
        self.assertNotIn("EVIDENCE_CANARY", result.stdout + result.stderr)
        self.assertEqual(["VERIFICATION_TEXT_INVALID"], json.loads(result.stdout)["errors"])


if __name__ == "__main__":
    unittest.main()
