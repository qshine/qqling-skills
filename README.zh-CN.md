# qqling-skills

[English](README.md) | [简体中文](README.zh-CN.md)

一组适用于 Codex、Claude Code 及其他支持 Skills 格式的 Agent 的独立 Skills，涵盖仓库体检、Skill 使用分析和夜班排班。

每个 Skill 都包含 `SKILL.md` 入口及配套脚本、参考资料。具体功能取决于所在 Agent 可用的工具和数据；其中 `ql-skill-usage-auditor` 目前分析的是 Codex 会话日志。

## Skills

| Name | 介绍 |
| --- | --- |
| [ql-harness-doctor](ql-harness-doctor/SKILL.md) | 对单个 Git 仓库做 Harness 规范体检：依据 14 章研究归并的 46 个控制项，给出六种诊断状态、规范覆盖率、L0–L4 成熟度与分组建议。检查任务状态流转和异常中断后的恢复流程，区分规则声明、执行记录与结果核验。仅在用户明确点名时手动调用。 |
| [ql-skill-usage-auditor](ql-skill-usage-auditor/SKILL.md) | 统计 Codex Skill 的实际加载次数，提供周期排行、趋势可视化、覆盖状态和安全的清理建议。普通文本中的 Skill 名称或 `$skill-name` 提及不会被计入使用次数。 |
| [ql-schedule-night-shifts](ql-schedule-night-shifts/SKILL.md) | 根据人员、月份、请假和个人要求生成科室夜班 Excel 排班表，支持中国法定节假日、跨月公平账本、候选方案确认和临时请假后的最小改动修复。 |

## 安装

为你使用的 Agent（如 Codex 或 Claude Code）安装 Skill。将 `<skill-name>` 替换为上表中以 `ql-` 开头的 Skill 名称：

```bash
npx skills add qshine/qqling-skills --skill <skill-name>
```

## Harness Doctor 使用方式

Harness Doctor 仅在用户明确点名时手动调用，普通开发任务不自动触发。例如：

> 使用 ql-harness-doctor Skill 诊断当前仓库，先给建议，等我选择和确认后再补齐。

诊断阶段只读。用户选择补强项后，Skill 统一预览所有文件差异，最终确认一次才新建或追加 Harness 文档。也可以只要求诊断。L4 只诊断，不创建自治循环。

任务检查覆盖实现前生成清单、开始任务前持久化 `in_progress`、验证后及时记录 `done`，以及异常中断后先将已保存状态与仓库证据核对再继续。需要执行证据的控制不能仅凭文档评为已满足。结果已核验表示确实检查过，不代表检查通过。

运行需要 macOS/Linux 和 Python 3.9+，不依赖第三方 Python 包；预览和应用需本地 `/usr/bin/git`。控制项目录版本为 0.4.0，诊断报告版本为 1.1.0；旧报告需重新评估。

完整流程与边界见[工作流](ql-harness-doctor/references/workflow.md)、[任务状态规则](ql-harness-doctor/references/task-state-policy.md)和[证据质量规则](ql-harness-doctor/references/evidence-quality.md)。
