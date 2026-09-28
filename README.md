# qqling-skills

[English](README.md) | [简体中文](README.zh-CN.md)

A collection of self-contained Agent Skills for Codex, Claude Code, and other agents that support the Skills format, covering repository diagnostics, Skill usage analysis, and shift scheduling.

Each Skill includes a `SKILL.md` entry point and its own scripts and references. Available capabilities depend on the tools and data accessible to the host agent; `ql-skill-usage-auditor` currently analyzes Codex session logs.

## Skills

| Name | Description |
| --- | --- |
| [ql-harness-doctor](ql-harness-doctor/SKILL.md) | Audits a single Git repository against 46 Harness controls consolidated from 14 research chapters. Reports six diagnostic states, control coverage, L0–L4 maturity, and grouped recommendations. Checks task status transitions and recovery after interruptions, and distinguishes declared rules, execution records, and verified results. Runs only when explicitly invoked by name. |
| [ql-skill-usage-auditor](ql-skill-usage-auditor/SKILL.md) | Counts actual Codex Skill loads and provides rankings by period, trend visualizations, coverage status, and safe cleanup recommendations. Skill names or `$skill-name` mentions in ordinary text do not count as usage. |
| [ql-schedule-night-shifts](ql-schedule-night-shifts/SKILL.md) | Creates departmental night-shift schedules in Excel from staff availability, the target month, leave, and individual requirements. Supports Chinese public holidays, a fairness ledger across months, candidate schedule approval, and minimal-change repairs after unexpected leave. |

## Installation

Install the Skill for your agent, such as Codex or Claude Code. Replace `<skill-name>` with one of the `ql-` Skill names listed above:

```bash
npx skills add qshine/qqling-skills --skill <skill-name>
```
