from pathlib import Path
import importlib.util
import sys
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1] / "skill-usage-auditor"
VALIDATOR = SKILL_DIR / "scripts" / "validate_skill.py"
SPEC = importlib.util.spec_from_file_location("validate_skill", VALIDATOR)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


class SkillStructureTests(unittest.TestCase):
    def test_skill_structure_is_valid(self):
        self.assertEqual([], validator.validate(SKILL_DIR))

    def test_main_script_contains_no_token_estimation_feature(self):
        text = (SKILL_DIR / "scripts" / "skill_usage_auditor.py").read_text(
            encoding="utf-8"
        ).lower()
        self.assertNotIn("token_estimate", text)
        self.assertNotIn("estimated_tokens", text)


if __name__ == "__main__":
    unittest.main()
