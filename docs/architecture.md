# Stage-Harness 架构与实现细节

## 状态机

### 阶段定义

```python
STAGES = ["IDEA", "CLARIFY", "SPEC", "PLAN", "EXECUTE", "VERIFY", "FIX", "DONE"]
```

### 转移规则

```python
TRANSITIONS = {
    "IDEA":    ["CLARIFY"],
    "CLARIFY": ["SPEC"],
    "SPEC":    ["PLAN"],
    "PLAN":    ["EXECUTE"],
    "EXECUTE": ["VERIFY", "PLAN"],      # 可回退到 PLAN
    "VERIFY":  ["FIX", "DONE"],         # 审查不通过进 FIX，通过进 DONE
    "FIX":     ["VERIFY", "PLAN"],      # 修复后回 VERIFY，或回退到 PLAN
    "DONE":    [],                       # 终态
}
```

```
IDEA ──→ CLARIFY ──→ SPEC ──→ PLAN ──→ EXECUTE ──→ VERIFY ──→ DONE
                                ↑          ↑           ↓
                                └──────────┴─── FIX ←──┘
```

### state.json 结构

每个 Epic 在 `.harness/features/<epic-id>/state.json` 中维护状态：

```json
{
  "epic_id": "sh-1-rbac",
  "current_stage": "CLARIFY",
  "interrupt_budget": 2,
  "interrupts_used": 0,
  "created_at": "2026-04-01T00:00:00Z",
  "updated_at": "2026-04-01T00:00:00Z",
  "stage_history": [
    {"from": "IDEA", "to": "CLARIFY", "at": "2026-04-01T00:00:00Z"}
  ],
  "skipped_gates": []
}
```

### 状态转移执行

```bash
harnessctl state transition sh-1-rbac SPEC
```

执行步骤：
1. 加载当前 state.json
2. 验证 `current_stage → to` 是否在 TRANSITIONS 中合法
3. 更新 `current_stage`、`updated_at`、追加 `stage_history`
4. 原子写入 state.json

---

## 扫描与知识分层（profile-driven）

多仓或大仓场景下，插件按 **画像驱动** 缩圈，避免全工作区盲扫。逻辑上分三层（与 `multi-repo scan optimization` 方案一致）：

| 层 | 产物 | 作用 |
|----|------|------|
| 索引与契约 | `.harness/repo-catalog.yaml`（multi-repo）、`.harness/features/<epic-id>/cross-repo-impact-index.json` | 先定「哪些仓、哪些契约」再下钻 |
| 路由与预算 | `.harness/project-profile.yaml` 中 `workspace_mode` 与 `scan.*`、`.harness/features/<epic-id>/surface-routing.json` | 限定路径、`repo_id`、`dive_strategy`、`scan_budget`、`evidence_level` |
| 知识与回源 | `.harness/memory/codemaps/<repo_id>/*.md` | 热点模块摘要；非真相源，冲突时以源码与契约为准 |

CLARIFY 中 `impact-analyst` 负责 `impact-scan.md`；multi-repo 时另写 `cross-repo-impact-index.json`。Lead / `project-surface` 生成 `surface-routing.json`。PLAN 各 scout 默认只在该路由与 codemap 提示范围内工作。VERIFY 的 reviewer 优先审查路由内 diff，避免对未登记范围全仓 Grep。

---

## harnessctl.py CLI 参考

核心 CLI，约 2370 行纯 Python（零外部依赖），管理 `.harness/` 目录的所有操作。

### 全局选项

```
harnessctl [--project-root PATH] <command> [options]
```

`--project-root`：指定项目根目录，默认从当前目录向上搜索 `.harness/`。

### 命令总览

