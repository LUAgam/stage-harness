# SKILL: stage-gate

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


阶段门禁技能。在每个阶段出口执行产物完整性检查，确保进入下一阶段所需的所有产物齐备、决策已处理、议会已通过。

---

## 触发条件

- 每次调用 `$HARNESSCTL state transition` 前自动检查
- 收到 `/harness:gate` 命令时手动触发
- 由各阶段 SKILL 的出口条件检查调用

---

## 阶段产物清单

### CLARIFY 出口

| 产物 | 路径 | 说明 |
|------|------|------|
| domain-frame.json | `.harness/features/<epic-id>/domain-frame.json` | domain-scout 领域框架草稿 |
| generated-scenarios.json | `.harness/features/<epic-id>/generated-scenarios.json` | scenario-expander 场景展开 |
| scenario-coverage.json | `.harness/features/<epic-id>/scenario-coverage.json` | Lead 语义归并后的场景覆盖台账 |
| challenge-report.md | `.harness/features/<epic-id>/challenge-report.md` | challenger 报告（须含 `## Summary`） |
| clarification-notes.md | `.harness/features/<epic-id>/clarification-notes.md` | 需求澄清记录（须含 Domain Frame / 领域框架 标题） |
| impact-scan.md | `.harness/features/<epic-id>/impact-scan.md` | 影响面扫描结果（须含 `## Blast Radius Summary` / `## High Impact Surfaces` / `## Medium Impact Surfaces`） |
| surface-routing.json | `.harness/features/<epic-id>/surface-routing.json` | 承载面路由与扫描预算（**必备**；`surfaces` 非空且含 `type`/`path`） |
| unknowns-ledger.json | `.harness/features/<epic-id>/unknowns-ledger.json` | 未知问题台账 |
| decision-packet.json | `.harness/features/<epic-id>/decision-packet.json` | 决策包 |
| decision-bundle.json | `.harness/features/<epic-id>/decision-bundle.json` | 全量决策分类 |

`workspace_mode: multi-repo` 时另须 **`cross-repo-impact-index.json`**（有效 JSON，`repos` 为数组）——由 `harnessctl stage-gate check CLARIFY` 校验，见 `scripts/harnessctl.py`。

### SPEC 出口

| 产物 | 路径 | 说明 |
|------|------|------|
| specs/{epic-id}.md | `.harness/specs/<epic-id>.md` | 规格文档 |
| spec-council-notes.md | `.harness/features/<epic-id>/spec-council-notes.md` | 轻议会审查记录（**`harnessctl stage-gate check SPEC` 必备**，与 `STAGE_GATE_ARTIFACTS["SPEC"]` 一致） |
| verdict-light_council.json | `.harness/features/<epic-id>/councils/verdict-light_council.json` | 轻议会聚合裁决（建议由 `harnessctl council aggregate` 写入；**非** CLI 门禁必备文件） |

### PLAN 出口

