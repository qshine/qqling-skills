#!/usr/bin/env python3
"""Compose exact text over a text-free Xiaohongshu cover base."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Optional

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:  # pragma: no cover - exercised by the CLI error path
    Image = ImageDraw = ImageFont = ImageOps = None


class CompositionError(ValueError):
    """Raised when a layout cannot be rendered safely and deterministically."""


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
DEFAULT_CJK_FONTS = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)


def require_pillow() -> None:
    """Fail with an actionable message when Pillow is unavailable."""

    if Image is None:
        raise CompositionError(
            "Pillow is required for exact text composition. Install "
            "xhs-cover-director/requirements.txt or use the bundled Codex Python runtime."
        )


def load_spec(path: Path) -> dict[str, Any]:
    """Load a JSON object from *path*."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CompositionError(f"layout specification does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CompositionError(f"invalid layout JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CompositionError("layout specification must be a JSON object")
    return value


def parse_color(value: Any, field: str, *, allow_none: bool = False) -> Optional[str]:
    """Validate a hexadecimal RGB or RGBA color."""

    if value is None and allow_none:
        return None
    if not isinstance(value, str) or HEX_COLOR.fullmatch(value) is None:
        raise CompositionError(f"{field} must be #RRGGBB or #RRGGBBAA")
    return value


def parse_box(value: Any, field: str, canvas: tuple[int, int]) -> tuple[int, int, int, int]:
    """Validate an [x, y, width, height] box inside *canvas*."""

    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise CompositionError(f"{field} must be four integer values [x, y, width, height]")
    x, y, width, height = value
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise CompositionError(f"{field} must have non-negative coordinates and positive size")
    if x + width > canvas[0] or y + height > canvas[1]:
        raise CompositionError(f"{field} extends beyond the canvas")
    return x, y, width, height


def safe_fraction(value: Any, field: str, minimum: float, default: float) -> float:
    """Validate one proportional safe-area margin."""

    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompositionError(f"{field} must be a decimal proportion")
    fraction = float(value)
    if fraction < minimum or fraction >= 0.5:
        raise CompositionError(f"{field} must be at least {minimum:.2f} and less than 0.50")
    return fraction


def parse_safe_area(
    value: Any,
    canvas: tuple[int, int],
) -> tuple[dict[str, float], tuple[int, int, int, int]]:
    """Return validated safe-area fractions and their inner pixel box."""

    if value is None:
        config: dict[str, Any] = {}
    elif isinstance(value, dict):
        config = value
    else:
        raise CompositionError("safe_area must be an object")
    fractions = {
        "top": safe_fraction(config.get("top"), "safe_area.top", 0.08, 0.10),
        "bottom": safe_fraction(config.get("bottom"), "safe_area.bottom", 0.08, 0.10),
        "left": safe_fraction(config.get("left"), "safe_area.left", 0.05, 0.05),
        "right": safe_fraction(config.get("right"), "safe_area.right", 0.05, 0.05),
    }
    if fractions["top"] + fractions["bottom"] >= 1:
        raise CompositionError("safe_area top and bottom margins leave no usable height")
    if fractions["left"] + fractions["right"] >= 1:
        raise CompositionError("safe_area left and right margins leave no usable width")
    left = math.ceil(canvas[0] * fractions["left"])
    top = math.ceil(canvas[1] * fractions["top"])
    right = canvas[0] - math.ceil(canvas[0] * fractions["right"])
    bottom = canvas[1] - math.ceil(canvas[1] * fractions["bottom"])
    return fractions, (left, top, right - left, bottom - top)


def ensure_inside_safe_area(
    box: tuple[int, int, int, int],
    safe_box: tuple[int, int, int, int],
    field: str,
) -> None:
    """Reject important content boxes outside the configured safe area."""

    x, y, width, height = box
    safe_x, safe_y, safe_width, safe_height = safe_box
    if (
        x < safe_x
        or y < safe_y
        or x + width > safe_x + safe_width
        or y + height > safe_y + safe_height
    ):
        raise CompositionError(f"{field} must stay inside the configured safe area")


def parse_padding(value: Any, field: str) -> tuple[int, int]:
    """Return horizontal and vertical padding."""

    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value, value
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in value)
    ):
        return value[0], value[1]
    raise CompositionError(f"{field} must be a non-negative integer or [horizontal, vertical]")


