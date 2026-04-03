---
description: "执行需求澄清全流程（含 domain-scout 前置 + 并行分析 + 决策分类 + 中断预算）"
argument-hint: "<epic-id>"
---

# harness-clarify

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，先解析本地 CLI 路径：

```bash
if [ -z "${HARNESSCTL:-}" ]; then
  candidates=(
    "./stage-harness/scripts/harnessctl"
    "../stage-harness/scripts/harnessctl"
    "$(git rev-parse --show-toplevel 2>/dev/null)/stage-harness/scripts/harnessctl"
  )

  for candidate in "${candidates[@]}"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      HARNESSCTL="$candidate"
      break
    fi
  done
fi

test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "harnessctl not found. Set HARNESSCTL=/abs/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


> **⚠️ CRITICAL CONSTRAINTS — 本命令严格遵守以下规则，不得违反：**
>
> 1. **禁止跨阶段生成内容**：在 CLARIFY 阶段，严禁生成任何规格文档（PRD、SDD、spec、技术设计、接口设计）。这些内容属于 SPEC 阶段，必须通过 `/harness:spec` 命令生成。
> 2. **must_confirm 必须打断用户**：Decision Bundle 中所有 `must_confirm` 类决策，**必须呈现给用户并等待回复**，不得自行假设答案。用户回复前，流程处于暂停状态。
> 3. **每个产物必须通过指定脚本生成**：不得手动写入格式不兼容的产物文件。各产物的生成命令见下方各步骤。
> 4. **通过 stage-gate check 才算完成**：未通过 `$HARNESSCTL stage-gate check CLARIFY` 的 CLARIFY 阶段**不算完成**，禁止推进到 SPEC。若 `.harness/config.json` 中 `clarify_closure_mode` 为 `notes_only`，门禁仅校验 `clarification-notes.md` 的六轴/极简绕行与闭环结构（见 `docs/usage.md`）。

---

## 角色定义

CLARIFY 阶段 orchestrator。按 `harness:clarify` skill 执行（**domain-scout 为每次必经 Step 0**），维护中断预算，通过指定脚本输出标准化产物。不跳过任何步骤，不自行决定 must_confirm 项的答案。

---

## 前置检查

### 1. 确认初始化

```bash
$HARNESSCTL status
```

若无 `.harness/` 目录，提示运行 `/harness:start`，终止。

### 2. 确定 epic-id

- 若 `$ARGUMENTS` 包含 epic-id，直接使用。
- 若无 epic-id，列出活跃 epic 供选择：
  ```bash
  $HARNESSCTL epic list
  ```
  等待用户选择后继续。

### 3. 检查中断预算

```bash
$HARNESSCTL budget check --epic-id <epic-id>
```

- 若返回 `EXHAUSTED`（退出码 1）：告知用户预算已用完，展示当前 Decision Bundle 状态后终止。

### 4. Lead 路由：闭环模式与极简 Epic

执行步骤前：

1. 查看 `.harness/config.json` 中 `clarify_closure_mode`（缺省为 `full`）；亦可 `$HARNESSCTL config list`。
2. **`full`**：`unknown` / 待确认须进入 `unknowns-ledger.json`、`decision-bundle.json`、`decision-packet.json`（与下列 Step 3+ 一致）。
3. **`notes_only`**：同一 Epic 的 UNK、`must_confirm`、覆盖摘要可**全部**写在 `clarification-notes.md` 编号列表中，**不**要求为本 run 单独创建孤立 JSON；门禁以 `stage-gate check CLARIFY` 对 notes 的结构校验为准。
4. **极简澄清绕行**（Chore：纯文案、拼写、样式 token、依赖 bump、仅 README 等，**无**业务逻辑/持久化/API/权限/多入口/线上行为）：在 `clarification-notes.md` 增加 `## 极简澄清绕行`，声明六轴 **全局 `not_applicable` + 一句总理由**；仍须有 Domain Frame 类小节，并在同一文件声明「无待确认」或列出待确认项。凡涉及逻辑或对外行为的 Epic **禁止**使用该绕行。

可选自检：`$HARNESSCTL clarify-selfcheck --epic-id <epic-id>`（不阻断，供人工核对）。

---

## 执行步骤

**REQUIRED SKILL:** Use `harness:clarify` skill

### Step 0 — 领域预分析（domain-scout，必选）

在结合代码库做影响扫描之前执行：

