# Stage-Harness

阶段化 AI 开发 Harness：在 Claude Code 中把模糊需求走成 **IDEA → CLARIFY → SPEC → PLAN → EXECUTE → VERIFY → DONE**（含 **FIX** 回路）的端到端流水线，配合 `harnessctl` 门禁、产物校验与 slash 命令编排。

更完整的概念与目录说明见 [docs/README.md](docs/README.md)；命令与流程细节见 [docs/usage.md](docs/usage.md)。使用 **`claude --plugin-dir <本仓库根>`** 加载插件时，启动 Epic 请用 **`/stage-harness:harness-start`**（编排见 `commands/harness-start.md`）。

---

## 当前已具备的核心能力

- **阶段化开发闭环**：已具备 `IDEA -> CLARIFY -> SPEC -> PLAN -> EXECUTE -> VERIFY -> DONE` 主链，以及 `FIX -> VERIFY` 回路。
- **结构化分析产物**：CLARIFY / PLAN / VERIFY / DONE 会落 `domain-frame.json`、`impact-scan.md`、`scenario-coverage.json`、`decision-bundle.json`、`verification.json`、`delivery-summary.md`、`release-notes.md` 等产物，而不是只停留在对话里。
- **阶段门禁与自检**：已支持 `stage-gate check`、`clarify-selfcheck`、`verify-artifacts.sh`，可以在推进阶段前做结构校验与阻断。
- **多仓基础能力**：已支持 `workspace_mode`、`repo-catalog`、`cross-repo-impact-index.json`、`surface-routing.json`，具备 multi-repo 工作区的影响扫描与路由基础。
- **复用资产基础**：已支持 `memory/pitfalls.md`、`memory/codemaps/*`、`codemap-audit`，可以沉淀热点模块认知并检查 CodeMap 是否 stale。
- **验证与交付闭环**：已支持 `verification.json`、验收议会、返工回路，以及 `delivery-summary.md` / `release-notes.md` 交付产物。

## 当前正在补强

- **执行证据链**：已有 `execution-trace.jsonl` 和 trace 事件基础，但完整 session archive / audit 视图仍在继续完善。
- **用户关注点闭环**：已支持 `Focus Points` / `focus-points.json` 校验，但从 CLARIFY 贯穿到 TASK / TEST / VERIFY 的完整闭环仍在增强。
- **候选技能与度量**：已具备 `skill-miner`、candidate-skills、`scan-metrics.json`、`scan-roi.jsonl` 基础，但完整自学习闭环与更宽的成功率指标仍在 roadmap 中。

完整演进方向见 [docs/roadmap.md](docs/roadmap.md)。

---

## 安装与环境

1. **加载本插件**：将整个仓库作为 Claude Code 插件根目录（含 `.claude-plugin/plugin.json`）。使用 Claude CLI 时通过 **`--plugin-dir`** 指向本仓库根目录即可，例如：
   ```bash
   claude --plugin-dir /opt/agent-delivery-claude/stage-harness
   ```
   请将路径换成本机克隆位置；非交互/打印模式同样需要携带该参数。`plugin.json` 里 **`name` 为 `stage-harness`**，slash 命名空间为 **`/stage-harness:`**，启动 Epic 时在对话中输入 **`/stage-harness:harness-start <需求描述>`**（编排说明见 `commands/harness-start.md`）。
2. 为脚本加上执行权限：
   ```bash
   chmod +x scripts/harnessctl.py scripts/*.sh
   ```
3. 若未把 `harnessctl` 装进系统 `PATH`，在**被开发项目的根目录**设置 `HARNESSCTL`，指向插件内的 CLI（按布局二选一）：
   ```bash
   # 被开发项目与插件目录分离时（推荐写绝对路径，与 --plugin-dir 指向同一克隆）
   export HARNESSCTL=/opt/agent-delivery-claude/stage-harness/scripts/harnessctl
   # 若你使用仓库内的 Python 入口，也可 export …/scripts/harnessctl.py

   # 被开发仓库把本插件作为子目录 stage-harness/ 时
   # export HARNESSCTL="${HARNESSCTL:-./stage-harness/scripts/harnessctl}"
   ```
4. 首次使用 **`/stage-harness:harness-start`** 时会初始化项目下的 `.harness/`（也可手动执行 `$HARNESSCTL init`）。

---

## Slash 命令一览

在对话中使用以下命令（阶段为流水线中的位置；具体行为以各 `commands/harness-*.md` 为准）：