def resolve_path(raw_path: str, base_dir: Path) -> Path:
    """Resolve a user path relative to a layout specification."""

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def find_cjk_font(raw_path: Any, base_dir: Path) -> Path:
    """Resolve an explicit CJK font or locate a conservative platform default."""

    if raw_path is not None:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise CompositionError("font must be a non-empty path string")
        font_path = resolve_path(raw_path, base_dir)
        if not font_path.is_file():
            raise CompositionError(f"font does not exist: {font_path}")
        return font_path
    for candidate in DEFAULT_CJK_FONTS:
        font_path = Path(candidate)
        if font_path.is_file():
            return font_path.resolve()
    raise CompositionError("no CJK font found; set the top-level font field to a CJK font file")


def normalize_lines(value: Any, field: str) -> list[dict[str, Any]]:
    """Normalize block lines while preserving every source character."""

    if not isinstance(value, list) or not value:
        raise CompositionError(f"{field} must be a non-empty list")
    lines: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        line_field = f"{field}[{index}]"
        if isinstance(item, str):
            line = {"text": item}
        elif isinstance(item, dict):
            line = dict(item)
        else:
            raise CompositionError(f"{line_field} must be a string or object")
        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CompositionError(f"{line_field}.text must be a non-empty string")
        if any(character in text for character in ("\n", "\r", "\t")):
            raise CompositionError(f"{line_field}.text cannot contain control whitespace")
        lines.append(line)
    return lines


def canonical_copy(config: dict[str, Any], lines: list[dict[str, Any]], field: str) -> str:
    """Validate the canonical copy against its visual line plan."""

    text = config.get("text")
    if not isinstance(text, str) or not text.strip():
        raise CompositionError(f"{field}.text must contain the exact canonical copy")
    if any(character in text for character in ("\n", "\r", "\t")):
        raise CompositionError(f"{field}.text cannot contain control whitespace")
    canonical_characters = "".join(text.split())
    planned_characters = "".join("".join(line["text"].split()) for line in lines)
    if canonical_characters != planned_characters:
        raise CompositionError(f"{field}.text does not match the characters in {field}.lines")
    return text


def positive_int(value: Any, field: str, default: int) -> int:
    """Validate a positive integer with a default."""

    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CompositionError(f"{field} must be a positive integer")
    return value


def non_negative_int(value: Any, field: str, default: int) -> int:
    """Validate a non-negative integer with a default."""

    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CompositionError(f"{field} must be a non-negative integer")
    return value


def load_font(font_path: Path, size: int, font_index: int) -> Any:
    """Load one font face and normalize renderer errors."""

    try:
        return ImageFont.truetype(str(font_path), size=size, index=font_index)
    except OSError as exc:
        raise CompositionError(f"cannot load font {font_path} at index {font_index}: {exc}") from exc


def glyph_fingerprint(font: Any, character: str) -> tuple[tuple[int, int], bytes]:
    """Create a stable bitmap signature for one glyph."""

    mask = font.getmask(character)
    return mask.size, bytes(mask)


def ensure_glyphs(font: Any, texts: Iterable[str]) -> None:
    """Reject characters that map to the font's missing-glyph bitmap."""

    missing_signature = glyph_fingerprint(font, "\U0010ffff")
    missing = sorted(
        {
            character
            for text in texts
            for character in text
            if not character.isspace() and glyph_fingerprint(font, character) == missing_signature
        }
    )
    if missing:
        raise CompositionError("font is missing glyphs for: " + " ".join(missing))


def text_size(font: Any, text: str, stroke_width: int) -> tuple[int, int, tuple[int, int, int, int]]:
    """Measure text including its stroke."""

    left, top, right, bottom = font.getbbox(text, stroke_width=stroke_width)
    return right - left, bottom - top, (left, top, right, bottom)


def rotated_bounds(width: int, height: int, degrees: float) -> tuple[int, int]:
    """Return the axis-aligned size of a rotated rectangle."""

    radians = math.radians(abs(degrees))
    rotated_width = math.ceil(width * math.cos(radians) + height * math.sin(radians))
    rotated_height = math.ceil(width * math.sin(radians) + height * math.cos(radians))
    return rotated_width, rotated_height


