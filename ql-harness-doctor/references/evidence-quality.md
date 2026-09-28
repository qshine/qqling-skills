# 诊断证据分层

用户于 2026-09-13 要求分开呈现“规则已声明、发现执行记录、执行结果已核验”。本机制作用于所有控制，目的是让报告显示依据和未验证范围，不认证执行记录的真实性。

## 三个独立证据栏

| 栏位 | 输入字段 | 能证明什么 | 不能据此推断 |
| --- | --- | --- | --- |
| 规则已声明 | declarations | 可读规则、命令、验收约定存在且语义相关 | 实际运行过、执行成功、全部任务遵守 |
| 发现执行记录 | execution_records | 有具体任务、状态变化或运行结果的记录 | 记录真实、仍适用、与实际结果一致 |
| 执行结果已核验 | result_checks | Agent 实际核对记录与另一处结果/观察，列出方法、范围、时间、结论和限制 | Python 执行过测试、记录经过认证、整个仓库长期合规 |

同一文件可以包含不同种类的证据，但必须分别定位。同一处声明不能又标为执行记录；同一行记录不能充当自己的核验，核验观察也不能引用声明本身。另一条语义独立的执行事件可以同时列为 execution_records 和 observation，以保留其实际来源类别。不同的行号只是最低结构边界，语义上还必须是不同依据：把同一句“已通过”复制到另一行仍然属于自证。

## 如何核验

- `record_cross_check`：实际把任务记录与另一处可读的验证输出、状态转换记录或结果工件核对，说明具体任务/版本/时序及相符或不符之处。转述、复制同一主张、仅引用 SHA、文件名或测试命令不算独立结果。
- `reproduction`：Agent 在当前授权下真实复现检查，并将任务记录与可引用的实际结果比较。Doctor 的 scan/assess 不运行该命令；只读诊断不能为了获得更高层级自行执行项目命令。
- 每次核验有 `scope`（任务、版本、时间或检查范围）、`checked_at`（带时区的实际核验时间）、`outcome`（confirmed / contradicted / inconclusive）、`limitations`（范围、真实性、采样、过期或环境限制）。confirmed 表示观察支持该项主张，不等于“所有测试全绿”。
- 核验需要当前 EvidenceBundle 内可读的具体行号引用。外部工具结果、被排除的日志或普通业务源码无法引用时，保留 recorded/无法验证并说明限制；不要扩大扫描、绕过截断或未经确认把结果写入仓库。需要另行核验/保留记录时明确提出其精确范围。
- 核验后目标内容变化、引用过期、结果不再可比时重新取证。不得为旧记录补造新的运行时间，也不能把声明 `executed=false` 的命令当成实际运行。

## 接口

每条 Agent 判断仍包含 control_id、status、rationale、evidence，新增可选的 evidence_trace 对象。省略它时已有引用显示 unclassified，不猜测其种类，也不能评为 satisfied。旧版无证据的缺口判断仍可用于诊断。

下面的 ID、行号、时间和结论仅展示格式，必须换成真实观察：

```json
{
  "control_id": "HD-STA-003",
  "status": "partial",
  "rationale": "已核对一项任务的开始记录，其余更新时点尚无足够证据。",
  "evidence": [
    {"file_id": "EV-实际规则文件标识", "line": 8},
    {"file_id": "EV-实际任务文件标识", "line": 12},
    {"file_id": "EV-实际观察文件标识", "line": 5}
  ],
  "evidence_trace": {
    "declarations": [{"file_id": "EV-实际规则文件标识", "line": 8}],
    "execution_records": [{"file_id": "EV-实际任务文件标识", "line": 12}],
    "result_checks": [{
      "record": {"file_id": "EV-实际任务文件标识", "line": 12},
      "observation": {"file_id": "EV-实际观察文件标识", "line": 5},
      "method": "record_cross_check",
      "scope": "仅任务 T1 在指定版本上的开始顺序",
      "checked_at": "2026-09-13T10:00:00+08:00",
      "outcome": "confirmed",
      "limitations": "仅核对可读任务记录，尚未覆盖完成更新和异常恢复。"
    }]
  }
}
```

三个证据栏均须出现，可以为空数组。分类引用必须是 evidence 的子集，record 必须列在 execution_records 中，record/observation 都须为具体行号。每组最多 256 项，禁止重复引用/核验对；scope 和 limitations 均为非空、最长 2000 字符且不含敏感信息的文本。method、outcome、字段集合和时间格式均校验。无核验时不能用空对象或占位值凑齐结果。

## 状态与计分

每个控制在目录中显式定义 `evidence.minimum_level`：

- declared：以规则或静态结构为主，例如指令读取条件；仍须语义完整一致。
- recorded：要求实际发生的决策、评估或维护记录，例如关键决策记录。
- verified：需要核对实际执行或结果，例如修改前基线、任务状态时序、异常恢复、完成验证、提交与可执行架构约束。

报告逐项输出 evidence_trace、evidence_level、minimum_evidence_level；最高层级为 none / unclassified / declared / recorded / verified。存在核验且所有核验有明确结论（confirmed 或 contradicted）时，层级为 verified；存在 inconclusive 时保留 recorded 并展示未确定范围。已核验的反证仍是 verified，但控制不能评为 satisfied；“核验过”与“核验支持主张”必须区分。

评为 satisfied 必须达到最低层级，且不能有未确认或相反的核验。违反时 assess 明确拒绝，Agent 应补充合法证据或修正状态，不静默降级，也不自动补运行。达到最低层级不自动改变状态：一个样本或一个子检查通过，不能覆盖其余缺口。

六种状态和覆盖率公式不变。evidence_levels 是按最高层级统计的互斥分布，总数为控制数；verification_outcomes 按核验记录数分别统计 confirmed（支持主张）、contradicted（反驳主张）、inconclusive（未能确定），总数可以不同于控制数。两者都与规范覆盖率分开，不额外加分。报告和建议必须同时显示“状态 / 最低要求 / 规则 / 执行记录 / 核验与限制”；缺证据栏写“未提供”，不能省略后让用户误以为已核验。

DiagnosticReport 版本为 1.1.0，目录为 0.4.0；其他机器工件版本不变。旧报告须重新 assess，recommend/select 拒绝旧版本和证据门槛被篡改的报告。摘要是内容一致性检查，不是批准、身份认证或独立审计。
