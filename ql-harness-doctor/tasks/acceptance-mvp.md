# Harness Doctor MVP 交付与验证记录

日期：2026-09-06。结果：七模块实现完成，自包含 Skill 可本地调用。用户要求直接完成实现；没有把该要求记成逐项人工验收或未来自动写入许可。

## 交付

- [Skill 入口](../SKILL.md) 与 agents/openai.yaml：发现、只读诊断、混合确认和复诊协议。
- [控制目录](../references/catalog/controls.json)：46 个 canonical 控制、74 个章节候选别名、14 章来源，控制目录版本 0.1.0、契约 1.0.0；固定提交 77e7a3e21469dcbece2558086c8d91657abeaa40。
- scripts/collect_evidence.py、safe_io.py、evidence_contract.py：有界静态取证、安全 I/O、结构和溯源约束。
- scripts/diagnostic.py、selection.py：Agent 判断校验、六状态覆盖率、L0–L4 门槛、分组与显式选择。
- scripts/changes.py：完整 diff、确认摘要、漂移预检、新建/追加、静态验证和部分失败报告。
- scripts/doctor.py：[统一接口](../references/workflow.md)，支持 scan/assess/recommend/select/preview/apply。
- README 和 .github/workflows/test.yml 已接入；未更改其他 Skill 的实现或测试。

## 自动验证

Harness Doctor 共 128 项测试通过，无跳过：

| 测试文件 | 数量 | 可观察的验证内容 |
| --- | ---: | --- |
| test_control_catalog.py + test_catalog_hardening.py | 73 | 目录、来源版本、14 章/74 别名、依赖/迁移、错误隐私与只读 |
| test_repository_evidence.py | 13 | 行号/哈希、作用域、秘密/链接/特殊文件、命令不执行、有界扫描 |
| test_diagnostic_selection.py | 10 | 六状态、分母为零、累积门槛/L4、引用、依赖/对称冲突、空/重复/未知选择 |
| test_changes.py | 9 | 预览零写入、精确确认、取消、篡改/漂移、保留原字节、重复应用拒绝、部分失败 |
| test_doctor.py | 5 | 从扫描到修改再诊断的真实临时仓库流程、跨根误用、错误输入、自包含复制、Skill 资源 |
| test_runtime_hardening.py | 18 | 证据错形、旧规则冲突、静态配置、分支/提交/index/链接漂移、短写、验证失败、worktree、Git 钩子、预算与非有限数 |

本机 Python 3.9.6 和随附 Python 3.12.14 均运行 Harness Doctor 回归。现有 ql-skill-usage-auditor 35 项、ql-schedule-night-shifts 7 项、xhs-cover-director 34 项在随附 Python 环境全部通过，无跳过；共计 204 个不同测试用例。

验证命令（从此专用 worktree 根运行）：

```bash
python3 -B -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -v
python3 -B ql-harness-doctor/scripts/validate_catalog.py --json
python3 -B ql-skill-usage-auditor/scripts/validate_skill.py ql-harness-doctor
PYTHONPYCACHEPREFIX=/tmp/harness-doctor-pycache python3 -m py_compile ql-harness-doctor/scripts/*.py
git diff --check
```

CLI 在当前 worktree 做只读 smoke scan：成功、32 个候选文件、策略内完成，无错误。这个结果只是验证扫描可用，没有伪造本仓库的语义诊断或效率收益。

附加的 skill-creator quick_validate 工具因本机缺少其 PyYAML 依赖而不能运行；未安装额外依赖。已使用仓库自带的零依赖结构验证器，并在端到端测试检查入口、元数据、资源存在与独立目录调用。GitHub Actions 已配置 Python 3.9/3.12，尚未推送触发远端运行，不能声称远端 CI 已通过。

## 审查结果与限制

按正确性、可维护性、模块边界、安全和资源预算审查，补齐了错形证据、跨仓库报告误用、不能自动修复的冲突、预览体积和 JSON 数值溢出防线。新增测试先暴露拒绝行为缺失，再实现防护；未跳过断言或降低已有测试门槛。

- 语义判断由调用此 Skill 的 Agent 作出。端到端使用人工构造的判断输入，证明协议和安全行为，不等于独立真人/另一 Agent 已评估诊断准确率。真实项目的语义校准属于后续迭代，不影响调用链交付。
- 只支持 macOS/Linux 所需的 POSIX 安全文件接口，Windows 不静默降级。当前本地验证环境为 macOS；Linux 由已接入的 CI 负责后续验证。
- 取证启发式不能识别所有秘密；摘录、扫描和命令解析都有明确预算/白名单。无法验证不是缺失，元数据或文档存在不是能力已满足。
- 修改只新建/追加允许的 Harness 工件，不覆盖、不删除、不安装依赖、不改业务/CI、不联网、不创建 L4 自治循环。静态检查不执行生成脚本或项目测试。
- 清单摘要不是认证机制；用户仍须在看到完整预览后明确最终确认。并发/IO异常可能部分应用，不自动回滚；不适合与恶意本机进程对抗。
- 原始研究文件、固定来源和控制目录语义未因实现方便而改写；来源扩展机制已记录，未来 OpenAI/Anthropic/论文来源尚未收录。

## Git 与交付范围

所有实现位于专用 worktree `qqling-skills-harness-doctor`、分支 `codex-xxxx-harness-doctor-research`。未在主工作区编辑代码，未全局安装、推送或合并。临时仓库用于测试，未将原始抓取副本、缓存、个人数据或测试生成物加入 Git。

原控制目录人工审阅项保留历史，但用户已明确要求继续实现；不再以该项暂停本次工作。本记录完成实现交付，不代表代替用户批准下一次仓库补强。
