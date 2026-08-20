---
name: skill-usage-auditor
description: Audit verifiable Codex Skill loads, compare usage over a time window, visualize rankings and trends, and prepare safe low-use or overlapping-Skill reviews. Use when users ask which Skills they actually use, which have no observed loads, which overlap, or which they might quarantine or remove.
---

# Skill Usage Auditor

Count actual, verifiable Skill loads rather than textual mentions. Use the evidence to support human review; never treat it as automatic removal authority.

## Quick reference

| Command | Purpose |
| --- | --- |
| `sync` | Import verifiable Skill-load events from current and archived sessions. |
| `stats` | Synchronize and show ranked rolling-window counts, trends, and advice. |
| `audit` | Synchronize and freeze low-use candidates with coverage-aware advice. |
| `record NAME` | Store a separately labeled manual record; exclude it from exact stats by default. |
| `remove REPORT IDS --confirmation TEXT` | Quarantine an exactly confirmed selection. |
| `restore REPORT ID` | Restore one quarantined Skill. |
| `automation-prompt` | Print the audit-only weekly prompt. |

Place global options before the command. Use `--skill-root`, `--session-root`, and `--state` for non-default locations.

```bash
python3 scripts/skill_usage_auditor.py stats --window-days 7
python3 scripts/skill_usage_auditor.py stats --window-days 30
python3 scripts/skill_usage_auditor.py stats --window-days 90
python3 scripts/skill_usage_auditor.py audit --window-days 30 --max-uses 1
```

Use `stats --include-manual` only when the user explicitly wants manual records mixed into the report. Do not pass `--now` to `audit`, `remove`, or `restore`; freshness checks use real UTC time.

## Evidence contract

Count each distinct, verifiable load. Accept only:

- a complete runtime-injected `<skill>` payload whose name and path match an installed Skill;
- a supported direct or shell read of the exact installed `SKILL.md`;
- a structured Skill-read event that identifies an exact path or an unambiguous installed name.

Exclude ordinary names, `$skill-name` mentions, catalog listings, recommendations, descriptions, search results, and selector counts. When retained logs cannot prove a load, do not infer one.

Report zero as “no observed loads in this window.” Always show coverage status, scanned roots, supported records, warnings, and the coverage notice.

## Advice labels

- **keep**: protected or repeatedly loaded.
- **observe**: loaded once, or zero loads with partial coverage.
- **merge_check**: low-use Skills with strongly overlapping descriptions.
- **consider_remove**: zero observed loads only when scanned coverage is complete.

If no supported session records exist, refuse to rank removal candidates.

## Safe removal

Never select `.system`, plugin-managed, or auditor-owned Skills. Keep discovery, review, confirmation, quarantine, and restore separate.

After the user selects sorted candidate IDs, require this exact second confirmation:

```text
CONFIRM SKILL REMOVAL <report-id> <candidate-id-1> <candidate-id-2> ...
```

Reject silence, approximate confirmation, expired reports, changed fingerprints, duplicate IDs, or changed paths. Quarantine instead of deleting; restore without overwriting an occupied original path.

## Weekly audit

When requested, create exactly one local weekly automation, defaulting to Monday at 09:00 in the user's timezone. Use the exact output of `automation-prompt`. Schedule only `audit`; never schedule removal.

## Development verification

After changing parsing, storage, statistics, advice, or removal behavior, run:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skill-usage-auditor/scripts/skill_usage_auditor.py
```

For each new event parser, add a positive load case, a textual-mention negative case, and an idempotent re-sync case.
