# Series layout and delivery specification

Read this reference after the page copy, text-free 9:16 bases, and individual layout specifications are ready.

## Series JSON

Create one series file whose paths resolve relative to that file:

```json
{
  "caption": "我把让人头大的夜班表交给了一个 Skill……\n\n#Codex #排班自动化 #医生夜班",
  "pages": [
    {"id": "01-cover", "role": "cover", "layout": "./01-cover.layout.json"},
    {"id": "02-problem", "role": "content", "layout": "./02-problem.layout.json"},
    {"id": "03-solution", "role": "content", "layout": "./03-solution.layout.json"},
    {"id": "04-proof", "role": "content", "layout": "./04-proof.layout.json"},
    {"id": "05-ending", "role": "content", "layout": "./05-ending.layout.json"}
  ]
}
```

Rules:

- `caption` is required, non-empty, and at most 300 Unicode characters after trimming.
- `pages` contains one to five items in delivery order.
- Every `id` is unique, uses lowercase letters, digits, and hyphens, and starts with its two-digit page number (`01-` through `05-`).
- The first page has role `cover`; every later page has role `content`.
- Every layout path is unique and points to a valid single-page specification.
- Every rendered page is 9:16, uses identical dimensions, and has unique title and complete canonical copy.

## Render transactionally

Run:

```bash
python3 scripts/compose_series.py \
  --spec /path/to/series.json \
  --output-dir /path/to/final-series
```

The script renders into a sibling staging directory, validates the entire set, and publishes only after every page passes. It refuses existing target files unless `--force` is explicitly requested.

The output directory contains:

- one numbered PNG and exact-copy manifest per page;
- `series.manifest.json` with ordered page metadata, copy, hashes, dimensions, and caption;
- `caption.txt` containing the exact publishing caption.

Do not hand-edit a rendered page or caption after composition. Update the canonical layout or series specification and render again.
