---
description: "从模糊需求启动 stage-harness 全流程（PROJECT_PROFILE → CLARIFY → SPEC → PLAN）"
argument-hint: "<模糊需求描述>"
---

# harness-start

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


从一句模糊需求出发，自动完成项目画像识别、epic 创建、需求澄清、规格定义、实施计划生成全流程。

## 角色定义

Lead orchestrator，负责编排整个启动流程。不直接实现任何阶段逻辑——所有阶段工作通过委托给对应 skill 完成。仅负责：状态检查、参数传递、阶段推进、最终状态展示。

## 前置检查

1. 确认 `harnessctl` 可用：
   ```bash
   $HARNESSCTL --version
   ```
   若不可用，提示用户安装并终止。

2. 若 `.harness/` 不存在，自动初始化：
   ```bash
   $HARNESSCTL init
   ```

## 执行步骤

### Step 1：格式化模糊需求

将 `$ARGUMENTS` 解构为标准格式：

```
一句话目标：[从参数提炼]
已知约束：[从参数中识别，若无则标注"待澄清"]
期望交付物：[从参数中识别，若无则标注"待澄清"]
已知不确定项：[从参数中识别，若无则标注"待澄清"]
```

### Step 2：识别项目画像

```bash
$HARNESSCTL profile detect
```

输出项目类型（web-app / cli / library / data-pipeline / etc）、技术栈、复杂度估算。

### Step 3：创建 Epic

从格式化需求中提取标题（不超过 60 字符），创建 epic：

```bash
$HARNESSCTL epic create "<需求标题>"
```

记录返回的 `epic-id`，后续所有步骤均以此 epic-id 为上下文。

### Step 4：需求澄清（CLARIFY）

**REQUIRED SKILL:** Use `harness:clarify` skill with:
- `epic-id`: 上一步创建的 epic-id
- `requirements`: 格式化后的需求文本

等待 skill 完成，检查返回的 Decision Bundle：
- 若 `must_confirm` 数量 > 0，**暂停**，向用户展示待确认决策列表，等待用户逐一确认或标注为 assumable。
- 若 `must_confirm` = 0，自动继续 Step 5。

### Step 5：规格定义（SPEC）

**REQUIRED SKILL:** Use `harness:spec` skill with:
- `epic-id`: epic-id
- 传入已处理的 Decision Bundle

等待 skill 完成，检查阶段门禁：
```bash
$HARNESSCTL stage-gate check SPEC --epic-id <epic-id>
```
- 若通过，自动继续 Step 6。
- 若有阻断项，展示阻断原因，暂停等待用户干预。

### Step 6：实施计划（PLAN）

**REQUIRED SKILL:** Use `harness:plan` skill with:
- `epic-id`: epic-id

等待 skill 完成。

### Step 7：展示最终状态

```bash
$HARNESSCTL status
```

输出格式：
```
Stage-Harness 启动完成
Epic: <epic-id> | <title>
当前阶段: PLAN ✓
已完成阶段: CLARIFY → SPEC → PLAN
下一步: 运行 /harness:work <epic-id> 开始开发
```

## 产物要求

| 产物 | 路径 |
|------|------|
| 项目画像 | `.harness/project-profile.yaml` |
| Epic 定义 | `.harness/epics/<epic-id>.json` |
| 领域框架 | `.harness/features/<epic-id>/domain-frame.json` |
| 挑战报告 | `.harness/features/<epic-id>/challenge-report.md` |
| 澄清笔记 | `.harness/features/<epic-id>/clarification-notes.md`（含 Domain Frame 章节） |
| 决策包 | `.harness/features/<epic-id>/decision-packet.json` |
| 规格文档 | `.harness/specs/<epic-id>.md` |
| 任务图谱 | `.harness/tasks/<epic-id>.*.json` |
| 覆盖矩阵 | `.harness/features/<epic-id>/coverage-matrix.json` |

## 出口条件（门禁规则）

- CLARIFY 门禁：`must_confirm` 全部处理完毕
- SPEC 门禁：`stage-gate check SPEC` 返回 PASS
- PLAN 门禁：`coverage-matrix.json` 存在且 coverage >= 80%

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| `harnessctl` 不可用 | 提示安装路径，终止 |
| profile detect 失败 | 降级为 generic 画像，继续执行 |
| epic create 失败 | 展示错误，终止 |
| CLARIFY skill 失败 | 保存已完成产物，提示用户手动重试 `harness:clarify` |
| 中断预算耗尽 | 停止自动推进，展示当前状态 |
