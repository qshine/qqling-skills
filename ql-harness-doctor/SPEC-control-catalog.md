# Spec: Harness Doctor Control Catalog

2026-09-13 增补：用户直接授权任务状态流程和证据分层。目录 0.4.0、schema 1.1.0，在每项 evidence 中增加 minimum_level（declared/recorded/verified）；所有控制的证据门槛在本版明确登记，旧报告必须重评。HD-STA-001/003/005 加入及时持久化和异常核对恢复流程，沿用 46 个控制、74 个来源别名及既有成熟度门槛；来源注册表不变。详细契约见 [诊断模块](SPEC-diagnostic-assessment.md)，本轮进度见 [任务清单](tasks/task-evidence-update.md)。

> Module id: `control-catalog`
>
> Status: Implemented; automated acceptance complete (2026-09-06), final human review pending
>
> Capability map: [CAPABILITY-MAP.md](CAPABILITY-MAP.md)
>
> Research basis: [implementation-plan.md](implementation-plan.md) and L01–L14 chapter notes

## Objective

Build the versioned, machine-readable source of truth that defines what Harness Doctor evaluates. The catalog must convert the 74 chapter-level research candidates into a smaller set of stable product controls without losing provenance, and it must provide every downstream module with one unambiguous contract for:

- control identity and lifecycle;
- source snapshots and document provenance;
- applicability and evidence expectations;
- six diagnostic states;
- L0–L4 maturity gates;
- coverage calculation;
- dependencies, conflicts, alternatives and supersession.

The direct consumers are `diagnostic-assessment`, `recommendation-selection` and `skill-orchestration`. The end users are independent developers, Tech Leaders and platform engineers, but this module exposes one shared catalog rather than role-specific copies.

Success means a downstream consumer can load one current catalog version, trace every active control to fixed sources, interpret policy fields consistently, and reject malformed or internally contradictory data before diagnosis begins.

## Assumptions

2026-09-09 增补：用户明确要求每次独立修改任务新建 Worktree、完成后提交。目录升级为 0.2.0，在 HD-SCP-001 与 HD-STA-004 内增加强制子检查，保留 46 个控制、74 个书籍别名、既有门槛归属和 schema。严格要求的来源是用户，不改写为书籍或厂商观点。证据、例外与版本迁移见 [Git 工作流规则](references/git-workflow-policy.md)；变更验收见 [本轮记录](tasks/git-workflow-update.md)。下列 initial 指初版，不代表当前版本。

后续用户仅确认 R02：当前目录 0.3.0、来源注册表 0.2.0，在 HD-BST-002 下增加修改前健康基线与前后失败对照，保留 L2 门槛、46 控制和 74 别名。只登记 R02 引用的 Anthropic 文章；其他候选不生效。详见 [R02 规则](references/baseline-policy.md) 和 [验收记录](tasks/baseline-update.md)。旧目录报告需重新诊断，schema 和 Python 接口不变。

1. The initial catalog version is `0.1.0` and the data schema version is `1.0.0`.
2. Initial user-facing titles and descriptions are Chinese; localization infrastructure is outside MVP.
3. Every `Lxx-Cyy` candidate is assigned to exactly one canonical control or explicitly excluded with a rationale.
4. L0 is the absence of sufficient lower-level gates, not a maturity assigned to individual controls; controls use L1–L4.
5. L4 controls are represented in the catalog but are diagnostic-only in MVP.
6. The runtime ships and loads one active catalog version at a time; it does not maintain parallel API versions.
7. Chapter-level provenance is required; a narrower section locator is optional when it materially improves traceability.

## User Stories

- As a diagnostic consumer, I can load controls with predictable fields and enum values without parsing prose notes.
- As a recommendation consumer, I can follow dependencies and avoid presenting duplicate chapter-derived suggestions.
- As a maintainer, I can add a new source snapshot without overwriting an existing source or reusing a control ID.
- As a reviewer, I can trace a control back to the exact source revision and the original chapter candidate IDs.
- As a CI maintainer, I can run one deterministic validator that reports every catalog problem with stable error codes.
- As a future report reader, I can still interpret historical control IDs after a control is deprecated or superseded.

## Tech Stack

- Data format: UTF-8 JSON, two-space indentation, trailing newline.
- Schemas: JSON Schema documents stored with the catalog for editor support and contract documentation.
- Validation runtime: Python 3.9+ standard library only.
- Tests: Python standard-library `unittest` and temporary directories.
- Version control: Git; source snapshots use immutable revisions whenever available.
- External services: none. Validation is offline and read-only.

