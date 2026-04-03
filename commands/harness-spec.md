---
description: "规格定义（ShipSpec /feature-planning + 轻议会审查）"
argument-hint: "<epic-id>"
---

# harness-spec

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


基于 CLARIFY 产物生成规格文档。接入 ShipSpec 的 `/feature-planning` 能力，结合澄清阶段的 Decision Bundle，经轻议会审查后输出最终规格。

## 角色定义

SPEC 阶段 orchestrator。负责验证 CLARIFY 前置产物、转换 Decision Bundle 为规格输入、调度 spec skill 执行、编排轻议会审查。不直接编写规格内容——规格内容由 spec skill 产出。

## 前置检查

### 1. 验证 CLARIFY 产物完整

```bash
$HARNESSCTL stage-gate check CLARIFY --epic-id <epic-id>
```

若检查失败，展示缺失产物列表，提示先完成 `/harness:clarify <epic-id>`，终止。

### 2. 验证 must_confirm 已处理

解析 `decision-packet.json`，检查 `must_confirm` 列表：

```bash
$HARNESSCTL bundle check-confirmed --epic-id <epic-id>
```

若存在未处理的 `must_confirm` 项：
- 展示待处理列表
- 提示用户逐一确认或标注为 `assumable`
- 等待用户确认后继续

## 执行步骤

### Step 1：转换 Decision Bundle 为规格输入

将 `unknowns-ledger.json` 中的问题转写为规格条目：
- `unknowns` 中的高优先级项 → 规格中的约束条件
- `unknowns` 中的中优先级项 → 规格中的开放问题（待 spec 阶段处理）
- `deferrable` 决策 → 规格中的"超出当前范围"声明

### Step 2：生成规格文档

**REQUIRED SKILL:** Use `harness:spec` skill

向 skill 传入：
- `epic-id`
- `clarification_notes`: `.harness/features/<epic-id>/clarification-notes.md` 的内容
- `decision_bundle`: `decision-packet.json` 的内容
- `generated_scenarios`: `.harness/features/<epic-id>/generated-scenarios.json` 的内容（若存在）
- `scenario_coverage`: `.harness/features/<epic-id>/scenario-coverage.json` 的内容（若存在）
- `converted_spec_items`: Step 1 转换产出的规格条目

**重要限制：** 调用 ShipSpec `/feature-planning` 时，**禁止安装或激活**以下 3 个 Stop 钩子：
- `task-loop-hook.sh`
- `feature-retry-hook.sh`
- `planning-refine-hook.sh`

这 3 个钩子属于 ShipSpec 内部循环机制，在 stage-harness 上下文中会干扰 harness 自身的状态管理。

### Step 3：轻议会审查

召集轻议会的 3 个 reviewer 并行审查规格文档，各自独立产出意见：

| Reviewer 角色 | 审查维度 |
|-------------|---------|
| challenger | 是否存在冲突需求、范围蔓延或关键遗漏 |
| requirement-analyst | 需求覆盖是否完整、验收标准是否清晰 |
| impact-analyst | 影响面、依赖与高风险项是否被规格覆盖 |

汇总议会意见：
- CRITICAL 意见：必须修改后才能继续
- HIGH 意见：建议修改
- LOW 意见：记录在案，不阻断

若有 CRITICAL 意见，重新触发 spec skill 修订，最多 2 轮。

## 产物要求

| 产物 | 路径 |
|------|------|
| 规格文档 | `.harness/specs/<epic-id>.md` |
| 议会意见 | `.harness/features/<epic-id>/spec-council-notes.md` |
| 阶段门禁记录 | `.harness/features/<epic-id>/stage-gate-SPEC.json` |

`specs/<epic-id>.md` 必须包含：
- 功能需求（来自 clarification-notes）
- 非功能需求（来自 impact-scan）
- 验收标准（可测试、可量化）
- 超出范围声明（来自 deferrable 决策）
- 开放问题（中优先级 unknowns）
- 当 `generated-scenarios.json` / `scenario-coverage.json` 中存在高/中置信度且非 `dropped_invalid` 的 `SCN-xxx` 条目时，规格须包含与之对应的结构化场景或时序表达，并写清可验证的闭合行为；语义提示与严格模式由 `scripts/harnessctl.py` 的 `_spec_semantic_warnings` 与 `spec_semantic_hints_strict` 配置共同约束

## 出口条件（门禁规则）

```bash
$HARNESSCTL stage-gate check SPEC --epic-id <epic-id>
```

CLI 在 SPEC 门禁检查通过时，仍可能对规格打印 **语义提示**（stderr，**默认非阻断**），内容以结构化场景覆盖与 FR–AC 可追溯性为主；实现见 `scripts/harnessctl.py` 的 `_spec_semantic_warnings`。若在 `.harness/config.json` 设置 `"spec_semantic_hints_strict": true`，则上述提示会变为 **门禁失败项**。

通过条件：
- `specs/<epic-id>.md` 存在
- 规格文档包含验收标准章节
- 议会无未处理的 CRITICAL 意见
- 所有 unknowns-ledger 高优先级项均在规格中有对应条目

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| CLARIFY 门禁未通过 | 终止，提示先完成澄清阶段 |
| must_confirm 未处理 | 暂停，等待用户确认 |
| spec skill 失败 | 保留部分产物，报告失败原因 |
| 议会修订超过 2 轮 | 以当前版本继续，在门禁记录中标注 |
| ShipSpec Stop 钩子被意外激活 | 立即停用，输出警告 |