| 产物 | 路径 | 说明 |
|------|------|------|
| tasks/*.json | `.harness/tasks/<epic-id>.*.json` | 所有 task 文件 |
| bridge-spec.md | `.harness/features/<epic-id>/bridge-spec.md` | Bridge 产出 |
| coverage-matrix.json | `.harness/features/<epic-id>/coverage-matrix.json` | 覆盖矩阵 |
| surface-routing.json | `.harness/features/<epic-id>/surface-routing.json` | 与 CLARIFY 一致，**PLAN 门禁复验** |
| verdict-plan_council.json | `.harness/features/<epic-id>/councils/verdict-plan_council.json` | 计划议会 verdict |

### EXECUTE 出口

| 产物 | 路径 | 说明 |
|------|------|------|
| receipts/*.json | `.harness/features/<epic-id>/receipts/<task-id>.json` | 每个 task 的 runtime receipt |
| git commits | `git log` 中包含所有 task commit | 原子提交记录 |

### VERIFY 出口

| 产物 | 路径 | 说明 |
|------|------|------|
| verification.json | `.harness/features/<epic-id>/verification.json` | 验收结果（**`harnessctl stage-gate check VERIFY` 必备**；建议含 `code_review` / `logic_review` / `test_review` / `security` / `spec_compliance`） |
| verdict-acceptance_council.json | `.harness/features/<epic-id>/councils/verdict-acceptance_council.json` | 验收议会聚合裁决（**当** `verification.json` 中无 `acceptance_council` / `council_verdict` 为 `PASS` 或 `CONDITIONAL_PASS` 时，门禁用此文件兜底；否则可不作为阻断条件） |

`stage-gate check VERIFY`：`verification.json` 须存在；其中 `acceptance_council` 或 `council_verdict` 须为 `PASS`/`CONDITIONAL_PASS`，**否则**尝试读取 `verdict-acceptance_council.json` 的 `verdict` 是否为 `PASS`/`CONDITIONAL_PASS`。若 `verification.json` 中 `code_review` / `logic_review` / `test_review` / `security` / `spec_compliance` **存在且值为** `FAIL`（大小写不敏感），或 `critical_issues` 非空，门禁失败。

### DONE 出口

| 产物 | 路径 | 说明 |
|------|------|------|
| release-notes.md | `.harness/features/<epic-id>/release-notes.md` | 发布说明 |
| delivery-summary.md | `.harness/features/<epic-id>/delivery-summary.md` | 交付总结 |
| verdict-release_council.json | `.harness/features/<epic-id>/councils/verdict-release_council.json` | 发布议会裁决（**必备**；`verdict` 须为 `RELEASE_READY` 或 `RELEASE_WITH_CONDITIONS`） |

---

## 门禁检查流程

### Step 1 — 读取当前阶段

```bash
CURRENT_STAGE=$($HARNESSCTL state get <epic-id> --json | jq -r '.current_stage')
```

### Step 2 — 检查产物完整性

对当前阶段的每个必备产物执行存在性检查：

```bash
# 示例：PLAN 出口检查
missing=()

# 检查 tasks
task_count=$(ls .harness/tasks/<epic-id>.*.json 2>/dev/null | wc -l)
if [[ "$task_count" -eq 0 ]]; then
  missing+=("tasks/*.json (no tasks created)")
fi

# 检查 coverage-matrix
if [[ ! -f ".harness/features/<epic-id>/coverage-matrix.json" ]]; then
  missing+=("coverage-matrix.json")
fi

# 检查 council verdict
if [[ ! -f ".harness/features/<epic-id>/councils/verdict-plan_council.json" ]]; then
  missing+=("verdict-plan_council.json")
else
  verdict=$(jq -r '.verdict' .harness/features/<epic-id>/councils/verdict-plan_council.json)
  if [[ "$verdict" == "BLOCK" || "$verdict" == "FAIL" ]]; then
    missing+=("verdict-plan_council.json: verdict=$verdict (must not be BLOCK/FAIL)")
  fi
fi
```

### Step 3 — 检查 Decision Bundle

```bash
# 检查是否有未处理的 must_confirm 项
must_confirm_count=$(jq '[.decisions[] | select(.must_confirm == true and .resolved == false)] | length' \
  .harness/features/<epic-id>/decision-packet.json 2>/dev/null || echo 0)

if [[ "$must_confirm_count" -gt 0 ]]; then
  missing+=("decision-packet.json: $must_confirm_count must_confirm items unresolved")
fi
```

### Step 4 — 检查议会 verdict

```bash
council_verdict=$(jq -r '.verdict' .harness/features/<epic-id>/councils/verdict-plan_council.json 2>/dev/null || echo "MISSING")

case "$council_verdict" in
  BLOCK|FAIL|NOT_READY)
    missing+=("plan council verdict: $council_verdict (blocking)")
    ;;
  MISSING)
    missing+=("verdict-plan_council.json (file not found)")
    ;;
esac
```

### Step 5 — 裁决

**产物不齐全 → 阻断**：

```
GATE BLOCKED: <current-stage> → <next-stage>

Missing artifacts:
  - <artifact-1>
  - <artifact-2>

Action required: Complete the above before advancing.
```

**全部满足 → 自动放行**：

```bash
echo "GATE PASSED: <current-stage> → <next-stage>"
$HARNESSCTL state transition <epic-id> <next-stage>
```

---

## 门禁规则摘要

| 规则 | 阻断条件 |
|------|---------|
| 产物完整性 | 任意必备产物缺失（以 `$HARNESSCTL stage-gate check` 与 `STAGE_GATE_ARTIFACTS` 为准） |
| Decision Bundle | 任意 `must_confirm` 未处理 |
| 议会 verdict（PLAN 等） | 对应 `verdict-*.json` 为 `BLOCK` / `FAIL` / `NOT_READY` 等阻断值 |
| EXECUTE 出口 | 任意 task 缺少 receipt（或非 done/blocked） |
| VERIFY 出口 | `verification.json` 验收字段未通过、维度 `FAIL`、`critical_issues` 非空；或兜底议会裁决不通过 |
| DONE 出口 | `verdict-release_council.json` 缺失或 `verdict` 非放行值 |

---

## 手动强制跳过（紧急情况）

```bash
# 需要人工明确授权，记录到 decision-packet
$HARNESSCTL gate skip <STAGE> --epic-id <epic-id> \
  --justification "emergency production fix"
```

跳过记录写入 `.harness/features/<epic-id>/gate-skips.json`，供审计使用。
