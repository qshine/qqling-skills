---
name: schedule-night-shifts
description: Generate, confirm, and minimally repair auditable monthly night-shift schedules for hospital departments. Use when a scheduler provides staff, a month, leave or no-night restrictions, preferences, and optionally a previously confirmed workbook, and needs an Excel schedule that accounts for Chinese weekends, official holidays, and recent-month fairness. Do not use for daytime or multi-shift staffing.
---

# 科室夜班排班

Turn natural-language scheduling requests into a normalized JSON request, then use the bundled deterministic script. Never assign shifts by freehand reasoning.

## Workflow

1. Collect the target year/month, staff names, leave ranges, month-wide no-night staff, and any individual rules. Accept a previously confirmed workbook when cross-month fairness is needed.
2. Classify language before running the script:
   - Treat 请假、不能、不值、必须、最多、至少 as hard constraints.
   - Treat 希望、尽量、最好、优先 as soft preferences.
   - Ask only when a name, date, or rule strength is genuinely ambiguous.
3. Restate the normalized rules to the user. Do not include staff names in any web request.
4. Obtain the target year's holiday calendar:
   - Search only for the State Council annual holiday notice on a `gov.cn` host. In environments with `agent-reach`, use its web/search route.
   - Extract every official holiday date and adjusted working weekend date, plus the source title, URL, and publication date.
   - Reuse a verified same-year calendar embedded in a confirmed history workbook when available.
   - If no official notice exists or it cannot be verified, stop and ask the user for confirmed holiday and adjusted-workday dates. Never silently infer them.
5. Read [references/request-schema.md](references/request-schema.md), create the request JSON in a temporary directory, and locate the bundled Python runtime containing `openpyxl` through the workspace dependency loader.
6. Run one mode:
   - `generate`: create a pending workbook with up to three distinct candidates.
   - `finalize`: after the user selects a candidate, create a confirmed workbook and append only that schedule to history.
   - `repair`: add late constraints to a confirmed workbook and create a new revision with as few changed dates as possible.
7. Report the output workbook and any unmet soft preferences. If the script reports infeasibility, show its conflict diagnosis; never relax a hard constraint without explicit user direction.

## Commands

```bash
python scripts/schedule_night_shifts.py generate \
  --request /tmp/night-shift-request.json \
  --output /absolute/path/candidates.xlsx \
  [--history /absolute/path/previous-confirmed.xlsx]

python scripts/schedule_night_shifts.py finalize \
  --workbook /absolute/path/candidates.xlsx \
  --choice recommended \
  --output /absolute/path/confirmed.xlsx

python scripts/schedule_night_shifts.py repair \
  --workbook /absolute/path/confirmed.xlsx \
  --changes /tmp/night-shift-changes.json \
  --output /absolute/path/revised.xlsx
```

Use a new output path rather than overwriting an input workbook. Candidate workbooks have status `pending` and must never be used as history.

## Invariants

- Cover every date with exactly one active staff member.
- Never schedule leave, no-night staff, or two consecutive nights for the same person, including across month boundaries.
- Preserve all hard constraints. Preferences may be missed only when needed for feasibility or fairness, and missed preferences must be disclosed.
- Color every calendar Saturday/Sunday and official holiday yellow. An adjusted working weekend stays yellow visually but scores as an ordinary workday. A person's gray leave cell overrides yellow.
- Treat this as an administrative staffing aid, not autonomous clinical decision-making. Require the scheduler to confirm a candidate before history is updated.