No third-party JSON Schema package is required in MVP. `validate_catalog.py` implements the required invariants directly and also verifies that schema files are valid JSON. Full standards-compliant JSON Schema evaluation may be added later as an optional development dependency, but it cannot become a runtime requirement without approval.

## Commands

Run commands from the repository root.

```bash
# Validate the production catalog with human-readable output
python3 ql-harness-doctor/scripts/validate_catalog.py

# Validate with the stable machine-readable result envelope
python3 ql-harness-doctor/scripts/validate_catalog.py --json

# Validate a fixture or alternate catalog directory
python3 ql-harness-doctor/scripts/validate_catalog.py --catalog-dir ql-harness-doctor/tests/fixtures/control_catalog/valid

# Run this module's tests
python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v

# Catch Python syntax errors
python3 -m py_compile ql-harness-doctor/scripts/validate_catalog.py

# Check whitespace errors in this module's implementation files
git diff --check -- ql-harness-doctor/references/catalog ql-harness-doctor/scripts/validate_catalog.py ql-harness-doctor/tests/test_control_catalog.py
```

Build and development-server commands are not applicable: this module consists of static data, schemas and a validator.

## Project Structure

```text
ql-harness-doctor/
├── CAPABILITY-MAP.md
├── SPEC-control-catalog.md
├── references/
│   ├── catalog/
│   │   ├── controls.json
│   │   ├── controls.schema.json
│   │   ├── sources.json
│   │   └── sources.schema.json
│   └── chapters/
│       └── lecture-01.md ... lecture-14.md
├── scripts/
│   └── validate_catalog.py
└── tests/
    ├── fixtures/
    │   └── control_catalog/
    ├── test_control_catalog.py
    └── test_catalog_hardening.py
```

- `controls.json` is the current product-control and diagnostic-policy contract.
- `sources.json` is the immutable source-snapshot and document registry.
- The schema files document the accepted shapes; the Python validator enforces shape plus cross-file invariants.
- Chapter notes remain research evidence. Runtime consumers do not load all chapter notes.
- Test fixtures contain synthetic minimal catalogs and must not copy the full production catalog.

## Public Contract

### Contract files

The `ControlCatalog` interface is the validated pair:

```text
ControlCatalog = controls.json + sources.json
```

A consumer must treat either file failing validation as failure of the whole contract. It must not continue with a partial catalog.

All JSON field names use `snake_case`. Enum values use lowercase `snake_case`, except maturity values (`L0`–`L4`) and stable identifiers (`HD-VER-001`). Arrays whose order has no semantic meaning are stored in deterministic lexical order. Control order is canonical by `(domain, id)` and source-document order is canonical by `id`.

### `controls.json` root

```json
{
  "schema_version": "1.0.0",
  "catalog_version": "0.1.0",
  "domains": [],
  "diagnostic_statuses": [],
  "coverage_policy": {},
  "maturity_levels": [],
  "controls": [],
  "excluded_candidates": []
}
```

Required semantics:

- `schema_version` describes the JSON contract.
- `catalog_version` describes control content and policy content.
- `domains` declares the allowed control domains and their display order.
- `diagnostic_statuses`, `coverage_policy` and `maturity_levels` are authoritative policy data, not duplicated prose hints.
- `controls` contains active and deprecated canonical controls.
- `excluded_candidates` records research candidates intentionally not promoted to a canonical control.

### Domain entry

The initial domain IDs are fixed to:

```text
HD-FND, HD-KNW, HD-INS, HD-BST, HD-SCP, HD-STA,
HD-VER, HD-ARC, HD-OBS, HD-HYG, HD-AUT, HD-GRF
```

Each domain entry contains:

```json
{
  "id": "HD-VER",
  "title": "验证与终止",
  "description": "分层完成门槛、跨边界验证、证据及可操作失败反馈",
  "display_order": 7
}
```

Domain IDs are stable. Changing, removing or repurposing one is a breaking schema change.

### Diagnostic status entry

The catalog contains exactly these machine values:

```text
satisfied, partial, missing, conflict, unverifiable, not_applicable
```

Each entry provides a Chinese label and definition. The evaluation precedence is fixed:

```text
applicability → conflict → verifiability → satisfied/partial/missing
```

Adding or changing status semantics is a breaking policy change and requires human approval.

### Coverage policy

The root policy must encode the following behavior without weights:

