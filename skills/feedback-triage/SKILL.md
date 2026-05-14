# SKILL: feedback-triage

## CLI Bootstrap

```bash
if [ -z "${HARNESSCTL:-}" ]; then
  # 1. Read from .harness/config.json if available
  if [ -f ".harness/config.json" ]; then
    _cfg_path=$(python3 -c "import json,sys;print(json.load(open('.harness/config.json')).get('harnessctl_path',''))" 2>/dev/null)
    [ -n "$_cfg_path" ] && [ -x "$_cfg_path" ] && HARNESSCTL="$_cfg_path"
  fi

  # 2. Fallback: search common locations
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
fi

test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "harnessctl not found. Set HARNESSCTL or add harnessctl_path to .harness/config.json" >&2
  exit 1
}
```

---

## 概述

Feedback Triage Council 调度技能。当 stage-reminder hook 自动提交 feedback 后，
本 skill 负责完整执行多 agent 评审流程，决定是否 reopen 及返回哪个阶段。

---

## 触发条件

- stage-reminder.sh 检测到 feedback_candidate 并自动提交 HFB-xxx
- additionalContext 注入 `[Feedback - AUTO SUBMITTED]` 指令
- 也可手动触发

---

## 硬性规则（绝对禁止）

1. **禁止手工复刻 feedback 流程**：禁止用 Bash/Write/Edit 工具手动创建 `evidence-pack.json`、`votes/*.json`、`verdict.json` 文件。必须通过 `harnessctl` 标准命令完成每一步。PreToolUse hooks 会自动拦截违规操作。
2. **禁止使用旧版 vote schema**：`decision` 字段仅接受以下值：`REOPEN_CLARIFY`、`REOPEN_SPEC`、`REOPEN_PLAN`、`STAY_EXECUTE`、`NO_REOPEN_WITH_EVIDENCE`、`INSUFFICIENT_EVIDENCE`、`REJECT`、`DEFER`。旧版值（如 `agree_reopen`、`conditional`、`reopen` 等）会被 aggregate-triage 拒绝。
3. **confirmed in-scope 后自动继续**：triage 裁决后，若 verdict 为 low/medium risk 的 REOPEN_* 或 STAY_EXECUTE，必须自动执行后续步骤（plan-amendment → approve → reopen/create-task），不得询问用户"要不要修"。仅 `scope_change` 或 `high risk` 需人工确认。
4. **confirmed feedback 必须立即处理**：feedback 提交后不得跳过 triage 直接回答用户，也不得 idle 等待。
5. **related-gap-scan 必须在 scope_gap 裁决后执行**：verdict 为 REOPEN_* 或 STAY_EXECUTE + scope_gap 时，必须运行 `related-gap-scan`，结果送入 amendment-plan。
6. **Vote 必须通过 write-vote 命令提交**：Agent 投票必须使用 `harnessctl feedback write-vote` 命令，禁止直接写入 votes 目录。write-vote 会注入 `_managed`、`_written_by`、`_schema_version`、`_vote_session_id` 元数据，aggregate-triage 会校验这些字段存在且 `_managed=true`。`evidence` 数组不得为空，每条 evidence 必须引用具体文件路径或代码片段。

---

## 前置条件

- 存在活跃 epic（ACTIVE_EPIC_ID 非空）
- 存在 status=submitted 的 feedback（由 hook 自动创建）

---

## 执行流程

### Step 1: 确认 Feedback 已提交

如果 hook 已自动提交，从 additionalContext 中获取 feedback_id。
否则手动提交：

```bash
$HARNESSCTL feedback submit \
  --epic-id ${EPIC_ID} \
  --stage ${CURRENT_STAGE} \
  --text "<用户原文摘要>" \
  --json
```

### Step 2: 收集证据包

```bash
$HARNESSCTL feedback evidence-pack \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --json
```

输出 `HFB-xxx.evidence-pack.json`，包含：
- feedback 原文 + 阶段
- impact-scan 覆盖情况
- surface-routing 匹配
- spec 存在性
- coverage-matrix 任务覆盖
- source_evidence_hints（关键词 + 候选路径）
- **source_probe_results**（P2 动态代码搜索结果）：
  - 基于 feedback 关键词自动搜索项目源码
  - 返回命中文件列表 + 短代码片段（每文件最多 20 行，总计最多 200 行）
  - Council agents 可直接引用 `candidates[].snippets` 作为 evidence
