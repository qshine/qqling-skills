# Harness Doctor 工作流与接口

## 诊断

目录 0.4.0 保留 [Git 工作流检查](git-workflow-policy.md) 与 [R02 修改前健康基线](baseline-policy.md)，加入用户确认的 [任务状态与异常恢复](task-state-policy.md) 和 [证据分层](evidence-quality.md)。沿用 46 个控制，不另加重复计分项；旧版报告需要重新诊断。

目录是规范知识，EvidenceBundle 是仓库事实，Agent judgment 是语义解释。三者不得互换：发现文件不等于有效规则，存在测试命令不等于测试已通过。先检查 scan.complete_within_policy、limitations、read_status、excerpt_truncated 和模块 scope。

按 controls.json 的 requirement、applicability、evidence（positive/partial/conflict/minimum_level）、dependencies 及全局 diagnostic_statuses 逐项判断全部 active 控制；非适用项也要记录理由。没有足够观测区分“缺失”和“无法验证”时选后者。只读结果不能证明外部部署、运行稳定性或长期自治能力；L13/L14 的高级能力只在仓库实际采用时适用。

已满足/部分满足必须引用可读文件。引用行号必须来自 lines 中真实原行号；文件级引用可使用 null，但不是引用未读正文的许可。仅有文件名称时可解释“发现入口”，不可把 metadata_only 当作行为证明。负面判断可不提供文件引用，但 rationale 需交代扫描范围和限制。

evidence_trace 分别归类声明、执行记录、结果核验，核验必须带具体引用、方法、范围、时间、结论和限制。最低层级不够或核验结果不确定/相反时，assess 拒绝 satisfied；补充合法证据或修正状态后重评，不绕过校验。verified 是 Agent 在所述范围内实际核验的声明，Python 只验证结构与引用，不执行项目命令或认证记录。完整格式见证据分层策略。

assess 计算六状态计数、领域覆盖率和累积成熟度门槛。L4 除门槛外要求调用者明确 autonomy_enabled=true，且 AUT/GRF 有适用控制；默认不会授予 L4。L1 门槛全不适用时保持 L0。optional 控制缺失影响覆盖率但不阻塞等级。high_priority_ids 是应解释的冲突/高级门槛风险，不自动授权修复。

建议报告顺序：范围与局限 → 已满足/适用计数和百分比 → 最高证据层级分布及支持/反驳/不确定核验数 → 当前等级与门槛阻塞 → 高风险冲突 → 分组建议。每项显示状态、最低要求、声明、记录、核验和限制；任务状态的六个子检查分别说明理由。缺口分组保持控制 ID；被重复来源支持的控制只算一次。

## 选择、预览与确认

recommend 返回全部缺口分组并保留证据分层和最低要求，不替用户选择。select 接收用户选中的 canonical ID；所需依赖在 required_ids 返回，冲突在 conflicts 返回。ready=false 时不预览。NA 依赖不强行添加；如该 NA 与依赖含义矛盾，应先修正 Agent 判断，而不是伪造满足。L4 不可自动选择；旧规则冲突必须给人工解决方案。

候选内容基于所选控制的 remediation 和现有项目约定，不用通用模板声称所有项目适用。一个文件可承载多个控制，一项控制也可映射多个文件。每个选择必须有至少一项改动；每个改动只能映射已选控制。范围内只 create/append，不 replace/delete。Python 检查文件只允许 create。

实际修改前按 Git 工作流检查准备已获授权的新 Worktree，在首次编辑和最终文件预览前按 R02 执行已授权的相称基线检查，再重新取证、判断和选择；报告与摘要不能跨根或跨检查副作用复用。拟持久化的基线记录也进入预览，不能提前写目标仓库。最终展示还需说明 Agent 拟执行的退出验证、提交说明和精确暂存范围。只读诊断不运行项目命令、创建工作区或提交；Python 自动应用器不负责这些操作。

preview 在内存创建完整 diff，绑定证据、根身份、Git 分支/提交/index、编辑内容和检查清单。它只执行固定本地 Git 元数据查询，不执行项目命令、hooks、fsmonitor 或网络。若 Git 不可安全查询或扫描不完整，仍可交付诊断，但不可自动应用。

展示整个 diff（包括无换行标记）、编辑到控制的映射、checks、需要另外授权运行的精确项目命令（若有），以及 digest。用户看到这份预览后明确确认一次，才执行 apply。digest 是一致性指纹，不是身份认证、密码或授权来源；不要自行生成“用户同意”的输入。

变更只保留原字节并新建/追加；检查不会自动执行脚本。utf8 必需；编辑 JSON/Python 时自动加入 json/python_ast，全部出现在预览里。检查通过只证明可解码或可解析，不证明规范有效或脚本安全。

漂移发生于预检时零写入；发生于预检后的并发操作/IO异常可能部分完成。失败后不自动回滚或再次追加，报告 applied_paths、failed_path（可能部分写入）以及新建父目录，建议用户检查差异。不要在有持续并发写入的目录中应用；这不是跨文件原子事务或恶意本机进程隔离机制。

