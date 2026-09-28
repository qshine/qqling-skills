#!/usr/bin/env python3
"""Validate this Skill's required structure without third-party dependencies."""

from __future__ import annotations

from pathlib import Path
import re
import sys


def validate(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_dir = skill_dir.resolve()
    skill_md = skill_dir / "SKILL.md"
    agent_yaml = skill_dir / "agents" / "openai.yaml"
    if not skill_md.is_file():
        return ["SKILL.md is missing"]
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---(?:\n|\Z)", text, re.DOTALL)
    if match is None:
        return ["SKILL.md must start with closed YAML frontmatter"]
    fields = {}
    for line in match.group("frontmatter").splitlines():
        if not line.strip() or line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    if fields.get("name") != skill_dir.name:
        errors.append("frontmatter name must match the Skill directory")
    if not fields.get("description"):
        errors.append("frontmatter description is required")
    unexpected = sorted(set(fields) - {"name", "description"})
    if unexpected:
        errors.append("unexpected frontmatter fields: " + ", ".join(unexpected))
    if "TODO" in text:
        errors.append("SKILL.md contains TODO text")
    if not agent_yaml.is_file():
        errors.append("agents/openai.yaml is missing")
    else:
        interface = agent_yaml.read_text(encoding="utf-8")
        if f"${skill_dir.name}" not in interface:
            errors.append("default_prompt must explicitly mention the Skill")
        for key in ("display_name:", "short_description:", "default_prompt:"):
            if key not in interface:
                errors.append(f"agents/openai.yaml is missing {key[:-1]}")
    return errors


def main(argv: list[str] | None = None) -> int:
    arguments = argv or sys.argv[1:]
    skill_dir = Path(arguments[0]) if arguments else Path(__file__).resolve().parents[1]
    errors = validate(skill_dir)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"valid: {skill_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
