# Task List: Harness Doctor Control Catalog

> Module id: `control-catalog`
>
> Status: Tasks 1–9 complete (2026-09-06); automated acceptance passed, final human review pending.
>
> Plan: [plan.md](plan.md)
>
> Evidence: [acceptance-control-catalog.md](acceptance-control-catalog.md)

## Phase 1: Executable contract

## Task 1: Establish validator and CLI boundary

**Description:** Create the minimal validator, stable result type, CLI argument handling and one valid synthetic catalog pair. Start with failing tests for the approved success and boundary-failure behavior.

**Acceptance criteria:**

- [x] A minimal valid pair returns no findings and CLI exit code 0 in human and JSON modes.
- [x] Missing, unreadable or malformed JSON returns exit code 2 without a traceback or host-specific absolute path.
- [x] `validate_catalog(catalog_dir)` is read-only and returns deterministically ordered `ValidationError` values.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py --catalog-dir ql-harness-doctor/tests/fixtures/control_catalog/valid`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py --catalog-dir ql-harness-doctor/tests/fixtures/control_catalog/valid --json`

**Dependencies:** None

**Files likely touched:**

- `ql-harness-doctor/scripts/validate_catalog.py`
- `ql-harness-doctor/tests/test_control_catalog.py`
- `ql-harness-doctor/tests/fixtures/control_catalog/valid/controls.json`
- `ql-harness-doctor/tests/fixtures/control_catalog/valid/sources.json`

**Estimated scope:** Medium — 4 files

## Task 2: Add schema documents and shape validation

**Description:** Define the documented JSON shapes and make the validator reject missing fields, unknown required structures, wrong primitive/container types and unsupported schema versions.

**Acceptance criteria:**

- [x] Both schema documents are valid JSON and describe every required root and nested contract field.
- [x] Shape validation reports stable field paths and collects independent safe findings without cascading exceptions.
- [x] Unsupported schema major versions fail closed while the approved `1.0.0` fixture remains valid.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 -m py_compile ql-harness-doctor/scripts/validate_catalog.py`
- [x] `git diff --check -- ql-harness-doctor/references/catalog ql-harness-doctor/scripts/validate_catalog.py ql-harness-doctor/tests/test_control_catalog.py`

**Dependencies:** Task 1

**Files likely touched:**

- `ql-harness-doctor/references/catalog/controls.schema.json`
- `ql-harness-doctor/references/catalog/sources.schema.json`
- `ql-harness-doctor/scripts/validate_catalog.py`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Estimated scope:** Medium — 4 files

## Checkpoint A: Contract boundary

- [x] Tasks 1–2 acceptance criteria pass.
- [x] Human and JSON result envelopes match the approved Spec.
- [x] Validation has not modified any fixture or repository file.
- [x] Review findings before semantic invariants are added.

## Phase 2: Semantic invariants

## Task 3: Enforce identity, ordering and cross-reference invariants

**Description:** Add stable ID formats, uniqueness, canonical ordering and resolution checks across domains, controls, sources, documents, gates and source references.

**Acceptance criteria:**

- [x] Malformed or duplicate domain, control, source, document and candidate IDs produce their approved error families.
- [x] Unknown references and domain/control prefix mismatches are rejected with precise paths.
- [x] Non-canonical domain, control and document ordering is reported without rewriting input.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py --catalog-dir ql-harness-doctor/tests/fixtures/control_catalog/valid --json`

**Dependencies:** Task 2

**Files likely touched:**

- `ql-harness-doctor/scripts/validate_catalog.py`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Estimated scope:** Small — 2 files

## Task 4: Enforce policy, graph, lifecycle and maturity invariants

**Description:** Validate exact status/coverage semantics, maturity activation and gates, dependency cycles, symmetric conflicts, alternatives and deprecation/supersession rules.

**Acceptance criteria:**

- [x] The six statuses, unweighted coverage policy and L0–L4 activation rules accept only the approved semantics.
- [x] Direct and multi-hop dependency cycles, asymmetric conflicts and unknown alternatives are rejected.
- [x] Invalid lifecycle states, deprecated gates and broken supersession links are rejected.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 -m py_compile ql-harness-doctor/scripts/validate_catalog.py`

**Dependencies:** Task 3

**Files likely touched:**

- `ql-harness-doctor/scripts/validate_catalog.py`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Estimated scope:** Small — 2 files

## Task 5: Build the fixed production source registry

**Description:** Create the production source snapshot and fourteen lecture document entries from the approved research metadata, then prove every source identifier and immutable revision is correct.

**Acceptance criteria:**

- [x] `sources.json` defines `walkinglabs-he@77e7a3e` with the full fixed commit, accessed date and canonical project URL.
- [x] Document IDs `walkinglabs-he-L01` through `walkinglabs-he-L14` each have the correct title, page URL and source path.
- [x] The production source registry passes schema, ordering, uniqueness and immutable-revision validation.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] Dedicated source-only validation passes; full production CLI validation is deferred until Task 6 adds the matching `controls.json`.

**Dependencies:** Task 2; may proceed in parallel with Tasks 3–4

**Files likely touched:**

- `ql-harness-doctor/references/catalog/sources.json`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Estimated scope:** Small — 2 files

## Checkpoint B: Initial semantic validation

- [x] Tasks 3–5 acceptance criteria pass.
- [x] Tasks 3–5 validation families have failing tests; Task 9 completes the remaining boundary and provenance cases.
- [x] All L01–L14 source documents resolve at the fixed snapshot.
- [x] Validator complexity and source accuracy were reviewed before canonical controls are written.

## Phase 3: Canonical product controls

## Task 6: Consolidate L1–L2 controls

**Description:** Convert foundational, knowledge, instruction, bootstrap, scope, state and early verification candidates into deduplicated L1–L2 canonical controls with full evidence and remediation fields.

**Acceptance criteria:**

- [x] Every promoted L1–L2 control has a stable `HD-<DOMAIN>-NNN` ID, gate decision, complete contract fields and fixed source references.
- [x] Chapter aliases assigned in this slice appear exactly once and duplicates map to one canonical control rather than separate score items.
- [x] L1–L2 maturity gates express “discoverable/startable” and “bounded/restartable” without introducing L3 or L4 behavior.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py`
- [x] Manual semantic comparison with L01–L08 notes and implementation-plan sections 3–4

