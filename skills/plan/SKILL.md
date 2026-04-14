# SKILL: plan

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


PLAN 阶段计划生成技能。将 SPEC 产物转化为可执行的任务图谱，建立覆盖矩阵，确保每个已知风险都有对应的 task、验证手段和证据要求。

---

## 触发条件

- 当前 epic state = `PLAN`
- 收到 `/harness:plan` 命令
- 从 EXECUTE 回流（`$HARNESSCTL state transition <epic-id> PLAN`）

---

## 核心流程

### Step 1 — 承载面缩圈复核

```bash
$HARNESSCTL state get <epic-id>
```

**必须**存在 `.harness/features/<epic-id>/surface-routing.json`（`stage-gate check CLARIFY` / `PLAN` 已要求）。读取并确认后续调研范围：

```bash
test -f .harness/features/<epic-id>/surface-routing.json || {
  echo "error: surface-routing.json missing — complete CLARIFY surface routing first" >&2
  exit 1
}
cat .harness/features/<epic-id>/surface-routing.json
```

确认：
- 哪些承载面（surfaces）被标记为 in-scope
- 哪些已在 SPEC 阶段排除
- 跨承载面边界是否已在 spec 中明确
- `repo_id` / `scan_budget` / `evidence_level` 是否与 `cross-repo-impact-index.json`（如有）一致

建议先对相关缓存运行，并将结果落盘为本轮 PLAN 产物：

```bash
harnessctl memory codemap-audit .harness/memory/codemaps/<repo_id> --epic-id <epic-id> --json
```

若结果显示 `stale > 0`、`invalid > 0` 或目标条目 `reason != ok`，在调度 scout 时明确要求**以源码/契约为准，仅将 codemap 作为低置信背景**。若提供了 `--epic-id`，CLI 会额外写出 `.harness/features/<epic-id>/codemap-audit.json`，应将该文件作为 scouts 的辅助输入。

### Step 2 — 并行 scouts 调研

通过 Task 工具**并行**调度 scout agents（**仅**以 `surface-routing.json` 的 `scout_assignments` / `assigned_to` 与 `surfaces[]` 为准；禁止因“路由不全”自行扩大到未登记路径）。**每个 scout 须先**查看 `.harness/features/<epic-id>/codemap-audit.json`（如有）与 `.harness/memory/codemaps/` 下相关模块笔记，再对源码做定点阅读。

| Scout | 职责 |
|-------|------|
| repo-router | 代码结构、模块边界、入口 |
| docs-scout | CLARIFY/SPEC 文档与意图对齐 |
| design-scout | 架构与接口约定 |
| config-scout | 配置、环境、部署约束 |
| symbol-navigator | 符号与调用点 |
| dependency-mapper | 依赖与 import 链 |

每个 scout 输出：已知实体清单 + 发现的约束/风险；**不得**在未登记路径上做大范围盲扫。

### Step 3 — 生成 task 图谱

批量创建 tasks，每个 task 必须包含：
- `surface` 字段（隶属哪个承载面）
- `acceptance_criteria`（可验证的完成标准）
- `dependencies`（前置 task IDs）
- `evidence`（需要产出的证据文件/测试结果）

```bash
# 为每个 task 运行
$HARNESSCTL task create <epic-id> "<task-title>" --surface <surface-name>
```

跨承载面 task 必须在 task JSON 中写明：
- `boundary`：承载面边界描述
- `deps_cross_surface`：跨面依赖说明
- `integration_points`：联调点清单

### Step 4 — 构建 coverage matrix

```bash
$HARNESSCTL coverage map  # 如已实现；否则手动构建
```

构建规则：

1. 读取 `.harness/features/<epic-id>/unknowns-ledger.json`
2. 对每条 unknown 条目，映射到：
   - 对应的 task ID
   - 验证手段（测试/日志/人工确认）
   - 证据文件路径
3. 无法映射的风险写入 `coverage-matrix.json` 的 `unmapped_risks` 字段

```json
// .harness/features/<epic-id>/coverage-matrix.json
{
  "version": "1.0",
  "epic_id": "<epic-id>",
  "mappings": [
    {
      "unknown_id": "U-001",
      "task_id": "sh-1.3",
      "validation": "integration test",
      "evidence_path": "test-results/auth-flow.json"
    }
  ],
  "unmapped_risks": [
    {
      "unknown_id": "U-005",
      "reason": "需要外部服务配合，无法在当前 sprint 验证",
      "mitigation": "文档记录，下期处理"
    }
  ]
}
```

### Step 5 — 技术 plan-review

调度 `plan-reviewer` agent 审查计划：

```
Task: plan-reviewer
Input: {
  "epic_id": "<epic-id>",
  "tasks_dir": ".harness/tasks/",
  "coverage_matrix": ".harness/features/<epic-id>/coverage-matrix.json",
  "spec_path": ".harness/specs/<epic-id>.md"
}
```

plan-reviewer 输出 JSON verdict，写入 `.harness/features/<epic-id>/plan-review.json`。

如果 verdict = `BLOCK`，停止流程，修复后重新执行 Step 3。

### Step 6 — 计划议会

调用 `council/SKILL.md`，参数：

```
council_type: plan_council
epic_id: <epic-id>
context: {
  tasks_count: <N>,
  coverage_matrix: <path>,
  plan_review_verdict: <verdict>
}
```

议会 verdict 写入 `.harness/features/<epic-id>/councils/verdict-plan_council.json`。

### Step 7 — Decision Bundle / Packet

调用 `decision-bundle/SKILL.md`，处理本阶段产生的所有决策点。

所有 `must_confirm` 项必须在阶段出口前处理完毕。

---

## 出口条件（全部满足）

- [ ] `plan-review.json` verdict = `READY`
- [ ] `verdict-plan_council.json` verdict = `READY` 或 `READY_WITH_CONDITIONS`
- [ ] `coverage-matrix.json` 已生成，`unmapped_risks` 已显性暴露
- [ ] 所有 `must_confirm` 决策已处理
- [ ] `decision-packet.json` 已更新

出口命令：

```bash
$HARNESSCTL state transition <epic-id> EXECUTE
```

---

## 硬规则

1. 不能只有功能拆分，没有风险与验证拆分——每个 unknown 必须有对应 task
2. 任何无法映射到 task 的风险必须在 `unmapped_risks` 显性暴露，不允许静默忽略
3. PLAN 是后半程控制中心——EXECUTE 发现的新问题必须回流 PLAN，不允许就地扩写
4. 跨承载面 task 必须写明边界、依赖和联调点，不允许隐含耦合

---

## 回流处理

EXECUTE 阶段回流时：

1. 读取 EXECUTE 产生的 triage 报告（`.harness/features/<epic-id>/triage-<timestamp>.json`）
2. 识别回流原因：`plan_patch`（计划变更）或 `spec_patch`（规格变更）
3. 仅修改受影响的 tasks，不重写整个计划
4. 重新执行 Step 4–7
