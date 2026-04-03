---
description: "开发执行（Worker 循环：re-anchor→preflight→TDD→smoke→commit+receipt）"
argument-hint: "<epic-id 或 task-id>"
---

# harness-work

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


执行开发阶段。Worker 按 5 Phase 循环逐任务实现，生成 runtime receipt，直至所有任务完成或遇到阻断。

## 角色定义

EXECUTE 阶段 orchestrator。负责验证 PLAN 前置产物、确定执行任务、调度 work skill 运行 Worker 循环、检测阻断条件。不直接编写代码——代码实现由 work skill 内部的 Worker 产出。

## 前置检查

验证 PLAN 产物完整：

```bash
$HARNESSCTL stage-gate check PLAN --epic-id <epic-id>
```

必须存在：
- `.harness/tasks/<epic-id>.*.json`（至少一个）
- `.harness/features/<epic-id>/coverage-matrix.json`

若检查失败，提示先完成 `/harness:plan <epic-id>`，终止。

## 确定执行目标

根据 `$ARGUMENTS` 的格式：

- 若参数格式为 `sh-N-xxxx`（epic-id）：找该 epic 第一个 `status = pending` 且依赖已满足的任务
  ```bash
  $HARNESSCTL task next --epic-id <epic-id>
  ```
- 若参数格式为 `sh-N.M`（task-id）：直接执行该任务

若无可执行任务（全部 done 或 blocked），展示汇总并提示：
- 若全部 done：运行 `/harness:review <epic-id>`
- 若有 blocked：列出阻断原因，等待用户干预

## 执行步骤

**REQUIRED SKILL:** Use `harness:work` skill

向 skill 传入：
- `task-id`: 确定的任务 ID
- `epic-id`: epic-id
- `task_spec_path`: `.harness/tasks/<epic-id>.<n>.json`

skill 内部执行 Worker 5 Phase 循环：

| Phase | 名称 | 内容 |
|-------|------|------|
| 1 | re-anchor | 重读任务规格和验收标准，确认理解无偏差 |
| 2 | preflight | 检查依赖就绪、环境可用、无阻断条件 |
| 3 | TDD | 先写测试（RED），再写实现（GREEN），重构（IMPROVE） |
| 4 | smoke | 运行 smoke 测试验证基本功能可用 |
| 5 | commit + receipt | 提交代码，生成 task receipt |

### 循环控制

单任务完成后，自动检查下一个可执行任务：
```bash
$HARNESSCTL task next --epic-id <epic-id>
```

循环继续，直到触发停止条件。

### 停止条件（任一触发即停）

- 所有任务 `status = done`
- preflight 失败（依赖未就绪）
- smoke 测试失败
- 同一任务连续 3 次失败（会计入中断预算消耗）
- 中断预算耗尽

## 产物要求

每个完成的任务必须产出：

| 产物 | 路径 |
|------|------|
| Runtime Receipt | `.harness/features/<epic-id>/receipts/<task-id>.json` |
| 代码变更 | git commit（符合 conventional commits 格式） |
| 任务状态更新 | `.harness/tasks/<epic-id>.<n>.json` 中 `status` 更新为 `done` |

`receipt` 文件必须包含：
- `task_id`
- `started_at` / `completed_at`
- `smoke_result`: `PASS` 或 `FAIL`
- `test_coverage_pct`
- `files_changed`: 变更文件列表
- `commit_sha`

## 出口条件（门禁规则）

当前批次任务全部完成后：
- 所有任务均有对应 receipt 文件
- 所有 smoke 测试结果为 `PASS`
- 无 preflight 失败未处理

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| PLAN 门禁未通过 | 终止，提示先完成计划阶段 |
| preflight 失败 | 展示失败原因，标记任务为 `blocked`，继续下一个 |
| smoke 失败 | 记录失败，消耗预算，重试（最多 3 次） |
| 连续 3 次失败 | 标记任务为 `blocked`，消耗中断预算，展示失败详情 |
| 中断预算耗尽 | 保存当前进度，终止循环 |
