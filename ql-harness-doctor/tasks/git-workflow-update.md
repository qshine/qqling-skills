# 2026-09-09：Git 工作流检查增补

## 授权与范围

用户明确要求新增两条检查并完成本次修改后的 Git 提交；另调研厂商文章，其他候选须再次确认后才纳入 Skill。本记录是已批准要求的增补与验收，不重新开启 Spec 审批，也不表示用户已验收研究候选。

- 本任务新 Worktree：`qqling-skills-harness-doctor-git-policy`。
- 分支：`codex-xxxx-harness-doctor-git-policy`；修改前基线：`3b28d76661c6ddecb234df099b0f8c080881d4ff`。
- 不改主工作区或原研究 Worktree，不修改其他 Skill、README、CI、来源原章或取证/应用脚本。
- 新建 Worktree 和完成后提交按独立修改任务计算；同一未完成任务续做可复用其专用 Worktree；纯只读/无文件变化不制造空操作。

## 实现与兼容性

两条分别归入 HD-SCP-001（L2）和 HD-STA-004（L3），作为可独立说明的强制子检查，不新增重复计分项。目录为 0.2.0、schema 为 1.0.0、书籍来源注册表仍为 0.1.0；控制数 46、章节别名数 74 均不变。两项 requirement 明确记录用户来源和日期，避免错误归因。旧目录报告需重新诊断。

Python 继续只读取证，Agent 负责语义判断；测试中的合成判断不是对真实仓库执行合规的证明。SKILL 与工作流要求按 [规则文件](../references/git-workflow-policy.md) 检查执行证据；没有证据不能仅凭 `.git` 文件或 SHA 字符串给满分。实际补强的 Worktree 准备在最终文件预览前完成，换根重新诊断；相称验证和本地提交由 Agent 在授权范围内单独执行，不给扫描器或 apply 增加 Git 写能力。

## 验证记录

- 先写 4 项回归，初次运行出现预期的版本/旧报告拒绝断言失败；修改控制目录后 4 项通过。
- `python3 -B -m unittest discover -s ql-harness-doctor/tests -p 'test_*.py' -q`：Python 3.9 与 3.12 各 132 项通过。
- `python3 -B ql-harness-doctor/scripts/validate_catalog.py --json`：通过。
- `python3 -B ql-skill-usage-auditor/scripts/validate_skill.py ql-harness-doctor`：通过。
- Python 3.12 下其他三个 Skill 的 76 项回归通过（35 + 7 + 34）。未安装新依赖。
- Python 语法、Git 差异空白和本轮文档本地链接检查通过；研究候选 R01–R08 连续且不进入运行时目录。
- 回归分别覆盖：两项用户规则与版本/不重复计分、Worktree 缺口阻塞 L2 且可补强、提交缺口阻塞 L3 且进入建议、旧目录报告不可复用。

自审保留原 HD-SCP-001 的范围/非目标/工作上限证据；只加强用户要求，没有删除原约束。实现没有新增依赖、网络调用或自动 Git 写入；只改目录数据、指令、对应 Spec/计划和回归。主工作区与原研究 Worktree 均保持干净。此为本地自审，不冒充独立人工验收。

历史 MVP 验收保留其原始日期和计数；本轮不宣称验证了实际用户使用 Skill 时的模型遵循率、所有历史任务的工作区创建顺序或远端 CI。

## 研究交接

[厂商文章研究与候选清单](../research/openai-anthropic-harness-2026-09-09.md) 存于 research/，不在 Skill 的默认资料路由中，也未注册为目录来源。该文区分已有覆盖、建议细化、条件性新能力和不建议照搬的做法。下一步只等待用户选择候选；未获确认前不更新检查规则、门槛、源注册表或取证权限。

本任务提交 SHA 在交付消息与 Git 历史中记录，不在该提交内自引用它自己的 SHA。未推送、合并或全局安装。
