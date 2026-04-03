# SKILL: review

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


VERIFY 阶段审查引擎技能。通过跨模型多维审查、spec compliance 核查、安全审查、对抗补盲和验收议会，确保交付物满足规格要求，无遗漏风险。

---

## 触发条件

- 当前 epic state = `VERIFY`
- 收到 `/harness:review` 命令
- 从 FIX 阶段完成后重新进入 VERIFY

---

## 核心流程

### Step 1 — 汇总 runtime receipts

收集所有 task 的 receipt，建立 EXECUTE 阶段的完整证据清单。

```bash
# 列出所有 receipt
ls .harness/features/<epic-id>/receipts/

# 验证 receipt 完整性
for task_id in $($HARNESSCTL task list <epic-id> --json | jq -r '.[].id'); do
  receipt=".harness/features/<epic-id>/receipts/${task_id}.json"
  if [[ ! -f "$receipt" ]]; then
    echo "MISSING RECEIPT: $task_id"
  fi
done
```

汇总输出 `verification-context.json`（临时文件，供后续 reviewer 使用）：

```json
{
  "epic_id": "<epic-id>",
  "tasks_total": <n>,
  "tasks_with_receipts": <n>,
  "receipts_paths": [],
  "new_risks_accumulated": [],
  "coverage_matrix_path": ".harness/features/<epic-id>/coverage-matrix.json"
}
```

如果有缺失 receipt，**阻断**，不进入后续审查。

---

### Step 2 — 跨模型技术 review（并行）

通过 Task 工具**并行**调度 reviewer（与 `harness-review` 一致时至少包含 code / logic / test）：

```
并行调度：
  Task A: code-reviewer
    Input: {
      "epic_id": "<epic-id>",
      "diff_range": "<base>..<head>",
      "spec_path": ".harness/specs/<epic-id>.md"
    }
  Task B: logic-reviewer
    Input: {
      "epic_id": "<epic-id>",
      "receipts_dir": ".harness/features/<epic-id>/receipts/",
      "spec_path": ".harness/specs/<epic-id>.md",
      "domain_frame_path": ".harness/features/<epic-id>/domain-frame.json",
      "generated_scenarios_path": ".harness/features/<epic-id>/generated-scenarios.json",
      "scenario_coverage_path": ".harness/features/<epic-id>/scenario-coverage.json"
    }
  Task C: test-reviewer
    Input: {
      "epic_id": "<epic-id>",
      "spec_path": ".harness/specs/<epic-id>.md",
      "receipts_dir": ".harness/features/<epic-id>/receipts/",
      "diff_range": "<base>..<head>",
      "domain_frame_path": ".harness/features/<epic-id>/domain-frame.json",
      "generated_scenarios_path": ".harness/features/<epic-id>/generated-scenarios.json",
      "scenario_coverage_path": ".harness/features/<epic-id>/scenario-coverage.json"
    }
```

若相应文件不存在，logic-reviewer 与 test-reviewer 的输入中可省略 `domain_frame_path`、`generated_scenarios_path`、`scenario_coverage_path`。

等待各 agent 完成，收集 verdict；**logic-reviewer** 与 **test-reviewer** 须核对 spec 场景矩阵 / 事件序列，以及 `domain-frame` 与 `generated-scenarios.json` / `scenario-coverage.json` 中的高风险条目是否在实现与测试或 receipt 中有可验证证据。

---

### Step 3 — spec compliance 审查

调度 `runtime-auditor` agent，专门检查实现与规格的对齐：

```
Task: runtime-auditor
Input: {
  "epic_id": "<epic-id>",
  "spec_path": ".harness/specs/<epic-id>.md",
  "receipts_dir": ".harness/features/<epic-id>/receipts/",
  "coverage_matrix": ".harness/features/<epic-id>/coverage-matrix.json"
}
```

runtime-auditor 输出：
- spec compliance 报告
- 漂移清单（实现超出或偏离 spec 的地方）
- 不变量违反情况

---

### Step 4 — 安全审查

调度 `security-reviewer` agent：

```
Task: security-reviewer
Input: {
  "epic_id": "<epic-id>",
  "diff_range": "<base>..<head>",
  "surface": "<primary-surface>"
}
```

---

### Step 5 — 对抗式补盲

调度 `challenger` agent（如果存在），输出分类结果：

| 分类 | 说明 |
|------|------|
| 已测并通过 | 覆盖率已足够，可以接受 |
| 未测但可接受 | 风险可控，文档记录即可 |
| 未测且必须补 | 阻断，必须补充测试后才能通过 |

如果没有 `challenger` agent，由主会话人工判断覆盖盲区。

"未测且必须补"的项目写入 `verification.json` 的 `required_additions` 字段，进入 FIX 阶段。

---

### Step 6 — 验收议会

调用 `council/SKILL.md`，参数：

```
council_type: acceptance_council
epic_id: <epic-id>
context: {
  code_review_verdict: <verdict>,
  logic_review_verdict: <verdict>,
  test_review_verdict: <verdict>,
  spec_compliance_verdict: <verdict>,
  security_verdict: <verdict>,
  uncovered_risks: <list>
}
```

议会 verdict 写入 `.harness/features/<epic-id>/councils/verdict-acceptance_council.json`。

---

### Step 7 — Stage Smoke

调用 `runtime-harness/SKILL.md` 的 Stage Smoke 检查点（Checkpoint 4）：

```bash
# 全量回归测试
<project-test-command>

# 验证所有 receipts 存在且 smoke.passed = true
```

---

## 出口条件（全部满足）

- [ ] 技术 review（code + logic + test，按实际并行调度）均 verdict = `PASS`
- [ ] spec compliance 无漂移（或漂移已被 acceptance_council 豁免）
- [ ] 安全审查 verdict = `PASS`
- [ ] 对抗补盲无"未测且必须补"项（或已全部补充）
- [ ] `verdict-acceptance_council.json` verdict = `PASS` 或 `CONDITIONAL_PASS`（若以此文件作为议会记录）
- [ ] Stage Smoke 通过

```bash
# 写入 verification.json
cat > .harness/features/<epic-id>/verification.json << 'EOF'
{
  "epic_id": "<epic-id>",
  "stage": "VERIFY",
  "code_review": "PASS",
  "logic_review": "PASS",
  "test_review": "PASS",
  "spec_compliance": "PASS",
  "security": "PASS",
  "council_verdict": "PASS",
  "stage_smoke": "PASS",
  "timestamp": "<iso8601>"
}
EOF

# 推进状态
$HARNESSCTL state transition <epic-id> DONE
```

---

## 失败处理

任何审查失败（verdict = FAIL）：

1. 收集所有 FAIL findings
2. 写入 `verification.json`，标记具体失败维度
3. 转入 FIX 阶段：

```bash
$HARNESSCTL state transition <epic-id> FIX
```

FIX 完成后重新回到 VERIFY，从 Step 1 开始。
