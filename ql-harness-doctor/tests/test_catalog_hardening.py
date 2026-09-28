"""Consumer and adversarial cases for the catalog boundary."""

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

from test_control_catalog import (
    PRODUCTION_CATALOG, SKILL_ROOT, VALIDATOR_PATH, VALID_FIXTURE,
    load_valid_documents, load_validator_module, write_documents,
)


class CatalogHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def variant(self, mutate, production=False):
        if production:
            controls, sources = [json.loads((PRODUCTION_CATALOG / name).read_text())
                                 for name in ("controls.json", "sources.json")]
        else:
            controls, sources = load_valid_documents()
        mutate(controls, sources)
        with tempfile.TemporaryDirectory() as directory:
            write_documents(Path(directory), controls, sources)
            return list(self.validator.validate_catalog(Path(directory)))

    def test_missing_production_candidate_is_rejected_by_cli_validator(self):
        errors = self.variant(lambda c, s: c["controls"][0]["source_aliases"].clear(), True)
        self.assertIn("CATALOG_CANDIDATE_UNDISPOSED", {e.code for e in errors})

    def test_malformed_readable_documents_are_not_echoed_to_errors(self):
        marker = "/Users/private/credential-CANARY\nforged-output"
        errors = self.variant(lambda c, s: c["controls"][0].update(
            {"id": marker, "domain": marker, "dependencies": [marker]}))
        rendered = self.validator.render_json(errors) + self.validator.render_human(errors)
        self.assertNotIn("CANARY", rendered)
        self.assertNotIn("/Users/", rendered)

    def test_unknown_field_names_do_not_leak_values_or_terminal_controls(self):
        errors = self.variant(lambda c, s: c.update({"/Users/private/CANARY\n": 1}))
        self.assertNotIn("CANARY", self.validator.render_json(errors))
        self.assertTrue(errors)

    def test_duplicate_keys_and_non_json_constants_fail_parse(self):
        for raw in ('{"schema_version":"1.0.0","schema_version":"2.0.0"}',
                    '{"controls": NaN}', '{"controls": Infinity}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "controls.json").write_text(raw)
                (root / "sources.json").write_bytes((VALID_FIXTURE / "sources.json").read_bytes())
                result = self.cli(root, "--json")
                self.assertEqual(2, result.returncode)
                self.assertIn("CATALOG_JSON_INVALID", result.stdout)

    def test_empty_requirements_and_guidance_are_invalid(self):
        errors = self.variant(lambda c, s: c["controls"][0].update(
            {"requirement": " ", "applicability": {"applies_when": [], "not_applicable_when": []}}))
        self.assertIn("CATALOG_VALUE_INVALID", {e.code for e in errors})

    def test_evidence_minimum_is_required_and_cannot_be_arbitrary(self):
        errors = self.variant(lambda c, s: c["controls"][0]["evidence"].pop("minimum_level"))
        self.assertIn("CATALOG_FIELD_MISSING", {e.code for e in errors})
        for value in ("none", "unclassified", "trust_me"):
            errors = self.variant(lambda c, s: c["controls"][0]["evidence"].update(minimum_level=value))
            self.assertIn("CATALOG_ENUM_INVALID", {e.code for e in errors})
        for value in ("declared", "recorded", "verified"):
            self.assertEqual([], self.variant(
                lambda c, s: c["controls"][0]["evidence"].update(minimum_level=value)))

    def test_ordered_relation_arrays_cannot_have_duplicates_or_self_alternatives(self):
        for updates in ({"alternatives": ["HD-FND-001"]},
                        {"conflicts_with": ["HD-FND-001"]},
                        {"dependencies": ["HD-FND-003", "HD-FND-002"]},
                        {"alternatives": ["HD-FND-002", "HD-FND-002"]}):
            with self.subTest(updates=updates):
                errors = self.variant(lambda c, s: c["controls"][0].update(updates))
                self.assertTrue(errors)

    def test_lifecycle_versions_cannot_precede_introduction_or_exceed_catalog(self):
        for updates in ({"introduced_in": "0.2.0"}, {"changed_in": "0.0.1"}):
            errors = self.variant(lambda c, s: c["controls"][0]["lifecycle"].update(updates))
            self.assertIn("CATALOG_LIFECYCLE_INVALID", {e.code for e in errors})

    def test_valid_deprecation_and_symmetric_conflict_are_accepted(self):
        def mutate(c, s):
            c["catalog_version"] = "0.2.0"
            old = c["controls"][-1]
            old["is_gate"] = False
            old["lifecycle"].update(status="deprecated", deprecated_in="0.2.0",
                                    changed_in="0.2.0", superseded_by="HD-FND-003")
            c["maturity_levels"][-1]["gate_control_ids"] = []
            c["controls"][0]["conflicts_with"] = ["HD-FND-003"]
            c["controls"][2]["conflicts_with"] = ["HD-FND-001"]
        self.assertEqual([], self.variant(mutate))

    def test_invalid_versions_and_moving_source_revisions_are_rejected(self):
        for value in ("latest", "01.2.3", "1", "-1.0.0"):
            errors = self.variant(lambda c, s: c.update(schema_version=value))
            self.assertTrue(errors)
        for revision in ({"kind": "git_commit", "value": "a" * 7},
                         {"kind": "published_at", "value": "tomorrow"},
                         {"kind": "archived_snapshot", "value": "main"}):
            errors = self.variant(lambda c, s: s["source_snapshots"][0].update(revision=revision))
            self.assertIn("CATALOG_SOURCE_REVISION_INVALID", {e.code for e in errors})

    def test_non_utf8_and_directories_are_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "controls.json").write_bytes(b"\xff")
            (root / "sources.json").mkdir()
            result = self.cli(root, "--json")
            self.assertEqual(2, result.returncode)
            self.assertEqual(2, len(json.loads(result.stdout)["errors"]))
            self.assertNotIn(directory, result.stdout)

    def test_json_human_and_repeated_runs_agree(self):
        c, s = load_valid_documents()
        c["controls"][0]["dependencies"] = ["HD-FND-999"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_documents(root, c, s)
            machine = self.cli(root, "--json")
            repeat = self.cli(root, "--json")
            human = self.cli(root)
        self.assertEqual(1, machine.returncode)
        self.assertEqual(1, human.returncode)
        self.assertEqual(machine.stdout, repeat.stdout)
        expected = "".join(f"{e['code']} {e['path']}: {e['message']}\n"
                           for e in json.loads(machine.stdout)["errors"])
        self.assertEqual(expected, human.stderr)

    def test_cli_usage_failure_is_sanitized(self):
        result = self.cli(VALID_FIXTURE, "--unknown=/Users/private/CANARY", "--json")
        self.assertEqual(2, result.returncode)
        self.assertNotIn("CANARY", result.stdout + result.stderr)

    def test_deep_dependency_chains_do_not_use_python_recursion(self):
        controls = [{"id": str(index), "dependencies": [str(index + 1)]}
                    for index in range(1500)]
        controls[-1]["dependencies"] = []
        errors = []
        self.validator.validate_dependency_graph(controls, errors)
        self.assertEqual([], errors)
        controls[-1]["dependencies"] = ["0"]
        self.validator.validate_dependency_graph(controls, errors)
        self.assertEqual(["CATALOG_DEPENDENCY_CYCLE"], [e.code for e in errors])

    def test_missing_or_malformed_installed_schemas_fail_at_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "controls.schema.json").write_text("{")
            with patch.object(self.validator, "DEFAULT_CATALOG_DIR", root):
                errors = self.validator.validate_catalog(VALID_FIXTURE)
            self.assertEqual({"CATALOG_FILE_MISSING", "CATALOG_JSON_INVALID"},
                             {e.code for e in errors})

    def test_fifo_and_invalid_paths_are_rejected_without_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            os.mkfifo(path)
            # Avoid hanging a broken implementation: any content read is a test failure.
            with patch.object(Path, "read_text", side_effect=AssertionError("FIFO read")):
                _, errors = self.validator.load_json_document(path, "controls.json")
            self.assertEqual(["CATALOG_FILE_UNREADABLE"], [e.code for e in errors])
        _, errors = self.validator.load_json_document(Path("\x00"), "controls.json")
        self.assertEqual(["CATALOG_FILE_UNREADABLE"], [e.code for e in errors])

    def test_empty_arrays_and_invalid_orders_are_rejected(self):
        cases = [lambda c, s: c["controls"][0]["evidence"].update(positive=[]),
                 lambda c, s: c["controls"][0]["remediation"].update(artifact_types=[]),
                 lambda c, s: c["domains"][0].update(display_order=0),
                 lambda c, s: s["source_snapshots"][0].update(documents=[])]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.assertIn("CATALOG_VALUE_INVALID", {e.code for e in self.variant(mutate)})

    def test_fixed_book_requires_matching_chapters_and_full_revision(self):
        def book(sources):
            return next(source for source in sources["source_snapshots"]
                        if source["id"] == "walkinglabs-he@77e7a3e")

        cases = [lambda c, s: book(s)["documents"].pop(),
                 lambda c, s: book(s)["revision"].update(value="a" * 40),
                 lambda c, s: c["controls"][0]["source_refs"].clear()]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.assertIn("CATALOG_PROVENANCE_MISSING",
                              {e.code for e in self.variant(mutate, True)})

    def test_fixed_book_rejects_unknown_candidates_and_missing_domains(self):
        for mutate in (lambda c, s: c["controls"][0]["source_aliases"].append("L01-C99"),
                       lambda c, s: c["domains"].pop(),
                       lambda c, s: c["domains"].append({"id": "HD-XYZ", "title": "Extra",
                                                        "description": "Extra", "display_order": 13})):
            self.assertTrue(self.variant(mutate, True))

    def test_explicit_publication_dates_and_archives_are_accepted(self):
        for revision in ({"kind": "published_at", "value": "2026-09-04"},
                         {"kind": "archived_snapshot", "value": "sha256:" + "a" * 64},
                         {"kind": "archived_snapshot", "value":
                          "https://web.archive.org/web/20260904000000/https://example.org/doc"}):
            with self.subTest(revision=revision):
                self.assertEqual([], self.variant(
                    lambda c, s: s["source_snapshots"][0].update(revision=revision)))

    def test_sources_reject_private_paths_credentials_and_invalid_dates(self):
        cases = [lambda c, s: s["source_snapshots"][0].update(accessed_on="yesterday"),
                 lambda c, s: s["source_snapshots"][0].update(canonical_url="/Users/private/CANARY"),
                 lambda c, s: s["source_snapshots"][0]["documents"][0].update(
                     page_url="https://user:CANARY@example.org/doc"),
                 lambda c, s: s["source_snapshots"][0]["documents"][0].update(
                     source_path="../CANARY.md")]
        for mutate in cases:
            errors = self.variant(mutate)
            self.assertIn("CATALOG_VALUE_INVALID", {e.code for e in errors})
            self.assertNotIn("CANARY", self.validator.render_json(errors))

    def test_schema_shapes_match_python_contract_recursively(self):
        def compare(schema, shape, document):
            if "$ref" in schema:
                schema = document["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
            if shape["kind"] == "nullable_string":
                self.assertEqual({"string", "null"}, set(schema["type"]))
            else:
                self.assertEqual(shape["kind"], schema["type"])
            if shape["kind"] == "object":
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(set(shape["fields"]), set(schema["required"]))
                self.assertEqual(set(shape["fields"]), set(schema["properties"]))
                for key, field in shape["fields"].items():
                    compare(schema["properties"][key], field, document)
            elif shape["kind"] == "array":
                compare(schema["items"], shape["item"], document)
        for stem, shape in (("controls", self.validator.CONTROLS_DOCUMENT_SHAPE),
                            ("sources", self.validator.SOURCES_DOCUMENT_SHAPE)):
            schema = json.loads((PRODUCTION_CATALOG / f"{stem}.schema.json").read_text())
            compare(schema, shape, schema)

    def test_production_json_is_canonical_and_all_aliases_have_provenance(self):
        for stem in ("controls", "sources"):
            raw = (PRODUCTION_CATALOG / f"{stem}.json").read_text(encoding="utf-8")
            self.assertEqual(json.dumps(json.loads(raw), ensure_ascii=False, indent=2) + "\n", raw)
        controls = json.loads((PRODUCTION_CATALOG / "controls.json").read_text())["controls"]
        self.assertEqual(46, len(controls))
        for control in controls:
            documents = {ref["document_id"] for ref in control["source_refs"]}
            for alias in control["source_aliases"]:
                self.assertIn(f"walkinglabs-he-{alias[:3]}", documents)

    def test_missing_entry_is_not_an_applicability_exemption_and_blockers_stay_open(self):
        controls = {c["id"]: c for c in json.loads(
            (PRODUCTION_CATALOG / "controls.json").read_text())["controls"]}
        self.assertNotIn("仓库尚未配置任何 Agent 指令入口",
                         controls["HD-INS-001"]["applicability"]["not_applicable_when"])
        self.assertIn("恢复条件", controls["HD-STA-001"]["requirement"])
        self.assertIn("不得标记为完成", controls["HD-STA-001"]["requirement"])
        self.assertIn("回写", controls["HD-STA-003"]["requirement"])

    def test_offline_readonly_validation_preserves_hashes_mtimes_and_git_status(self):
        paths = sorted(PRODUCTION_CATALOG.glob("*.json"))
        def snapshot():
            return [(hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in paths]
        def git_status():
            return subprocess.check_output(["git", "status", "--porcelain"], cwd=SKILL_ROOT.parent)
        before, status = snapshot(), git_status()
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.assertEqual([], list(self.validator.validate_catalog(PRODUCTION_CATALOG)))
        self.assertEqual(before, snapshot())
        self.assertEqual(status, git_status())

    def cli(self, root, *flags):
        return subprocess.run([sys.executable, str(VALIDATOR_PATH), "--catalog-dir", str(root),
                               *flags], capture_output=True, text=True, check=False)


if __name__ == "__main__":
    unittest.main()