```json
{
  "numerator_statuses": ["satisfied"],
  "excluded_from_denominator": ["not_applicable"],
  "zero_denominator_result": "N/A",
  "is_weighted": false
}
```

The human-readable formula remains:

```text
coverage = satisfied / (all controls - not_applicable) × 100%
```

The policy is declarative in this module; calculation belongs to `diagnostic-assessment`.

### Maturity level entry

The catalog contains L0 through L4 in order. Each level has a title, description, activation rule and `gate_control_ids`.

```json
{
  "id": "L3",
  "title": "可验证、可维护",
  "description": "分层验证和安全维护门槛均满足",
  "requires_lower_levels": true,
  "activation": "default",
  "gate_control_ids": ["HD-HYG-001", "HD-VER-001"]
}
```

Rules:

- L0 has no control IDs and represents failure to meet L1.
- L1–L3 use `activation: "default"`.
- L4 uses `activation: "explicit_autonomy"`; all L4 controls being not applicable never awards L4.
- Every gate ID must resolve to an active control at the same or lower maturity.
- A control marked `is_gate: true` must appear in at least one maturity level's gate list.

### Canonical control entry

```json
{
  "id": "HD-VER-001",
  "title": "完成定义具有可执行证据",
  "domain": "HD-VER",
  "maturity": "L2",
  "is_gate": true,
  "requirement": "任务完成条件必须指向可执行或可重复的验证证据。",
  "applicability": {
    "applies_when": ["仓库使用 Agent 执行非平凡开发任务"],
    "not_applicable_when": []
  },
  "evidence": {
    "positive": ["任务模板同时声明行为和验证方式"],
    "partial": ["存在验证命令但未进入完成门槛"],
    "conflict": ["任务模板与 CI 对完成条件定义不同"]
  },
  "remediation": {
    "summary": "为任务模板补充行为级验收和验证入口。",
    "artifact_types": ["agent_instruction", "task_template"],
    "risk": "low"
  },
  "dependencies": [],
  "conflicts_with": [],
  "alternatives": [],
  "source_refs": [
    {
      "source_id": "walkinglabs-he@77e7a3e",
      "document_id": "walkinglabs-he-L01",
      "locator": "",
      "note": "完成定义和验证缺口"
    }
  ],
  "source_aliases": ["L01-C04"],
  "lifecycle": {
    "status": "active",
    "introduced_in": "0.1.0",
    "changed_in": "0.1.0",
    "deprecated_in": null,
    "superseded_by": null
  }
}
```

Control rules:

- ID format is `HD-[A-Z]{3}-[0-9]{3}` and IDs are never reused.
- `domain` must match the ID prefix and a declared domain.
- `maturity` is one of L1–L4.
- Applicability and evidence arrays contain decision-changing guidance, not generic filler.
- Dependencies must form an acyclic graph and resolve to active controls.
- `conflicts_with` relationships must be symmetric.
- `alternatives` means either control can satisfy a higher-level intent; it does not remove either control from coverage automatically.
- Every active control has at least one valid source reference and one source alias in version `0.1.0`.
- A deprecated control remains present, has `deprecated_in`, points to an active `superseded_by` control when a replacement exists, and cannot be a maturity gate.

### Excluded research candidate

```json
{
  "id": "L04-C99",
  "rationale": "The candidate duplicates a non-actionable example and does not define a repository control.",
  "decision": "not_adopted"
}
```

An excluded ID cannot also appear in `source_aliases`. Exclusion is exceptional: it requires a concrete product rationale, not merely “duplicate,” because duplicates should normally map to the same canonical control.

### `sources.json` root

```json
{
  "schema_version": "1.0.0",
  "registry_version": "0.1.0",
  "source_snapshots": []
}
```

The initial source snapshot has the stable ID `walkinglabs-he@77e7a3e` and records:

- title and publisher;
- canonical project URL;
- revision kind `git_commit`;
- full revision `77e7a3e21469dcbece2558086c8d91657abeaa40`;
- accessed date `2026-09-04`;
- language `zh`;
- fourteen document entries, `walkinglabs-he-L01` through `walkinglabs-he-L14`.

Each document entry contains its ID, title, page URL and repository source path. Future sources without immutable revisions must use an explicit revision kind such as `published_at` or `archived_snapshot` and record enough information to reproduce the cited version. `latest` is not a valid revision.

For the adopted Anthropic web article, `source_path` records the canonical site-relative route without a leading slash, not an invented Git source file. `published_at` identifies its publication date only: it does not prove immutable content. The access date, original URL, adopted scope and this reproducibility limitation are explicit in the registry and R02 policy; no archived content or commit hash is claimed.

