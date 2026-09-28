import importlib.util
import json
import copy
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = SKILL_ROOT / "scripts" / "validate_catalog.py"
VALID_FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "control_catalog" / "valid"
PRODUCTION_CATALOG = SKILL_ROOT / "references" / "catalog"
CHAPTERS_DIR = SKILL_ROOT / "references" / "chapters"
CONTROLS_SCHEMA = SKILL_ROOT / "references" / "catalog" / "controls.schema.json"
SOURCES_SCHEMA = SKILL_ROOT / "references" / "catalog" / "sources.schema.json"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("harness_doctor_validate_catalog", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load catalog validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_valid_documents():
    controls = json.loads((VALID_FIXTURE / "controls.json").read_text(encoding="utf-8"))
    sources = json.loads((VALID_FIXTURE / "sources.json").read_text(encoding="utf-8"))
    return controls, sources


def write_documents(catalog_dir: Path, controls, sources):
    (catalog_dir / "controls.json").write_text(
        json.dumps(controls, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (catalog_dir / "sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class CatalogCliBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR_PATH), *args],
            cwd=SKILL_ROOT.parent,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_valid_fixture_returns_no_findings(self):
        errors = self.validator.validate_catalog(VALID_FIXTURE)

        self.assertEqual([], list(errors))

    def test_valid_fixture_cli_succeeds_in_human_mode(self):
        result = self.run_cli("--catalog-dir", str(VALID_FIXTURE))

        self.assertEqual(0, result.returncode)
        self.assertEqual("Catalog is valid.\n", result.stdout)
        self.assertEqual("", result.stderr)

    def test_valid_fixture_cli_succeeds_in_json_mode(self):
        result = self.run_cli("--catalog-dir", str(VALID_FIXTURE), "--json")

        self.assertEqual(0, result.returncode)
        self.assertEqual({"ok": True, "errors": []}, json.loads(result.stdout))
        self.assertEqual("", result.stderr)

    def test_missing_catalog_file_returns_exit_code_two_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_dir = Path(temp_dir)
            (catalog_dir / "sources.json").write_text("{}\n", encoding="utf-8")

            result = self.run_cli("--catalog-dir", str(catalog_dir))

        self.assertEqual(2, result.returncode)
        self.assertIn("CATALOG_FILE_MISSING controls.json", result.stderr)
        self.assertNotIn(str(catalog_dir), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_json_returns_exit_code_two_in_json_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_dir = Path(temp_dir)
            (catalog_dir / "controls.json").write_text("{not-json}\n", encoding="utf-8")
            (catalog_dir / "sources.json").write_text("{}\n", encoding="utf-8")

            result = self.run_cli("--catalog-dir", str(catalog_dir), "--json")

        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual("CATALOG_JSON_INVALID", payload["errors"][0]["code"])
        self.assertEqual("controls.json", payload["errors"][0]["path"])
        self.assertNotIn(str(catalog_dir), result.stdout)
        self.assertNotIn("Traceback", result.stdout)

    def test_validation_does_not_modify_fixture_files(self):
        paths = [VALID_FIXTURE / "controls.json", VALID_FIXTURE / "sources.json"]
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]

        self.validator.validate_catalog(VALID_FIXTURE)

        after = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        self.assertEqual(before, after)


class CatalogShapeValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def validate_variant(self, mutate):
        controls, sources = load_valid_documents()
        controls = copy.deepcopy(controls)
        sources = copy.deepcopy(sources)
        mutate(controls, sources)
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_dir = Path(temp_dir)
            write_documents(catalog_dir, controls, sources)
            return list(self.validator.validate_catalog(catalog_dir))

    def test_schema_documents_are_valid_json_with_expected_roots(self):
        controls_schema = json.loads(CONTROLS_SCHEMA.read_text(encoding="utf-8"))
        sources_schema = json.loads(SOURCES_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual("https://json-schema.org/draft/2020-12/schema", controls_schema["$schema"])
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", sources_schema["$schema"])
        self.assertIn("controls", controls_schema["required"])
        self.assertIn("source_snapshots", sources_schema["required"])

    def test_missing_root_and_nested_fields_are_reported(self):
        def mutate(controls, sources):
            del controls["catalog_version"]
            del controls["controls"][0]["requirement"]
            del sources["source_snapshots"][0]["documents"][0]["page_url"]

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_FIELD_MISSING", "controls.json.catalog_version"),
                ("CATALOG_FIELD_MISSING", "controls.json.controls[0].requirement"),
                (
                    "CATALOG_FIELD_MISSING",
                    "sources.json.source_snapshots[0].documents[0].page_url",
                ),
            ],
            [(error.code, error.path) for error in errors],
        )

    def test_wrong_container_and_primitive_types_are_reported(self):
        def mutate(controls, sources):
            controls["domains"] = "not-a-list"
            controls["controls"][0]["is_gate"] = "yes"
            sources["source_snapshots"][0]["accessed_on"] = 20260904

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_TYPE_INVALID", "controls.json.controls[0].is_gate"),
                ("CATALOG_TYPE_INVALID", "controls.json.domains"),
                ("CATALOG_TYPE_INVALID", "sources.json.source_snapshots[0].accessed_on"),
            ],
            [(error.code, error.path) for error in errors],
        )

    def test_unknown_fields_are_rejected_at_each_object_boundary(self):
        def mutate(controls, sources):
            controls["unexpected"] = True
            controls["controls"][0]["evidence"]["unknown"] = []
            sources["source_snapshots"][0]["documents"][0]["extra"] = "value"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_FIELD_UNKNOWN", "controls.json.<unknown[0]>"),
                ("CATALOG_FIELD_UNKNOWN", "controls.json.controls[0].evidence.<unknown[0]>"),
                (
                    "CATALOG_FIELD_UNKNOWN",
                    "sources.json.source_snapshots[0].documents[0].<unknown[0]>",
                ),
            ],
            [(error.code, error.path) for error in errors],
        )

    def test_unsupported_schema_major_versions_fail_closed(self):
        def mutate(controls, sources):
            controls["schema_version"] = "2.0.0"
            sources["schema_version"] = "3.1.0"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_VERSION_UNSUPPORTED", "controls.json.schema_version"),
                ("CATALOG_VERSION_UNSUPPORTED", "sources.json.schema_version"),
            ],
            [(error.code, error.path) for error in errors],
        )

    def test_independent_shape_errors_are_collected(self):
        def mutate(controls, sources):
            del controls["catalog_version"]
            del sources["registry_version"]

        errors = self.validate_variant(mutate)

        self.assertEqual(2, len(errors))
        self.assertEqual(
            {"controls.json.catalog_version", "sources.json.registry_version"},
            {error.path for error in errors},
        )


class CatalogIdentityValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def validate_variant(self, mutate):
        controls, sources = load_valid_documents()
        controls = copy.deepcopy(controls)
        sources = copy.deepcopy(sources)
        mutate(controls, sources)
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_dir = Path(temp_dir)
            write_documents(catalog_dir, controls, sources)
            return list(self.validator.validate_catalog(catalog_dir))

    def findings(self, errors, code):
        return [(error.code, error.path) for error in errors if error.code == code]

    def test_malformed_identity_tokens_are_rejected(self):
        def mutate(controls, sources):
            controls["domains"][0]["id"] = "FND"
            controls["controls"][0]["id"] = "HD-fnd-1"
            controls["controls"][0]["source_aliases"] = ["chapter-one"]
            controls["excluded_candidates"].append(
                {"id": "L99-C01", "rationale": "测试", "decision": "not_adopted"}
            )
            sources["source_snapshots"][0]["id"] = "fixture source"
            sources["source_snapshots"][0]["documents"][0]["id"] = "fixture document"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_ID_INVALID", "controls.json.controls[0].id"),
                ("CATALOG_ID_INVALID", "controls.json.controls[0].source_aliases[0]"),
                ("CATALOG_ID_INVALID", "controls.json.domains[0].id"),
                ("CATALOG_ID_INVALID", "controls.json.excluded_candidates[0].id"),
                ("CATALOG_ID_INVALID", "sources.json.source_snapshots[0].documents[0].id"),
                ("CATALOG_ID_INVALID", "sources.json.source_snapshots[0].id"),
            ],
            self.findings(errors, "CATALOG_ID_INVALID"),
        )

    def test_duplicate_identity_tokens_are_rejected(self):
        def mutate(controls, sources):
            controls["domains"].append(copy.deepcopy(controls["domains"][0]))
            controls["domains"][1]["display_order"] = 2
            controls["controls"].append(copy.deepcopy(controls["controls"][0]))
            controls["excluded_candidates"] = [
                {"id": "L02-C01", "rationale": "测试一", "decision": "not_adopted"},
                {"id": "L02-C01", "rationale": "测试二", "decision": "not_adopted"},
            ]
            sources["source_snapshots"].append(copy.deepcopy(sources["source_snapshots"][0]))
            sources["source_snapshots"][0]["documents"].append(
                copy.deepcopy(sources["source_snapshots"][0]["documents"][0])
            )

        errors = self.validate_variant(mutate)

        self.assertEqual(
            {
                "controls.json.controls[4].id",
                "controls.json.domains[1].id",
                "controls.json.excluded_candidates[1].id",
                "sources.json.source_snapshots[0].documents[1].id",
                "sources.json.source_snapshots[1].id",
            },
            {path for _, path in self.findings(errors, "CATALOG_DUPLICATE_ID")},
        )

    def test_control_domain_must_be_declared_and_match_id_prefix(self):
        def mutate(controls, _sources):
            controls["controls"][0]["domain"] = "HD-KNW"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_DOMAIN_MISMATCH", "controls.json.controls[0].domain"),
                ("CATALOG_REFERENCE_UNKNOWN", "controls.json.controls[0].domain"),
            ],
            [
                (error.code, error.path)
                for error in errors
                if error.path == "controls.json.controls[0].domain"
            ],
        )

    def test_control_and_gate_references_must_resolve(self):
        def mutate(controls, _sources):
            controls["controls"][0]["dependencies"] = ["HD-FND-999"]
            controls["controls"][0]["conflicts_with"] = ["HD-FND-998"]
            controls["controls"][0]["alternatives"] = ["HD-FND-997"]
            controls["maturity_levels"][1]["gate_control_ids"].append("HD-FND-996")

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_REFERENCE_UNKNOWN", "controls.json.controls[0].alternatives[0]"),
                ("CATALOG_REFERENCE_UNKNOWN", "controls.json.controls[0].conflicts_with[0]"),
                ("CATALOG_REFERENCE_UNKNOWN", "controls.json.controls[0].dependencies[0]"),
                (
                    "CATALOG_REFERENCE_UNKNOWN",
                    "controls.json.maturity_levels[1].gate_control_ids[1]",
                ),
            ],
            self.findings(errors, "CATALOG_REFERENCE_UNKNOWN"),
        )

    def test_source_references_must_resolve_within_the_snapshot(self):
        def mutate(controls, _sources):
            controls["controls"][0]["source_refs"] = [
                {
                    "source_id": "missing-source@v1",
                    "document_id": "fixture-L01",
                    "locator": "",
                    "note": "测试来源",
                },
                {
                    "source_id": "fixture-source@v1",
                    "document_id": "fixture-L14",
                    "locator": "",
                    "note": "测试来源",
                },
            ]

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_REFERENCE_UNKNOWN", "controls.json.controls[0].source_refs[0].source_id"),
                (
                    "CATALOG_REFERENCE_UNKNOWN",
                    "controls.json.controls[0].source_refs[1].document_id",
                ),
            ],
            self.findings(errors, "CATALOG_REFERENCE_UNKNOWN"),
        )

    def test_domain_control_and_document_order_is_canonical(self):
        def mutate(controls, sources):
            controls["domains"].append(
                {
                    "id": "HD-KNW",
                    "title": "知识",
                    "description": "测试知识域",
                    "display_order": 0,
                }
            )
            controls["controls"].reverse()
            sources["source_snapshots"][0]["documents"].append(
                {
                    "id": "fixture-L00",
                    "title": "Fixture document zero",
                    "page_url": "https://example.invalid/fixture/L00",
                    "source_path": "docs/fixture/L00.md",
                }
            )

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                ("CATALOG_ORDER_INVALID", "controls.json.controls"),
                ("CATALOG_ORDER_INVALID", "controls.json.domains"),
                (
                    "CATALOG_ORDER_INVALID",
                    "sources.json.source_snapshots[0].documents",
                ),
            ],
            self.findings(errors, "CATALOG_ORDER_INVALID"),
        )


class CatalogPolicyValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def validate_variant(self, mutate):
        controls, sources = load_valid_documents()
        controls = copy.deepcopy(controls)
        sources = copy.deepcopy(sources)
        mutate(controls, sources)
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_dir = Path(temp_dir)
            write_documents(catalog_dir, controls, sources)
            return list(self.validator.validate_catalog(catalog_dir))

    def paths_for(self, errors, code):
        return [error.path for error in errors if error.code == code]

    def test_diagnostic_status_ids_and_order_are_exact(self):
        def mutate(controls, _sources):
            controls["diagnostic_statuses"][1]["id"] = "almost"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["controls.json.diagnostic_statuses"],
            self.paths_for(errors, "CATALOG_POLICY_INVALID"),
        )

    def test_coverage_policy_is_exact_and_unweighted(self):
        def mutate(controls, _sources):
            controls["coverage_policy"] = {
                "numerator_statuses": ["satisfied", "partial"],
                "excluded_from_denominator": [],
                "zero_denominator_result": "0",
                "is_weighted": True,
            }

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["controls.json.coverage_policy"],
            self.paths_for(errors, "CATALOG_POLICY_INVALID"),
        )

    def test_maturity_level_order_and_activation_are_exact(self):
        def mutate(controls, _sources):
            controls["maturity_levels"].reverse()
            controls["maturity_levels"][0]["activation"] = "default"
            controls["maturity_levels"][4]["requires_lower_levels"] = True

        errors = self.validate_variant(mutate)

        self.assertIn(
            "controls.json.maturity_levels",
            self.paths_for(errors, "CATALOG_MATURITY_INVALID"),
        )

    def test_maturity_gates_must_be_eligible_and_complete(self):
        def mutate(controls, _sources):
            controls["controls"][0]["is_gate"] = False
            controls["maturity_levels"][1]["gate_control_ids"].append("HD-FND-002")
            controls["maturity_levels"][4]["gate_control_ids"] = []

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                "controls.json.controls[3].is_gate",
                "controls.json.maturity_levels[1].gate_control_ids[0]",
                "controls.json.maturity_levels[1].gate_control_ids[1]",
            ],
            self.paths_for(errors, "CATALOG_MATURITY_GATE_INVALID"),
        )

    def test_controls_cannot_use_l0_maturity(self):
        def mutate(controls, _sources):
            controls["controls"][0]["maturity"] = "L0"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["controls.json.controls[0].maturity"],
            self.paths_for(errors, "CATALOG_MATURITY_INVALID"),
        )


class CatalogGraphLifecycleValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def validate_variant(self, mutate):
        controls, sources = load_valid_documents()
        controls = copy.deepcopy(controls)
        sources = copy.deepcopy(sources)
        mutate(controls, sources)
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_dir = Path(temp_dir)
            write_documents(catalog_dir, controls, sources)
            return list(self.validator.validate_catalog(catalog_dir))

    def paths_for(self, errors, code):
        return [error.path for error in errors if error.code == code]

    def test_direct_and_multi_hop_dependency_cycles_are_rejected(self):
        variants = [
            lambda controls: controls["controls"][0].update(
                {"dependencies": ["HD-FND-001"]}
            ),
            lambda controls: controls["controls"][0].update(
                {"dependencies": ["HD-FND-004"]}
            ),
        ]

        for mutate_controls in variants:
            with self.subTest(mutate_controls=mutate_controls):
                errors = self.validate_variant(
                    lambda controls, _sources: mutate_controls(controls)
                )
                self.assertTrue(self.paths_for(errors, "CATALOG_DEPENDENCY_CYCLE"))

    def test_conflict_relationships_must_be_symmetric(self):
        def mutate(controls, _sources):
            controls["controls"][0]["conflicts_with"] = ["HD-FND-002"]

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["controls.json.controls[0].conflicts_with[0]"],
            self.paths_for(errors, "CATALOG_CONFLICT_ASYMMETRIC"),
        )

    def test_dependencies_must_target_active_controls(self):
        def mutate(controls, _sources):
            controls["controls"][0]["is_gate"] = False
            controls["controls"][0]["lifecycle"].update(
                {"status": "deprecated", "deprecated_in": "0.2.0"}
            )
            controls["maturity_levels"][1]["gate_control_ids"] = []

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["controls.json.controls[1].dependencies[0]"],
            self.paths_for(errors, "CATALOG_REFERENCE_INACTIVE"),
        )

    def test_active_and_deprecated_lifecycle_states_are_consistent(self):
        def mutate(controls, _sources):
            controls["controls"][0]["lifecycle"]["deprecated_in"] = "0.2.0"
            controls["controls"][3]["lifecycle"].update(
                {
                    "status": "deprecated",
                    "deprecated_in": None,
                    "superseded_by": "HD-FND-999",
                }
            )

        errors = self.validate_variant(mutate)

        self.assertEqual(
            {
                "controls.json.controls[0].lifecycle",
                "controls.json.controls[0].lifecycle.deprecated_in",
                "controls.json.controls[3].lifecycle.deprecated_in",
                "controls.json.controls[3].lifecycle.superseded_by",
            },
            set(self.paths_for(errors, "CATALOG_LIFECYCLE_INVALID")),
        )
        self.assertEqual(
            ["controls.json.maturity_levels[4].gate_control_ids[0]"],
            self.paths_for(errors, "CATALOG_MATURITY_GATE_INVALID"),
        )

    def test_unknown_lifecycle_and_risk_enums_are_rejected(self):
        def mutate(controls, _sources):
            controls["controls"][0]["lifecycle"]["status"] = "retired"
            controls["controls"][1]["remediation"]["risk"] = "severe"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                "controls.json.controls[0].lifecycle.status",
                "controls.json.controls[1].remediation.risk",
            ],
            self.paths_for(errors, "CATALOG_ENUM_INVALID"),
        )

    def test_catalog_and_lifecycle_versions_must_be_semver(self):
        def mutate(controls, sources):
            controls["catalog_version"] = "next"
            controls["controls"][0]["lifecycle"]["changed_in"] = "yesterday"
            sources["registry_version"] = "v1"

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                "controls.json.catalog_version",
                "controls.json.controls[0].lifecycle.changed_in",
                "sources.json.registry_version",
            ],
            self.paths_for(errors, "CATALOG_VERSION_INVALID"),
        )

    def test_active_controls_require_source_refs_and_candidate_aliases(self):
        def mutate(controls, _sources):
            controls["controls"][0]["source_refs"] = []
            controls["controls"][1]["source_aliases"] = []

        errors = self.validate_variant(mutate)

        self.assertEqual(
            [
                "controls.json.controls[0].source_refs",
                "controls.json.controls[1].source_aliases",
            ],
            self.paths_for(errors, "CATALOG_PROVENANCE_MISSING"),
        )

    def test_candidate_mapping_duplicates_and_exclusion_overlap_are_rejected(self):
        def mutate(controls, _sources):
            controls["controls"][1]["source_aliases"] = ["L01-C01"]
            controls["excluded_candidates"] = [
                {
                    "id": "L01-C03",
                    "rationale": "不纳入产品控制项",
                    "decision": "not_adopted",
                }
            ]

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["controls.json.controls[1].source_aliases[0]"],
            self.paths_for(errors, "CATALOG_CANDIDATE_DUPLICATE"),
        )
        self.assertEqual(
            ["controls.json.excluded_candidates[0].id"],
            self.paths_for(errors, "CATALOG_CANDIDATE_OVERLAP"),
        )

    def test_exclusions_require_a_decision_and_concrete_rationale(self):
        def mutate(controls, _sources):
            controls["excluded_candidates"] = [
                {"id": "L02-C01", "rationale": "", "decision": "duplicate"}
            ]

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["controls.json.excluded_candidates[0].decision"],
            self.paths_for(errors, "CATALOG_ENUM_INVALID"),
        )
        self.assertEqual(
            ["controls.json.excluded_candidates[0].rationale"],
            self.paths_for(errors, "CATALOG_PROVENANCE_MISSING"),
        )

    def test_source_revisions_must_be_reproducible(self):
        def mutate(_controls, sources):
            sources["source_snapshots"][0]["revision"] = {
                "kind": "git_commit",
                "value": "latest",
            }

        errors = self.validate_variant(mutate)

        self.assertEqual(
            ["sources.json.source_snapshots[0].revision"],
            self.paths_for(errors, "CATALOG_SOURCE_REVISION_INVALID"),
        )


class ProductionSourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def expected_documents_from_notes(self):
        documents = []
        for lecture_number in range(1, 15):
            lecture_id = f"L{lecture_number:02d}"
            note_path = CHAPTERS_DIR / f"lecture-{lecture_number:02d}.md"
            lines = note_path.read_text(encoding="utf-8").splitlines()
            heading = lines[0].removeprefix("# ")
            page_url = next(line.removeprefix("- 页面：") for line in lines if line.startswith("- 页面："))
            source_path = next(
                line.removeprefix("- 源码：`").removesuffix("`")
                for line in lines
                if line.startswith("- 源码：")
            )
            documents.append(
                {
                    "id": f"walkinglabs-he-{lecture_id}",
                    "title": heading,
                    "page_url": page_url,
                    "source_path": source_path,
                }
            )
        return documents

    def test_production_source_registry_matches_all_chapter_metadata(self):
        sources = json.loads(
            (PRODUCTION_CATALOG / "sources.json").read_text(encoding="utf-8")
        )

        self.assertEqual("1.0.0", sources["schema_version"])
        self.assertEqual("0.2.0", sources["registry_version"])
        snapshots = {source["id"]: source for source in sources["source_snapshots"]}
        self.assertEqual({"walkinglabs-he@77e7a3e", "anthropic-long-running@2025-11-26"}, set(snapshots))
        snapshot = snapshots["walkinglabs-he@77e7a3e"]
        self.assertEqual("walkinglabs-he@77e7a3e", snapshot["id"])
        self.assertEqual("Walking Labs", snapshot["publisher"])
        self.assertEqual(
            "https://github.com/walkinglabs/learn-harness-engineering",
            snapshot["canonical_url"],
        )
        self.assertEqual(
            {
                "kind": "git_commit",
                "value": "77e7a3e21469dcbece2558086c8d91657abeaa40",
            },
            snapshot["revision"],
        )
        self.assertEqual("2026-09-04", snapshot["accessed_on"])
        self.assertEqual("zh", snapshot["language"])
        self.assertEqual(self.expected_documents_from_notes(), snapshot["documents"])

    def test_production_source_registry_passes_shape_and_semantic_validation(self):
        sources = json.loads(
            (PRODUCTION_CATALOG / "sources.json").read_text(encoding="utf-8")
        )
        errors = []

        self.validator.validate_shape(
            sources,
            self.validator.SOURCES_DOCUMENT_SHAPE,
            "sources.json",
            errors,
        )
        self.validator.validate_sources_identity(sources, errors)
        self.validator.validate_source_semantics(sources, errors)

        self.assertEqual([], errors)


class ProductionCoreCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def load_controls(self):
        return json.loads(
            (PRODUCTION_CATALOG / "controls.json").read_text(encoding="utf-8")
        )

    def test_l1_l2_slice_uses_the_approved_canonical_mapping(self):
        controls = self.load_controls()
        expected = {
            "HD-BST-001": ["L06-C01"],
            "HD-BST-002": ["L06-C02"],
            "HD-BST-003": ["L06-C04"],
            "HD-FND-001": ["L02-C01"],
            "HD-INS-001": ["L02-C02", "L04-C01"],
            "HD-INS-002": ["L04-C02", "L04-C03"],
            "HD-KNW-001": ["L03-C01"],
            "HD-KNW-002": ["L03-C02", "L03-C03"],
            "HD-SCP-001": ["L07-C01", "L07-C02"],
            "HD-SCP-002": ["L01-C01", "L07-C03"],
            "HD-STA-001": ["L01-C03", "L05-C01", "L06-C03"],
            "HD-STA-002": ["L05-C02"],
            "HD-STA-003": ["L08-C01", "L08-C02"],
            "HD-VER-001": ["L01-C04", "L02-C04"],
        }
        actual_by_alias = {
            alias: control["id"]
            for control in controls["controls"]
            for alias in control["source_aliases"]
        }

        for control_id, aliases in expected.items():
            for alias in aliases:
                self.assertEqual(control_id, actual_by_alias[alias])

    def test_l1_l2_aliases_are_unique_and_each_has_chapter_provenance(self):
        controls = self.load_controls()["controls"]
        l1_l2_aliases = {
            "L01-C01",
            "L01-C03",
            "L01-C04",
            "L02-C01",
            "L02-C02",
            "L02-C04",
            "L03-C01",
            "L03-C02",
            "L03-C03",
            "L04-C01",
            "L04-C02",
            "L04-C03",
            "L05-C01",
            "L05-C02",
            "L06-C01",
            "L06-C02",
            "L06-C03",
            "L06-C04",
            "L07-C01",
            "L07-C02",
            "L07-C03",
            "L08-C01",
            "L08-C02",
        }
        aliases = [
            alias
            for control in controls
            for alias in control["source_aliases"]
            if alias in l1_l2_aliases
        ]

        self.assertEqual(23, len(aliases))
        self.assertEqual(len(aliases), len(set(aliases)))
        for control in controls:
            document_ids = {ref["document_id"] for ref in control["source_refs"]}
            for alias in control["source_aliases"]:
                if alias in l1_l2_aliases:
                    self.assertIn(f"walkinglabs-he-{alias[:3]}", document_ids)

    def test_l1_l2_controls_have_complete_product_contracts(self):
        controls = self.load_controls()
        expected_domains = [
            "HD-FND",
            "HD-KNW",
            "HD-INS",
            "HD-BST",
            "HD-SCP",
            "HD-STA",
            "HD-VER",
            "HD-ARC",
            "HD-OBS",
            "HD-HYG",
            "HD-AUT",
            "HD-GRF",
        ]

        self.assertEqual(expected_domains, [domain["id"] for domain in controls["domains"]])
        core_controls = [
            control
            for control in controls["controls"]
            if control["maturity"] in {"L1", "L2"}
        ]
        self.assertTrue(core_controls)
        for control in core_controls:
            self.assertTrue(control["title"].strip())
            self.assertTrue(control["requirement"].strip())
            self.assertTrue(control["applicability"]["applies_when"])
            self.assertTrue(control["evidence"]["positive"])
            self.assertTrue(control["evidence"]["partial"])
            self.assertTrue(control["evidence"]["conflict"])
            self.assertTrue(control["remediation"]["summary"].strip())
            self.assertTrue(control["remediation"]["artifact_types"])

    def test_production_pair_is_valid_after_l1_l2_slice(self):
        errors = self.validator.validate_catalog(PRODUCTION_CATALOG)

        self.assertEqual([], list(errors))