| 命令 | 子命令 | 说明 |
|------|--------|------|
| `init` | — | 初始化 `.harness/` 目录 |
| `config` | `get`, `set`, `list` | 管理 config.json |
| `profile` | `detect`, `show`, `discover-repo-aliases` | 项目画像检测、查看与多仓别名启发式补全 |
| `epic` | `create`, `show`, `list`, `set-worktree` | Epic 管理 |
| `task` | `create`, `start`, `done`, `fail`, `block`, `show`, `list`, `next` | 任务管理 |
| `state` | `get`, `transition`, `patch`, `next` | 状态机操作 |
| `stage-gate` | `check` | 阶段门禁检查 |
| `receipt` | `write`, `show`, `list` | 执行回执管理 |
| `council` | `run`, `aggregate` | 议会运行与投票聚合 |
| `memory` | `append-pitfalls`, `codemap-probe` | 经验沉淀与 CodeMap 陈旧度探针 |
| `triage` | — | 问题分诊 |
| `budget` | `check`, `consume` | 中断预算管理 |
| `guard` | `check` | 守卫检查（门禁+预算+确认） |
| `bundle` | `summary`, `pending-confirms`, `check-confirmed` | 决策包查询 |
| `coverage` | `map`, `show` | 覆盖矩阵管理 |
| `gate` | `skip` | 跳过阶段门禁 |
| `skill` | `list`, `show`, `promote`, `archive` | 技能管理 |
| `status` | — | 总览状态 |
| `validate` | — | 目录完整性校验 |
| `patch` | `diagnose`, `apply`, `promote` 等 | 即时纠偏与系统进化 |

### 命令详细参考

#### init

```bash
harnessctl init [--force] [--json]
```

创建 `.harness/` 及子目录：`surfaces/`, `features/`, `epics/`, `specs/`, `tasks/`, `memory/`。
写入默认 `config.json` 和 `project-profile.yaml`。

#### config

```bash
harnessctl config get <key> [--json]
harnessctl config set <key> <value> [--json]
harnessctl config list [--json]
```

默认配置：

```json
{
  "version": "4.3",
  "risk_level": "medium",
  "interrupt_budget": 2,
  "auto_advance": false,
  "council_required": true
}
```

#### profile

```bash
harnessctl profile detect [--json]
harnessctl profile show [--json]
harnessctl profile discover-repo-aliases [--write] [--json]
```

`detect` 根据标志文件自动检测项目类型：

| 标志文件 | 类型 |
|---------|------|
| `package.json` | frontend |
| `go.mod` | backend |
| `setup.py` / `pyproject.toml` | library |
| `Dockerfile` | backend |
| `*.tf` | infra |

`discover-repo-aliases`：读取 `.harness/repo-catalog.yaml`，按各 `repos[].path` 扫描根目录下的 `package.json` / `go.mod` / `Cargo.toml` / `pyproject.toml` / `pom.xml`，将发现的包名与模块前缀**合并**进 `package_aliases`、`import_prefixes`；默认仅打印/输出 JSON，加 `--write` 写回目录。

#### memory

```bash
harnessctl memory append-pitfalls --epic-id <id> [--json]
harnessctl memory codemap-probe <path-to-codemap.md> [--write] [--json]
```

- `append-pitfalls`：把 `unknowns-ledger.json` 中高影响 CLARIFY 条目追加到 `memory/pitfalls.md`。
- `codemap-probe`：解析 CodeMap 前置 YAML（须含 `source_paths`），在**项目根**的 Git 仓库内比较 `verified_commit` 与 `HEAD` 之间列出的路径是否变化；`stale` 时进程退出码为 1。`--write` 会写入 `codemap_probe_at`、`codemap_stale`，并在陈旧时将 `confidence` 降为 `low`。未设置 `verified_commit` 时不判陈旧（退出码 0），仅提示需设定基线。

#### epic

```bash
harnessctl epic create <title> [--json]
harnessctl epic show <id> [--json]
harnessctl epic list [--json]
harnessctl epic set-worktree <id> <path> [--branch <branch>] [--json]
```

Epic ID 格式：`sh-<N>-<slug>`（如 `sh-1-rbac-permission`）。
创建时自动在 `features/<epic-id>/` 下初始化 `state.json`。

#### task

