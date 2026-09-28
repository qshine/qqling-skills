# Capability Map: Harness Doctor

> 状态：Phase 0 已批准（2026-09-04）。

## 范围假设

- MVP 完整覆盖 L0–L3；L4 只诊断，不生成自治循环、自动化或图编排。
- 一次只处理当前单一仓库；诊断不读取外部 CI、Issue、日志或云平台。
- Python 3.9+ 标准库负责确定性只读取证，Agent 负责语义判断。
- 只读诊断默认不落盘；仓库写入只发生在统一预览和最终确认之后。
- CI 修改、新测试框架、依赖安装和外部副作用不属于默认补强范围。

## 模块

| Module id | Responsibility and owned interface | Depends on |
| --- | --- | --- |
| `control-catalog` | 定义稳定控制项、来源版本、适用性、六种状态、L0–L4 门槛和覆盖率；拥有 `ControlCatalog` 契约 | — |
| `repository-evidence` | 安全扫描一个仓库并生成不含语义结论的结构化证据；拥有 `EvidenceBundle` 契约 | — |
| `diagnostic-assessment` | 将控制目录与仓库证据映射为适用性、状态、成熟度、覆盖率及可追溯理由；拥有 `DiagnosticReport` 契约 | `control-catalog`, `repository-evidence` |
| `recommendation-selection` | 对诊断缺口去重分组、展示依赖和风险，并记录用户选择；拥有 `SelectionManifest` 契约 | `control-catalog`, `diagnostic-assessment` |
| `change-preview` | 在仓库外生成候选内容、完整 unified diff、验证命令和原文件哈希；拥有 `PreviewManifest` 契约 | `repository-evidence`, `recommendation-selection` |
| `confirmed-application` | 校验最终确认与目标漂移，只应用已预览改动，运行已授权验证并报告结果；拥有 `ApplicationResult` 契约 | `repository-evidence`, `change-preview` |
| `skill-orchestration` | 提供 `SKILL.md` 与 Agent 元数据，串联只读诊断、选择、预览、确认、修改和复验；拥有用户可见交互协议及最终端到端验收 | `control-catalog`, `repository-evidence`, `diagnostic-assessment`, `recommendation-selection`, `change-preview`, `confirmed-application` |

## 依赖方向与构建顺序

```text
control-catalog ───────┐
                      ├─→ diagnostic-assessment
repository-evidence ──┘          │
                                 ▼
                    recommendation-selection
                                 │
                                 ▼
                         change-preview
                                 │
                                 ▼
                    confirmed-application
                                 │
                                 ▼
                      skill-orchestration
```

构建顺序：`control-catalog` 与 `repository-evidence` 可并行 → `diagnostic-assessment` → `recommendation-selection` → `change-preview` → `confirmed-application` → `skill-orchestration`。

## 跨模块规则

- 接口由提供方模块的 Spec 定义；消费方只能依赖已批准的契约。
- 依赖保持单向，不允许下游模块反向修改上游语义。
- 测试、fixture、安全用例和文档归属各自模块；`skill-orchestration` 负责最终跨模块行为测试、README 和 CI 接入。
- Spec 命名固定为 `SPEC-<module-id>.md`。2026-09-06 用户要求直接完成全部实现，后续实施采用 [统一 MVP 计划](tasks/mvp-plan.md)，不再逐模块暂停审批；接口边界和运行时用户确认要求不变。

## Phase 0 审阅记录

- 模块可以分别验收，并且删掉任一可选下游模块不会迫使上游 Spec 重写。
- 所有依赖均为单向且无循环。
- 控制目录、证据、诊断、选择、预览、执行和交互编排的责任没有重叠。
- 用户已于 2026-09-04 确认模块 ID、边界、依赖方向和构建顺序；`control-catalog` 已进入模块级门控流程。

## 当前交付状态（2026-09-06）

| 模块 | 详细 Spec / Plan | 实现与验收 |
| --- | --- | --- |
| `control-catalog` | [Spec](SPEC-control-catalog.md)、原 tasks/plan.md | 已实现；46 控制、74 来源别名、14 章；73 项目录回归 |
| `repository-evidence` | [Spec](SPEC-repository-evidence.md)、MVP 任务 1 | 已实现；有界静态扫描、Schema、隐私/链接/资源边界 |
| `diagnostic-assessment` | [Spec](SPEC-diagnostic-assessment.md)、MVP 任务 2 | 已实现；Agent 判断校验、六状态、覆盖率、累积门槛 |
| `recommendation-selection` | [Spec](SPEC-recommendation-selection.md)、MVP 任务 3 | 已实现；分组建议、显式选择、依赖/冲突、L4 边界 |
| `change-preview` | [Spec](SPEC-change-preview.md)、MVP 任务 4 | 已实现；完整 diff、静态检查、根/Git/文件基线 |
| `confirmed-application` | [Spec](SPEC-confirmed-application.md)、MVP 任务 5 | 已实现；最终确认、新建/追加、漂移阻断、部分失败报告 |
| `skill-orchestration` | [Spec](SPEC-skill-orchestration.md)、MVP 任务 6–7 | 已实现；SKILL、元数据、统一 CLI、端到端、README/CI |

当前可通过 [SKILL.md](SKILL.md) 本地调用。完整验证与限制见 [MVP 交付记录](tasks/acceptance-mvp.md)；原 [control-catalog 验收记录](tasks/acceptance-control-catalog.md) 保留历史，不伪造人工审阅。未执行全局安装、推送、合并或远端 CI。
