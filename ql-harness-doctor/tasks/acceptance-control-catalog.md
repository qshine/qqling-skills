# Control Catalog 验收记录

> 日期：2026-09-06。范围：`SPEC-control-catalog.md`、`tasks/plan.md` 与 `tasks/todo.md` 的任务 1–9。
>
> 结论：本模块实现和自动验收完成，最终人工审阅仍待完成。不是完整 Harness Doctor Skill 的验收。

## 交付清点

- 控制目录版本 `0.1.0`、来源注册表版本 `0.1.0`、Schema 版本 `1.0.0`。
- 12 个控制域、46 个规范控制项、74 个唯一章节 alias；未采纳项为 0。
- L1：4 项；L2：11 项；L3：16 项；L4：15 项。L3 的两个可选控制不阻断成熟度。
- 来源为 14 章中文讲义，同一快照 `walkinglabs-he@77e7a3e`，固定提交 `77e7a3e21469dcbece2558086c8d91657abeaa40`，读取日期 2026-09-04。
- 四份目录 JSON、Python 只读验证器、最小合成 fixture、两份目录测试文件。
- 没有创建 `SKILL.md`、Agent 元数据、取证器、诊断器、补强生成器或应用器。

## Spec 逐项证据

| 标准 | 证据 | 结果 |
| --- | --- | --- |
| CC-01 文件与结构 | 四份 JSON 可解析；递归 Schema/程序 shape 对照测试；生产目录通过完整验证 | 通过 |
| CC-02 六状态与策略 | `CatalogPolicyValidationTests` 检查状态、覆盖率、L0–L4 顺序、激活条件和门槛 | 通过 |
| CC-03 控制域 | 生产目录测试检查 12 域；身份、前缀、排序与 display_order 反例 | 通过 |
| CC-04 完整控制项 | shape、非空指导、生命周期、关系、来源、成熟度切片测试 | 通过 |
| CC-05 74 候选处置 | 从十四份研究笔记提取候选集；与唯一 alias/排除集对照；运行时拒绝漏项、未知项、重复、重叠 | 通过 |
| CC-06 来源快照 | `ProductionSourceRegistryTests` 对照章节元数据；固定完整 SHA 和 14 文档变异反例 | 通过 |
| CC-07 图与生命周期 | 直接/多跳环、1500 节点长链、对称冲突、依赖失效、替代引用、版本顺序、弃用门槛反例 | 通过 |
| CC-08 CLI 退出码 | 合法输入为 0，语义错误为 1，用法/文件/解析边界错误为 2；CLI 子进程测试 | 通过 |
| CC-09 安全稳定输出 | 人类与 JSON 模式同一错误集；重复运行输出相同；秘密 canary、绝对路径、未知字段与用法输入不回显 | 通过 |
| CC-10 回归 | Python 3.9.6 执行 73 项目录测试，全部通过，无跳过；语法检查通过 | 通过 |
| CC-11 离线只读 | 拦截网络调用；验证前后文件哈希、mtime、Git 状态不变；拒绝 FIFO 和非法路径 | 通过 |
| CC-12 下游边界 | 公共 `validate_catalog(catalog_dir)` 与 CLI 均可消费完整数据对；运行时不读取章节笔记 | 通过 |

测试位于 [基础与生产目录测试](../tests/test_control_catalog.py) 和 [边界安全测试](../tests/test_catalog_hardening.py)。

## 实际验证

从 worktree 根目录运行：

```bash
python3 -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v
python3 ql-harness-doctor/scripts/validate_catalog.py
python3 ql-harness-doctor/scripts/validate_catalog.py --json
env PYTHONPYCACHEPREFIX=/tmp/harness-doctor-pycache python3 -m py_compile ql-harness-doctor/scripts/validate_catalog.py ql-harness-doctor/tests/test_control_catalog.py ql-harness-doctor/tests/test_catalog_hardening.py
git diff --check
```

结果：73 项测试通过；人类模式输出 `Catalog is valid.`；JSON 模式输出 `{"ok": true, "errors": []}`；语法与空白检查通过。缓存定位到仓库外，不是 Skill 运行依赖。

附加现有模块回归：