```bash
harnessctl task create <epic-id> <title> [--surface <surface>] [--json]
harnessctl task start <task-id> [--json]
harnessctl task done <task-id> [--json]
harnessctl task fail <task-id> [--json]
harnessctl task block <task-id> [--json]
harnessctl task show <task-id> [--json]
harnessctl task list <epic-id> [--status <status>] [--json]
harnessctl task next --epic-id <id> [--json]
```

任务 ID 格式：`sh-<N>.<M>`（如 `sh-1.3`）。
任务状态：`pending`, `in_progress`, `done`, `failed`, `blocked`。
`next` 返回下一个可执行（pending 且依赖已满足）的任务。

#### state

```bash
harnessctl state get <id> [--json]
harnessctl state transition <id> <STAGE> [--json]
harnessctl state patch <id> --set <key=value> [--set <key=value>] [--json]
harnessctl state next --epic-id <id> [--json]
```

`transition` 会校验转移合法性。
`patch` 用于更新 state.json 中的任意字段（如 `interrupts_used`）。
`next` 返回自治模式下建议执行的下一步动作。

#### stage-gate

```bash
harnessctl stage-gate check <STAGE> --epic-id <id> [--json]
```

检查指定阶段的必需产物和关键语义门禁是否齐全。

产物定义：

```python
STAGE_GATE_ARTIFACTS = {
    "CLARIFY": [
        "{features_dir}/domain-frame.json",
        "{features_dir}/generated-scenarios.json",
        "{features_dir}/scenario-coverage.json",
        "{features_dir}/challenge-report.md",
        "{features_dir}/clarification-notes.md",
        "{features_dir}/impact-scan.md",
        "{features_dir}/surface-routing.json",
        "{features_dir}/unknowns-ledger.json",
        "{features_dir}/decision-bundle.json",
        "{features_dir}/decision-packet.json",
    ],
    "SPEC": [
        ".harness/specs/{epic_id}.md",
        "{features_dir}/spec-council-notes.md",
        "{features_dir}/scenario-coverage.json",
    ],
    "PLAN": [
        "{features_dir}/bridge-spec.md",
        "{features_dir}/coverage-matrix.json",
        "{features_dir}/surface-routing.json",
    ],
    "EXECUTE": [
        "{features_dir}/receipts",
    ],
    "VERIFY": [
        "{features_dir}/verification.json",
    ],
    "DONE": [
        "{features_dir}/delivery-summary.md",
        "{features_dir}/release-notes.md",
        "{features_dir}/councils/verdict-release_council.json",
    ],
}
```

其中 `{features_dir}` = `.harness/features/<epic-id>`。

**CLARIFY** 另校验：`clarification-notes.md` 须含 `Domain Frame` / `领域框架` 标题；`challenge-report.md` 须含 `## Summary`；`domain-frame.json` 须含约定键名；`generated-scenarios.json` 与 `scenario-coverage.json` 须为有效 JSON 且包含 `scenarios` 数组；`impact-scan.md` 须含 `## Blast Radius Summary` / `## High Impact Surfaces` / `## Medium Impact Surfaces`；`surface-routing.json` 须为有效 JSON 且 `surfaces` 为非空数组、每项含 `type` 与 `path`。若 `.harness/project-profile.yaml` 中 `workspace_mode: multi-repo`，还须存在有效的 `cross-repo-impact-index.json`（含 `repos` 数组）。

**PLAN**：除表内文件外，`surface-routing.json` 须仍存在（与 CLARIFY 一致），供 scouts 强约束。

**SPEC**：`spec_semantic_hints_strict` 为 `true` 时，`_spec_semantic_warnings` 的提示会记入 `missing`；默认仅 stderr 提示。

**VERIFY**：`verification.json` 内 `code_review` / `logic_review` / `test_review` / `security` / `spec_compliance` 若**存在**且值为 `FAIL`，门禁失败；并与 `acceptance_council` / `council_verdict`、`critical_issues` 一并校验；验收未写入 JSON 时可读 `verdict-acceptance_council.json` 兜底。

