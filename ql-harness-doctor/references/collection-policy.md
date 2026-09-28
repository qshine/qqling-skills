# 单仓库取证策略 0.1.0

## 根、边界与保密

只接受显式 Git 工作区根（根下有普通 .git 目录或文件），不向上寻找仓库、不访问同级仓库。支持普通工作区与 linked worktree，拒绝根 .git 链接、文件系统根和用户主目录。POSIX 安全目录句柄是运行前提；Windows 返回平台不支持，不降级到跟随链接的扫描。

取证器不联网、不启动子进程、不导入项目、不调用 Git。普通 .git 只安全有界读取 HEAD/index 的 SHA-256；worktree 的指针不打开。Git 工作区状态恒为 unverifiable，不能称为 clean。预览阶段另有固定 Git 元数据查询，两者权限不同。

排除规则以 scripts/collect_evidence.py 的 EXCLUDED_NAMES/excluded 为准：.git、依赖/构建/缓存、logs、凭据目录、.env*（包括 example）、包含 secret/credential/private-key 的名称、密钥/日志/数据库扩展名。路径含控制字符、绝对路径、遍历片段或疑似敏感信息时不输出原名。链接、硬链接、跨设备、特殊文件、嵌套 .git 仓库不进入正文扫描。

允许正文也检查常见凭据赋值、私钥、长访问令牌、认证 URL 和本机个人目录；命中后 withheld_sensitive，不输出正文、命令或内容哈希。检测是启发式，不能保证任何格式秘密都被识别；高保密仓库应先由用户清理允许文档或不调用扫描。stdout 会进入 Agent 上下文，不能称为内容不离开本机。

## 候选与正文

文件命中类别只代表发现依据；普通业务源码不读。正文默认允许下列命中文档的 md/mdx/rst/txt；其他后缀只有明确白名单可读。

| 类别 | 名称/位置发现规则 | 额外正文白名单 |
| --- | --- | --- |
| agent_instruction | AGENTS.md、CLAUDE.md、.cursorrules；rules/.agents/.claude 目录 | .cursorrules、规则目录的 .mdc |
| project_documentation | README/CONTRIBUTING 前缀、docs 目录 | 无 |
| architecture_decision | 名称含 architect/adr/decision，adr/decisions 目录 | 无 |
| task_state | spec/plan/todo/progress/handoff/feature_list/constraints 前缀、tasks/.harness 目录 | 对应前缀 .json；tasks/.harness 下 .json |
| package_manifest | package.json、pyproject.toml、Cargo.toml、go.mod、pom.xml、Gemfile | 这些文件 |
| toolchain | .python-version、.node-version、.nvmrc、.tool-versions、rust-toolchain.toml | 这些文件 |
| task_runner | Makefile、justfile、Taskfile.yml | 这些文件 |
| verification | 名称含 test/pytest/eslint/ruff/mypy/tsconfig/check，tests/test/checks 目录 | pytest.ini、tox.ini、ruff.toml、mypy.ini、tsconfig.json、.eslintrc.json；测试代码仅元数据 |
| ci_configuration | .github/workflows 下 | .yml/.yaml |
| automation | 名称含 automat/workflow/schedule/workspace | automation.yaml/yml、workspace.json、schedule.yaml/yml |
| observability | 名称含 observ/telemetry/logging/metric | logging.yaml/yml、observability.yaml/yml、telemetry.json |
| maintenance | 名称含 maintenan/cleanup/hygiene | maintenance.yaml/yml、hygiene.json |

package.json 仅解析顶层 scripts 的静态名称，Makefile/justfile 仅简单目标；声明 executed 恒为 false。任意 JSON/YAML 不因后缀可读。无支持的命令解析器时，不猜测命令结构或运行结果。

## 固定预算与限制

10,000 个目录项、256 个候选、深度 12、单正文 65,536 字节、正文总计 2 MiB、单文件 120 行、单行 400 字符、总摘录 64,000 字符、单份 Git 元数据 8 MiB。超预算先停止读取/枚举再报告，过大目录整体跳过，避免依赖不稳定抽样。

lines 保留原行号；sha256 对完整允许文件计算，摘录截断不等于哈希截断。有限摘录在 excerpt_truncated 表示；策略排除不算遍历失败。资源限制、应读正文读取失败或扫描漂移令 complete_within_policy=false；语义判断仍需考虑其余 content_unavailable 和策略排除。

扫描非原子快照；不会自动保存报告、缓存、日志或数据库。不保证 atime 不变。应用前必须重新验证，且不支持与持续并发写入或恶意本机进程对抗。