| 测试模块 | 实际执行通过 | 环境跳过 | 说明 |
| --- | ---: | ---: | --- |
| ql-skill-usage-auditor | 35 | 0 | 全部通过 |
| ql-schedule-night-shifts | 5 | 2 | 缺少 openpyxl，工作簿测试未执行 |
| xhs-cover-director | 6 | 28 | 缺少 Pillow，图像相关测试未执行 |

未为无关模块安装依赖；不能把这些跳过项说成已验证。上述模块文件未改动。

## 审查后修复

1. **严格输入**：拒绝重复 JSON 字段、NaN/Infinity、非 UTF-8、非常规文件；检查发行版 Schema 文件的 JSON 可读性。
2. **错误隐私**：不再把控制 ID、路径形式输入或未知字段原文写入错误；未知字段用稳定序号定位。
3. **处置完整性**：不仅在生产数据测试中比对 74 候选，也在运行时检查固定书籍 inventory 与逐章来源。
4. **版本与图**：来源必须有明确版本标识，生命周期版本不可越界；长依赖链不依赖递归栈。
5. **内容一致性**：规范化无语义顺序的数组；将原来的 `Skill 提炼` locator 清空，因为它是本地研究笔记栏目、不是书籍源码章节名。保留章级固定来源与 alias。
6. **适用性与交接**：缺入口不能豁免根指令控制；阻塞必须记录恢复条件且不能报完成；会话结束要回写权威状态再同步派生工件。

本轮遵循 `code-review-and-quality` 的正确性、安全性和可维护性审查，新增了针对发现问题的回归用例，而没有放宽原有质量门槛。

## 跨章节产品裁决核对

| 设计问题 | 当前承载控制与边界 |
| --- | --- |
| 入口与知识重复 | FND-001 检查五类子系统是否可发现；KNW-001 检查知识是否足以回答问题；INS-001 检查指令是否承担条件路由。不能仅凭同一文件存在就判三项满足 |
| 完成与验证重复 | SCP-002 定义行为；VER-001 要求完成证据；VER-002 分层门控；STA-005 绑定工作项状态和证据有效性。只有不同要求的实质证据才能分别满足 |
| 通过状态并非永久 | STA-005 允许证据失效后重新打开，并记录原因 |
| 历史失败 | HYG-001 使用明确基线且不得新增失败，不要求越界修复无关历史问题 |
| WIP 与并行 | SCP-001 默认 WIP=1；AUT-004 仅在隔离、所有权与集成门成立时支持并行 |
| 外部权威 | KNW-002 / STA-003 保留权威链接与同步责任，不声称静态扫描验证过外部系统 |
| E2E 与独立复核 | VER-004 按真实变更边界选择验证；AUT-003 / GRF-004 处理高风险或图的独立上下文，而非给普通仓库强制上自治架构 |
| 行数与图化阈值 | INS-001 不设行数硬门槛；GRF-001 将“三项信号”作为经验提示而非机械阈值 |

以上是 Harness Doctor 的产品控制划分，不是对书籍逐字引用。语义状态判定和防止重复文件计分的行为仍须由下游 `diagnostic-assessment` 验证。

## 已知边界与后续入口

- L4 只声明数据和建议；全部“不适用”不应自动授予 L4。实际成熟度计算属于尚未实现的诊断模块。
- 验证器是明确契约的专用检查器，不是完整 JSON Schema 引擎；离线校验不证明远端来源此刻可访问或真实。
- 当前候选 ID 命名与固定清点针对本书。引入新来源族及其候选 namespace 需更新契约、库存及回归，不能静默添加不受检查的别名。
- 验证器不修改任何目标仓库；本轮没有业务代码、README、CI 或现有 Skill 改动。章节原研究笔记也没有改动。
- 改动位于独立 `codex-xxxx-harness-doctor-research` worktree；主工作区检查为干净；没有推送或合并。
- `tasks/todo.md` 中仅“最终人工审阅”保持未勾选。下一份待制定规格是 `repository-evidence`，其后仍有诊断、选择、预览、应用、交互编排五个模块。见 [能力地图](../CAPABILITY-MAP.md)。
