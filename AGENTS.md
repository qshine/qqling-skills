# Repository Guidelines

## Project Structure & Module Organization

This repository contains self-contained Codex Skills. Each top-level skill directory uses a kebab-case name, such as `skill-usage-auditor/`, and includes:

- `SKILL.md` for frontmatter and operating instructions.
- `scripts/` for deterministic Python implementations and validators.
- `agents/openai.yaml` for the Skill’s display metadata and default prompt.
- `references/` for schemas or supporting guidance when needed.

Each Skill keeps its `test_*.py` regression files beside `SKILL.md`. Repository-level usage and installation instructions belong in `README.md`; CI configuration is in `.github/workflows/test.yml`.

## Build, Test, and Development Commands

There is no packaging or build step. Use Python 3.9 or newer.

```bash
python -m unittest discover -s skill-usage-auditor -p 'test_*.py' -v
python skill-usage-auditor/scripts/validate_skill.py
python -m py_compile skill-usage-auditor/scripts/*.py
```

These commands run the full test suite, validate Skill structure, and catch Python syntax errors. Run all checks before opening a pull request.

## Git Worktree Workflow

If a task requires modifying code, automatically create and switch to a dedicated Git worktree before making any code changes. Do not edit code directly in the primary working tree. The worktree must use a new branch whose name starts with `codex-xxxx`, for example `codex-xxxx-fix-parser`.

## Coding Style & Naming Conventions

Follow standard Python conventions: four-space indentation, `snake_case` functions and variables, `PascalCase` classes, and explicit imports. Keep type hints on public helpers and use `pathlib.Path` for filesystem work. Prefer deterministic logic and clear validation errors over implicit fallback behavior. Name tests `test_<behavior>` and skill directories in kebab-case. Keep `SKILL.md` frontmatter limited to `name` and `description`; `name` must match its directory.

## Testing Guidelines

Tests use the standard-library `unittest` framework. Add focused regression tests for every behavior change, including failure and safety cases. No numeric coverage threshold is enforced, but changes to parsers, persistence, statistics, or removal behavior should exercise both positive and negative paths.

## Commit & Pull Request Guidelines

Recent history uses short Conventional Commit-style subjects, for example `feat: add precise skill usage auditor` and `docs: update skill installation command`. Use an imperative, scoped summary such as `test: cover direct Skill reads`. Pull requests should explain the user-visible change, list validation commands run, and link relevant issues.

## Security & Generated Files

Do not commit session logs, credentials, temporary JSON, or local state databases. Use temporary directories in tests and keep destructive Skill operations behind explicit confirmation.
