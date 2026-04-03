# SKILL: council

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


分层议会调度技能。根据议会类型动态选择 reviewer 列表，并行执行所有审查，汇总 verdict，自动裁决放行或阻断。

---

## 触发条件

由其他 SKILL 调用，传入 `council_type` 参数：
- `light_council` — 由 `spec/SKILL.md` 调用（SPEC 阶段）
- `plan_council` — 由 `plan/SKILL.md` 调用（PLAN 阶段）
- `acceptance_council` — 由 `review/SKILL.md` 调用（VERIFY 阶段）
- `release_council` — 由 `done/SKILL.md` 调用（DONE 阶段）

---

## 议会类型配置

| 类型 | 阶段 | Reviewer 数量 | 裁决选项 |
|------|------|--------------|---------|
| `light_council` | SPEC | 3-5 | GO / REVISE / HOLD |
| `plan_council` | PLAN | 5-7 | READY / REVISE / BLOCK |
| `acceptance_council` | VERIFY | 5-7 | PASS / FAIL |
| `release_council` | DONE | 3-4 | RELEASE_READY / RELEASE_WITH_CONDITIONS / NOT_READY |

---

## Reviewer 矩阵

### light_council（SPEC）

与 `harness-spec`、`usage`、`architecture` 一致：**必选（3）**为 `challenger`、`requirement-analyst`、`impact-analyst` — 审查规格完整性、需求覆盖与影响面是否写入 spec。

**风险加强（high risk → 可选追加）**：`plan-reviewer`、`logic-reviewer`、`security-reviewer`（或 `code-reviewer`、`test-reviewer`）— 由编排层按项目需要并行加审，不改变轻议会最小三人组定义。

### plan_council（PLAN）

**必选（5）**：plan-reviewer、logic-reviewer、security-reviewer、test-reviewer、code-reviewer

**风险加强（high risk → 追加 2）**：runtime-auditor + 项目特定 reviewer

### acceptance_council（VERIFY）

**必选（5）**：code-reviewer、logic-reviewer、security-reviewer、test-reviewer、runtime-auditor

**风险加强（high risk → 追加 2）**：plan-reviewer + 项目特定 reviewer

### release_council（DONE）

**必选（3）**：logic-reviewer、security-reviewer、runtime-auditor

**风险加强（high risk → 追加 1）**：code-reviewer

---

## 议会召集流程

### Step 1 — 确定议会配置

```bash
# 读取 epic 风险等级
RISK_LEVEL=$($HARNESSCTL state get <epic-id> --json | jq -r '.risk_level')

# 确定 reviewer 列表
# high risk: 使用完整列表（含加强项）
# medium/low risk: 使用必选列表
```

### Step 2 — 为每个 reviewer 准备上下文

每个 reviewer 需要的上下文因类型而异：

```json
// plan_council reviewer 上下文
{
  "epic_id": "<epic-id>",
  "spec_path": ".harness/specs/<epic-id>.md",
  "tasks_dir": ".harness/tasks/",
  "coverage_matrix": ".harness/features/<epic-id>/coverage-matrix.json",
  "council_type": "plan_council",
  "my_role": "<reviewer-name>"
}

// acceptance_council reviewer 上下文
{
  "epic_id": "<epic-id>",
  "spec_path": ".harness/specs/<epic-id>.md",
  "receipts_dir": ".harness/features/<epic-id>/receipts/",
  "diff_range": "<base>..<head>",
  "council_type": "acceptance_council",
  "my_role": "<reviewer-name>"
}
```

### Step 3 — 并行 Task 调度所有 reviewer

```
并行调度（示例：plan_council with 5 reviewers）：
  Task 1: plan-reviewer     (上下文见 Step 2)
  Task 2: logic-reviewer    (上下文见 Step 2)
  Task 3: security-reviewer (上下文见 Step 2)
  Task 4: test-reviewer     (上下文见 Step 2)
  Task 5: code-reviewer     (上下文见 Step 2)
```

等待所有 reviewer 完成，收集 verdict JSON。

### Step 4 — 汇总 verdict

**汇总规则（优先级由高到低）**：

1. 任何 `BLOCK` / `FAIL` → 整体 = `BLOCK` / `FAIL`
2. 任何 `HOLD` / `NOT_READY` → 整体 = 对应最严格 verdict
3. 所有 `REVISE` （无 BLOCK/FAIL）→ 整体 = `REVISE`
4. 全部 `GO` / `PASS` / `READY` / `RELEASE_READY` → 整体通过
5. 混合（部分 REVISE，部分 GO）→ 取最严格

**severity 上卷规则**：整体 severity = 所有 reviewer 中最高的 severity。

### Step 5 — 生成 council verdict

```bash
cat > .harness/features/<epic-id>/councils/verdict-<council-type>.json << 'EOF'
{
  "council_type": "<council-type>",
  "epic_id": "<epic-id>",
  "stage": "<stage>",
  "reviewers": [
    {
      "role": "<reviewer-name>",
      "verdict": "<individual-verdict>",
      "severity": "<none|low|medium|high|critical>",
      "findings_count": <n>
    }
  ],
  "verdict": "<aggregated-verdict>",
  "severity": "<max-severity>",
  "blocking_findings": [],
  "timestamp": "<iso8601>"
}
EOF
```

---

## 自动放行规则

| overall_verdict | 行为 |
|----------------|------|
| `GO` / `READY` / `PASS` / `RELEASE_READY` | 自动放行，调用方继续流程 |
| `REVISE` / `HOLD` | 阻断，输出需要修订的 findings 清单 |
| `BLOCK` / `FAIL` / `NOT_READY` | 硬阻断，输出全部 blocking_findings |
| `RELEASE_WITH_CONDITIONS` | 半放行，记录条件，允许继续但需标注 |

---

## 失败后的修订循环

```
整体 verdict = REVISE/BLOCK/FAIL
  ↓
输出 blocking_findings 清单
  ↓
调用方修复（回流对应阶段或就地修复）
  ↓
重新调用 council/SKILL.md（相同 council_type）
  ↓
重新汇总 verdict
```

修订次数超过 3 次 → 升级为人工干预，写入 `interrupt-budget`。

---

## 动态强度控制

风险等级影响 reviewer 数量和通过阈值：

| risk_level | reviewer 数量 | 通过阈值 |
|-----------|--------------|---------|
| `low` | 最小必选 | 多数通过即可 |
| `medium` | 必选 | 全部通过 |
| `high` | 必选 + 加强 | 全部通过，severity ≤ medium |