**DONE**：`councils/verdict-release_council.json` 须存在且 `verdict` 为 `RELEASE_READY` 或 `RELEASE_WITH_CONDITIONS`。

#### receipt

```bash
harnessctl receipt write <task-id> [--base-commit <sha>] [--head-commit <sha>] [--smoke-passed true|false] [--json]
harnessctl receipt show <task-id> [--json]
harnessctl receipt list <epic-id> [--json]
```

回执存储在 `.harness/features/<epic-id>/receipts/` 目录下。

#### council

```bash
harnessctl council run <council_type> --epic-id <id> [--json]
harnessctl council aggregate <council_type> --epic-id <id> [--json]
```

4 种议会类型及成员：

```python
COUNCIL_AGENTS = {
    "light_council": ["challenger", "requirement-analyst", "impact-analyst"],
    "plan_council": ["code-reviewer", "security-reviewer", "logic-reviewer",
                     "test-reviewer", "plan-reviewer"],
    "acceptance_council": ["code-reviewer", "logic-reviewer", "security-reviewer",
                           "test-reviewer", "runtime-auditor"],
    "release_council": ["logic-reviewer", "security-reviewer", "runtime-auditor"],
}
```

#### config.json 扩展项

| 键 | 类型 | 说明 |
|----|------|------|
| `spec_semantic_hints_strict` | bool | 默认 `false`。为 `true` 时，`stage-gate check SPEC` 将 `_spec_semantic_warnings` 的每条提示视为阻断。 |

#### budget

```bash
harnessctl budget check --epic-id <id> [--json]
harnessctl budget consume --epic-id <id> [--json]
```

`check` 返回预算剩余情况。
`consume` 消耗 1 次中断预算（更新 `interrupt_budget.consumed` / `remaining`）。

风险等级→预算映射：

| risk_level | interrupt_budget |
|-----------|-----------------|
| low | 1 |
| medium | 2 |
| high | 3 |

#### guard

```bash
harnessctl guard check --epic-id <id> [--stage <STAGE>] [--json]
```

综合检查：阶段门禁 + 预算余量 + Decision Packet 确认状态。自治模式每次循环前调用。

#### bundle

```bash
harnessctl bundle summary --epic-id <id> [--json]
harnessctl bundle pending-confirms --epic-id <id> [--json]
harnessctl bundle check-confirmed --epic-id <id> [--json]
```

查询 `decision-bundle.json` 和 `decision-packet.json` 的状态。

#### coverage

```bash
harnessctl coverage map --epic-id <id> [--reset] [--json]
harnessctl coverage show --epic-id <id> [--json]
```

管理 `coverage-matrix.json`，映射需求→任务的覆盖关系。

#### gate

```bash
harnessctl gate skip <STAGE> --epic-id <id> [--justification <text>] [--json]
```

将指定阶段加入 `skipped_gates` 列表，跳过门禁检查。

#### skill

```bash
harnessctl skill list [--json]
harnessctl skill show <skill-id> [--json]
harnessctl skill promote <skill-id> [--json]
harnessctl skill archive <skill-id> [--reason <text>] [--json]
```

管理候选技能的生命周期。

#### status

```bash
harnessctl status [--json] [--check-init]
```

`--check-init`：仅检查 `.harness/` 是否已初始化。

#### validate

```bash
harnessctl validate [--json]
```

校验 `.harness/` 目录结构完整性。

---

## Shell 脚本参考

### decision-bundle.sh

**路径**：`scripts/decision-bundle.sh`

管理决策包的 CRUD 操作。

```bash
decision-bundle.sh generate <epic-id>    # 从 clarification-notes 生成初始 bundle
decision-bundle.sh add <epic-id>         # 交互添加决策条目
decision-bundle.sh status <epic-id>      # 查看 bundle 状态摘要
decision-bundle.sh resolve <epic-id> <decision-id>  # 标记决策为 resolved
decision-bundle.sh packet <epic-id>      # 提取 must_confirm → decision-packet.json
```