- spec 存在性
- coverage-matrix 任务覆盖
- source_evidence_hints（关键词 + 候选路径）

### Step 3: 初始化 Council

```bash
$HARNESSCTL feedback council-triage \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --json
```

返回 `votes_dir` 和 `agents` 列表。

### Step 4: 并行调度 6 个 Reviewer Agent

使用 Agent 工具并行调度（复用已有 agent 定义）。每个 agent **必须通过 `harnessctl feedback write-vote` 提交投票**，禁止直接写入 votes 目录文件：

```
Agent 1 (requirement-analyst):
  读取 evidence-pack，判断用户反馈是否改变需求语义/范围/用户意图。
  通过 write-vote 提交投票：
  $HARNESSCTL feedback write-vote --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID} \
    --agent requirement-analyst --stdin <<< '<vote JSON>'

Agent 2 (impact-analyst):
  读取 evidence-pack + 项目源码（按 source_evidence_hints 检索），
  判断是否遗漏影响面（仓库、模块、页面、接口）。
  通过 write-vote 提交投票：
  $HARNESSCTL feedback write-vote --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID} \
    --agent impact-analyst --stdin <<< '<vote JSON>'

Agent 3 (challenger):
  读取 evidence-pack，尝试反证"无需调整"是否站得住。
  通过 write-vote 提交投票：
  $HARNESSCTL feedback write-vote --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID} \
    --agent challenger --stdin <<< '<vote JSON>'

Agent 4 (plan-reviewer):
  读取 evidence-pack + tasks，判断 PLAN/tasks 是否遗漏相关任务。
  通过 write-vote 提交投票：
  $HARNESSCTL feedback write-vote --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID} \
    --agent plan-reviewer --stdin <<< '<vote JSON>'

Agent 5 (test-reviewer):
  读取 evidence-pack + spec，判断验收标准和测试是否覆盖。
  通过 write-vote 提交投票：
  $HARNESSCTL feedback write-vote --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID} \
    --agent test-reviewer --stdin <<< '<vote JSON>'

Agent 6 (code-reviewer):
  读取 evidence-pack + 相关源码（按 candidate_paths 检索），
  判断代码证据是否支持结论。注意：code-reviewer 只做事实判断，
  不单独决定上游阶段。
  通过 write-vote 提交投票：
  $HARNESSCTL feedback write-vote --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID} \
    --agent code-reviewer --stdin <<< '<vote JSON>'
```

> **⛔ 禁止行为**：Agent 不得使用 Write/Edit/Bash 直接创建 `votes/*.json` 文件。
> PreToolUse hooks 会拦截此类操作。只有 `write-vote` 命令能写入 votes 目录，
> 并自动注入 `_managed`/`_written_by`/`_schema_version`/`_vote_session_id` 元数据。

### Vote JSON 格式 (v2 Unified Schema)

每个 agent 必须输出：

```json
{
  "agent": "<agent-name>",
  "feedback_id": "<feedback-id>",
  "decision": "<FEEDBACK_TRIAGE_OUTCOME>",
  "classification": "<feedback-classification>",
  "target_stage": "<CLARIFY|SPEC|PLAN|EXECUTE>",
  "confidence": 0.86,
  "evidence": ["具体证据描述1", "具体证据描述2"],
  "reasoning": "判断理由简述",
  "related_gaps": [
    {
      "category": "test|docs|config|frontend|backend|auth|i18n|infra|data",
      "description": "同类遗漏描述",
      "confidence": 0.7
    }
  ]
}
```

强校验规则：
- `decision=REOPEN_PLAN` → `target_stage` 必须是 `PLAN`
- `decision=REOPEN_SPEC` → `target_stage` 必须是 `SPEC`
- `decision=REOPEN_CLARIFY` → `target_stage` 必须是 `CLARIFY`
- `decision=STAY_EXECUTE` → `target_stage` 必须是 `EXECUTE`
- `decision=NO_REOPEN_WITH_EVIDENCE` → `evidence` 非空

