# OpenAI / Anthropic Harness 建议对照与待确认清单

> 状态：用户仅确认并纳入 R02（目录 0.3.0、HD-BST-002），见 [生效规则](../references/baseline-policy.md)。R01、R03–R08 仍待确认，未进入检查目录；不得因 R02 的文章已登记而采用其余建议。
>
> 读取日期：2026-09-09。研究时对照基线：Harness Doctor 目录 0.2.0，46 个控制；书籍仍固定于 `77e7a3e21469dcbece2558086c8d91657abeaa40`。

## 结论先行

初始建议优先讨论 R01–R05；用户随后仅选择 R02，其余继续保留为候选。多数是把已有检查写得更可验证，不应为了吸收新文章而重复增加分母。

用户已确认的两项另行生效：每次独立修改任务新建 Worktree，完成并验证后提交。它们归入 HD-SCP-001 / HD-STA-004，细则见 [Git 工作流规则](../references/git-workflow-policy.md)。本研究不替用户确认其余项目。

## 1. 来源与阅读边界

选读以下 8 篇官方工程文章的正文，包含与结论有关的文字示例；不是对两家公司全部出版物的穷尽综述。未运行文章附带的示例项目、评测或在线服务，不把作者的实验效果当作本项目复现结果。网页会更新，本轮记录 URL、发布日期和读取日期，没有保存原始网页副本，也不声称它们有不可变的提交快照。

初次通过 agent-reach 的网页通道读取时，本机代理连接失败；随后改用官方站点网页读取完成研究。以下观点均有官方原文支撑，不引用二手解读。表中是来源转述；第 2–5 节中检查设计、优先级与落点是我们的产品推论。