**Decision Bundle JSON 结构**：

```json
{
  "epic_id": "sh-1-xxx",
  "decisions": [
    {
      "id": "DEC-001",
      "type": "must_confirm",
      "description": "是否需要多角色支持？",
      "proposed_default": "单角色",
      "status": "pending",
      "resolved_value": null
    }
  ]
}
```

**Decision Packet**（`decision-packet.json`）：仅包含 `must_confirm` 且 `status=pending` 的决策子集，供中断预算机制使用。

### unknowns-ledger-update.sh

**路径**：`scripts/unknowns-ledger-update.sh`

管理未知问题台账。

```bash
unknowns-ledger-update.sh init <epic-id>          # 初始化空台账
unknowns-ledger-update.sh add <epic-id>            # 添加未知条目
unknowns-ledger-update.sh resolve <epic-id> <id>   # 标记为 resolved
unknowns-ledger-update.sh status <epic-id>         # 查看台账状态
unknowns-ledger-update.sh sift <epic-id>           # 将 resolved 条目沉淀到 memory/pitfalls.md
```

**Unknowns Ledger JSON 结构**：

```json
{
  "epic_id": "sh-1-xxx",
  "unknowns": [
    {
      "id": "UNK-001",
      "description": "用户角色是单个还是数组？",
      "discovered_at": "CLARIFY",
      "impact": "high",
      "resolution": "resolved",
      "resolution_note": "代码分析确认为单个 string 字段",
      "blocks": ["REQ-001"]
    }
  ]
}
```

### bridge-shipspec-to-deepplan.sh

**路径**：`scripts/bridge-shipspec-to-deepplan.sh`

在 PLAN 阶段将 ShipSpec 规格说明转化为深度实现计划。读取 `.harness/specs/<epic-id>.md`，输出 `.harness/features/<epic-id>/bridge-spec.md`。

### verify-artifacts.sh

**路径**：`scripts/verify-artifacts.sh`

验证指定阶段的必需产物是否齐全。与 `harnessctl stage-gate check` 保持同步，作为独立脚本供钩子和命令调用。

```bash
verify-artifacts.sh <epic-id> [STAGE]
```

### council-runner.sh

**路径**：`scripts/council-runner.sh`

议会运行脚本，协调多 Agent 投票流程。

### smoke-check.sh / smoke_test.sh

**路径**：`scripts/smoke-check.sh`, `scripts/smoke_test.sh`

冒烟测试脚本，在 EXECUTE 阶段每个任务完成后运行基础健全性检查。

---

## 钩子系统

定义在 `hooks/hooks.json`，共 6 个钩子点：

### SessionStart

**脚本**：`hooks/scripts/session-start.sh`

会话开始时自动执行：
- 检测是否有活跃 Epic
- 输出当前阶段、预算余量、健康状态上下文
- 帮助 Agent 快速恢复上下文

### UserPromptSubmit

**脚本**：`hooks/scripts/stage-reminder.sh`

每次用户输入前执行：
- 输出当前阶段提醒
- 帮助 Agent 保持阶段感知

### PreToolUse (Bash)

**脚本**：`hooks/scripts/pre-tool-use.sh`

**Matcher**：`Bash`（仅在 Bash 工具调用前触发）

拦截危险命令：
- `git reset --hard`
- `rm -rf /`
- `DROP TABLE`
- 其他高风险 shell 操作

### Stop

**脚本**：`hooks/scripts/stop.sh`

会话结束时执行：
- 为每个活跃 Epic 生成 `handoff.md`
- 记录当前阶段、进度、待办事项
- 确保下次会话可以无缝恢复

### TaskCompleted

**脚本**：`hooks/scripts/task-completed.sh`

任务完成时触发后处理逻辑。

### TeammateIdle

**脚本**：`hooks/scripts/teammate-idle.sh`

队友空闲时触发通知处理。

---