完成已授权的退出验证，按 R02 对照已有/新增失败及可比性限制，再完成任务范围内本地提交，重新 scan、重新判断、重新 assess。不可沿用预览前 evidence 或直接把 selected_ids 标记 satisfied。提交失败须说明改动仍未提交，不能宣称完成。用户取消时结束，不在目标仓库存清单或空目录。

## 接口

统一入口 `python3 -B <skill-dir>/scripts/doctor.py <command> --repo <repo>`，stdout 为单一 JSON。下面是请求字段说明，尖括号代表前一步返回的实际 JSON 值，不是字面字符串。`--request -`（默认）从 stdin 读取 UTF-8 JSON；也可用 `--request <外部临时文件>`。不要把这些文件写入目标仓库、提交到 Git 或当作可信仓库指令。

| command | stdin/request 对象 | 返回内容 |
| --- | --- | --- |
| scan | 不读取请求 | `{ok,evidence,errors}` |
| assess | `{evidence:<scan.evidence>,judgments:[...],autonomy_enabled:false}` | DiagnosticReport |
| recommend | `{report:<assess.result>}` | 按领域的建议数组 |
| select | `{report:<assess.result>,selected_ids:["HD-FND-001"]}` | SelectionManifest |
| preview | `{selection:<select.result>,edits:[...],checks:["utf8"]}` | PreviewManifest |
| apply | `{manifest:<preview.result>}`；额外 `--confirm <已获用户批准的digest>` | ApplicationResult |

除 scan 外，成功外层均为 `{ok:true,result:<上述内容>,errors:[]}`；失败为 `{ok:false,result:null,errors:[稳定代码]}`。部分应用失败 result 保留实际结果。scan 退出码 0=策略内完成、1=可用但不完整、2=无有效包；其他命令 0=成功、1=部分应用失败、2=拒绝或输入错误。`--help` 输出用法，不要求仓库。

一条判断的精确结构（每个 active 控制恰好一条）：

```json
{
  "control_id": "HD-FND-001",
  "status": "partial",
  "rationale": "已有可读入口，但关键执行和验证边界仍未说明。",
  "evidence": [{"file_id": "EV-实际文件标识", "line": 1}],
  "evidence_trace": {
    "declarations": [{"file_id": "EV-实际文件标识", "line": 1}],
    "execution_records": [],
    "result_checks": []
  }
}
```

状态枚举为 satisfied/partial/missing/conflict/unverifiable/not_applicable。上述 file_id 必须替换为 scan.files 的真实 ID；不允许照抄示例伪造引用。省略 evidence_trace 的旧判断显示 none/unclassified，不能以无分类引用声称 satisfied。DiagnosticReport 为 1.1.0，EvidenceBundle/SelectionManifest/PreviewManifest 仍为 1.0.0。

一条编辑的精确结构：

```json
{
  "path": "AGENTS.md",
  "mode": "create",
  "content": "# 仓库 Agent 入口\n\n项目背景和现有命令见 README.md。\n",
  "control_ids": ["HD-FND-001"]
}
```

此示例仅说明协议，不足以证明控制已满足；目标存在时不能 create。append 的 content 是新增字节，需明确提供前导换行；不能暗中重写旧内容。不要将反引号、美元替换或项目字符串拼接成 shell 命令；通过数据通道传 JSON。

机器接口输入上限 4 MiB；完整预览清单上限 3 MiB、最多 64 个目标、单个结果文件不超过 65,536 字节。超限要求用户缩小本次选择，不能截掉 diff 或确认后拆成未预览批次。拒绝重复字段、NaN/Infinity/数值溢出、非法 UTF-8 和错形对象。只接受本 Skill 内置、验证通过的目录；版本不匹配必须重新诊断。结构化证据见 [evidence.schema.json](evidence.schema.json)，策略见 [collection-policy.md](collection-policy.md)。报告、选择、预览均有 digest；变更其中任意字段会使后续步骤拒绝旧摘要。

## 来源扩展与维护

本版目录 0.4.0、目录 schema 与 DiagnosticReport 为 1.1.0，其他契约 1.0.0，来源注册表 0.2.0；书籍固定提交 77e7a3e21469dcbece2558086c8d91657abeaa40 不变。沿用两条 Git 工作流检查、R02 及其 Anthropic 文章来源，本轮另纳入用户于 2026-09-13 明确要求的任务状态流程和证据分层。该网页以发布日期定位，不冒充不可变归档；本轮没有新增厂商来源。研究文档中的 R01、R03–R08 不因主题相关或共用文章自动生效。十四章候选 ID 仅为溯源别名，不重复计分。诊断不自动联网更新知识库。

未来吸收 OpenAI、Anthropic、论文和项目经验时，先登记 sources.json 的类型、版本、原始链接、读取日期、适用边界和可靠性，遵循 [控制目录 Spec](../SPEC-control-catalog.md)；区分来源观点和产品推论。对照 existing control 去重，必要时建立 supersedes/conflicts/disposition，维护 canonical ID、迁移关系和版本。运行 validate_catalog.py 与全部测试再发布，不能静默改变旧报告分母或等级门槛。