**Dependencies:** Tasks 4 and 5

**Files likely touched:**

- `ql-harness-doctor/references/catalog/controls.json`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Estimated scope:** Small by file count, medium by semantic review — 2 files

## Task 7: Consolidate L3 controls

**Description:** Add the verification, architecture, observability and clean-maintenance controls that make completion externally evidenced and repositories maintainable.

**Acceptance criteria:**

- [x] L3 controls preserve the approved distinctions between command discovery, actual evidence, cross-boundary verification and completion gates.
- [x] The catalog encodes the approved conflict resolutions for E2E applicability, existing failing baselines, evidence invalidation and safe cleanup.
- [x] L3 aliases are unique, source-backed and do not duplicate L1–L2 score items.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py`
- [x] Manual semantic comparison with L09–L12 notes and implementation-plan section 3.3

**Dependencies:** Task 6

**Files likely touched:**

- `ql-harness-doctor/references/catalog/controls.json`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Estimated scope:** Small by file count, medium by semantic review — 2 files

## Checkpoint C: Core catalog semantic review

- [x] Tasks 6–7 acceptance criteria pass.
- [x] L1–L3 gates match the approved maturity definitions.
- [x] Repeated themes listed in implementation-plan section 3.2 are counted once.
- [x] Source-to-control mappings were reviewed before adding diagnostic-only L4 controls.

## Phase 4: Advanced controls and integration

## Task 8: Consolidate L4 controls and complete candidate dispositions

**Description:** Add diagnostic-only autonomy and graph controls, then close the disposition ledger for all 74 research candidates.

**Acceptance criteria:**

- [x] L4 controls cover bounded loops, state recovery, independent verification, isolation, permissions, graph applicability, routing, anchors and review capacity.
- [x] L4 uses `explicit_autonomy`; all controls being not applicable cannot award L4, and no remediation generates autonomous systems in MVP.
- [x] Exactly 74 candidate IDs are mapped once or explicitly excluded with a concrete rationale; mapped and excluded sets do not overlap.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py`
- [x] Manual semantic comparison with L13–L14 notes and implementation-plan L4 boundaries

**Dependencies:** Task 7

**Files likely touched:**

- `ql-harness-doctor/references/catalog/controls.json`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Estimated scope:** Small by file count, medium by semantic review — 2 files

## Task 9: Harden production integrity and CLI behavior

**Description:** Add final production-catalog, deterministic-output and read-only contract tests, then close all twelve Spec success criteria.

**Acceptance criteria:**

- [x] Production tests extract all chapter candidates, resolve every provenance link and validate the complete catalog pair.
- [x] Human and JSON modes produce equivalent, deterministic findings with exact exit codes and no traceback, secret or host path leakage.
- [x] Before/after hashes, mtimes and Git status prove validation is offline and read-only.

**Verification:**

- [x] `python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py`
- [x] `python3 ql-harness-doctor/scripts/validate_catalog.py --json`
- [x] `python3 -m py_compile ql-harness-doctor/scripts/validate_catalog.py`
- [x] `git diff --check -- ql-harness-doctor/references/catalog ql-harness-doctor/scripts/validate_catalog.py ql-harness-doctor/tests/test_control_catalog.py`

**Dependencies:** Task 8

**Files likely touched:**

- `ql-harness-doctor/scripts/validate_catalog.py`
- `ql-harness-doctor/tests/test_control_catalog.py`

**Actual scope:** Validator, existing catalog tests, new `test_catalog_hardening.py`, canonical catalog cleanup and acceptance documentation. Safety regressions motivated the extra test file; no downstream behavior was added.

## Checkpoint D: Module complete

- [x] Tasks 8–9 acceptance criteria pass.
- [x] Spec criteria `CC-01` through `CC-12` have recorded evidence.
- [x] Production catalog and tests pass from the repository root.
- [x] Git diff contains only this module's approved files and documentation status changes.
- [ ] Human reviews the completed module before work advances to `repository-evidence`.
