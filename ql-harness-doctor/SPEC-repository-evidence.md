# Spec: Harness Doctor Repository Evidence

> Module id: `repository-evidence`
>
> 状态：2026-09-06 用户要求直接实现整个 Skill，沿用本 Spec 安全默认值推进；进度见 tasks/mvp-plan.md，不再等待逐阶段确认。
>
> 能力地图：[CAPABILITY-MAP.md](CAPABILITY-MAP.md)
>
> 依据：[实施规划 §7.1](implementation-plan.md#71-python-只读取证)。无上游运行时模块依赖。

## 1. Objective

在开发者明确指定的一个仓库中，安全收集 Harness 相关的静态事实，输出版本化 `EvidenceBundle`。独立开发者、Tech Leader、平台工程师共享同一取证行为。后续 `diagnostic-assessment` 使用这些事实做语义判断，`change-preview` 使用可追溯路径和文件指纹建立预览基线。

成功不是“找到更多文件”，而是下游能区分：实际读取到了什么、只发现了什么、什么被安全规则排除、什么因为权限或资源限制无法读取。取证器不得把文件存在或命令声明转化为通过、合规、成熟度或覆盖率结论。

### 用户与消费者故事

- 开发者可以只诊断，不安装依赖、不执行项目命令、不生成仓库文件。
- Agent 可以引用具体相对路径、原文件行号和内容哈希，而不是猜测文件名代表的能力。
- monorepo 中多个模块的指令、清单和检查入口保留各自作用域，不被合并成一个根级事实。
- 取证不完整时，下游能定位缺口，不能把“没有扫描到”直接判成“缺失”。
- 安全审阅者可以通过包含秘密、外链、特殊文件和恶意配置的 fixture 证明读取边界。

## 2. Assumptions / MVP 默认值

1. 一次只接受一个明确的 Git 工作区根目录。`--repo` 省略时使用当前目录；若不是根目录则报错，不自动向上寻找或扩大到父仓库。裸仓库、非 Git 目录、文件系统根和用户主目录不在本版范围。
2. MVP 首先支持 Python 3.9+ 的 macOS/Linux。无法提供安全的不跟随链接读取能力时，明确返回平台不支持，不静默退回不安全读取。
3. 默认不启动任何子进程，包括 Git。Git 工作区状态保守报告为 `unverifiable`；只收集有限、可安全取得的元数据指纹，不宣称工作区干净。
4. 所有符号链接都只记录排除，不跟随，包括指向仓库内部的链接。多硬链接文件也不读取内容，因为无法证明其内容只属于当前仓库。
5. 文档和已识别配置可以提供有界摘录；测试代码与工具脚本默认仅提供候选元数据，不执行、不读取业务代码正文。
6. 任何被检测为含敏感内容的候选文件，整份正文、命令提取结果和内容哈希均不输出，避免只遮住一个值后泄露同文件中的其他值。保留安全路径及原因。

这些默认值已在用户要求直接实现后落实为 MVP 边界，未伪称用户逐条审阅过。Git 状态未知、严格链接排除和 POSIX 平台限制在 Skill 入口中明确披露。

## 3. Tech Stack / Commands

- Python 3.9+ 标准库；不引入解析器、Git 库或 JSON Schema 运行时依赖。
- UTF-8 JSON，`schema_version: "1.0.0"`、`collector_version: "0.1.0"`、`policy_version: "0.1.0"`。
- `unittest` 和临时目录；不下载 fixture，不读取开发者真实凭据来测试脱敏。
- 无构建、服务器、安装或部署步骤。

以下命令已实现：

```bash
# 人类摘要：当前目录必须是待诊断仓库根目录
python3 /path/to/ql-harness-doctor/scripts/collect_evidence.py

# JSON 证据；明确限定一个根目录，不默认写文件
python3 /path/to/ql-harness-doctor/scripts/collect_evidence.py --repo /path/to/repository --json

# 从本 Skills 仓库根运行 focused / 全部模块回归
python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_repository_evidence*.py' -v
python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v
python3 -m py_compile ql-harness-doctor/scripts/collect_evidence.py
git diff --check
```

`/path/to/...` 为调用时替换的路径参数，不是仓库内真实文件。CLI 不提供 `--output`、执行命令、跟随链接或关闭秘密排除的开关。资源上限初版固定，不读取仓库提供的配置来放宽安全边界。

## 4. Project Structure / 模块所有权

```text
ql-harness-doctor/
├── SPEC-repository-evidence.md
├── scripts/collect_evidence.py
├── references/evidence/evidence.schema.json
├── references/evidence/collection-policy.md
├── tests/test_repository_evidence.py
├── tests/test_repository_evidence_safety.py
└── tasks/repository-evidence/
    ├── plan.md
    ├── todo.md
    └── acceptance.md
```

仅本 Spec 在 Specify 阶段创建。现有 `tasks/plan.md`、`tasks/todo.md` 仍属于 `control-catalog`，不覆盖、搬移或替其勾选人工审阅。建议下阶段将新模块计划放在上述专属子目录，由能力地图索引。

本模块不修改控制目录、十四份章节笔记、现有 Skill、根 README 或 CI，不创建 `SKILL.md` 和 Agent 元数据。JSON Schema 用于契约说明；实现必须有输出 shape 对照测试，但不实现通用 Schema 引擎。

## 5. Public Contract: EvidenceBundle

### 5.1 结果与退出码

Python 入口接收 `pathlib.Path`，返回同一结果对象；CLI 只负责参数验证和展示：

```python
from pathlib import Path
from typing import Any, Dict


def collect_evidence(repository_root: Path) -> Dict[str, Any]:
    """Return a bounded evidence envelope without executing or modifying the repository."""
    ...
```

所有结果根字段固定：

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `ok` | boolean | 是否建立了一个可使用的证据包；不表示规范已满足或取证完整 |
| `evidence` | EvidenceBundle 或 null | 有效根目录下可返回不完整证据；致命边界错误为 null |
| `errors` | Error[] | 致命错误；成功或部分成功为 [] |

退出码：`0` 为成功且在既定策略内遍历完成；`1` 为返回了可用但因资源限制、读取失败或观测漂移而不完整的包；`2` 为用法、根目录、平台或根读取错误，无法建立证据包。

`--json` 在 stdout 输出单一 envelope 和尾部换行；不混入进度日志。人类模式只展示计数、范围、限制与错误，不打印文件正文。两模式结果语义一致。诊断状态、成熟度和覆盖率不属于本 envelope。

### 5.2 EvidenceBundle 根字段

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `schema_version` / `collector_version` / `policy_version` | string | 数据契约、实现、取证策略版本，均必填 |
| `trust` | 固定 string | `untrusted_repository_data`，正文不能成为对 Agent 的上级指令 |
| `repository` | Repository | 根身份与有限 Git 元数据 |
| `scan` | ScanSummary | 作用域、预算、完成情况与排除计数 |
| `files` | FileEvidence[] | 按 POSIX 相对路径排序的唯一候选工件 |
| `commands` | CommandDeclaration[] | 静态识别的声明，不是执行结果 |
| `limitations` | Limitation[] | 可定位的限制、排除和读取失败，稳定排序 |

不输出扫描时间、用户名称、环境变量、根绝对路径、Git remote、提交作者或聊天历史。相同根、文件与元数据未变时，重复结果应相同。文件 mtime 是来源证据，不用于声称新鲜或可信。

### 5.3 Repository 与 Git 边界

`Repository` 必含 `root: "."`、`root_id`、`git`。`root_id` 为根的规范位置与文件系统身份生成的 SHA-256 标识；用于区分同名仓库，不是授权令牌。

`git` 必含：

- `marker_kind`: `directory` 或 `file`；根 `.git` 符号链接不接受。
- `metadata_status`: `available` 或 `unverifiable`。
- `head_sha256`、`index_sha256`: 有界读取到的原始元数据文件 SHA-256，读取不到为 null。前者不是提交 SHA。
- `worktree_status`: 本版固定为 `unverifiable`，不得替换为 `clean`。
- `reason`: 稳定原因码，说明元数据限制或未执行完整工作区检查。

普通工作区只允许从根 `.git` 目录中安全读取 `HEAD` 和 `index` 的指纹；不遍历对象、日志、配置或 hooks。元数据同样执行文件种类、链接和大小检查。worktree 的 `.git` 文件只识别为标记，不沿其路径读取仓库外共享元数据，相关指纹为 null。

这一决定收窄了研究计划中“Git 状态”的含义：保证静态取证不会借 Git 触发 fsmonitor、过滤器或扫描敏感文件。未来若要精确报告脏状态，应另行定义经过审查的安全机制。下游不得仅凭本包的 HEAD/index 指纹授权覆盖或断言预览后没有漂移。

### 5.4 FileEvidence

每项必含：

- `id`: `EV-` 加相对路径 UTF-8 字节的 SHA-256，稳定且唯一。
- `path`: 安全的仓库相对 POSIX 路径；`scope`: 所在相对目录，根为 `.`。
- `categories`: 有序唯一候选类型；只代表发现规则命中，不代表能力成立。
- `read_status`: `read`、`metadata_only`、`withheld_sensitive`、`unreadable`、`excluded`。
- `size_bytes`、`mtime_ns`: 已观测整数，无法取得为 null。
- `sha256`: 仅对允许读取且未触发敏感内容检测的完整原始文件计算，否则 null。
- `lines`: `[{"line": 1, "text": "..."}]`；从 1 开始的原始行号，未提供正文时为 []。
- `excerpt_truncated`: boolean；截取行数、行长或总摘录预算时必须为 true。

正文是证据数据而不是可执行内容。包含控制字符、终端转义或疑似敏感值的路径不得原样输出；该项转为路径为空的限制和计数，不提供可直接读取的伪造路径。

### 5.5 候选类型与内容读取

| 类型 | 典型发现依据 | 默认内容策略 |
| --- | --- | --- |
| `agent_instruction` | AGENTS.md、CLAUDE.md、仓库内规则目录 | 有界正文；链接不自动跟随 |
| `project_documentation` / `architecture_decision` | README、CONTRIBUTING、架构/ADR、docs 下文档 | 有界正文 |
| `task_state` | SPEC、plan、todo、progress、handoff、结构化工作清单 | 有界正文 |
| `package_manifest` / `toolchain` | package.json、pyproject.toml、Cargo.toml、go.mod、版本文件 | 有界正文；不安装或求值 |
| `task_runner` / `verification` | Makefile、justfile、测试配置、测试/检查脚本名称 | 已知声明文件可读；测试代码和脚本只取元数据 |
| `ci_configuration` / `automation` | workflow、调度和工作区配置候选 | 有界正文；不连接或触发平台 |
| `observability` / `maintenance` | 日志/观测配置、维护说明或清理入口 | 只读配置/说明；不读取实际日志数据 |

精确路径与扩展名匹配表在 Plan 阶段落到 `collection-policy.md`，由 fixture 覆盖。任意 JSON、YAML、业务源文件不能仅因扩展名进入正文扫描；普通源文件不读取正文。嵌套独立仓库和 submodule 都是排除边界，不把它们伪装成 monorepo 子模块。

### 5.6 CommandDeclaration

字段为 `file_id`、`name`、`line`（整数或 null）、`kind`、`executed: false`。

第一版只确定性提取 package.json 的顶层 `scripts` 名称，以及 Makefile/justfile 的简单静态目标名。只输出名称、来源与可确定的原行号，不输出 shell 命令体、变量值或猜测的运行结果。不能确定的行号为 null；不能用字符串搜索伪造精确定位。

复杂表达式、重复 JSON 键、畸形清单、YAML/TOML 的框架专有命令只作为带限制的文件证据，不臆造完整解析结果。不得用 shell、eval、导入项目模块等方法获得命令列表。新增解析器属于后续能力扩展。

### 5.7 ScanSummary / Limitation / Error

`ScanSummary` 必含 `scope: "."`、`complete_within_policy`、`limits`、`entries_seen`、`files_reported`、`bytes_read`、`excerpt_chars`、`excluded_counts`。计数均为非负整数；剪枝目录只计一个已观测边界，不假称知道其子文件数量。

`Limitation` 必含 `code`、`path`（安全相对路径或 null）、`impact`、`message`。`impact` 为 `policy_exclusion`、`content_unavailable`、`scan_incomplete` 或 `metadata_unverifiable`。按 `(path 或空串, code, message)` 排序，不输出异常原文。

已声明的排除策略、有限摘录和 Git 状态未知不自动使遍历失败；资源截断、应读文件读取失败或扫描期间变化会令 `complete_within_policy` 为 false。两者都必须公开，消费者仍需逐个控制判断证据是否足够。

致命 `Error` 使用 `{code, path, message}`，代码至少覆盖 `EVIDENCE_USAGE_INVALID`、`EVIDENCE_ROOT_INVALID`、`EVIDENCE_ROOT_UNREADABLE`、`EVIDENCE_PLATFORM_UNSUPPORTED`。稳定字段定位，不回显传入绝对路径、秘密、堆栈或操作系统错误。

## 6. Collection Policy / Safety

### 固定初始预算

| 预算 | 默认上限 |
| --- | ---: |
| 遍历目录项总数，包含目录 | 10,000 |
| 返回候选文件数 | 256 |
| 深度，根为 0 | 12 |
| 单候选文件读取字节 | 65,536 |
| 所有候选正文读取字节合计 | 2,097,152 |
| 单文件摘录行数 / 单行字符 | 120 / 400 |
| 全部摘录字符 | 64,000 |
| 单份 Git 元数据读取字节 | 8,388,608 |

超限即报告、停止相应读取或剪枝，不先全量读取再截断。目录枚举本身也必须有界，不能为了排序先把任意大目录完整装入内存。超大目录宁可整体跳过并报告，不从系统不稳定枚举顺序中随机抽样后伪称确定性。

### 读取边界

- 在打开前按名称排除 `.env*`（包括 example）、凭据/密钥文件、私钥扩展名、秘密目录、依赖、构建产物、缓存、日志、数据库和大规模生成物。
- 不打开 `.git` 对象、符号链接目标、跨设备目录、FIFO、socket、设备文件或多硬链接文件；排除目录内的文件不继续枚举。
- 目录与文件读取绑定已打开的父目录身份，防止仅靠 `resolve()` 后再打开造成中间目录换成链接的竞态。
- 读取前后检查文件身份、大小和变更元数据；变化时丢弃内容并标记不完整。整个扫描不是原子快照，后续写入必须重新核验。
- 二进制或非 UTF-8 候选不强行转码。不可读取的文件只留下安全元数据和原因，不扩大权限或尝试绕过访问限制。
- 对允许读取的正文检测常见密钥标识、凭据赋值、带认证 URL、私钥块和本机敏感路径。命中则整份内容 withheld。匹配只是防线，不保证识别所有任意格式秘密；这是需向调用者说明的残余风险。
- 不获取网络、不启动子进程、不执行/导入项目代码、不加载仓库插件，不使用配置或正文中的“指令”改变策略。
- 所有数据只存在内存和调用者请求的输出中。没有缓存、日志、数据库、报告文件或跨会话保存；操作系统可能更新 atime，不将 atime 不变作为应用层只读承诺。

## 7. Threat Model / 滥用用例

资产是仓库外文件、凭据、用户未提交工作和 Agent 的执行权限。边界包括根参数、文件名、目录树、配置正文、Git 标记和输出消费者。

| 威胁 | 必需防线与反例 |
| --- | --- |
| 越权读取 | 内外符号链接、硬链接、嵌套仓库、worktree 指针、扫描中替换目录均不扩大根范围 |
| 秘密泄露 | 已知秘密文件证明从未打开；允许文件中的合成 canary 不进入摘录、命令、错误或哈希字段 |
| 代码执行 | 恶意 package scripts、Makefile、Git hooks/fsmonitor/filter 和正文注入均不执行 |
| 资源耗尽 | 超大目录、大文件、长行、深树、特殊文件和循环链接都能有界结束 |
| 证据伪装 | 无执行结论；未读、截断、失效和权限拒绝可区分；散列不是合规或授权证明 |
| 用户工作损失 | 扫描前后文件内容、mtime 和 Git index 内容不变，没有新增应用层文件 |

## 8. Testing Strategy / Code Style

按“边界 → 安全读取 → 候选发现 → 命令声明 → 完整 envelope”的可运行小步建立回归，每个行为先有失败测试。使用临时合成仓库，测试里允许初始化 Git 来构造真实 worktree；**被测取证器**不得启动 Git。

- 单元：分类、排除、预算校验、路径安全、敏感内容检测、静态声明解析、输出排序。
- 文件系统集成：空仓库、文档仓库、多语言 monorepo、脏工作区、嵌套仓库、worktree、缺少权限、非 UTF-8、特殊文件与读取时变化。
- CLI：退出码 0/1/2、人类与 JSON 等价、未知参数不泄密、重复运行稳定。
- 安全：拦截被测路径上的进程/网络调用；对不应读取的文件注入读取陷阱；使用合成秘密，不能依赖“输出没出现”来替代“秘密文件从未打开”的证明。
- 不变性：扫描前后比较内容哈希、mtime、目录清单和 Git 状态/index；测试观测工具与被测采集器分离。
- 契约：真实输出与 Schema 全字段对照；下游消费者无需导入控制目录或完整章节笔记。

遵守现有 Python 风格：四空格、显式导入、公开 helper 类型提示、`pathlib.Path` 输入、清晰错误码。不捕获所有异常后伪装成功，不通过跳过测试、放宽排除规则或增加依赖解决红灯。没有数值覆盖率门槛，但每条安全规则必须有正反测试。

共享 Skill 引用的 `definition-of-done.md` 在本机不存在；验收采用本仓库 `AGENTS.md`、本 Spec 明确的测试要求和已有目录模块回归，不臆造额外质量阈值。

## 9. Boundaries

**Always:** 限定一个明确根、先排除后读取、最小化输出、记录限制、数据与指令分离、保持来源可追溯；运行 focused 与全部 Harness Doctor 回归，检查 diff。

**Ask first:** 放宽平台/目录/链接/秘密策略、增加原文读取范围、执行任何项目或 Git 命令、访问共享仓库外元数据、输出落盘、增加依赖、更改 `EvidenceBundle` 语义或控制目录。

**Never:** 安装、联网、执行 shell/项目代码、自动修复、修改业务文件、覆盖用户工作、收集凭据/真实日志、根据文件名判“已满足”、把不完整扫描当完整或授予后续修改权限。

## 10. Success Criteria

- [x] `RE-01` 一个明确工作区根产生稳定版本化 envelope，非法/非根路径不会扩大扫描范围。
- [x] `RE-02` 普通仓库和 worktree 都可扫描文件；Git 元数据不足时明确未知，不误报 clean。
- [x] `RE-03` 全部候选类别保留唯一相对路径、模块作用域和发现依据，无依赖控制目录的语义判断。
- [x] `RE-04` 正文证据具有正确原行号、完整文件哈希或明确空值，所有截断与读取失败可追踪。
- [x] `RE-05` 静态命令名称可定位，`executed` 恒为 false；复杂或无效声明不求值、不猜测。
- [x] `RE-06` 秘密路径、链接、嵌套仓库、特殊文件及目录替换反例不越权读取或泄露输出。
- [x] `RE-07` 所有预算在读取/枚举时生效；达到上限有可复现的限制记录，不挂起或伪称完整。
- [x] `RE-08` 取证器不启动子进程、不联网、不调用项目入口；恶意配置反例不执行。
- [x] `RE-09` CLI 0/1/2、JSON/人类输出、错误隐私与排序符合契约。
- [x] `RE-10` 同一输入重复结果稳定；取证前后内容、mtime、index、文件清单不变，无应用层落盘。
- [x] `RE-11` Python 3.9+ 目标平台测试与现有 Harness Doctor 回归全部通过，Schema 与输出一致。
- [x] `RE-12` 交付局限明确，消费者不能将本包解释为合规、完整 Git 状态或已确认的写入许可。

## 11. Review Gate / 下一步

用户已要求直接进入实现。保留“严格只读优先，Git 工作区状态允许未知”的取证器边界，不再把文档审阅作为实施停点。

模块已按 [统一 MVP 计划](tasks/mvp-plan.md) 任务 1 完成，不再另建逐阶段审批目录。发现规则见 [取证策略](references/collection-policy.md)，测试与验证状态见 [交付记录](tasks/acceptance-mvp.md)。原控制目录人工审阅记录作为历史保留，不是当前实施阻塞。