有效 decision 值：
- `REOPEN_CLARIFY` — 需求澄清阶段遗漏，需回退到 CLARIFY
- `REOPEN_SPEC` — 规格定义遗漏，需回退到 SPEC
- `REOPEN_PLAN` — 计划遗漏，需回退到 PLAN
- `STAY_EXECUTE` — 上游产物已覆盖，只是实现漏改
- `NO_REOPEN_WITH_EVIDENCE` — 确认无需调整，有充分证据
- `INSUFFICIENT_EVIDENCE` — 证据不足，无法判断
- `REJECT` — 反馈无效
- `DEFER` — 延期处理

### Agent 职责边界

| Agent | 判断范围 | 不应判断 |
|-------|----------|----------|
| requirement-analyst | 需求语义/范围/意图是否变化 | 代码实现细节 |
| impact-analyst | 影响面是否遗漏 | 具体代码修改方案 |
| challenger | "无需调整"结论是否有漏洞 | 具体返工方案 |
| plan-reviewer | 任务拆分是否遗漏 | 需求是否合理 |
| test-reviewer | 验收/测试是否覆盖 | 代码实现 |
| code-reviewer | 代码事实（是否缺口） | 上游阶段决策 |

### Step 5: 聚合 Verdict

```bash
$HARNESSCTL feedback aggregate-triage \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --json
```

聚合规则（按最早失效层级优先）：
1. 任何 `REOPEN_CLARIFY` → 整体 reopen CLARIFY
2. 否则任何 `REOPEN_SPEC` → reopen SPEC
3. 否则任何 `REOPEN_PLAN` → reopen PLAN
4. 全部 `NO_REOPEN_WITH_EVIDENCE` 且证据充分 → 不 reopen
5. 证据不足 → `INSUFFICIENT_EVIDENCE`（阻断，要求补证据）

### Step 5.5: Related-Gap Scan (v2 — MANDATORY)

After aggregation, **必须**检查是否需要 related-gap-scan。以下条件触发（任一即可）：

- verdict 为 `REOPEN_*`（任意 reopen 决策）
- verdict 为 `STAY_EXECUTE` 且 classification 含 `scope_gap`
- 任意 vote 的 `related_gaps` 非空

```bash
$HARNESSCTL feedback related-gap-scan \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --phase pre \
  --json
```

This generates `HFB-xxx.related-gap-scan.json` with sibling categories to check.

> **⛔ 禁止行为**：scope_gap 类型的 verdict 不得跳过 related-gap-scan 直接进入 amendment。
> scan 结果必须合入 amendment-plan，确保兄弟缺口同批修复。

The scan results feed into the amendment-plan to ensure sibling gaps are addressed together.
If scan discovers high-confidence sibling gaps (confidence ≥ 0.7), they must be included
in the amendment plan as additional tasks.

### Step 6: 根据 Verdict 执行后续

读取 verdict：

```bash
cat .harness/features/${EPIC_ID}/councils/feedback_triage_council/${FEEDBACK_ID}/verdict.json
```

#### 6a. REOPEN_* 路径

```bash
# triage.json 已由 aggregate 自动生成
$HARNESSCTL feedback plan-amendment --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID}
```

**Auto-Execute Matrix (v2)**：

| Verdict | Low Risk | Medium Risk | High Risk |
|---------|----------|-------------|-----------|
| `REOPEN_PLAN` | 自动 | 自动 + revision-diff gate | 人工确认 |
| `REOPEN_SPEC` | 自动 | 自动 + revision-diff gate | 人工确认 |
| `REOPEN_CLARIFY` | 自动 | 自动 + revision-diff gate | 人工确认 |
| `STAY_EXECUTE` | 自动 | 自动 + review gate | 非破坏性自动；破坏性人工确认 |
| `scope_change` | 人工确认 | 人工确认 | 人工确认 |

核心原则：`当前范围内 + 非破坏性 + 可验证 = 自动修`

**Risk-based approve 判断**：
1. 读取 epic state 中的 `risk_level`（默认 low）
2. 如果 classification 为 `scope_change` 或 `blocker`：始终人工确认
3. 如果 risk_level=high 且 verdict 为 REOPEN_*：人工确认
4. 否则：**自动 approve 并立即执行，不得询问用户确认**