## 产物体系

### 阶段→产物映射（完整）

| 阶段 | 产物路径 | 说明 |
|------|---------|------|
| **CLARIFY** | `features/<epic>/domain-frame.json` | 领域框架（domain-scout） |
| | `features/<epic>/generated-scenarios.json` | 场景展开（scenario-expander） |
| | `features/<epic>/scenario-coverage.json` | 语义归并场景台账（Lead） |
| | `features/<epic>/challenge-report.md` | 挑战报告 |
| | `features/<epic>/clarification-notes.md` | 需求澄清备忘录 |
| | `features/<epic>/impact-scan.md` | 影响扫描报告 |
| | `features/<epic>/surface-routing.json` | 承载面路由与扫描预算（project-surface / Lead；**门禁必备**） |
| | `features/<epic>/unknowns-ledger.json` | 未知问题台账 |
| | `features/<epic>/decision-bundle.json` | 决策包 |
| | `features/<epic>/decision-packet.json` | 待确认决策包 |
| **SPEC** | `specs/<epic-id>.md` | 规格说明书 |
| | `features/<epic>/spec-council-notes.md` | 规格议会审查记录 |
| | `features/<epic>/scenario-coverage.json` | 场景覆盖（与 CLARIFY 同源，SPEC 门禁复验） |
| **PLAN** | `features/<epic>/bridge-spec.md` | Bridge 规格→计划 |
| | `features/<epic>/coverage-matrix.json` | 需求覆盖矩阵 |
| | `features/<epic>/surface-routing.json` | 与 CLARIFY 一致，PLAN 门禁复验 |
| **EXECUTE** | `features/<epic>/receipts/` | 任务执行回执目录 |
| **VERIFY** | `features/<epic>/verification.json` | 审查验证结果 |
| **DONE** | `features/<epic>/delivery-summary.md` | 交付摘要 |
| | `features/<epic>/release-notes.md` | 发布说明 |

### 辅助产物（非门禁要求）

| 产物 | 说明 |
|------|------|
| `features/<epic>/surface-map.md` | 需求→文件路由图（project-surface-router；Lead 据此生成 `surface-routing.json`） |
| `features/<epic>/cross-repo-impact-index.json` | multi-repo 时结构化仓级/契约索引（`workspace_mode: multi-repo` 时 CLARIFY 门禁必备） |
| `features/<epic>/requirements-draft.md` | 需求草案 |
| `features/<epic>/deep-dive-*.md` | 深度调查备忘录 |
| `features/<epic>/handoff.md` | 会话交接备忘录 |
| `memory/pitfalls.md` | 经验沉淀 |

---

## Council 系统

### 工作机制

1. `harnessctl council run --type <type>` 启动议会，输出参与 Agent 列表
2. 编排层调用各 Agent 进行独立审查/投票
3. `harnessctl council aggregate --type <type>` 聚合投票结果
4. 根据投票结果决定是否通过

### 4 种议会

#### light_council（轻量议会）

- **阶段**：CLARIFY→SPEC 过渡
- **成员**：challenger, requirement-analyst, impact-analyst
- **职责**：审查规格说明的完整性和一致性

#### plan_council（计划议会）

- **阶段**：PLAN
- **成员**：code-reviewer, security-reviewer, logic-reviewer, test-reviewer, plan-reviewer
- **职责**：审查任务计划的合理性、安全性、可测试性

#### acceptance_council（验收议会）

- **阶段**：VERIFY
- **成员**（与 `skills/council/SKILL.md` 一致）：code-reviewer, logic-reviewer, security-reviewer, test-reviewer, runtime-auditor
- **职责**：多维度验收审查

#### release_council（发布议会）

- **阶段**：DONE
- **成员**（与 `skills/council/SKILL.md` 一致）：logic-reviewer, security-reviewer, runtime-auditor；高风险可追加 code-reviewer
- **职责**：最终发布审查

---

## Agent 角色清单

共 23 个 Agent，按职能分组：

