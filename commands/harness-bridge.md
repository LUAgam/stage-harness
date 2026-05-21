---
description: "ShipSpec → deep-plan 桥接（将规格产物合并为统一输入格式）"
argument-hint: "<epic-id>"
---

# harness-bridge

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


将 SPEC 阶段产物（PRD、SDD、TASKS、unknowns-ledger）桥接转换为 deep-plan 可接受的统一输入格式（bridge-spec.md），供 PLAN 阶段使用。

## 角色定义

SPEC→PLAN 桥接 orchestrator。负责验证 SPEC 产物完整性、运行桥接脚本、验证桥接输出。通常由 `harness-plan` 在 Step 1 自动调用，也可独立执行以单独验证或重新生成桥接文档。

## 前置检查

验证 SPEC 产物完整：

```bash
$HARNESSCTL stage-gate check SPEC --epic-id <epic-id>
```

必须满足：
- `.harness/specs/<epic-id>.md` 存在
- spec 文档包含验收标准章节

若检查失败，提示先完成 `/harness:spec <epic-id>`，终止。

## 执行步骤

**REQUIRED SKILL:** Use `bridge-spec` skill

向 skill 传入：
- `epic-id`
- `feature`: epic-id 对应的 ShipSpec feature 名称（如未传入，使用 epic-id）

skill 内部执行：

### Step 1：定位 ShipSpec 产物

查找以下路径（按优先级）：
1. `.shipspec/planning/<feature>/PRD.md`
2. `.harness/specs/<epic-id>.md`（fallback：使用 harness 原生规格）

### Step 2：运行桥接脚本

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/bridge-shipspec-to-deepplan.sh <feature> <epic-id>
```

脚本负责：
- 从 PRD.md 提取需求摘要与优先级
- 从 SDD.md 提取架构决策（如存在）
- 从 TASKS.json 提取任务清单（如存在）
- 从 unknowns-ledger.json 提取未闭环问题

输出到：`.harness/features/<epic-id>/bridge-spec.md`

### Step 2.5：保留完整验收标准（硬性）

bridge-spec.md 必须包含 `## Acceptance Criteria（完整验收标准）` 章节，该章节**逐条原文引用** `requirements-draft.md`（或 `.harness/specs/<epic-id>.md`）中每个 REQ/FR 的所有验收标准。

**格式要求**：

```markdown
## Acceptance Criteria（完整验收标准）

### FR-001 <标题>
1. <验收标准原文第1条>
2. <验收标准原文第2条>
...

### FR-002 <标题>
1. <验收标准原文第1条>
...
```

**禁止行为**：
- 禁止将多条验收标准压缩为一行括号摘要（如 `AC-001: 导出弹窗（标题动态、内容选择）`）
- 禁止省略任何验收标准条目，即使看似"显而易见"
- 禁止用自己的语言改写验收标准，必须保留原文

**为什么这是硬性要求**：bridge-spec 是 PLAN 和 EXECUTE 阶段的唯一输入源。验收标准中的 UI 文案、格式规则、交互行为细节一旦在此处丢失，下游所有阶段都无法恢复，导致实现与需求系统性偏差。

### Step 3：验证桥接输出

验证 bridge-spec.md 满足条件：
- 文件非空（> 100 bytes）
- 包含 `## Requirements` 章节
- 包含 `## Technical Design` 章节
- 包含 `## Acceptance Criteria（完整验收标准）` 章节
- Acceptance Criteria 章节中的 FR/REQ 条目数量 >= requirements-draft 中的 REQ 数量（允许合并但不允许减少）
- 若 unknowns-ledger 有 open 条目，确认 `## Open Unknowns` 章节存在

## 产物要求

| 产物 | 路径 |
|------|------|
| 桥接规格文档 | `.harness/features/<epic-id>/bridge-spec.md` |

`bridge-spec.md` 为**只读参考文档**，PLAN 阶段不直接修改它。ShipSpec 产物更新后重新运行此命令即可覆盖。

## 出口条件

- `bridge-spec.md` 存在且非空
- 包含 `## Requirements` 与 `## Technical Design` 章节
- 包含 `## Acceptance Criteria（完整验收标准）` 章节，且该章节逐条列出了所有 FR/REQ 的验收标准原文

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| SPEC 门禁未通过 | 终止，提示先完成规格阶段 |
| ShipSpec 产物不存在 | 使用 `.harness/specs/<epic-id>.md` 作为 fallback，输出警告 |
| 桥接脚本失败 | 展示详细错误，检查 `${CLAUDE_PLUGIN_ROOT}/scripts/` 路径与文件权限 |
| 桥接输出验证失败 | 展示缺失章节，提示手动检查 PRD/SDD 内容完整性 |