> **⛔ 禁止行为**：verdict 确认 in-scope 后，禁止输出类似"要我现在创建任务并实施吗？"的询问。
> 应当直接执行 approve-amendment → reopen → re-* skill 或 task-graph merge。

```bash
$HARNESSCTL feedback approve-amendment --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID}
$HARNESSCTL reopen --epic-id ${EPIC_ID} --to ${TARGET_STAGE} --feedback-id ${FEEDBACK_ID}
```

然后根据 target_stage 执行对应 re-* skill：
- CLARIFY → re-clarify skill
- SPEC → re-spec skill
- PLAN → re-plan skill

**REOPEN 回退后必须重新完成对应阶段门禁**：
- REOPEN_PLAN → 重新执行 PLAN 阶段（更新 task graph），然后从 PLAN 出口门禁重新进入 EXECUTE
- REOPEN_SPEC → 重新执行 SPEC，然后重新执行 PLAN，然后进入 EXECUTE
- REOPEN_CLARIFY → 重新执行 CLARIFY → SPEC → PLAN → EXECUTE

使用 `harnessctl feedback re-complete` 标记每个回退阶段的完成：
```bash
$HARNESSCTL feedback re-complete --epic-id ${EPIC_ID} --feedback-id ${FEEDBACK_ID} \
  --stage ${COMPLETED_STAGE} --artifacts "tasks/,coverage-matrix.json"
```

#### 6b. NO_REOPEN_WITH_EVIDENCE 路径

基于 council 证据回答用户原始问题，然后关闭：

```bash
$HARNESSCTL feedback close \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --evidence "Council verdict: NO_REOPEN_WITH_EVIDENCE. <具体理由>"
```

#### 6c. INSUFFICIENT_EVIDENCE 路径

不允许关闭。输出提示：

```
证据不足，无法确定是否需要返工。
请补充以下信息后重新评审：
- [列出缺失的证据点]
```

#### 6d. STAY_EXECUTE 路径

留在当前阶段修复（不 reopen），**自动**创建补充任务并立即通过 `/harness:work` 执行：

```bash
$HARNESSCTL task-graph merge \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --new-tasks '[{"title": "...", "surface": "..."}]' \
  --json
```

> **⛔ 禁止行为**：STAY_EXECUTE 裁决后，禁止询问用户"是否需要创建任务"。
> 必须直接创建补充任务并用 `/harness:work` 执行。

修复完成后关闭 feedback。

---

## 完整流程图

```
feedback_candidate 检测
  → hook 自动 submit HFB-xxx
  → Guard 阻断（submitted feedback 存在，禁止 idle）
  → harnessctl feedback run-triage（自动执行 evidence-pack + council-triage init）
  → 6 agent 并行评审（必须使用 Agent 工具，禁止手工生成 vote JSON）
  → harnessctl feedback aggregate-triage（v2 严格 schema 校验）
  → harnessctl feedback continue（自动执行后续）：
      REOPEN_*         → plan-amendment → risk-based auto-approve → reopen → re-* skill → re-complete gate
      NO_REOPEN        → evidence answer → close
      INSUFFICIENT     → 阻断，要求补证据
      STAY_EXECUTE     → 自动补充任务 → /harness:work 执行 → close
      scope_gap 类型   → mandatory related-gap-scan → 兄弟缺口合入 amendment
```

### 硬性约束速查

| 约束 | 说明 |
|------|------|
| 禁止手工复刻 | 不得用 Bash/Write 创建 evidence-pack/votes/verdict 文件，hooks 自动拦截 |
| write-vote 唯一路径 | Agent 投票必须通过 `harnessctl feedback write-vote`，注入 managed 元数据 |
| evidence 非空 | vote 的 evidence 数组不得为空，必须引用具体文件/代码 |
| v2 schema only | decision 仅限 8 个标准值，旧值被 aggregate 拒绝 |
| 自动继续 | low/medium risk 确认后自动执行，不问用户 |
| feedback 不得 idle | submitted/triaged 状态的 feedback 必须立即处理 |
| related-gap-scan | scope_gap 类型必须执行，结果送入 amendment |
| approve-amendment gate | 高置信度 related gaps 必须在 Amend 或 Deferred(含 reason) 中体现 |
| REOPEN 门禁 | 回退阶段必须重新完成门禁，使用 re-complete 标记 |