### CLARIFY 阶段 Agent

| Agent | 说明 |
|-------|------|
| `lead-orchestrator` | 总编排器，协调 CLARIFY 各环节 |
| `domain-scout` | 领域/产品侧预分析（不读代码）→ `domain-frame.json`，CLARIFY 必经 Step 0 |
| `scenario-expander` | 基于 `domain-frame.json` 展开高风险场景 → `generated-scenarios.json` |
| `requirement-analyst` | 分解 Epic 为结构化需求（REQ-xxx） |
| `impact-analyst` | 扫描代码库受影响范围，评估爆炸半径；必要时可在 agent 内部基于阈值做 2-4 路并行 fan-out，最终汇总为单份 `impact-scan.md` |
| `challenger` | 魔鬼代言人，压力测试假设和需求 |
| `project-surface-router` | 将需求映射到具体文件路径 |
| `deep-dive-specialist` | 深度调查歧义需求，产出澄清备忘录 |

### PLAN 阶段 Agent（表面研究）

| Agent | 说明 |
|-------|------|
| `repo-router` | 仓库结构导航，定位相关模块 |
| `docs-scout` | 搜索项目文档和注释 |
| `design-scout` | 搜索设计模式和架构约定 |
| `config-scout` | 搜索配置文件和环境变量 |
| `symbol-navigator` | 符号级代码导航（函数、类、接口） |
| `dependency-mapper` | 依赖关系映射 |

### 审查 Agent

| Agent | 说明 |
|-------|------|
| `code-reviewer` | 代码质量审查 |
| `security-reviewer` | 安全漏洞审查 |
| `logic-reviewer` | 业务逻辑正确性审查 |
| `test-reviewer` | 测试覆盖和质量审查 |
| `quality-auditor` | 综合质量审计 |
| `plan-reviewer` | 计划合理性审查 |

### 其他 Agent

| Agent | 说明 |
|-------|------|
| `worker` | 任务执行者，TDD 开发循环 |
| `release-reviewer` | 发布就绪审查 |
| `runtime-auditor` | 运行时行为审计 |
| `skill-miner` | 从交付中提取可复用候选技能 |

---

## Skill 清单

共 18 个 Skill：

| Skill | 说明 |
|-------|------|
| `auto` | 自治模式运行逻辑 |
| `bridge-spec` | ShipSpec→深度计划桥接 |
| `clarify` | CLARIFY 阶段执行逻辑 |
| `council` | 议会运行与聚合 |
| `decision-bundle` | 决策包管理 |
| `impact-scan` | 影响扫描执行 |
| `interrupt-budget` | 中断预算管理 |
| `memory` | 经验沉淀与回忆 |
| `plan` | PLAN 阶段执行逻辑 |
| `project-profile` | 项目画像检测与管理 |
| `project-surface` | 项目表面分析 |
| `review` | VERIFY 阶段审查逻辑 |
| `runtime-harness` | 运行时 harness 管理 |
| `skill-evolution` | 技能生命周期管理 |
| `spec` | SPEC 阶段执行逻辑 |
| `stage-gate` | 阶段门禁检查逻辑 |
| `work` | EXECUTE 阶段工作逻辑 |
| `worktree` | Git worktree 管理 |

---

## 模板文件

`templates/` 目录提供产物模板：

