---
description: "实施计划生成（承载面调研 + task图谱 + coverage matrix + 计划议会）"
argument-hint: "<epic-id>"
---

# harness-plan

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


基于 SPEC 产物生成实施计划。执行承载面调研、任务图谱构建、覆盖矩阵生成，经计划议会审查后输出最终任务列表。

## 角色定义

PLAN 阶段 orchestrator。负责验证 SPEC 前置产物、桥接 ShipSpec 与 deep-plan、调度 plan skill 执行、编排计划议会。不直接分解任务——任务分解由 plan skill 内部产出。

## 前置检查

验证 SPEC 产物完整：

```bash
$HARNESSCTL stage-gate check SPEC --epic-id <epic-id>
```

若检查失败，展示缺失产物列表，提示先完成 `/harness:spec <epic-id>`，终止。

## 执行步骤

### Step 1：运行 bridge 脚本

将 ShipSpec 产物转换为 deep-plan 输入格式：

```bash
bridge-shipspec-to-deepplan.sh <feature> <epic-id>
```

bridge 脚本负责：
- 读取 `.harness/specs/<epic-id>.md`
- 提取验收标准、约束条件、依赖关系
- 生成 deep-plan 兼容的输入文件

### Step 2：承载面调研 + task 图谱 + coverage matrix + 计划议会

**REQUIRED SKILL:** Use `harness:plan` skill

向 skill 传入：
- `epic-id`
- `spec_path`: `.harness/specs/<epic-id>.md`
- `bridge_output`: Step 1 bridge 脚本的产出路径

skill 内部并行执行：

**承载面调研（并行 scouts）：**
- 先读 `.harness/features/<epic-id>/surface-routing.json`（及 `cross-repo-impact-index.json` 如有），再读 `.harness/memory/codemaps/` 下相关笔记，**后**定点读源码；不得在未登记路径上盲扫全仓。
- repo-router / symbol-navigator：在路由范围内扫描代码结构、符号与可复用模块
- dependency-mapper / config-scout：依赖、配置与集成点（受 `scout_assignments` 约束）
- docs-scout / design-scout：文档与设计约束，与路由及契约 `interfaces[]` 对齐

**task 图谱构建：**
- 基于规格验收标准分解任务
- 建立任务依赖关系（DAG）
- 每个任务估算点数（Fibonacci：1/2/3/5/8）
- 超过 5 点的任务自动拆分

**coverage matrix 生成：**
- 规格需求 → task 映射
- 验收标准覆盖率统计
- 覆盖率 < 80% 时告警
- 若规格或 `domain-frame` 摘要中含「场景矩阵 / 事件序列 / 高风险时序」，应在任务或测试映射中显式覆盖（与 `_spec_semantic_warnings` 建议一致）

**计划议会（5 reviewer）：**

| Reviewer 角色 | 审查维度 |
|-------------|---------|
| code-reviewer | 计划与代码落点是否一致，任务粒度是否可实施 |
| security-reviewer | 高风险任务是否覆盖安全约束 |
| logic-reviewer | 任务依赖关系是否合理，有无循环依赖 |
| test-reviewer | coverage matrix 是否达到 80%+，测试任务是否充分 |
| plan-reviewer | 任务点数估算、关键路径与整体计划可执行性 |

议会 REJECT 时，重新触发任务分解，最多 2 轮。

## 产物要求

| 产物 | 路径 |
|------|------|
| 任务 JSON 文件 | `.harness/tasks/<epic-id>.*.json` |
| 覆盖矩阵 | `.harness/features/<epic-id>/coverage-matrix.json` |
| 计划议会结论 | `.harness/features/<epic-id>/councils/verdict-plan_council.json` |

`verdict-plan_council.json` 必须包含字段：
- `verdict`: `READY`、`READY_WITH_CONDITIONS` 或 `BLOCK`
- `coverage_pct`: 覆盖率百分比
- `total_tasks`: 任务总数
- `total_points`: 总点数
- `critical_path`: 关键路径任务 ID 列表

## 出口条件（门禁规则）

通过条件：
- `tasks/` 目录下至少有一个任务文件
- `coverage-matrix.json` 存在且 `coverage_pct >= 80`
- `verdict-plan_council.json` 中 verdict 为 `READY` 或 `READY_WITH_CONDITIONS`
- 无循环依赖（DAG 验证通过）

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| SPEC 门禁未通过 | 终止，提示先完成规格阶段 |
| bridge 脚本失败 | 展示错误，提示检查 bridge 脚本路径 |
| 覆盖率 < 80% | 展示未覆盖的规格项，触发补充任务 |
| 议会 REJECT 超过 2 轮 | 以当前版本继续，在门禁记录中标注 |
| 循环依赖 | 列出循环路径，等待用户手动解决 |