- 调度 **`domain-scout`**：仅基于 Epic 描述、`project-profile.yaml`、可选领域标签；**不读代码仓库**。
- 产出 **`.harness/features/<epic-id>/domain-frame.json`**（轻量 JSON，字段见 `agents/domain-scout.md`）。
- Lead 将摘要写入 `clarification-notes.md` 的 **`## Domain Frame`** 或 **`## 领域框架`** 小节（可与后续 Q&A 合并编辑，但门禁要求该标题存在）。

### Step 1 — 需求澄清（Q&A）

通过对话式分析，把原始需求转化为结构化澄清笔记。重点提取：
- 核心功能诉求（用户真正要什么）
- 背景上下文（为什么，谁用）
- 已知约束（不能做什么）
- 初始假设列表

**产物写入：**

```bash
# 产物路径：.harness/features/<epic-id>/clarification-notes.md
# 由 Agent 直接写入（Markdown 格式，无脚本依赖）
```

clarification-notes.md 必须包含：
- 需求背景（1-3 段）
- 核心功能诉求列表
- 初始代码调查结论（如适用）
- 初始假设列表（将在后续步骤细化）
- **`## 六轴澄清覆盖`**（每轴 `covered` | `not_applicable` | `unknown` + 简短说明）**或** 已判定的 **`## 极简澄清绕行`**（全局 `not_applicable` + 总理由）
- **`## Unknowns 与待确认决策`**（编号列出 UNK / DEC / must_confirm，或明确写「本轮无待确认」）

### Step 2 — 影响扫描（代码库扫描）与并行需求/挑战/场景展开

**影响扫描**：分析需求影响到哪些模块、文件、接口。重点识别：
- 直接需要修改的模块（HIGH 变更概率）
- 间接受影响的模块（MEDIUM）
- 可能需要测试覆盖的路径

`impact-analyst` 读取 `project-profile.yaml`（含 `workspace_mode`、`scan.max_repos_deep_scan`、`scan.max_files_deep_read_per_scout`、`scan.max_subagents_wave`）后：

- **多仓**（`workspace_mode: multi-repo`）：先对照 `.harness/repo-catalog.yaml` 做契约优先的 **Phase A**，写出 **`cross-repo-impact-index.json`**；深扫仓数不得超过 `max_repos_deep_scan`，超出须在 `impact-scan.md` 的 Risk Flags 中要求 Lead/用户收敛后再深扫。
- **单仓 / monorepo**：沿用 map → scatter → gather；若首轮 map 命中 **3+ 主要模块/目录**、或 `risk_level=high`、或 broad/systemic，可在**自身内部**使用并行 subagents，且受上述 `scan.*` 预算约束。

对外仍只产出 **一份** 汇总后的 `impact-scan.md`（multi-repo 时另有一份 **`cross-repo-impact-index.json`**），不改变 CLARIFY 顶层的四角色并行契约。

**产物写入：**

```bash
# 产物路径：.harness/features/<epic-id>/impact-scan.md
# multi-repo 时同目录：cross-repo-impact-index.json（见 stage-harness/templates/cross-repo-impact-index.json）
# 由 Agent 直接写入（Markdown / JSON，无脚本依赖）
```

impact-scan.md 必须包含：
- `## High Impact Surfaces`（必须修改的模块 + 具体文件路径）
- `## Medium Impact Surfaces`（可能受影响的模块）
- `## Blast Radius Summary`（一句话总结影响范围）

**与本步并行（同一批次）**：

- **`requirement-analyst`**：输入含 `domain-frame.json` → `requirements-draft.md`
- **`challenger`**：输入含 `domain-frame.json` → **`challenge-report.md`**（须含 `## Summary`）
- **`scenario-expander`**：输入含 `domain-frame.json` → **`generated-scenarios.json`**

**沉淀规则**：`challenge-report.md` 中 **Critical Challenges** 与 **Warnings** 须在后续步骤进入 `unknowns-ledger.json`（`unknowns-ledger-update.sh add`）或 `decision-bundle.json`（`decision-bundle.sh add`），不得仅停留在报告中。**若 `clarify_closure_mode=notes_only`**，等价信息须写入 `clarification-notes.md` 的 **Unknowns 与待确认决策** 小节，编号可追溯即可。

### Step 2.5 — 语义归并（Semantic Reconciliation）

在初始化 unknowns 台账之前，Lead 应基于 `domain-frame.json`、`generated-scenarios.json`、`requirements-draft.md`、`challenge-report.md` 做一次语义闭合：

