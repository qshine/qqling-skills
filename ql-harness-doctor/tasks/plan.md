# Implementation Plan: Harness Doctor Control Catalog

> Module id: `control-catalog`
>
> Status: Implementation complete (2026-09-06); final human review pending
>
> Approved specification: [../SPEC-control-catalog.md](../SPEC-control-catalog.md)

## Overview

Implement the first Harness Doctor module as an offline, versioned `ControlCatalog` consisting of catalog/source JSON files, documented schemas and a deterministic Python validator. The work begins with the executable contract and its tests, adds cross-file invariants, then builds the production source registry and canonical controls in maturity slices. No diagnostic, recommendation, preview, application or Skill orchestration behavior is implemented in this module.

## Architecture Decisions

1. **One-version contract**: runtime consumers load one validated pair, `controls.json + sources.json`; partial loading and parallel schema versions are rejected.
2. **Boundary validation**: JSON is parsed and validated once at the validator boundary. Cross-file checks run only after the minimum shape is trustworthy.
3. **No runtime dependency**: Python 3.9+ standard library implements the validator. Schema documents provide a declarative contract but are not evaluated by a third-party package.
4. **Stable structured errors**: all validation findings use `ValidationError(code, path, message)`, deterministic sorting and the approved CLI envelope.
5. **Collect independent findings**: semantic validation reports all safely discoverable problems in one run; malformed or unreadable files use exit code 2 because deeper validation is impossible.
6. **Small fixture surface**: tests keep one minimal valid catalog pair and derive invalid variants in temporary directories. This avoids dozens of drifting fixture files.
7. **Semantic catalog slicing**: production controls are added sequentially by L1–L2, L3 and L4. The single `controls.json` file is never edited concurrently.
8. **Research traceability**: production tests extract `Lxx-Cyy` IDs from the fourteen chapter notes and compare them with canonical aliases plus explicit exclusions.
9. **L4 remains data-only**: L4 controls and activation policy are represented and validated, but no loop or graph behavior is created.
10. **No release integration yet**: `SKILL.md`, Agent metadata, repository README and CI changes belong to later modules defined in the capability map.

## Internal Design

The validator remains one executable script but is divided into small functions with explicit responsibilities:

```text
CLI arguments
    ↓
resolve catalog paths
    ↓
read + parse controls.json and sources.json
    ↓
minimum shape/type validation
    ↓
identity + ordering validation
    ↓
cross-reference + graph + lifecycle validation
    ↓
candidate provenance validation
    ↓
stable human or JSON result
```

Expected internal boundaries:

- `load_json_document(path, display_name)` handles only file and JSON boundary failures.
- `validate_controls_shape(...)` and `validate_sources_shape(...)` validate required fields and primitive/container types.
- focused helpers validate IDs, enum/policy values, ordering, references, cycles, conflicts, lifecycle and gates.
- `validate_catalog(catalog_dir)` returns a deterministically sorted sequence of findings without printing or mutation.
- `main(argv)` owns argument parsing, rendering and exit codes.

The production data dependency is:

```text
sources.json ───────────────┐
                           ├─→ controls.json source_refs
chapter notes L01–L14 ─────┘        │
                                    ├─→ source_aliases / excluded_candidates
controls.json controls ─────────────┘
```

## Dependency Graph

```text
Task 1: CLI boundary + valid fixture
    │
    ▼
Task 2: schemas + shape validation
    ├───────────────┐
    ▼               ▼
Task 3: IDs,        Task 5: production
ordering, refs      source registry
    │               │
    ▼               │
Task 4: policy,     │
graphs, lifecycle   │
    └───────┬───────┘
            ▼
Task 6: L1–L2 canonical controls
    │
    ▼
Task 7: L3 canonical controls
    │
    ▼
Task 8: L4 controls + complete dispositions
    │
    ▼
Task 9: production integrity + CLI hardening
```

## Task List

Tasks 1–9 are implemented and automatically verified. Evidence: [acceptance-control-catalog.md](acceptance-control-catalog.md). Human acceptance is a separate, still-open checkpoint.

The detailed checklist is maintained in [todo.md](todo.md).

### Phase 1: Executable contract

- [x] Task 1: Establish validator and CLI boundary
- [x] Task 2: Add schema documents and shape validation

### Checkpoint A: Contract boundary

- [x] Approved commands run against a minimal valid fixture.
- [x] Malformed, missing and unreadable input produce exit code 2 without traceback.
- [x] No catalog file is modified by validation.

### Phase 2: Semantic invariants

- [x] Task 3: Enforce identity, ordering and cross-reference invariants
- [x] Task 4: Enforce policy, graph, lifecycle and maturity invariants
- [x] Task 5: Build the fixed production source registry

### Checkpoint B: Initial semantic validation

- [x] Tasks 3–5 rule families have passing and failing tests; final undisposed-candidate and adversarial boundary cases were added in Task 9.
- [x] The source registry resolves all L01–L14 document IDs at the fixed commit.
- [x] Task 5 integration was reviewed after Tasks 3–4 and before Task 6.