### Version compatibility

- Runtime consumers support exactly one schema major version and fail closed on a different major version.
- Additive optional fields may be introduced in a schema minor release.
- Removing a field, changing its type or changing enum semantics requires a schema major release.
- Adding controls, sources or non-breaking guidance increments `catalog_version` according to semantic versioning.
- Existing control and source IDs remain resolvable after deprecation.
- The validator rejects multiple simultaneously active representations of the same catalog version.

## Validation and Error Semantics

`validate_catalog.py` validates inputs at the file boundary, then performs cross-file invariants on trusted parsed objects. It is read-only and never repairs data.

CLI exit codes:

- `0`: catalog is valid;
- `1`: files were readable but one or more validation errors were found;
- `2`: invalid CLI usage, missing/unreadable input, or malformed JSON prevented validation.

Human-readable errors use one line per finding:

```text
CATALOG_DUPLICATE_ID controls.json.controls[12].id: duplicate control id
```

`--json` returns one stable envelope on stdout:

```json
{
  "ok": false,
  "errors": [
    {
      "code": "CATALOG_DUPLICATE_ID",
      "path": "controls.json.controls[12].id",
      "message": "duplicate control id"
    }
  ]
}
```

Error ordering is deterministic by `(path, code, message)`. Output contains no timestamp, absolute host path, traceback or unordered set rendering. Human and JSON modes express the same findings.

Required error families include:

- malformed or missing file;
- unsupported schema/catalog version;
- missing/unknown field or invalid enum;
- duplicate or malformed domain, control, source, document or candidate ID;
- unknown cross-reference;
- control dependency cycle;
- asymmetric conflict relation;
- invalid lifecycle transition;
- invalid maturity gate;
- candidate mapped more than once, both mapped and excluded, or left undisposed;
- missing source provenance;
- non-canonical ordering.

## Code Style

Python uses four-space indentation, `snake_case`, explicit imports, `pathlib.Path`, type hints on public helpers and deterministic return values. Validation collects all independent errors instead of stopping at the first one. It catches only expected boundary exceptions and never uses a blanket silent fallback.

Representative interface style:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ValidationError:
    code: str
    path: str
    message: str


def validate_catalog(catalog_dir: Path) -> Sequence[ValidationError]:
    """Return deterministic validation findings without modifying catalog files."""
    ...