| 模板 | 用途 |
|------|------|
| `candidate-skill.md` | 候选技能模板 |
| `council-verdict.json` | 议会裁决数据模板（运行时会按 `councils/verdict-<type>.json` 落盘） |
| `coverage-matrix.json` | 覆盖矩阵模板 |
| `decision-bundle.json` | 决策包模板 |
| `decision-packet.json` | 决策包（待确认）模板 |
| `delivery-summary.md` | 交付摘要模板 |
| `epic-spec.md` | Epic 规格模板 |
| `impact-scan.md` | 影响扫描模板 |
| `interrupt-budget.json` | 中断预算模板 |
| `project-profile.yaml` | 项目画像模板 |
| `repo-catalog.yaml` | 多仓目录与别名（`workspace_mode: multi-repo`） |
| `cross-repo-impact-index.json` | 跨仓影响与契约索引（multi-repo 时 CLARIFY 校验） |
| `surface-routing.json` | 承载面路由与扫描预算（CLARIFY/PLAN 门禁） |
| `codemap-module.md` | 热点模块 CodeMap 笔记模板 |
| `release-notes.md` | 发布说明模板 |
| `runtime-receipt.json` | 任务回执数据模板（运行时 canonical 路径为 `receipts/<task-id>.json`） |
| `task-spec.md` | 任务规格模板 |
| `unknowns-ledger.json` | 未知台账模板 |

---

## 目录结构与文件路径约定

### 插件目录

```
stage-harness/
├── .claude-plugin/
│   └── plugin.json          # 插件清单
├── agents/                  # 23 个 Agent 定义
│   ├── lead-orchestrator.md
│   ├── requirement-analyst.md
│   ├── ...
│   └── worker.md
├── commands/                # 11 个阶段命令
│   ├── harness-start.md
│   ├── harness-clarify.md
│   ├── harness-spec.md
│   ├── harness-plan.md
│   ├── harness-work.md
│   ├── harness-review.md
│   ├── harness-fix.md
│   ├── harness-done.md
│   ├── harness-auto.md
│   ├── harness-status.md
│   └── harness-bridge.md
├── skills/                  # 18 个 Skill
│   ├── auto/SKILL.md
│   ├── clarify/SKILL.md
│   ├── ...
│   └── worktree/SKILL.md
├── hooks/
│   ├── hooks.json           # 钩子定义
│   └── scripts/             # 钩子脚本
│       ├── session-start.sh
│       ├── stage-reminder.sh
│       ├── pre-tool-use.sh
│       ├── stop.sh
│       ├── task-completed.sh
│       └── teammate-idle.sh
├── scripts/                 # 核心脚本
│   ├── harnessctl.py        # 核心 CLI（~2370 行）
│   ├── harnessctl           # CLI 入口脚本
│   ├── decision-bundle.sh
│   ├── unknowns-ledger-update.sh
│   ├── bridge-shipspec-to-deepplan.sh
│   ├── verify-artifacts.sh
│   ├── council-runner.sh
│   ├── smoke-check.sh
│   └── smoke_test.sh
├── templates/               # 产物模板
│   └── ...
└── docs/                    # 文档
    ├── README.md
    ├── usage.md
    ├── architecture.md
    ├── adapters.md
    └── project-profiles.md
```

### .harness/ 运行时目录

```
.harness/
├── config.json              # 全局配置
├── project-profile.yaml     # 项目画像
├── surfaces/                # 表面分析缓存
├── features/
│   └── sh-N-slug/           # 每个 Epic 独立目录
│       ├── state.json
│       ├── clarification-notes.md
│       ├── impact-scan.md
│       ├── unknowns-ledger.json
│       ├── decision-bundle.json
│       ├── decision-packet.json
│       ├── surface-map.md
│       ├── bridge-spec.md
│       ├── coverage-matrix.json
│       ├── verification.json
│       ├── delivery-summary.md
│       ├── release-notes.md
│       └── receipts/
├── epics/                   # Epic 元数据
│   └── sh-N-slug.json
├── specs/                   # 规格说明书
│   └── sh-N-slug.md
├── tasks/                   # 任务
│   └── sh-N-slug.M.json
└── memory/                  # 经验沉淀
    └── pitfalls.md
```

### 路径变量约定

脚本和命令中使用的路径变量：

| 变量 | 展开值 |
|------|--------|
| `${CLAUDE_PLUGIN_ROOT}` | 插件安装目录（如 `~/.claude/plugins/stage-harness`） |
| `{features_dir}` | `.harness/features/<epic-id>`（harnessctl 内部） |
| `{epic_id}` | Epic ID（如 `sh-1-rbac`） |