- 识别高/中置信度 `SCN-xxx` 中尚未落到 REQ/CHK 或决策的语义缝隙与组合冲突。
- 每个高/中置信度场景须映射到 REQ/CHK，或写入 **DEC/UNK**；不得仅留在 JSON。
- 产出 `.harness/features/<epic-id>/scenario-coverage.json`，记录 `SCN-xxx` 的 `covered | needs_decision | deferred | dropped_invalid` 状态和映射去向。
- 在 `clarification-notes.md` 增加 **语义归并** 或 **Semantic Reconciliation** 小节（可与 Traceability 合并），便于 `harnessctl stage-gate check CLARIFY` 在开启 `spec_semantic_hints_strict` 时识别闭合证据。

### Step 3 — 补盲（识别未知项）

针对 Step 1-2 发现的不确定点，整理未知问题台账。

**产物初始化：**

```bash
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/unknowns-ledger-update.sh init <epic-id>
```

对每个发现的未知项，创建临时 JSON 文件后写入 ledger：

```bash
# 每个 unknown 写为 /tmp/unk-XXX.json，格式：
# {
#   "id": "UNK-001",
#   "description": "...",
#   "discovered_at": "CLARIFY",
#   "impact": "high|medium|low",
#   "classification": "blocker|deferrable|assumable"
# }
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/unknowns-ledger-update.sh add <epic-id> /tmp/unk-XXX.json
```

### Step 4 — 收敛（去重归一）

检视 Step 3 的 unknowns-ledger，合并重复项，提升关键问题的优先级：

```bash
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/unknowns-ledger-update.sh status <epic-id>
```

若发现重复或派生问题，用 `resolve` 关闭次要项：

```bash
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/unknowns-ledger-update.sh resolve <epic-id> <unk-id> "merged into UNK-XXX"
```

### Step 5 — 承载面缩圈（边界确认）

根据 `impact-scan.md`（及 multi-repo 时的 `cross-repo-impact-index.json`）将需求范围圈定到最小必要集合：
- 明确哪些功能在范围内（in-scope）
- 明确哪些功能在范围外（out-of-scope）
- 更新 `clarification-notes.md` 末尾追加「范围边界」章节
- 按 `skills/project-surface/SKILL.md` 生成或更新 **`surface-routing.json`**（`repo_id`、`dive_strategy`、`scan_budget`、`evidence_level`），供 PLAN / VERIFY 约束扫描与审查范围

```bash
# 更新 clarification-notes.md（追加章节，不覆盖前文）
# surface-routing.json：.harness/features/<epic-id>/surface-routing.json
```

### Step 6 — 深挖（关键不确定项深入分析）

对 unknowns-ledger 中 `impact=high` 的 blocker 类问题，做专项代码调查：
- 读取相关代码文件
- 确认技术可行性
- 更新对应 unknown 的 `resolution` 或 `classification`

```bash
# 对已找到答案的 unknown：
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/unknowns-ledger-update.sh resolve <epic-id> <unk-id> "<调查结论>"
```

---

## Decision Bundle 构建

完成上述步骤（含 Step 2.5 语义归并）后，将所有剩余 unknowns 分类为三类决策并写入 Decision Bundle：

### 初始化 bundle

```bash
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/decision-bundle.sh generate <epic-id>
```

### 逐一添加决策

对每个决策，创建临时 JSON 文件并添加：

```bash
# /tmp/dec-XXX.json 格式：
# {
#   "id": "DEC-001",
#   "question": "...",
#   "category": "must_confirm",   ← 或 "assumable" 或 "deferrable"
#   "options": ["A: ...", "B: ..."],
#   "proposed_default": "A",
#   "why_now": "blocks SPEC section X"
# }
#
# assumable 类额外字段：
#   "assumption": "自动采用的默认值/假设描述"
#
# deferrable 类额外字段：
#   "defer_to": "SPEC"

HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/decision-bundle.sh add <epic-id> /tmp/dec-XXX.json
```

分类规则：
- **`must_confirm`**：如果选错会导致方案根本性偏差，必须人工确认
- **`assumable`**：有合理默认值，假设错了成本低，可自动采用后记录在案
- **`deferrable`**：不影响当前阶段推进，可延后到 SPEC/PLAN 处理

### 生成 Decision Packet（must_confirm 打包）

```bash
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/decision-bundle.sh packet <epic-id>
```

此命令生成 `decision-packet.json`，内含所有 `must_confirm` 类问题。

---

## ⛔ MANDATORY USER INTERRUPT（用户中断 — 必须等待回复）

检查 must_confirm 数量：