```

JSON uses two-space indentation and a trailing newline. IDs and enum values remain English machine tokens; user-facing text is Chinese. The validator does not depend on JSON object key order, but committed files use the schema's documented field order for reviewability.

## Testing Strategy

Tests use `unittest` and temporary directories. They invoke both public Python helpers and the CLI boundary.

### Unit tests

- Accept a minimal valid catalog and source registry.
- Reject every malformed ID and unsupported enum.
- Reject duplicate domains, controls, sources, documents and candidate dispositions.
- Reject missing and unknown cross-references.
- Detect direct and multi-hop dependency cycles.
- Detect asymmetric conflicts and invalid lifecycle/supersession states.
- Enforce exact six-status and coverage-policy semantics.
- Enforce L0–L4 ordering, lower-level requirements and explicit L4 activation.
- Enforce canonical ordering without mutating files.
- Produce deterministic findings regardless of input dictionary construction order.

### Production-catalog tests

- Validate the committed production catalog successfully.
- Extract all `Lxx-Cyy` IDs from the fourteen chapter notes and prove each appears exactly once across `source_aliases` and `excluded_candidates`.
- Prove all L01–L14 documents refer to the fixed source snapshot.
- Prove every active control has provenance and every source reference resolves.
- Prove all control IDs and source IDs remain unique.

### CLI contract tests

- Verify exit codes 0, 1 and 2.
- Verify human and JSON modes contain equivalent findings.
- Verify errors contain no absolute path or traceback.
- Verify validation does not change file contents, mtimes or repository status.

No numeric line-coverage threshold is introduced. Every validation rule must have at least one passing test and one failing test, including safety and lifecycle cases.

## Boundaries

### Always do

- Validate all catalog input at the file boundary before use.
- Preserve stable IDs and immutable source revisions.
- Keep source claims distinct from Harness Doctor product decisions.
- Map or explicitly exclude every chapter candidate.
- Record conflicts and supersession explicitly.
- Emit deterministic, actionable validation errors.
- Keep the module offline, read-only and Python 3.9+ compatible.

### Ask first

- Change six-state semantics, maturity gates or the coverage formula.
- Rename, repurpose, deprecate or split a published control or domain.
- Add a source family whose version cannot be made reproducible.
- Add a runtime dependency or require a full JSON Schema implementation.
- Introduce localization structure or change initial user-facing language.
- Move a control between maturity levels after publication.

### Never do

- Reuse a stable control, domain, source or document ID for a different meaning.
- Fetch network content during catalog validation.
- Treat a moving `latest` URL as a reproducible source revision.
- Silently overwrite conflicting sources or product decisions.
- Count duplicate source aliases as separate controls.
- load all fourteen research notes into every runtime diagnosis.
- Modify chapter notes, target repositories or external systems from the validator.
- Include credentials, local absolute paths or private source content in catalog data or errors.

## Success Criteria

Automated evidence for every criterion is recorded in [tasks/acceptance-control-catalog.md](tasks/acceptance-control-catalog.md). These checks certify this module, not the six downstream capabilities or a callable Skill.

- [x] `CC-01` The four catalog files exist, parse as UTF-8 JSON and conform to the documented contract.
- [x] `CC-02` `controls.json` declares exactly the six approved statuses, unweighted coverage policy and L0–L4 maturity semantics.
- [x] `CC-03` The twelve initial domains use stable IDs and deterministic ordering.
- [x] `CC-04` Every canonical control has a valid ID, domain, maturity, applicability, evidence, remediation, lifecycle and fixed provenance.
- [x] `CC-05` All 74 research candidate IDs are mapped exactly once or explicitly excluded with a non-empty rationale; none are duplicated or undisposed.
- [x] `CC-06` The initial source registry contains all fourteen lecture documents at commit `77e7a3e21469dcbece2558086c8d91657abeaa40` and no moving revision.
- [x] `CC-07` Dependencies are acyclic, conflicts are symmetric, references resolve and deprecated controls cannot remain maturity gates.
- [x] `CC-08` The validator exits with 0 for the production catalog, 1 for validation findings and 2 for usage/read/parse failures.
- [x] `CC-09` Human and JSON errors are deterministic, actionable and free of host-specific paths, tracebacks and sensitive content.
- [x] `CC-10` Module tests cover every validation rule with passing and failing cases and pass under Python 3.9+.
- [x] `CC-11` Validation is offline and read-only; before/after content hashes and repository status are unchanged.
- [x] `CC-12` A downstream consumer can load one validated `ControlCatalog` pair without consulting chapter notes or guessing policy semantics.

## Resolved Decisions

The human approved the Spec and its recommended defaults on 2026-09-04:

1. Initial catalog strings are Chinese-only; localization infrastructure is deferred.
2. Source references require chapter-level provenance; `locator` remains optional.
3. Applicable optional controls share the overall coverage denominator; maturity gates are reported separately.
4. Repository commands use the available `python3` executable; compatibility remains Python 3.9+.

## Approval Record

The objective, `ControlCatalog` file contract, version/error semantics, boundaries and success criteria are approved for Phase 2 planning. The plan was subsequently approved on 2026-09-04 and implemented. Final module review remains open; no human approval of the completed code is implied.

## Boundary clarifications established by acceptance tests

- JSON rejects duplicate keys and non-standard numeric constants. Non-UTF-8, non-regular files and malformed schema documents fail with exit code 2.
- Version values use numeric `MAJOR.MINOR.PATCH` without leading zeros. Lifecycle dates are version values ordered within the catalog version.
- Git revisions are full 40- or 64-character hexadecimal identities. `published_at` uses an ISO calendar date; `archived_snapshot` accepts `sha256:<64 lowercase hex>` or a timestamped `https://web.archive.org/web/<14 digits>/...` URL. This validates recorded identity, not availability or authenticity of external content.
- Source URLs are HTTP(S) without embedded credentials; source paths are relative POSIX paths. Access dates must be valid ISO dates.
- Errors identify known fields and array indices but never interpolate untrusted values. Unknown field names are represented as `<unknown[n]>`; CLI usage errors use `CATALOG_USAGE_INVALID`.
- Relation, alias, gate, source-reference and artifact-type arrays are unique and lexically ordered. Guidance arrays may retain explanatory order.
- The pinned book inventory is checked offline for complete dispositions and matching chapter references; schema shape parity is regression-tested without implementing all JSON Schema semantics.
- Runtime inventory and `Lxx-Cyy` aliases currently describe this book. Adopting a new candidate-ID namespace requires an explicit contract update and tests; it must not silently bypass provenance checks.