| 来源 | 发布日期 | 与本次最相关的观点及边界 |
| --- | --- | --- |
| S1 · OpenAI，[Harness engineering](https://openai.com/index/harness-engineering/) | 2026-02-11 | 让 Agent 能找到知识、运行应用、读取反馈；文章中的应用和观测环境可按 Worktree 隔离。规则尽量成为可执行约束。它描述特定团队的工程实验，不能直接推广其合并策略。 |
| S2 · OpenAI，[Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/) | 2026-01-23 | 模型、消息、工具结果和上下文管理共同构成循环。文章区分 shell 沙箱与 MCP 工具的执行边界；这是当时实现说明，不能据此断言所有产品版本的权限行为。 |
| S3 · OpenAI，[Unlocking the Codex harness: how we built the App Server](https://openai.com/index/unlocking-the-codex-harness/) | 2026-02-04 | 工具执行、批准、差异与完成有明确事件；会话状态持久化，使客户端可恢复。借鉴状态和授权边界，不意味着普通仓库要接入该协议。 |
| S4 · Anthropic，[Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 2025-11-26 | 长任务分初始化与增量开发；新会话先恢复状态、检查环境，完成一项后测试、提交并交接；不能靠改弱功能测试获得通过。场景主要是跨会话应用开发。 |
| S5 · Anthropic，[Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) | 2026-03-24 | 分工与评审要匹配模型和任务；评估者也需校准。模型升级后某些旧机制可以移除，组件应逐项实验。文中的多角色安排不是所有任务的默认答案。 |
| S6 · Anthropic，[Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 2025-09-29 | 有限注意力需要高信号上下文、按需检索与持久笔记；压缩应保留关键状态。不是“全部塞进上下文”，也不是越短越好。 |
| S7 · Anthropic，[Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) | 2025-09-11 | 工具职责、输入输出和错误说明要清晰；控制响应规模，用真实任务及留出集评估。不要把已有 API 全量包装成工具，格式和数量需由实验决定。 |
| S8 · Anthropic，[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | 2026-01-09 | 区分任务、重复尝试、评分器和最终结果；组合确定性检查与经人工校准的判断，覆盖应做/不应做案例，避免评测共享状态污染。评测不等于产品全部质量。 |

## 2. 已有覆盖：不建议重复增加检查

以下是对当前 [控制目录](../references/catalog/controls.json) 的映射，不代表我们已确认目标仓库实际满足。

| 厂商文章讨论的主题 | 现有控制 | 处理建议 |
| --- | --- | --- |
| 精炼入口、按需读取、仓库知识可发现（S1/S6） | HD-INS-001/002、HD-KNW-001/002 | 保留；不要再增加“必须有更长 AGENTS.md”或重复知识文件 |
| 文档维护、规则失效与机械化检查（S1） | HD-KNW-003、HD-ARC-001/002、HD-VER-003 | 细化失效链接/文档与实现不一致的例子即可，不加同义控制 |
| 小任务、完成定义、持久工作清单（S4） | HD-SCP-001/002、HD-STA-001/003/005 | 已覆盖主干；本次用户要求已加强 Worktree 与提交 |
| 真实用户路径而非只看单元测试（S4） | HD-VER-004/005、HD-OBS-001 | 保留适用性：UI、服务、脚本各用合适验证，不统一强制浏览器 |
| 显式批准、可恢复状态（S3） | HD-FND-003、HD-AUT-005、HD-STA-001、HD-GRF-005 | 维持诊断/执行分离；不可因文章中的自治能力自动获得权限 |
| 有界循环、独立复核、编排成本（S5） | HD-AUT-001/003、HD-GRF-001/007、HD-HYG-003 | 已有高级控制；不强制所有仓库采用多 Agent |

## 3. 增量建议与采纳状态

R 编号是研究编号，不是计分控制 ID。R02 已映射到 HD-BST-002；其余候选的成熟度和门槛仅为建议，未经确认不改变现有报告。

### R01 · Worktree 之外的运行环境隔离

来源依据：S1 描述按工作区启动独立应用及观测环境。[OpenAI 原文](https://openai.com/index/harness-engineering/)

我们的建议：对会启动服务或产生状态的任务，检查端口、测试数据库/目录、缓存、进程及日志是否有任务归属和清理边界。文件隔离不能作为这些资源也隔离的证明。

- 现有落点：HD-SCP-001 / HD-BST-001；HD-AUT-004 目前只覆盖 L4 并行场景，普通开发任务存在边界空缺。建议形成 L2 条件性子检查，不把服务仓库推向 L4。
- 仓库证据与补强：启动配置、任务资源映射、停止/清理说明和实际验证记录；仅补文档可保持部分满足。Doctor 不自动建数据库、启动进程或清理资源。
- 优先级：高；纯文档仓库不适用。

### R02 · 修改前先记录健康基线

已采纳：用户确认后纳入目录 0.3.0，检查和执行边界以 [R02 规则](../references/baseline-policy.md) 为准。下文保留研究时的提炼依据。

来源依据：S4 的新会话会先恢复上下文并检查已有应用状态。[Anthropic 原文](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

我们的建议：把“命令存在/近期运行过”细化为“本任务修改前运行相称检查并记录基线”；按任务风险选检查，不要求小文档修改启动整套应用。

- 现有落点：细化 HD-BST-002（L2）；与 HD-HYG-001 的退出基线衔接，不重复计分。
- 仓库证据与补强：基线提交、命令、结果、已有失败和本次新增失败的对照模板。既有红灯不能被本次任务掩盖，也不授权顺手修复无关问题。
- 优先级：高；没有运行条件时标记无法验证，不写成已通过。

### R03 · 不得偷偷降低验收标准

来源依据：S4 强调功能清单与测试不能被开发 Agent 改弱以获得通过。[Anthropic 原文](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

我们的建议：明确检查删除/跳过测试、减少断言、降低阈值、扩大忽略范围等差异；合理调整必须解释原因并获得相应批准，不能当作普通修复静默通过。

- 现有落点：HD-STA-005 / HD-VER-002（L3）已有证据门，尚可细化“证据标准本身被改弱”的识别与人工复核。
- 仓库证据与补强：验收基线、任务差异、例外审批及回归结果。先补规则和审查清单；真正的差异检测器需要后续单独实现、测试，不假装当前静态扫描器已能完成。
- 优先级：高；不采用“一律禁止修改测试”的绝对规则。

### R04 · 工具权限逐项核对，不能只看总开关

来源依据：S2 展示不同工具可能处于不同执行边界。[OpenAI 原文](https://openai.com/index/unrolling-the-codex-agent-loop/)

我们的建议：逐类列出 shell、本地文件工具、MCP/远程服务的读取、写入、网络、凭据和确认责任。声明“有沙箱”不足以证明所有工具都受同一限制。

- 现有落点：细化 HD-FND-003（L3），与 HD-AUT-005 去重；不要求仓库使用某家权限配置格式。
- 仓库证据与补强：脱敏工具清单、配置与权限说明、批准/拒绝案例。平台设置不可见时标记无法验证，不读取秘密或自动改账号权限。
- 优先级：高；使用外部工具/连接器时尤其重要。

### R05 · 评估集与评分器也要验证

来源依据：S8 强调正反案例、结果验证、重复运行及评分器校准；S5 展示独立评估者仍可能偏乐观。[评估文章](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)、[Harness 实验](https://www.anthropic.com/engineering/harness-design-long-running-apps)

我们的建议：检查是否有可复现任务集、已知应通过/应拒绝样本，以及人工抽查模型评分的记录。重复尝试至少区分“最终成功过”与“每次稳定成功”，不拿单次高分当可靠性证明。

- 现有落点：HD-FND-002 / HD-OBS-002（L3），与 HD-AUT-003 的独立复核互补。建议补证据要求，不先新增评分维度或硬性样本数量。
- 仓库证据与补强：任务/评分标准版本、环境重置说明、基线与结果、错判复核；普通仓库从代表性失败案例开始，平台团队再扩展。Doctor 只诊断和准备模板，不自动付费调用模型。
- 优先级：高；这是下一阶段验证 Harness Doctor 自己误判率的直接用途，不应只验证 JSON 和分数计算。

### R06 · Agent 工具的可用性契约

来源依据：S7 讨论清晰的工具职责、参数、响应规模和可行动错误。[Anthropic 原文](https://www.anthropic.com/engineering/writing-tools-for-agents)

我们的建议：对自研脚本、工具或 MCP，检查输入输出示例、错误后的下一步、分页/截断提示与副作用声明；“脚本存在”不能证明 Agent 能正确使用。

- 现有落点：HD-VER-003 / HD-FND-001 仅部分覆盖，确认后再决定独立控制还是工具型仓库子检查；建议 L2–L3 条件适用。
- 仓库证据与补强：工具定义、成功/非法输入/大响应样例及使用回归；优先文档和样例。不能把任何固定 token 上限或某种返回格式当通用阈值。
- 优先级：中；只使用成熟内置工具的普通仓库可不新增此项。

### R07 · 上下文压缩后的关键状态不丢失

来源依据：S6 强调按需检索与压缩时保留重要决定、未解决问题；S2 说明上下文管理是循环的一部分。[Anthropic 原文](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[OpenAI 原文](https://openai.com/index/unrolling-the-codex-agent-loop/)

我们的建议：给现有连续性规则增加恢复抽检：换会话后，是否仍能找回目标、非目标、禁止事项、验证状态和下一步；对正文截断也要明确“不完整”，不能静默当全文。

- 现有落点：HD-STA-006 / HD-INS-001/002，主要是证据细化；不新建一套长期记忆服务。
- 仓库证据与补强：权威状态文件、条件路由、一次恢复示例与未验证内容。普通短任务不强制压缩；Doctor 当前截断标记保留，不绕过取证限制。
- 优先级：中；跨会话长任务更有价值。

### R08 · 模型升级时复核 Harness 组件是否还值得保留

来源依据：S5 在模型变化后调整或移除旧机制，并主张逐组件实验。[Anthropic 原文](https://www.anthropic.com/engineering/harness-design-long-running-apps)

我们的建议：记录组件解决什么失败、带来多少质量收益及时间/成本负担；模型或任务改变时，做逐项保留/简化/替换决策。更多规则和更多 Agent 不自动代表更成熟。

- 现有落点：HD-HYG-003 已是 L4 控制，建议只细化对照实验和升级触发条件，不新增同义项目，也不下放成所有小仓库的硬门槛。
- 仓库证据与补强：组件清单、可比较实验、成本/质量结果与决策。仍仅提供设计建议，不自动删除规则、调度循环或换模型。
- 优先级：中；复杂 Harness / 平台工程场景适用。

## 4. 冲突与不建议照搬的做法

1. **每任务新建 Worktree 是用户规则，不是两家公司共同颁布的标准。** S1 提供隔离环境的工程例子；S4 支持增量提交与交接，但不能推出所有团队必须采用完全相同的任务粒度。
2. **不采用“提高吞吐就降低合并门槛”。** S1 明说其取舍依赖特定环境；我们的确认、验证、授权边界不因这个例子放宽。[来源](https://openai.com/index/harness-engineering/)
3. **不固化 initializer/coder、三 Agent、频繁重置或固定文件名。** S4/S5 的设计随任务与模型变化。先看缺口和可比较效果，不把文章架构照搬为仓库必需品。[长期任务](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)、[后续实验](https://www.anthropic.com/engineering/harness-design-long-running-apps)
4. **不把“结果优先”变成可以绕过授权流程。** S8 反对过拟合某一种解题路径，不代表批准、隔离与禁止副作用可以省略；R05 的结果评估必须同时遵守本项目已确认的安全规则。
5. **不将规范覆盖率改成效果评分。** 覆盖率仍只统计已满足/适用控制；部分满足不计分、不适用不进分母。速度、成功率、成本等仅作 R05/R08 的效果证据，不混入现有成熟度算法。

## 5. 剩余候选获确认后的落地方式（本轮不执行）

1. 用户选择 R 编号，并决定“补充现有检查”还是“新增条件性控制”；先确认适用性、门槛和证据，后做变更。
2. 在来源注册表登记实际采用的文章、读取日期、版本/可获得的固定标识和边界；将来源观点与产品规则分别标注。没有固定快照就明确说明，不伪造 SHA。
3. 优先复用现有 canonical ID；需要新增控制时先解决非书籍来源的 schema/别名契约，不能为绕过验证器伪造 `Lxx-Cyy` 别名。更新目录版本、去重映射和旧报告迁移规则。
4. 按现有“只读诊断 → 分组建议 → 选择 → 完整预览 → 最终确认 → 修改与验证”交互实施。新增动态取证、Git 差异检查、运行服务或评测执行能力须有独立边界与测试，不由文章建议隐式授权。
5. 使用可控仓库样例验证已满足、部分满足、缺失、冲突、无法验证和不适用，补误判/漏判案例。除确定性单元测试外，对 Agent 实际判断做人工抽检，并记录成本和适用范围。

目前只纳入 R02。R01、R03–R08 保持待确认，未来按用户选择继续；已有覆盖的主题不重复计分。
