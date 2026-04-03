# SKILL: runtime-harness

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


运行时 Harness 技能，定义持续控偏规则。在整个 EXECUTE 阶段持续运行，在 5 个检查点介入，确保实现不偏离 spec，证据完整，失败可追溯。

---

## 概述

runtime-harness 不是一个单独运行的阶段，而是嵌入到 `work/SKILL.md` 内循环的控偏层。每个检查点在特定时机触发，发现问题时立即阻断。

---

## 5 个检查点

---

### Checkpoint 1 — Preflight（任务开跑前）

**时机**：每个 task 的 Phase 2（Preflight 校验）

**校验内容**：

```
输入上下文完整性：
  - task JSON 可读且字段完整
  - spec 文件存在（.harness/specs/<epic-id>.md）
  - coverage-matrix.json 存在

依赖满足性：
  - task.dependencies 中所有 task_id 状态 = done

工作区状态：
  - git status 输出为 clean（无未追踪/未提交文件）
  - 或有明确的 stash/暂存理由

预算检查：
  - interrupt_budget.remaining > 0（否则需要人工授权）
```

**阻断条件**：任一项不满足。

---

### Checkpoint 2 — In-loop Eval（实现过程中漂移检测）

**时机**：Phase 3 实现阶段，GREEN 步骤完成后

**漂移检测（drift detection）**：

对比当前实现与 spec 中的约束：

```bash
# 读取 spec 中的不变量（invariants）
grep -A5 "## Invariants" .harness/specs/<epic-id>.md

# 读取 task acceptance_criteria
$HARNESSCTL task show <task-id> --json | jq '.acceptance_criteria'
```

检查：
1. 实现是否超出 task `acceptance_criteria` 范围？（scope creep）
2. 实现是否与 spec 中的不变量冲突？
3. 是否修改了计划外的文件？（`git diff --name-only` 对比 task 预期文件列表）

**失败计数**：每次测试失败（RED→GREEN 步骤）计数 +1，写入 epic state：

```json
"runtime_health": {
  "consecutive_failures": <n>,
  "drift_detected": <bool>,
  "last_smoke_pass": "<iso8601>"
}
```

**证据完整性**：验证实现产出了 task `evidence` 字段要求的所有文件。

**阻断条件**：
- `drift_detected = true`（实现偏离 spec）
- `consecutive_failures >= 3`

---

### Checkpoint 3 — Task Smoke（每个 task 完成后）

**时机**：Phase 4 Task Smoke

**最小可运行验证**：

```bash
# 运行 task 相关测试
<test-command> --filter <task-pattern>

# 验证证据文件
for evidence_file in $($HARNESSCTL task show <task-id> --json | jq -r '.evidence | to_entries[].value'); do
  test -f "$evidence_file" || echo "MISSING: $evidence_file"
done
```

**阻断条件**：
- 测试失败
- 证据文件缺失

**通过时**：更新 `runtime_health.last_smoke_pass`。

---

### Checkpoint 4 — Stage Smoke（EXECUTE 出口）

**时机**：所有 tasks 完成，准备转换到 VERIFY 前

**阶段级烟测**：

```bash
# 运行全量回归测试
<project-test-command>

# 验证所有 receipt 存在
for task_id in $($HARNESSCTL task list <epic-id> --json | jq -r '.[].id'); do
  test -f ".harness/features/<epic-id>/receipts/${task_id}.json" \
    || echo "MISSING RECEIPT: $task_id"
done

# 验证 coverage-matrix 的 mappings 全部有对应 receipt
```

**阻断条件**：
- 回归测试失败（smoke regression）
- 任何 task 缺少 receipt
- coverage-matrix 中的 mapping 没有对应证据

---

### Checkpoint 5 — Auto-Diagnose（失败时自动收集）

**时机**：任何检查点阻断时自动触发

**自动收集信息**：

```bash
# 1. 代码 diff
git diff HEAD~3..HEAD > .harness/features/<epic-id>/diag/diff-<timestamp>.patch

# 2. 最近测试日志
<test-command> 2>&1 | tail -100 > .harness/features/<epic-id>/diag/test-log-<timestamp>.txt

# 3. 环境摘要
node --version && npm --version && git log -3 --oneline \
  > .harness/features/<epic-id>/diag/env-<timestamp>.txt
```

**输出 triage 报告**：

```json
{
  "timestamp": "<iso8601>",
  "checkpoint": "<which-checkpoint>",
  "task_id": "<task-id>",
  "epic_id": "<epic-id>",
  "failure_reason": "<description>",
  "consecutive_failures": <n>,
  "diff_path": "<path>",
  "log_path": "<path>",
  "env_path": "<path>",
  "recommended_action": "local_fix | plan_patch | spec_patch | manual_review"
}
```

---

## 阻断条件汇总

以下任一条件满足时，runtime-harness 立即阻断当前 task 执行：

| 条件 | 来源检查点 |
|------|-----------|
| 任务目标与 spec 不一致（drift detected） | Checkpoint 2 |
| 依赖前置条件未满足 | Checkpoint 1 |
| 代码通过实现但未留下可验证 evidence | Checkpoint 3 |
| 连续失败超过阈值（3次） | Checkpoint 2 |
| 回归烟测失败 | Checkpoint 4 |

---

## 状态持久化

runtime-harness 的运行状态持久化到 epic state 的 `runtime_health` 字段：

```bash
# 读取当前 runtime health
$HARNESSCTL state get <epic-id> --json | jq '.runtime_health'

# 手动重置连续失败计数（修复后）
$HARNESSCTL state patch <epic-id> \
  --set runtime_health.consecutive_failures=0 \
  --set runtime_health.drift_detected=false
```
