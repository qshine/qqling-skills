from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "compose_cover.py"
SPEC = importlib.util.spec_from_file_location("compose_cover", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
compose_cover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compose_cover)


@unittest.skipIf(compose_cover.Image is None, "Pillow is not installed")
class ComposeCoverTests(unittest.TestCase):
    def setUp(self) -> None:
        candidates = (
            Path("/System/Library/Fonts/Menlo.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        )
        self.font_path = next((path.resolve() for path in candidates if path.is_file()), None)
        if self.font_path is None:
            self.skipTest("no portable ASCII test font is installed")

    def write_spec(self, directory: Path, **overrides: object) -> Path:
        spec = {
            "background_color": "#E7D3A8",
            "canvas": {"width": 300, "height": 400},
            "font": str(self.font_path),
            "title": {
                "text": "One sharp idea?",
                "box": [20, 40, 260, 150],
                "lines": [
                    {"text": "One sharp", "background": "#F8F4E8", "rotation": -1},
                    {"text": "idea?", "fill": "#111111", "background": "#E9B93F"},
                ],
                "max_font_size": 44,
                "min_font_size": 20,
                "padding": [10, 6],
                "line_gap": 5,
                "align": "center",
                "paper": True,
            },
        }
        spec.update(overrides)
        path = directory / "layout.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return path

    def test_render_writes_exact_copy_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            spec_path = self.write_spec(directory)
            output = directory / "cover.png"
            manifest_path = directory / "cover.manifest.json"

            manifest = compose_cover.render_cover(spec_path, output, manifest_path)

            self.assertTrue(output.is_file())
            self.assertEqual(manifest["canvas"]["aspect_ratio"], "3:4")
            self.assertEqual(manifest["safe_area"]["box"], [15, 40, 270, 320])
            self.assertEqual(manifest["format"], "png")
            self.assertEqual(manifest["blocks"][0]["text"], "One sharp idea?")
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["blocks"][0]["lines"][1]["text"], "idea?")
            self.assertEqual(len(saved_manifest["sha256"]), 64)

    def test_rejects_existing_output_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            spec_path = self.write_spec(directory)
            output = directory / "cover.png"
            output.write_bytes(b"existing")

            with self.assertRaisesRegex(compose_cover.CompositionError, "output already exists"):
                compose_cover.render_cover(spec_path, output)

            self.assertEqual(output.read_bytes(), b"existing")

    def test_refuses_to_overwrite_source_background(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            background = directory / "background.png"
            Image.new("RGB", (300, 400), "white").save(background)
            spec_path = self.write_spec(
                directory,
                background="background.png",
                background_color=None,
            )

            with self.assertRaisesRegex(compose_cover.CompositionError, "source background"):
                compose_cover.render_cover(spec_path, background, force=True)

    def test_rejects_out_of_bounds_title_box(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            title = {
                "text": "Out of bounds",
                "box": [250, 40, 100, 120],
                "lines": ["Out of bounds"],
                "max_font_size": 36,
                "min_font_size": 18,
            }
            spec_path = self.write_spec(directory, title=title)

            with self.assertRaisesRegex(compose_cover.CompositionError, "extends beyond"):
                compose_cover.render_cover(spec_path, directory / "cover.png")

    def test_rejects_font_without_chinese_glyphs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            title = {
                "text": "中文标题",
                "box": [20, 40, 260, 120],
                "lines": ["中文标题"],
                "max_font_size": 36,
                "min_font_size": 18,
            }
            spec_path = self.write_spec(directory, title=title)

            with self.assertRaisesRegex(compose_cover.CompositionError, "missing glyphs"):
                compose_cover.render_cover(spec_path, directory / "cover.png")

    def test_rejects_line_plan_that_changes_canonical_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            title = {
                "text": "Exact copy!",
                "box": [20, 40, 260, 120],
                "lines": ["Exact typo!"],
                "max_font_size": 36,
                "min_font_size": 18,
            }
            spec_path = self.write_spec(directory, title=title)

            with self.assertRaisesRegex(compose_cover.CompositionError, "does not match"):
                compose_cover.render_cover(spec_path, directory / "cover.png")

    def test_rejects_important_text_outside_safe_area(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            title = {
                "text": "Too close",
                "box": [20, 20, 260, 120],
                "lines": ["Too close"],
                "max_font_size": 36,
                "min_font_size": 18,
            }
            spec_path = self.write_spec(directory, title=title)

            with self.assertRaisesRegex(compose_cover.CompositionError, "safe area"):
                compose_cover.render_cover(spec_path, directory / "cover.png")

    def test_rejects_non_three_by_four_background_instead_of_cropping(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            background = directory / "wide.png"
            Image.new("RGB", (400, 300), "white").save(background)
            spec_path = self.write_spec(
                directory,
                background="wide.png",
                background_color=None,
            )

            with self.assertRaisesRegex(compose_cover.CompositionError, "extend its canvas"):
                compose_cover.render_cover(spec_path, directory / "cover.png")


class ValidationHelperTests(unittest.TestCase):
    @unittest.skipIf(compose_cover.Image is None, "Pillow is not installed")
    def test_default_canvas_is_1080_by_1440(self) -> None:
        image, canvas, background = compose_cover.create_canvas(
            {"background_color": "#FFFFFF"},
            Path.cwd(),
        )

        self.assertEqual(canvas, (1080, 1440))
        self.assertEqual(image.size, (1080, 1440))
        self.assertIsNone(background)

    def test_safe_area_requires_minimum_margins(self) -> None:
        with self.assertRaisesRegex(compose_cover.CompositionError, "at least 0.08"):
            compose_cover.parse_safe_area({"top": 0.05}, (1080, 1440))

    def test_normalize_lines_preserves_chinese_copy(self) -> None:
        lines = compose_cover.normalize_lines(
            [{"text": "普通照片"}, {"text": "也能很有感！"}],
            "title.lines",
        )

        self.assertEqual("".join(line["text"] for line in lines), "普通照片也能很有感！")

    def test_rejects_invalid_color(self) -> None:
        with self.assertRaisesRegex(compose_cover.CompositionError, "#RRGGBB"):
            compose_cover.parse_color("yellow", "title.fill")


if __name__ == "__main__":
    unittest.main()
