# Request schema

The scheduling script consumes UTF-8 JSON. Dates use `YYYY-MM-DD`; weekdays use ISO values `1` (Monday) through `7` (Sunday).

## Generate request

```json
{
  "year": 2026,
  "month": 8,
  "staff": ["张三", "李四", "王五"],
  "leaves": [
    {"name": "张三", "start": "2026-08-03", "end": "2026-08-07"}
  ],
  "no_night": ["王五"],
  "hard_constraints": [
    {"type": "required", "name": "李四", "dates": ["2026-08-12"]},
    {"type": "max_shifts", "name": "李四", "value": 5}
  ],
  "soft_preferences": [
    {"type": "avoid_weekdays", "name": "李四", "weekdays": [6], "weight": 1},
    {"type": "prefer_dates", "name": "张三", "dates": ["2026-08-20"], "weight": 1}
  ],
  "holiday_calendar": {
    "year": 2026,
    "holidays": ["2026-01-01", "2026-01-02", "2026-01-03"],
    "adjusted_workdays": ["2026-01-04"],
    "source_type": "official",
    "source_title": "国务院办公厅关于2026年部分节假日安排的通知",
    "source_url": "https://www.gov.cn/...",
    "publication_date": "2025-11-04"
  }
}
```

`staff` may also contain objects such as `{"name": "张三", "active": true}`. Inactive staff remain visible in history but are not scheduled.

Supported hard constraint types:

- `required`: assign the named person on every listed date.
- `unavailable`: do not assign the named person on listed dates.
- `max_shifts`: absolute monthly maximum.
- `min_shifts`: absolute monthly minimum.

Supported soft preference types:

- `avoid_dates`, `prefer_dates`
- `avoid_weekdays`, `prefer_weekdays`
- `max_shifts`, `min_shifts`

`weight` must be a positive integer and defaults to 1. Unknown types are rejected rather than ignored.

For a user-confirmed calendar override, use `source_type: "user_override"`, set `confirmed_by_user: true`, and include the supplied holiday and adjusted-workday dates. An official calendar requires a `gov.cn` source URL.

## Repair request

A repair file adds constraints to the confirmed workbook's embedded request:

```json
{
  "leaves": [{"name": "张三", "start": "2026-08-18", "end": "2026-08-20"}],
  "no_night": [],
  "hard_constraints": [],
  "soft_preferences": []
}
```

Use `replace_request` instead when the entire normalized request must be replaced. Its year, month, and staff roster must match the confirmed workbook.

## Candidate choices

`finalize --choice` accepts `recommended`, `fairness`, `preference`, `A`, `B`, `C`, or the corresponding Chinese sheet name. Only candidates actually present in the workbook can be confirmed.