### Phase 3: Canonical product controls

- [x] Task 6: Consolidate L1–L2 controls
- [x] Task 7: Consolidate L3 controls

### Checkpoint C: Core catalog semantic review

- [x] L1–L3 controls are deduplicated and preserve chapter provenance.
- [x] Maturity gates match the approved specification and implementation plan.
- [x] No chapter candidate is counted twice in the completed slices.

### Phase 4: Advanced controls and integration

- [x] Task 8: Consolidate L4 controls and finish candidate dispositions
- [x] Task 9: Harden production integrity and CLI behavior

### Checkpoint D: Module complete

- [x] All `CC-01` through `CC-12` success criteria pass.
- [x] Focused tests, syntax check, catalog validation and whitespace check pass.
- [x] Diff contains only approved `control-catalog` module files and documentation status updates.
- [ ] Human reviews the completed module before `repository-evidence` enters Specify.

## Vertical Slices

Although this module is data-heavy, each task produces a runnable vertical slice:

- Tasks 1–2 establish a consumer-visible command that can accept or reject a complete minimal contract.
- Tasks 3–4 add one validation rule family at a time through the same public CLI and error envelope.
- Task 5 makes source references usable against the actual book snapshot.
- Tasks 6–8 make progressively higher maturity controls loadable and valid without changing the interface.
- Task 9 proves the production data, research mapping and CLI behavior together.

No task creates an isolated schema, test suite or data file that cannot be exercised through the public validator.

## Verification Strategy

Every task follows red-green-refactor:

1. Add or refine the smallest failing `unittest` case.
2. Implement only enough validator or catalog data to satisfy that task.
3. Run the focused module test command.
4. Run the production validator once production files exist.
5. Run syntax and whitespace checks at checkpoints.

Required checkpoint commands:

```bash
python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v
python3 ql-harness-doctor/scripts/validate_catalog.py
python3 ql-harness-doctor/scripts/validate_catalog.py --json
python3 -m py_compile ql-harness-doctor/scripts/validate_catalog.py
git diff --check -- ql-harness-doctor/references/catalog ql-harness-doctor/scripts/validate_catalog.py ql-harness-doctor/tests/test_control_catalog.py
```

For read-only verification, tests capture file bytes, mtimes and relevant Git status before and after validator execution.

## Parallelization

- `control-catalog` is allowed to proceed while the separate `repository-evidence` module is still unspecified, because both are roots in the capability map. This plan does not start that other module.
- Within this module, Task 5 can be prepared after Task 2 while Tasks 3–4 are being implemented because it writes production `sources.json` rather than validator code.
- Tasks 6–8 must remain sequential because they all edit `controls.json` and perform semantic deduplication across maturity levels.
- Task 9 is sequential and begins only after all production controls and dispositions exist.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Validator reimplements too much JSON Schema | High maintenance and divergent semantics | Enforce only the documented contract and cross-file invariants; keep helpers small and directly tested |
| Shape errors cause unsafe downstream assumptions | Incorrect exceptions or misleading findings | Stop semantic checks for an invalid subtree while continuing independent safe checks |
| Error text becomes an accidental unstable API | Downstream tests or tools break | Stabilize code/path/envelope; keep prose concise and test only approved messages where necessary |
| Canonical control consolidation loses source meaning | Incorrect diagnosis later | Add controls in maturity slices, preserve exactly one primary candidate mapping and review at Checkpoint C |
| One candidate supports several concepts | Forced mapping hides nuance | Choose one primary canonical control; use ordinary source references on related controls without duplicating the alias |
| Production JSON becomes difficult to review | Semantic mistakes survive syntax checks | Canonical ordering, two-space formatting, small maturity slices and dedicated production integrity tests |
| Dependency or conflict relationships create cycles | Consumers cannot order recommendations | Validate dependency DAG and symmetric conflicts before accepting production data |
| Chapter notes change accidentally | Research evidence becomes unreliable | Treat notes as read-only inputs and include them only in before/after diff review |
| Python 3.9 compatibility regresses | Skill fails in supported repositories | Avoid newer syntax and include syntax/runtime verification under Python 3.9-compatible constructs |

## Scope Exclusions

- Repository scanning and `EvidenceBundle` generation.
- Agent semantic diagnosis and coverage calculation.
- Recommendation grouping or user selection.
- Candidate file rendering, diff preview or repository mutation.
- Autonomous loops, graph orchestration, external connectors and CI integration.
- Translation/localization infrastructure.

## Open Questions

No unresolved product questions remain for this module. Implementation details that would alter the approved contract—such as adding a dependency, changing error semantics or moving maturity gates—must return to the Spec review gate.

## Plan Approval Record

The human approved task order, checkpoints, file scope and risk treatment on 2026-09-04. Tasks 1–9 were implemented using test-driven and incremental implementation. The 2026-09-06 automated acceptance record does not replace final human review.