def line_rotation(line: dict[str, Any], field: str) -> float:
    """Validate a restrained line rotation."""

    value = line.get("rotation", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompositionError(f"{field}.rotation must be numeric")
    rotation = float(value)
    if not -8 <= rotation <= 8:
        raise CompositionError(f"{field}.rotation must be between -8 and 8 degrees")
    return rotation


def measure_lines(
    font: Any,
    lines: list[dict[str, Any]],
    padding: tuple[int, int],
    default_stroke: int,
    field: str,
) -> list[dict[str, Any]]:
    """Measure every line and its rotated paper block."""

    measured: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        line_field = f"{field}.lines[{index}]"
        stroke_width = non_negative_int(line.get("stroke_width"), f"{line_field}.stroke_width", default_stroke)
        width, height, bbox = text_size(font, line["text"], stroke_width)
        base_width = width + 2 * padding[0]
        base_height = height + 2 * padding[1]
        rotation = line_rotation(line, line_field)
        rotated_width, rotated_height = rotated_bounds(base_width, base_height, rotation)
        measured.append(
            {
                "line": line,
                "stroke_width": stroke_width,
                "bbox": bbox,
                "base_width": base_width,
                "base_height": base_height,
                "rotated_width": rotated_width,
                "rotated_height": rotated_height,
                "rotation": rotation,
            }
        )
    return measured


def fit_block(
    config: dict[str, Any],
    lines: list[dict[str, Any]],
    box: tuple[int, int, int, int],
    font_path: Path,
    font_index: int,
    field: str,
) -> tuple[Any, int, list[dict[str, Any]], tuple[int, int], int]:
    """Choose the largest font size that fits the configured block."""

    max_size = positive_int(config.get("max_font_size"), f"{field}.max_font_size", 144)
    min_size = positive_int(config.get("min_font_size"), f"{field}.min_font_size", 54)
    if min_size > max_size:
        raise CompositionError(f"{field}.min_font_size cannot exceed max_font_size")
    padding = parse_padding(config.get("padding", [24, 12]), f"{field}.padding")
    line_gap = non_negative_int(config.get("line_gap"), f"{field}.line_gap", 12)
    default_stroke = non_negative_int(config.get("stroke_width"), f"{field}.stroke_width", 0)
    for size in range(max_size, min_size - 1, -2):
        font = load_font(font_path, size, font_index)
        ensure_glyphs(font, (line["text"] for line in lines))
        measured = measure_lines(font, lines, padding, default_stroke, field)
        total_height = sum(item["rotated_height"] for item in measured) + line_gap * (len(lines) - 1)
        if max(item["rotated_width"] for item in measured) <= box[2] and total_height <= box[3]:
            return font, size, measured, padding, line_gap
    raise CompositionError(f"{field} text cannot fit its box at the minimum font size")


def stable_offset(seed: str, index: int, amount: int) -> int:
    """Return deterministic paper-edge jitter."""

    digest = hashlib.sha256(f"{seed}:{index}".encode("utf-8")).digest()
    return digest[0] % (2 * amount + 1) - amount


def paper_polygon(width: int, height: int, seed: str) -> list[tuple[int, int]]:
    """Build a restrained deterministic torn-paper outline."""

    amount = max(1, min(8, width // 80, height // 10))
    top = [(0, amount + stable_offset(seed, 0, amount))]
    top.extend(
        (round(width * fraction), amount + stable_offset(seed, index, amount))
        for index, fraction in enumerate((0.25, 0.5, 0.75), start=1)
    )
    top.append((width - 1, amount + stable_offset(seed, 4, amount)))
    bottom = [(width - 1, height - 1 - amount + stable_offset(seed, 5, amount))]
    bottom.extend(
        (round(width * fraction), height - 1 - amount + stable_offset(seed, index, amount))
        for index, fraction in enumerate((0.75, 0.5, 0.25), start=6)
    )
    bottom.append((0, height - 1 - amount + stable_offset(seed, 9, amount)))
    return top + bottom


def render_line_layer(
    font: Any,
    measured: dict[str, Any],
    padding: tuple[int, int],
    defaults: dict[str, Any],
    field: str,
) -> Any:
    """Render one exact line to a transparent layer."""

    line = measured["line"]
    fill = parse_color(line.get("fill", defaults.get("fill", "#111111")), f"{field}.fill")
    background = parse_color(
        line.get("background", defaults.get("background")), f"{field}.background", allow_none=True
    )
    stroke_fill = parse_color(
        line.get("stroke_fill", defaults.get("stroke_fill", "#FFFFFF")), f"{field}.stroke_fill"
    )
    width = measured["base_width"]
    height = measured["base_height"]
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if background is not None:
        if bool(defaults.get("paper", False)):
            draw.polygon(paper_polygon(width, height, line["text"]), fill=background)
        else:
            draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=max(0, min(12, height // 8)), fill=background)
    bbox = measured["bbox"]
    draw.text(
        (padding[0] - bbox[0], padding[1] - bbox[1]),
        line["text"],
        font=font,
        fill=fill,
        stroke_width=measured["stroke_width"],
        stroke_fill=stroke_fill,
    )
    if measured["rotation"]:
        layer = layer.rotate(
            measured["rotation"],
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )
    return layer


def render_block(
    canvas_image: Any,
    config: Any,
    canvas: tuple[int, int],
    safe_box: tuple[int, int, int, int],
    default_font: Path,
    base_dir: Path,
    field: str,
) -> dict[str, Any]:
    """Render a configured multiline text block and return manifest data."""

    if not isinstance(config, dict):
        raise CompositionError(f"{field} must be an object")
    box = parse_box(config.get("box"), f"{field}.box", canvas)
    ensure_inside_safe_area(box, safe_box, f"{field}.box")
    lines = normalize_lines(config.get("lines"), f"{field}.lines")
    text = canonical_copy(config, lines, field)
    font_path = find_cjk_font(config.get("font"), base_dir) if "font" in config else default_font
    font_index = non_negative_int(config.get("font_index"), f"{field}.font_index", 0)
    font, size, measured_lines, padding, line_gap = fit_block(
        config, lines, box, font_path, font_index, field
    )
    align = config.get("align", "left")
    if align not in {"left", "center", "right"}:
        raise CompositionError(f"{field}.align must be left, center, or right")
    total_height = sum(item["rotated_height"] for item in measured_lines) + line_gap * (len(lines) - 1)
    valign = config.get("valign", "top")
    if valign not in {"top", "center", "bottom"}:
        raise CompositionError(f"{field}.valign must be top, center, or bottom")
    if valign == "top":
        current_y = box[1]
    elif valign == "center":
        current_y = box[1] + (box[3] - total_height) // 2
    else:
        current_y = box[1] + box[3] - total_height

    manifest_lines: list[dict[str, Any]] = []
    for index, measured in enumerate(measured_lines):
        line_layer = render_line_layer(font, measured, padding, config, f"{field}.lines[{index}]")
        if align == "left":
            x = box[0]
        elif align == "center":
            x = box[0] + (box[2] - line_layer.width) // 2
        else:
            x = box[0] + box[2] - line_layer.width
        y = current_y
        if x < box[0] or x + line_layer.width > box[0] + box[2] or y + line_layer.height > box[1] + box[3]:
            raise CompositionError(f"{field}.lines[{index}] exceeds its box after rotation")
        canvas_image.alpha_composite(line_layer, (x, y))
        manifest_lines.append(
            {
                "text": measured["line"]["text"],
                "position": [x, y],
                "size": [line_layer.width, line_layer.height],
                "rotation": measured["rotation"],
            }
        )
        current_y += line_layer.height + line_gap
    return {
        "name": field,
        "text": text,
        "lines": manifest_lines,
        "box": list(box),
        "font": str(font_path),
        "font_index": font_index,
        "font_size": size,
    }


def create_canvas(spec: dict[str, Any], base_dir: Path) -> tuple[Any, tuple[int, int], Optional[Path]]:
    """Create a 3:4 canvas from a background image or solid color."""

    canvas_config = spec.get("canvas", {})
    if not isinstance(canvas_config, dict):
        raise CompositionError("canvas must be an object")
    width = positive_int(canvas_config.get("width"), "canvas.width", 1080)
    height = positive_int(canvas_config.get("height"), "canvas.height", 1440)
    if width * 4 != height * 3:
        raise CompositionError("canvas must use an exact 3:4 aspect ratio")
    if width < 300 or height < 400 or width > 6000 or height > 8000:
        raise CompositionError("canvas dimensions must stay between 300x400 and 6000x8000")
    background_value = spec.get("background")
    background_color = spec.get("background_color")
    if (background_value is None) == (background_color is None):
        raise CompositionError("set exactly one of background or background_color")
    if background_value is not None:
        if not isinstance(background_value, str) or not background_value.strip():
            raise CompositionError("background must be a non-empty path string")
        background_path = resolve_path(background_value, base_dir)
        if not background_path.is_file():
            raise CompositionError(f"background does not exist: {background_path}")
        try:
            with Image.open(background_path) as source:
                source = ImageOps.exif_transpose(source).convert("RGBA")
                if source.width * 4 != source.height * 3:
                    raise CompositionError(
                        "background is not 3:4; extend its canvas without cropping before composition"
                    )
                canvas_image = source.resize((width, height), resample=Image.Resampling.LANCZOS)
        except CompositionError:
            raise
        except OSError as exc:
            raise CompositionError(f"cannot open background image: {exc}") from exc
        return canvas_image, (width, height), background_path
    color = parse_color(background_color, "background_color")
    return Image.new("RGBA", (width, height), color), (width, height), None


def save_image(image: Any, output: Path) -> None:
    """Save PNG, JPEG, or WebP according to the output suffix."""

    suffix = output.suffix.lower()
    if suffix == ".png":
        image.save(output, format="PNG", optimize=True)
    elif suffix in {".jpg", ".jpeg"}:
        image.convert("RGB").save(output, format="JPEG", quality=95, subsampling=0)
    elif suffix == ".webp":
        image.save(output, format="WEBP", quality=95, method=6)
    else:
        raise CompositionError("output must use .png, .jpg, .jpeg, or .webp")


def render_cover(
    spec_path: Path,
    output_path: Path,
    manifest_path: Optional[Path] = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Render one cover and return its exact-copy manifest."""

    require_pillow()
    spec_path = spec_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve() if manifest_path else None
    if output_path.exists() and not force:
        raise CompositionError(f"output already exists; use --force to replace it: {output_path}")
    if manifest_path and manifest_path.exists() and not force:
        raise CompositionError(f"manifest already exists; use --force to replace it: {manifest_path}")
    if output_path == spec_path or manifest_path == spec_path:
        raise CompositionError("output and manifest must not overwrite the layout specification")
    if manifest_path == output_path:
        raise CompositionError("manifest and output paths must be different")

    spec = load_spec(spec_path)
    base_dir = spec_path.parent
    canvas_image, canvas, background_path = create_canvas(spec, base_dir)
    if background_path and output_path == background_path:
        raise CompositionError("output must not overwrite the source background")
    if background_path and manifest_path == background_path:
        raise CompositionError("manifest must not overwrite the source background")
    default_font = find_cjk_font(spec.get("font"), base_dir)
    if "title" not in spec:
        raise CompositionError("title is required")
    safe_fractions, safe_box = parse_safe_area(spec.get("safe_area"), canvas)

    blocks = [
        render_block(canvas_image, spec["title"], canvas, safe_box, default_font, base_dir, "title")
    ]
    labels = spec.get("labels", [])
    if not isinstance(labels, list):
        raise CompositionError("labels must be a list")
    if len(labels) > 8:
        raise CompositionError("labels cannot contain more than 8 blocks")
    for index, label in enumerate(labels):
        blocks.append(
            render_block(
                canvas_image,
                label,
                canvas,
                safe_box,
                default_font,
                base_dir,
                f"labels[{index}]",
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_image(canvas_image, output_path)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    manifest = {
        "canvas": {"width": canvas[0], "height": canvas[1], "aspect_ratio": "3:4"},
        "safe_area": {
            "fractions": safe_fractions,
            "box": list(safe_box),
        },
        "output": str(output_path),
        "format": output_path.suffix.lower().lstrip("."),
        "sha256": digest,
        "blocks": blocks,
    }
    if manifest_path:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path, help="JSON layout specification")
    parser.add_argument("--output", required=True, type=Path, help="final PNG, JPEG, or WebP")
    parser.add_argument("--manifest", type=Path, help="optional exact-copy JSON manifest")
    parser.add_argument("--force", action="store_true", help="replace existing output files")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Run the compositor CLI."""

    arguments = build_parser().parse_args(argv)
    try:
        manifest = render_cover(
            arguments.spec,
            arguments.output,
            arguments.manifest,
            force=arguments.force,
        )
    except CompositionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": manifest["output"],
                "sha256": manifest["sha256"],
                "title": manifest["blocks"][0]["text"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
