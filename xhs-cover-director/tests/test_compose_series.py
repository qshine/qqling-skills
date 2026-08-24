from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import compose_cover  # noqa: E402
import compose_series  # noqa: E402


@unittest.skipIf(compose_cover.Image is None, "Pillow is not installed")
class ComposeSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        candidates = (
            Path("/System/Library/Fonts/Menlo.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        )
        self.font_path = next((path.resolve() for path in candidates if path.is_file()), None)
        if self.font_path is None:
            self.skipTest("no portable ASCII test font is installed")
        cjk_candidates = (
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
            Path("/System/Library/Fonts/STHeiti Medium.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("C:/Windows/Fonts/msyh.ttc"),
        )
        self.cjk_font_path = next(
            (path.resolve() for path in cjk_candidates if path.is_file()),
            None,
        )

    def write_layout(
        self,
        directory: Path,
        index: int,
        *,
        title: str | None = None,
        canvas: tuple[int, int] = (360, 640),
        font_path: Path | None = None,
    ) -> Path:
        copy = title or f"Page {index}"
        spec = {
            "background_color": "#F2E4C7",
            "canvas": {"width": canvas[0], "height": canvas[1]},
            "font": str(font_path or self.font_path),
            "title": {
                "text": copy,
                "box": [24, 80, canvas[0] - 48, 180],
                "lines": [{"text": copy, "background": "#F8F4E8"}],
                "max_font_size": 38,
                "min_font_size": 18,
                "padding": [10, 6],
            },
        }
        path = directory / f"layout-{index}.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def write_series(
        self,
        directory: Path,
        *,
        count: int = 5,
        caption: str = "A concise caption. #topic",
        pages: list[dict[str, str]] | None = None,
    ) -> Path:
        if pages is None:
            pages = []
            for index in range(1, count + 1):
                layout = self.write_layout(directory, index)
                pages.append(
                    {
                        "id": f"{index:02d}-{'cover' if index == 1 else 'content'}",
                        "role": "cover" if index == 1 else "content",
                        "layout": layout.name,
                    }
                )
        path = directory / "series.json"
        path.write_text(
            json.dumps({"caption": caption, "pages": pages}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_renders_five_page_series_and_delivery_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            spec_path = self.write_series(directory)
            output_dir = directory / "output"

            manifest = compose_series.render_series(spec_path, output_dir)

            self.assertEqual(manifest["page_count"], 5)
            self.assertEqual(manifest["canvas"]["aspect_ratio"], "9:16")
            self.assertEqual(manifest["caption_length"], len("A concise caption. #topic"))
            self.assertTrue((output_dir / "caption.txt").is_file())
            self.assertTrue((output_dir / "series.manifest.json").is_file())
            for page in manifest["pages"]:
                self.assertTrue(Path(page["output"]).is_file())
                self.assertTrue(Path(page["manifest"]).is_file())

    def test_realistic_chinese_series_preserves_distinct_copy(self) -> None:
        if self.cjk_font_path is None:
            self.skipTest("no CJK test font is installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            titles = (
                "给女朋友做了个夜班神器",
                "手工排班太折磨",
                "硬规则绝不放松",
                "公平和偏好都能算",
                "机器算组合人来定",
            )
            pages = []
            for index, title in enumerate(titles, start=1):
                layout = self.write_layout(
                    directory,
                    index,
                    title=title,
                    font_path=self.cjk_font_path,
                )
                pages.append(
                    {
                        "id": f"{index:02d}-{'cover' if index == 1 else 'content'}",
                        "role": "cover" if index == 1 else "content",
                        "layout": layout.name,
                    }
                )
            caption = (
                "给科室夜班排表太费脑，我做了一个能处理请假、禁排、"
                "公平和个人偏好的 Skill。它一次给出候选方案，临时请假时"
                "也尽量少改原表；最终仍由排班负责人确认。"
                "\n#Codex #排班自动化 #医生夜班"
            )
            spec_path = self.write_series(directory, caption=caption, pages=pages)

            manifest = compose_series.render_series(spec_path, directory / "output")

            self.assertEqual([page["title"] for page in manifest["pages"]], list(titles))
            self.assertEqual(len({page["copy"] for page in manifest["pages"]}), 5)
            self.assertLessEqual(manifest["caption_length"], 300)

    def test_accepts_single_cover_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            spec_path = self.write_series(directory, count=1)

            manifest = compose_series.render_series(spec_path, directory / "output")

            self.assertEqual(manifest["page_count"], 1)

    def test_rejects_more_than_five_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            spec_path = self.write_series(directory, count=6)

            with self.assertRaisesRegex(compose_cover.CompositionError, "between 1 and 5"):
                compose_series.render_series(spec_path, directory / "output")

    def test_rejects_caption_over_three_hundred_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            spec_path = self.write_series(directory, count=1, caption="文" * 301)

            with self.assertRaisesRegex(compose_cover.CompositionError, "300 Unicode"):
                compose_series.render_series(spec_path, directory / "output")

    def test_rejects_wrong_role_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            layout = self.write_layout(directory, 1)
            spec_path = self.write_series(
                directory,
                pages=[{"id": "01-content", "role": "content", "layout": layout.name}],
            )

            with self.assertRaisesRegex(compose_cover.CompositionError, "role must be cover"):
                compose_series.render_series(spec_path, directory / "output")

    def test_rejects_duplicate_page_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = self.write_layout(directory, 1)
            second = self.write_layout(directory, 2)
            spec_path = self.write_series(
                directory,
                pages=[
                    {"id": "01-same", "role": "cover", "layout": first.name},
                    {"id": "01-same", "role": "content", "layout": second.name},
                ],
            )

            with self.assertRaisesRegex(compose_cover.CompositionError, "duplicate page id"):
                compose_series.render_series(spec_path, directory / "output")

    def test_rejects_page_id_without_order_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            layout = self.write_layout(directory, 1)
            spec_path = self.write_series(
                directory,
                pages=[{"id": "cover", "role": "cover", "layout": layout.name}],
            )

            with self.assertRaisesRegex(compose_cover.CompositionError, "start with 01-"):
                compose_series.render_series(spec_path, directory / "output")

    def test_rejects_duplicate_copy_without_publishing_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = self.write_layout(directory, 1, title="Same copy")
            second = self.write_layout(directory, 2, title="Same copy")
            spec_path = self.write_series(
                directory,
                pages=[
                    {"id": "01-cover", "role": "cover", "layout": first.name},
                    {"id": "02-content", "role": "content", "layout": second.name},
                ],
            )
            output_dir = directory / "output"

            with self.assertRaisesRegex(compose_cover.CompositionError, "titles must be unique"):
                compose_series.render_series(spec_path, output_dir)

            self.assertFalse(output_dir.exists())

    def test_rejects_three_by_four_page_without_publishing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            layout = self.write_layout(directory, 1, canvas=(300, 400))
            spec_path = self.write_series(
                directory,
                pages=[{"id": "01-cover", "role": "cover", "layout": layout.name}],
            )
            output_dir = directory / "output"

            with self.assertRaisesRegex(compose_cover.CompositionError, "must use a 9:16"):
                compose_series.render_series(spec_path, output_dir)

            self.assertFalse(output_dir.exists())

    def test_rejects_mixed_canvas_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = self.write_layout(directory, 1, canvas=(360, 640))
            second = self.write_layout(directory, 2, canvas=(450, 800))
            spec_path = self.write_series(
                directory,
                pages=[
                    {"id": "01-cover", "role": "cover", "layout": first.name},
                    {"id": "02-content", "role": "content", "layout": second.name},
                ],
            )

            with self.assertRaisesRegex(compose_cover.CompositionError, "identical canvas"):
                compose_series.render_series(spec_path, directory / "output")

    def test_refuses_existing_output_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            spec_path = self.write_series(directory, count=1)
            output_dir = directory / "output"
            output_dir.mkdir()
            existing = output_dir / "01-cover.png"
            existing.write_bytes(b"existing")

            with self.assertRaisesRegex(compose_cover.CompositionError, "already exists"):
                compose_series.render_series(spec_path, output_dir)

            self.assertEqual(existing.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