| 命令 | 阶段 | 说明 |
|------|------|------|
| `/stage-harness:harness-start` | IDEA→CLARIFY | 启动 Epic：初始化、画像、创建 Epic、进入 CLARIFY |
| `/stage-harness:harness-clarify` | CLARIFY | 需求澄清、影响扫描、决策包、门禁 |
| `/stage-harness:harness-spec` | SPEC | Decision Bundle → ShipSpec → 轻量议会 |
| `/stage-harness:harness-plan` | PLAN | Bridge、表面研究、任务 DAG、覆盖矩阵、Plan 议会 |
| `/stage-harness:harness-work` | EXECUTE | 按任务执行：锚定→预检→TDD→冒烟→提交与回执 |
| `/stage-harness:harness-review` | VERIFY | 并行审查、对抗性审查、验收议会 |
| `/stage-harness:harness-fix` | FIX | 按 `verification.json` 修复后回到 VERIFY |
| `/stage-harness:harness-done` | DONE | Release 议会、交付包、经验沉淀、技能挖掘 |
| `/stage-harness:harness-patch` | 任意 | 即时纠偏：诊断偏差、规则补丁草稿与热加载 |
| `/stage-harness:harness-auto` | 全阶段 | 自治循环推进直至 DONE |
| `/stage-harness:harness-status` | 任意 | 只读：Epic、阶段、预算、任务进度 |
| `/stage-harness:harness-bridge` | PLAN | ShipSpec → 深度计划的 Bridge 脚本 |

> **兼容说明**：若安装方式将插件注册为短名 `harness`，对话里也可能显示为 `/harness:*`；钩子与下文示例中的 **`/stage-harness:harness-*`** 会被等价识别，编排均以 `commands/harness-*.md` 为准。

---

## 典型使用方式

### 手动逐阶段

1. `/stage-harness:harness-start <需求描述>` — 创建 Epic 并停在 CLARIFY。
2. 按需执行 `/stage-harness:harness-clarify` → `/stage-harness:harness-spec` → `/stage-harness:harness-plan` → `/stage-harness:harness-work` → `/stage-harness:harness-review`。
3. 审查不通过时用 `/stage-harness:harness-fix`，再 `/stage-harness:harness-review`。
4. 通过后 `/stage-harness:harness-done` 收尾。

### 自治模式

```text
/stage-harness:harness-start 我想给系统加一个通知模块
/stage-harness:harness-auto
```

`/stage-harness:harness-auto` 会按当前阶段循环执行对应推进逻辑，并在 EXECUTE / VERIFY / FIX 间自动处理，直到 DONE。

### 运行受阻时（JIT 纠偏）

中断会话后可用 `/stage-harness:harness-patch <epic-id>` 生成规则补丁草稿，再配合 `/stage-harness:harness-auto <epic-id>` 热加载后继续。

---

## CLI 速查（`harnessctl`）

在项目根设置好 `HARNESSCTL` 后：

```bash
$HARNESSCTL status
$HARNESSCTL state get <epic-id>
$HARNESSCTL task list <epic-id>
$HARNESSCTL stage-gate check CLARIFY   # 各阶段名：SPEC、PLAN、VERIFY 等
$HARNESSCTL clarify-selfcheck --epic-id <epic-id>
$HARNESSCTL profile detect
```

多仓、`codemap`、`metrics`、门禁跳过等进阶用法见 [docs/usage.md](docs/usage.md) 的「状态查看」与「常见问题」。

---

## 仓库布局（与使用相关）

| 路径 | 作用 |
|------|------|
| `commands/` | 各 `/stage-harness:harness-*` slash 的编排说明（与 `commands/harness-*.md` 一一对应） |
| `agents/` | 专业 Agent 角色定义 |
| `skills/` | 可复用技能（如 clarify、plan、council） |
| `hooks/` | SessionStart、PreToolUse 等钩子 |
| `scripts/` | `harnessctl`、`verify-artifacts.sh`、`decision-bundle.sh` 等 |
| `templates/` | `project-profile.yaml`、`repo-catalog.yaml` 等模板 |
| `docs/` | 使用指南、架构与人类协作说明 |
| `tests/` | 测试（若有变更脚本行为，可在此补充用例） |

运行时产物落在**被开发仓库**的 `.harness/` 下（配置、Epic、`features/<epic-id>/` 等），不在本插件目录内。

---

## 延伸阅读

- [docs/README.md](docs/README.md) — 架构分层、七阶段表、Decision Bundle / 预算 / 议会、`.harness` 目录树  
- [docs/usage.md](docs/usage.md) — 安装细节、各命令流程与产物、FAQ  
- [docs/architecture.md](docs/architecture.md) — 实现与模块关系  
- [docs/human-workflow-and-orchestration.md](docs/human-workflow-and-orchestration.md) — 人类协作与编排注意点  
- [docs/roadmap.md](docs/roadmap.md) — 中长期功能规划、优先级与实施方向
