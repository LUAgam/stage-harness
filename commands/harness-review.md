---
description: "审查与验收（技术review + spec compliance + 安全审查 + 对抗式补盲 + 验收议会）"
argument-hint: "<epic-id>"
---

# harness-review

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


执行审查与验收阶段。并行技术 review、spec compliance 检查、安全审查，通过对抗式补盲识别遗漏，最终由验收议会裁决。

## 角色定义

VERIFY 阶段 orchestrator。负责验证 EXECUTE 前置产物、调度 review skill 执行并行审查、编排验收议会。不直接做通过/拒绝决定——裁决由验收议会产出。

## 前置检查

验证 EXECUTE 产物完整：

```bash
$HARNESSCTL stage-gate check EXECUTE --epic-id <epic-id>
```

必须满足：
- `.harness/features/<epic-id>/receipts/` 目录下有 receipt 文件
- 所有任务 `status = done` 或 `blocked`（无 `in_progress` 或未处理的 `pending` 任务）

若检查失败，列出未完成任务，提示先完成 `/harness:work <epic-id>`，终止。

## 执行步骤

**REQUIRED SKILL:** Use `harness:review` skill

向 skill 传入：
- `epic-id`
- `spec_path`: `.harness/specs/<epic-id>.md`
- `receipts_dir`: `.harness/features/<epic-id>/receipts/`
- （建议）`domain_frame_path`: `.harness/features/<epic-id>/domain-frame.json` — 若存在则一并传给 **logic-reviewer** / **test-reviewer**，用于核对 CLARIFY 阶段识别的边界场景是否在实现与测试中有证据
- （建议）`generated_scenarios_path`: `.harness/features/<epic-id>/generated-scenarios.json` — 若存在则传给 **logic-reviewer** / **test-reviewer**，用于核对系统展开的高风险场景是否在规格与实现中出现
- （建议）`scenario_coverage_path`: `.harness/features/<epic-id>/scenario-coverage.json` — 若存在则传给 **logic-reviewer** / **test-reviewer**，用于核对每个 `SCN-xxx` 是否有规格与测试证据

skill 内部执行并行审查：

### 并行 Reviewers

| Reviewer 角色 | 审查维度 |
|-------------|---------|
| code-reviewer | 代码质量、架构一致性、测试覆盖率 |
| logic-reviewer | 逻辑正确性、边界条件、错误路径；**规格中的场景矩阵/事件序列/时序**以及 `SCN-xxx` 覆盖是否与实现一致 |
| security-reviewer | 安全漏洞、权限控制、数据验证 |
| test-reviewer | 测试覆盖、验收标准映射、回归风险；**domain-frame、generated-scenarios、scenario-coverage 与 spec 中的高风险场景**是否有测试或 receipt 证据 |
| runtime-auditor | 实现与 spec 对齐、spec compliance、漂移与不变量（与 acceptance_council 核心成员一致） |
| quality-auditor | （可选）交付质量、回执完整性、残留风险 — 非 acceptance_council 必选五人组 |

所有 reviewer 并行执行，独立输出意见。

### 对抗式补盲

在并行审查完成后，执行对抗式补盲：
- 指定一个 adversarial-reviewer 角色
- 专门寻找"其他 reviewer 可能遗漏"的问题
- 重点关注：边界条件、并发问题、错误路径

### 验收议会

汇总所有 reviewer 意见，运行验收议会裁决：

```bash
$HARNESSCTL council run acceptance_council --epic-id <epic-id>
```

裁决规则：
- 任何 CRITICAL 问题 → `REJECTED`，必须修复后重新审查
- HIGH 问题 >= 3 → `CONDITIONAL_PASS`，需在 done 阶段处理
- 无 CRITICAL 且 HIGH < 3 → `PASS`

## 产物要求

| 产物 | 路径 |
|------|------|
| 验收结果 | `.harness/features/<epic-id>/verification.json` |
| 议会裁决 | `.harness/features/<epic-id>/councils/verdict-acceptance_council.json` |
| 审查汇总 | `.harness/features/<epic-id>/review-summary.md` |

`verification.json` 必须包含：
- `acceptance_council`: `PASS` / `CONDITIONAL_PASS` / `REJECTED`
- `code_review` / `logic_review` / `test_review` / `security` / `spec_compliance`：各并行 reviewer 的汇总结论（与 `review/SKILL.md` 示例一致时可简化）
- `reviewer_verdicts`: 各 reviewer 的意见列表（可选细化）
- `critical_issues`: CRITICAL 级别问题（PASS 时为空数组）
- `high_issues`: HIGH 级别问题列表
- `verified_at`: ISO 时间戳

## 出口条件（门禁规则）

```bash
$HARNESSCTL stage-gate check VERIFY --epic-id <epic-id>
```

通过条件：
- `verification.json` 存在
- `acceptance_council` 或 `council_verdict` 为 `PASS` 或 `CONDITIONAL_PASS`（与 `harnessctl` 的 `_verification_passed` 一致）
- 若文件中写有 `code_review` / `logic_review` / `test_review` / `security` / `spec_compliance`，任一为 `FAIL` 则 `$HARNESSCTL stage-gate check VERIFY` **不通过**
- 无未处理的 CRITICAL 问题（`critical_issues` 非空则失败）

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| EXECUTE 门禁未通过 | 终止，展示未完成任务列表 |
| security-reviewer FAIL | 强制终止，标注为 CRITICAL，不允许继续 |
| 议会 REJECTED | 列出 CRITICAL 问题，触发 FIX 阶段状态转换 |
| CONDITIONAL_PASS | 记录 HIGH 问题到待处理列表，允许继续到 done 阶段 |