```bash
$HARNESSCTL bundle pending-confirms --epic-id <epic-id>
```

**如果 must_confirm > 0：**

> **必须停止并向用户展示以下内容，等待用户回复后才能继续。不得自行选择答案。**

展示格式：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔔 CLARIFY 完成 — 需要您确认 N 项决策后才能继续
   （此为第 M 次中断，预算剩余 R 次）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[DEC-001] <问题描述>
  ▸ 选项 A: <描述>
  ▸ 选项 B: <描述>
  推荐: <推荐选项及理由>
  影响: <如果选错会发生什么>

[DEC-002] ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
请回复每项决策的选择（如：DEC-001=A, DEC-002=B）
回复后流程将自动继续到 SPEC 阶段。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**等待用户回复。收到回复前，不执行任何后续步骤。**

用户回复后：

```bash
# 消耗一次中断预算
$HARNESSCTL budget consume --epic-id <epic-id>

# 对每个已确认的决策调用 resolve：
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/decision-bundle.sh resolve <epic-id> DEC-001 "用户选择: A"
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/decision-bundle.sh resolve <epic-id> DEC-002 "用户选择: B"

# 同步到 unknowns-ledger（将对应 unknown 标记为已解决）：
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/unknowns-ledger-update.sh resolve <epic-id> <unk-id> "<用户决策结论>" CLARIFY
```

**如果 must_confirm == 0：**

所有决策均为 assumable/deferrable，无需打断用户，直接继续。

---

## 产物验证（Gate Check）

运行阶段门禁检查：

```bash
$HARNESSCTL stage-gate check CLARIFY --epic-id <epic-id>
```

检查项（以 `$HARNESSCTL stage-gate check CLARIFY` 为准）：

- **`clarify_closure_mode=full`（默认）**：`domain-frame.json`、`generated-scenarios.json`、`challenge-report.md`（含 `## Summary`）、`clarification-notes.md`（含 **Domain Frame / 领域框架 / 需求上下文** 标题，且含六轴或极简绕行 + Unknowns 闭环）、`impact-scan.md`、`scenario-coverage.json`、`surface-routing.json`、`unknowns-ledger.json`、`decision-bundle.json`、`decision-packet.json`；多仓时尚需 `cross-repo-impact-index.json`。
- **`clarify_closure_mode=notes_only`**：仅 **`clarification-notes.md`** 须存在且通过 CLI 内置结构校验（六轴表或极简绕行、闭环小节）。

**若任意检查项失败，报告缺失文件或校验错误并停止，不得推进到 SPEC。**

---

## 展示 CLARIFY 完成汇总

Gate 通过后，展示完成摘要：

```bash
$HARNESSCTL bundle summary --epic-id <epic-id>
HARNESS_DIR=.harness ${CLAUDE_PLUGIN_ROOT}/scripts/unknowns-ledger-update.sh status <epic-id>
$HARNESSCTL budget check --epic-id <epic-id>
```

输出：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ CLARIFY 完成 — <epic-id>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
决策分类：
  must_confirm : X 项（已全部确认）
  assumable    : Y 项（已记录假设）
  deferrable   : Z 项（延后处理）

未知项台账：
  High   : A 项
  Medium : B 项
  Low    : C 项

中断预算：已消耗 M / 总计 N 次，剩余 R 次

下一步：运行 /harness:spec <epic-id>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 出口条件（门禁规则）

| 条件 | 检查方式 |
|------|---------|
| clarify skill 全部步骤完成（含 domain-scout） | 产物文件均存在 |
| CLARIFY 门禁产物齐全 | `$HARNESSCTL stage-gate check CLARIFY` 通过 |
| 所有 must_confirm 已处理 | `$HARNESSCTL bundle check-confirmed` 返回 OK |
| 未生成任何 SPEC 级产物 | 无 `.harness/specs/<epic-id>.md` 文件 |

---

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| 中断预算耗尽 | 保存已完成产物，对所有剩余 must_confirm 应用 `proposed_default`，输出警告后继续 |
| unknowns-ledger-update.sh init 失败 | 检查 `${CLAUDE_PLUGIN_ROOT}/scripts/` 路径和执行权限 |
| decision-bundle.sh 命令失败 | 展示完整错误信息，检查 JSON 格式，不继续 |
| Gate check 失败 | 列出缺失文件，提示补充对应步骤，不允许继续 |
| 用户未回复 must_confirm | 流程保持暂停，下次 `/harness:clarify <epic-id>` 时从用户中断点恢复 |
