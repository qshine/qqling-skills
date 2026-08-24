#!/usr/bin/env python3
"""Render a validated 9:16 Xiaohongshu poster series transactionally."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Optional

from compose_cover import CompositionError, load_spec, render_cover


PAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_PAGES = 5
MAX_CAPTION_CHARACTERS = 300


def resolve_path(raw_path: str, base_dir: Path) -> Path:
    """Resolve a path relative to the series specification."""

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def validate_series_spec(spec_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Load and validate the editorial and file-level series contract."""

    spec = load_spec(spec_path)
    caption = spec.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        raise CompositionError("caption must be a non-empty string")
    caption = caption.strip()
    if len(caption) > MAX_CAPTION_CHARACTERS:
        raise CompositionError(
            f"caption must not exceed {MAX_CAPTION_CHARACTERS} Unicode characters"
        )

    raw_pages = spec.get("pages")
    if not isinstance(raw_pages, list) or not 1 <= len(raw_pages) <= MAX_PAGES:
        raise CompositionError(f"pages must contain between 1 and {MAX_PAGES} items")

    base_dir = spec_path.parent
    pages: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_layouts: set[Path] = set()
    for index, raw_page in enumerate(raw_pages):
        field = f"pages[{index}]"
        if not isinstance(raw_page, dict):
            raise CompositionError(f"{field} must be an object")
        page_id = raw_page.get("id")
        if not isinstance(page_id, str) or PAGE_ID.fullmatch(page_id) is None:
            raise CompositionError(
                f"{field}.id must use lowercase letters, digits, and hyphens"
            )
        if page_id in seen_ids:
            raise CompositionError(f"duplicate page id: {page_id}")
        seen_ids.add(page_id)
        expected_prefix = f"{index + 1:02d}-"
        if not page_id.startswith(expected_prefix) or page_id == expected_prefix:
            raise CompositionError(f"{field}.id must start with {expected_prefix}")

        role = raw_page.get("role")
        expected_role = "cover" if index == 0 else "content"
        if role != expected_role:
            raise CompositionError(f"{field}.role must be {expected_role}")

        raw_layout = raw_page.get("layout")
        if not isinstance(raw_layout, str) or not raw_layout.strip():
            raise CompositionError(f"{field}.layout must be a non-empty path string")
        layout_path = resolve_path(raw_layout, base_dir)
        if not layout_path.is_file():
            raise CompositionError(f"layout does not exist: {layout_path}")
        if layout_path in seen_layouts:
            raise CompositionError(f"layout must be unique for every page: {layout_path}")
        seen_layouts.add(layout_path)
        pages.append({"id": page_id, "role": role, "layout": layout_path})
    return caption, pages


def page_copy(manifest: dict[str, Any]) -> str:
    """Return the canonical copy represented by one rendered page."""

    text_parts = [block["text"].strip() for block in manifest["blocks"]]
    text_parts.extend(sticker["text"].strip() for sticker in manifest["emoji_stickers"])
    return "\n".join(part for part in text_parts if part)


def render_series(
    spec_path: Path,
    output_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Render all pages before publishing any validated output."""

    spec_path = spec_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    caption, pages = validate_series_spec(spec_path)
    final_targets = [output_dir / "caption.txt", output_dir / "series.manifest.json"]
    for page in pages:
        final_targets.extend(
            [output_dir / f"{page['id']}.png", output_dir / f"{page['id']}.manifest.json"]
        )
    if not force:
        existing = next((path for path in final_targets if path.exists()), None)
        if existing is not None:
            raise CompositionError(
                f"series output already exists; use --force to replace it: {existing}"
            )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}-staging-",
        dir=output_dir.parent,
    ) as temp_dir:
        staging_dir = Path(temp_dir)
        rendered_pages: list[dict[str, Any]] = []
        expected_canvas: Optional[dict[str, Any]] = None
        seen_titles: set[str] = set()
        seen_copy: set[str] = set()
        for index, page in enumerate(pages, start=1):
            image_name = f"{page['id']}.png"
            manifest_name = f"{page['id']}.manifest.json"
            staged_image = staging_dir / image_name
            staged_manifest = staging_dir / manifest_name
            manifest = render_cover(page["layout"], staged_image, staged_manifest)
            canvas = manifest["canvas"]
            if canvas["aspect_ratio"] != "9:16":
                raise CompositionError(f"series page {page['id']} must use a 9:16 canvas")
            if expected_canvas is None:
                expected_canvas = canvas
            elif canvas != expected_canvas:
                raise CompositionError("all series pages must use identical canvas dimensions")

            title = manifest["blocks"][0]["text"].strip()
            copy = page_copy(manifest)
            if title in seen_titles:
                raise CompositionError(f"series page titles must be unique: {title}")
            if copy in seen_copy:
                raise CompositionError(f"series page copy must be unique: {page['id']}")
            seen_titles.add(title)
            seen_copy.add(copy)

            final_image = output_dir / image_name
            final_manifest = output_dir / manifest_name
            manifest["output"] = str(final_image)
            staged_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            rendered_pages.append(
                {
                    "index": index,
                    "id": page["id"],
                    "role": page["role"],
                    "layout": str(page["layout"]),
                    "output": str(final_image),
                    "manifest": str(final_manifest),
                    "title": title,
                    "copy": copy,
                    "sha256": manifest["sha256"],
                }
            )

        assert expected_canvas is not None
        series_manifest = {
            "page_count": len(rendered_pages),
            "canvas": expected_canvas,
            "caption": caption,
            "caption_length": len(caption),
            "pages": rendered_pages,
        }
        (staging_dir / "caption.txt").write_text(caption + "\n", encoding="utf-8")
        (staging_dir / "series.manifest.json").write_text(
            json.dumps(series_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        for staged_file in staging_dir.iterdir():
            os.replace(staged_file, output_dir / staged_file.name)
    return series_manifest


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path, help="series JSON specification")
    parser.add_argument("--output-dir", required=True, type=Path, help="final series directory")
    parser.add_argument("--force", action="store_true", help="replace existing series outputs")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Run the transactional series compositor."""

    arguments = build_parser().parse_args(argv)
    try:
        manifest = render_series(arguments.spec, arguments.output_dir, force=arguments.force)
    except CompositionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output_dir": str(arguments.output_dir.expanduser().resolve()),
                "page_count": manifest["page_count"],
                "caption_length": manifest["caption_length"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
