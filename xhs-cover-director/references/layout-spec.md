# Deterministic layout specification

Use `scripts/compose_cover.py` after generating a text-free base. It requires Pillow and a CJK font. In the Codex desktop runtime, use the bundled Python runtime when ordinary `python3` does not provide Pillow.

The JSON file accepts either `background` or `background_color`, a strict 3:4 canvas, one required `title` block, and optional `labels`. Relative background and font paths resolve from the specification file. The default canvas is 1080 x 1440.

```json
{
  "background": "./text-free-base.png",
  "canvas": {"width": 1080, "height": 1440},
  "safe_area": {"top": 0.10, "bottom": 0.10, "left": 0.05, "right": 0.05},
  "font": "/absolute/path/to/a-cjk-font.ttc",
  "title": {
    "text": "普通照片也能很有感",
    "box": [70, 150, 940, 450],
    "lines": [
      {"text": "普通照片", "fill": "#111111", "background": "#F6F1E7", "rotation": -1.5},
      {"text": "也能很有感", "fill": "#FFFFFF", "background": "#D7A62A", "rotation": 1.0}
    ],
    "max_font_size": 144,
    "min_font_size": 72,
    "line_gap": 16,
    "padding": [30, 14],
    "align": "center",
    "paper": true
  },
  "labels": [
    {
      "text": "真实感 / 记忆点",
      "box": [650, 1000, 350, 110],
      "lines": [{"text": "真实感 / 记忆点", "fill": "#111111", "background": "#F1C84C"}],
      "max_font_size": 46,
      "min_font_size": 30,
      "padding": [18, 10]
    }
  ]
}
```

Coordinates are `[x, y, width, height]` in output pixels. Put the exact canonical copy in `text`, then plan visual line breaks through `lines`; the compositor rejects any character or punctuation mismatch between them. Each line can override `fill`, `background`, `stroke_width`, `stroke_fill`, and `rotation`. Supported alignment values are `left`, `center`, and `right`.

The safe-area defaults reserve 10% at the top and bottom and 5% at the left and right. Vertical margins may be reduced to 8%, but not below it; horizontal margins may not be below 5%. Every title and label box must fit entirely inside the resulting pixel box.

A background image must already have a strict 3:4 ratio. The compositor rejects any other ratio rather than cropping it. Extend a non-3:4 source with the preservation-first editing workflow before composition.

Run:

```bash
python3 scripts/compose_cover.py \
  --spec /path/to/layout.json \
  --output /path/to/cover.png \
  --manifest /path/to/cover.manifest.json
```

The compositor refuses invalid colors, missing fonts, out-of-bounds or unsafe boxes, text that cannot fit at the minimum size, non-3:4 backgrounds, and overwriting the source background. The manifest records the exact rendered copy, font sizes, boxes, safe-area fractions and pixels, output format, file digest, and canvas dimensions. Compare its `text` fields with the selected canonical copy before delivery.
