from __future__ import annotations

from pathlib import Path
import re
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]


class SkillStructureTests(unittest.TestCase):
    def test_skill_frontmatter_is_complete(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---\n", text, re.DOTALL)

        self.assertIsNotNone(match)
        assert match is not None
        fields = {
            key.strip(): value.strip()
            for key, value in (
                line.split(":", 1)
                for line in match.group("frontmatter").splitlines()
                if ":" in line
            )
        }
        self.assertEqual(fields["name"], SKILL_DIR.name)
        self.assertTrue(fields["description"])
        self.assertEqual(set(fields), {"name", "description"})
        self.assertNotIn("TODO", text)

    def test_referenced_resources_exist(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        references = re.findall(r"\]\((references/[^)]+)\)", text)

        self.assertTrue(references)
        for relative_path in references:
            self.assertTrue((SKILL_DIR / relative_path).is_file(), relative_path)
        self.assertTrue((SKILL_DIR / "scripts" / "compose_cover.py").is_file())

    def test_openai_metadata_mentions_skill(self) -> None:
        metadata = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn("display_name:", metadata)
        self.assertIn("short_description:", metadata)
        self.assertIn("default_prompt:", metadata)
        self.assertIn(f"${SKILL_DIR.name}", metadata)


if __name__ == "__main__":
    unittest.main()