class ProductionL3CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def load_controls(self):
        return json.loads(
            (PRODUCTION_CATALOG / "controls.json").read_text(encoding="utf-8")
        )

    def test_l3_slice_uses_the_approved_canonical_mapping(self):
        controls = self.load_controls()["controls"]
        actual_by_alias = {
            alias: control["id"]
            for control in controls
            for alias in control["source_aliases"]
        }
        expected_by_control = {
            "HD-ARC-001": ["L10-C03"],
            "HD-ARC-002": ["L10-C04"],
            "HD-FND-002": ["L01-C02", "L02-C05"],
            "HD-FND-003": ["L02-C03"],
            "HD-HYG-001": ["L12-C01", "L12-C06"],
            "HD-HYG-002": ["L12-C03"],
            "HD-KNW-003": ["L03-C04", "L04-C04", "L04-C05"],
            "HD-OBS-001": ["L11-C01"],
            "HD-OBS-002": ["L11-C03"],
            "HD-OBS-003": ["L11-C05"],
            "HD-SCP-001": ["L11-C02"],
            "HD-SCP-003": ["L09-C05"],
            "HD-STA-001": ["L07-C04"],
            "HD-STA-003": ["L08-C04", "L12-C02"],
            "HD-STA-004": ["L05-C03", "L05-C04", "L06-C05"],
            "HD-STA-005": ["L08-C03", "L08-C05"],
            "HD-VER-002": ["L09-C01", "L09-C02"],
            "HD-VER-003": ["L09-C03", "L11-C04"],
            "HD-VER-004": ["L10-C01", "L10-C02"],
            "HD-VER-005": ["L10-C05"],
        }

        for control_id, aliases in expected_by_control.items():
            for alias in aliases:
                self.assertEqual(control_id, actual_by_alias.get(alias))

    def test_catalog_has_54_unique_aliases_after_l3_slice(self):
        controls = [
            control for control in self.load_controls()["controls"]
            if control["maturity"] != "L4"
        ]
        aliases = [alias for control in controls for alias in control["source_aliases"]]

        self.assertEqual(54, len(aliases))
        self.assertEqual(len(aliases), len(set(aliases)))
        for control in controls:
            document_ids = {ref["document_id"] for ref in control["source_refs"]}
            for alias in control["source_aliases"]:
                self.assertIn(f"walkinglabs-he-{alias[:3]}", document_ids)

    def test_l3_gates_match_the_approved_maturity_boundary(self):
        controls = self.load_controls()
        level = next(level for level in controls["maturity_levels"] if level["id"] == "L3")

        self.assertEqual(
            [
                "HD-ARC-001",
                "HD-FND-003",
                "HD-HYG-001",
                "HD-HYG-002",
                "HD-KNW-003",
                "HD-OBS-001",
                "HD-OBS-002",
                "HD-OBS-003",
                "HD-STA-004",
                "HD-STA-005",
                "HD-VER-002",
                "HD-VER-003",
                "HD-VER-004",
                "HD-VER-005",
            ],
            level["gate_control_ids"],
        )

    def test_conflict_resolutions_are_explicit_in_control_requirements(self):
        controls = {control["id"]: control for control in self.load_controls()["controls"]}

        self.assertIn("不得新增", controls["HD-HYG-001"]["requirement"])
        self.assertIn("基线", controls["HD-HYG-001"]["requirement"])
        self.assertIn("变更表面", controls["HD-VER-004"]["requirement"])
        self.assertIn("重新打开", controls["HD-STA-005"]["requirement"])
        self.assertIn("预览", controls["HD-HYG-002"]["requirement"])
        self.assertIn("幂等", controls["HD-HYG-002"]["requirement"])

    def test_production_pair_is_valid_after_l3_slice(self):
        self.assertEqual([], list(self.validator.validate_catalog(PRODUCTION_CATALOG)))


class ProductionL4CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    def load_controls(self):
        return json.loads(
            (PRODUCTION_CATALOG / "controls.json").read_text(encoding="utf-8")
        )

    def research_candidates(self):
        candidates = set()
        for lecture_number in range(1, 15):
            note = (CHAPTERS_DIR / f"lecture-{lecture_number:02d}.md").read_text(
                encoding="utf-8"
            )
            candidates.update(re.findall(r"L[0-9]{2}-C[0-9]{2}", note))
        return candidates

    def test_l4_slice_uses_the_approved_canonical_mapping(self):
        controls = self.load_controls()["controls"]
        actual_by_alias = {
            alias: control["id"]
            for control in controls
            for alias in control["source_aliases"]
        }
        expected_by_control = {
            "HD-AUT-001": ["L13-C01", "L13-C02"],
            "HD-AUT-002": ["L13-C03"],
            "HD-AUT-003": ["L09-C04", "L13-C04"],
            "HD-AUT-004": ["L03-C05", "L07-C05", "L13-C05"],
            "HD-AUT-005": ["L13-C06"],
            "HD-AUT-006": ["L13-C07"],
            "HD-GRF-001": ["L14-C01"],
            "HD-GRF-002": ["L14-C02"],
            "HD-GRF-003": ["L14-C03"],
            "HD-GRF-004": ["L14-C04"],
            "HD-GRF-005": ["L14-C05"],
            "HD-GRF-006": ["L14-C06"],
            "HD-GRF-007": ["L14-C07"],
            "HD-HYG-003": ["L12-C04", "L12-C05"],
            "HD-STA-006": ["L05-C05"],
        }

        for control_id, aliases in expected_by_control.items():
            for alias in aliases:
                self.assertEqual(control_id, actual_by_alias.get(alias))

    def test_all_74_research_candidates_have_exactly_one_disposition(self):
        controls = self.load_controls()
        candidates = self.research_candidates()
        dispositions = [
            alias
            for control in controls["controls"]
            for alias in control["source_aliases"]
        ] + [candidate["id"] for candidate in controls["excluded_candidates"]]
        disposition_counts = Counter(dispositions)

        self.assertEqual(74, len(candidates))
        self.assertEqual(candidates, set(dispositions))
        self.assertEqual([], [item for item, count in disposition_counts.items() if count != 1])
        self.assertEqual([], controls["excluded_candidates"])

    def test_every_candidate_alias_resolves_to_its_chapter_source(self):
        controls = self.load_controls()["controls"]

        for control in controls:
            document_ids = {ref["document_id"] for ref in control["source_refs"]}
            for alias in control["source_aliases"]:
                self.assertIn(f"walkinglabs-he-{alias[:3]}", document_ids)

    def test_l4_is_explicit_diagnostic_only_and_scenario_gated(self):
        controls = self.load_controls()
        l4_controls = [
            control for control in controls["controls"] if control["maturity"] == "L4"
        ]
        level = next(level for level in controls["maturity_levels"] if level["id"] == "L4")

        self.assertEqual("explicit_autonomy", level["activation"])
        self.assertIn("至少一个", level["description"])
        self.assertEqual(15, len(l4_controls))
        self.assertEqual(
            sorted(control["id"] for control in l4_controls),
            level["gate_control_ids"],
        )
        for control in l4_controls:
            self.assertTrue(control["applicability"]["not_applicable_when"])
            self.assertTrue(control["remediation"]["summary"].startswith("仅提供"))

    def test_production_pair_is_valid_with_complete_dispositions(self):
        self.assertEqual([], list(self.validator.validate_catalog(PRODUCTION_CATALOG)))


if __name__ == "__main__":
    unittest.main()
