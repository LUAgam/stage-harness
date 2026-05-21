---
description: "Feedback 生命周期管理（查看、提交、分诊、批量关闭、清理）"
argument-hint: "<epic-id> [subcommand] [options]"
---

# harness-feedback

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```

---

## 概述

Feedback 生命周期管理命令。提供对 HFB（Harness Feedback）记录的查看、提交、分诊、关闭和清理能力。

与内部 `feedback-triage` skill 的关系：
- `feedback-triage` skill 负责 **6 agent 并行评审**的完整 triage 流程（evidence-pack → council → aggregate → auto-execute）
- 本命令负责 **用户侧管理操作**：查看状态、手动提交、批量关闭、物理清理
- 本命令的 `triage` 子命令会调度内部 `feedback-triage` skill，不重复实现

---

## 参数解析

从用户输入中解析：
- `EPIC_ID`：第一个参数，epic 标识符
- `SUBCOMMAND`：第二个参数，子命令（默认 `list`）
- 后续参数视子命令而定

支持的子命令：

| 子命令 | 说明 | 示例 |
|--------|------|------|
| `list` | 列出所有 HFB 及状态 | `/harness:feedback <epic-id> list` |
| `submit` | 提交并立即编排完整 triage | `/harness:feedback <epic-id> submit "前端页面需要适配"` |
| `submit --record-only` | 只记录不自动 triage | `/harness:feedback <epic-id> submit --record-only "批量备注"` |
| `triage` | 手动触发某个 HFB 的 triage 流程 | `/harness:feedback <epic-id> triage HFB-001` |
| `gate-check` | 检查未处理 HFB 是否阻断进展 | `/harness:feedback <epic-id> gate-check` |
| `close` | 关闭指定 HFB | `/harness:feedback <epic-id> close HFB-001 --reason "已修复"` |
| `close-all` | 批量关闭所有未关闭的 HFB | `/harness:feedback <epic-id> close-all` |
| `clean` | 物理删除所有 feedback 记录 | `/harness:feedback <epic-id> clean` |
| `stats` | 展示 feedback reopen 统计 | `/harness:feedback <epic-id> stats` |

如果未指定子命令，默认执行 `list`。

---

## 硬性规则

1. **`clean` 操作不可逆**：执行前必须向用户确认，展示将删除的文件数量。
2. **`triage` 必须调用内部 skill**：禁止手工创建 evidence-pack/votes/verdict 文件，必须通过 `harnessctl` + Agent 工具完成。
3. **`close-all` 会跳过已关闭的 HFB**：不会重复关闭。
4. **`submit` 默认强制编排完整 triage**：submit 后禁止停在 submitted 状态直接回答用户。只有 `--record-only` 允许只记录不处理。
5. **未处理 HFB 阻断后续**：存在 submitted/triaging/triaged(未 continue) 状态的 HFB 时，禁止执行与 feedback 处理无关的开发动作或阶段推进。
6. **`deferred` 不能无条件放行**：deferred 状态必须有 defer_reason + defer_to/defer_until + evidence，否则 gate-check 不放行。

---

## 执行流程

### 子命令：list（默认）

列出当前 epic 的所有 feedback 记录及状态。

```bash
$HARNESSCTL feedback list --epic-id ${EPIC_ID} --status all --json
```

以表格形式展示：

```
Feedback 列表 (epic: <epic-id>)
──────────────────────────────────────────────────────────────
ID        状态       类型                  内容摘要
──────────────────────────────────────────────────────────────
HFB-001   resolved   scope_gap_question    前端页面不需要调整吗？
HFB-002   closed     scope_gap_question    [duplicate of HFB-001]
HFB-003   submitted  correction            议会发现问题不会回退...
──────────────────────────────────────────────────────────────
合计: 3 条 (resolved: 1, closed: 1, submitted: 1)
```

如果无任何 feedback，显示：`当前 epic 无 feedback 记录。`

### 子命令：submit

提交新 feedback 并**立即编排完整 triage 闭环**。这是 orchestrator 入口，不是简单记录命令。

> **⛔ 核心约束**：submit 后禁止停在 submitted 状态。必须完成完整 triage 流程后，再基于 verdict 结论回答用户。
> 只有显式指定 `--record-only` 时，才允许只记录不处理（适用于批量录入/人工整理场景）。

#### 默认模式（submit + 自动 triage）

**Step 1**: 创建 HFB 记录

```bash
SUBMIT_RESULT=$($HARNESSCTL feedback submit \
  --epic-id ${EPIC_ID} \
  --stage ${CURRENT_STAGE} \
  --text "${FEEDBACK_TEXT}" \
  --source manual \
  --json)
FEEDBACK_ID=$(echo "$SUBMIT_RESULT" | python3 -c "import json,sys;print(json.load(sys.stdin)['feedback_id'])")
```

**Step 2**: 收集证据包

```bash
$HARNESSCTL feedback evidence-pack \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --json
```

**Step 3**: 初始化议会

```bash
$HARNESSCTL feedback council-triage \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --json
```

**Step 4**: 并行调度 6 agent 投票

使用 Agent 工具并行调度以下 6 个角色（必须通过 `harnessctl feedback write-vote` 提交，禁止手工创建 vote JSON）：

- requirement-analyst
- impact-analyst
- challenger
- plan-reviewer
- test-reviewer
- code-reviewer

每个 agent 必须：
- 引用具体文件路径或代码片段作为 evidence
- 使用 v2 schema 标准 decision 值
- 通过 `harnessctl feedback write-vote` 命令提交

**Step 5**: 聚合裁决

```bash
$HARNESSCTL feedback aggregate-triage \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --json
```

**Step 6**: Related-gap-scan（条件触发）

以下任一条件满足时，必须执行 related-gap-scan：
1. verdict 为 REOPEN_*（任何回退）
2. verdict 为 STAY_EXECUTE 且 classification 含 scope_gap
3. 任意 vote.related_gaps 非空
4. feedback classification = scope_gap_question

```bash
$HARNESSCTL feedback related-gap-scan \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --json
```

**Step 7**: 自动执行后续

```bash
$HARNESSCTL feedback continue \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --execute \
  --json
```

`continue --execute` 执行边界：只能调用 harness 编排命令（plan-amendment / approve-amendment / reopen / task-graph merge / re-complete / close）。真正代码/文档修改仍由对应阶段命令执行（`/harness:work`、re-plan、re-spec）。

| verdict | 后续动作 | 是否问用户 |
|---------|---------|-----------|
| STAY_EXECUTE + low/medium risk | 自动 task-graph merge → /harness:work | 不问 |
| REOPEN_* + low/medium risk | auto plan-amendment → approve → reopen | 不问 |
| NO_REOPEN_WITH_EVIDENCE | 带证据回答 → close | 不问 |
| INSUFFICIENT_EVIDENCE | 阻断，要求补证据 | 打断 |
| scope_change / high risk | 展示 amendment plan | 需确认 |

#### --record-only 模式

仅创建 HFB 记录，不自动 triage。HFB metadata 写入 `"record_only": true`。

```bash
$HARNESSCTL feedback submit \
  --epic-id ${EPIC_ID} \
  --stage ${CURRENT_STAGE} \
  --text "${FEEDBACK_TEXT}" \
  --source manual \
  --json
```

提交后在 HFB JSON 中补充 metadata：
```json
{"record_only": true, "triage_required": false}
```

> 注意：record-only 的 HFB 不会触发 gate-check 阻断。

### 子命令：triage

手动触发指定 HFB 的完整 triage 流程。

**Step 1**: 确认 feedback 状态为 `submitted`

```bash
$HARNESSCTL feedback list --epic-id ${EPIC_ID} --status open --json
```

若指定的 HFB 不存在或已处理，提示错误。

**Step 2**: 调用 `feedback-triage` skill 执行完整流程

按 `skills/feedback-triage/SKILL.md` 定义执行：
1. `harnessctl feedback evidence-pack`
2. `harnessctl feedback council-triage`
3. 6 agent 并行评审（通过 Agent 工具调度）
4. `harnessctl feedback aggregate-triage`
5. Related-gap scan（如适用）
6. 根据 verdict 自动执行后续动作

> **⛔ 禁止行为**：禁止跳过 council 评审直接关闭 feedback。

### 子命令：close

关闭指定的 HFB。

```bash
$HARNESSCTL feedback close \
  --epic-id ${EPIC_ID} \
  --feedback-id ${FEEDBACK_ID} \
  --evidence "${REASON}" \
  --force \
  --json
```

若 feedback 需要 reopen 但未执行，`--force` 标志会绕过校验。

### 子命令：close-all

批量关闭所有未关闭的 HFB。

```bash
$HARNESSCTL feedback close-all \
  --epic-id ${EPIC_ID} \
  --reason "${REASON}" \
  --json
```

展示关闭结果：

```
已关闭 N 条 feedback: HFB-001, HFB-003, ...
跳过 M 条已关闭: HFB-002, ...
```

### 子命令：clean

物理删除所有 feedback 记录（文件 + council 目录）。

**Step 1**: 先执行 list 展示当前状态

```bash
$HARNESSCTL feedback list --epic-id ${EPIC_ID} --status all --json
```

**Step 2**: 向用户确认

展示将删除的内容：
- feedback 目录下的文件数量
- council 记录数量

> 确认后执行，不可逆。

**Step 3**: 执行清理

```bash
$HARNESSCTL feedback clean \
  --epic-id ${EPIC_ID} \
  --json
```

### 子命令：stats

展示 feedback reopen 统计和模式分析。

```bash
$HARNESSCTL feedback reopen-stats --epic-id ${EPIC_ID} --json
```

以人类可读格式展示：
- 按 classification 分类的 reopen 次数
- 高频 reopen 模式
- 建议改进方向

### 子命令：gate-check

检查是否存在未处理的 feedback 阻断后续进展。返回结构化结果，包含阻断项和下一步操作。

```bash
$HARNESSCTL feedback gate-check --epic-id ${EPIC_ID} --json
```

输出示例（blocked）：
```json
{
  "status": "blocked",
  "blocked_count": 1,
  "blocked_items": [
    {
      "feedback_id": "HFB-003",
      "reason": "submitted_without_evidence_pack",
      "next_action": "feedback evidence-pack",
      "required_commands": [
        "feedback evidence-pack --epic-id <epic-id> --feedback-id HFB-003",
        "feedback council-triage --epic-id <epic-id> --feedback-id HFB-003"
      ]
    }
  ]
}
```

输出示例（pass）：
```json
{
  "status": "pass",
  "blocked_count": 0,
  "blocked_items": []
}
```

**阻断规则**：

| HFB 状态 | 是否阻断 |
|----------|---------|
| submitted（无 evidence-pack） | 阻断 |
| triaging（无 verdict） | 阻断 |
| triaged（未 continue） | 阻断 |
| amendment_planned（未 approve） | 阻断 |
| reopened（未 re-complete） | 阻断 |
| deferred（缺 reason/defer_to/evidence） | 阻断 |
| rejected（缺 evidence） | 阻断 |
| closed / resolved | 放行 |
| record_only=true | 放行（不参与 gate） |

**集成位置**：
- Stop hook / stage-reminder hook 在每次 prompt 时调用
- EXECUTE / VERIFY / DONE 阶段 gate 前调用
- 阻断时展示 `next_action` 和 `required_commands`，引导处理

---

## 产物要求

本命令不产出新的产物文件。所有操作通过 `harnessctl` 标准命令完成，产物由 `harnessctl` 管理。

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| epic 不存在 | 提示运行 `/harness:start` |
| feedback 目录不存在 | `list` 返回空，`clean` 提示无需清理 |
| 指定的 HFB-xxx 不存在 | 提示可用的 HFB ID 列表 |
| triage 阶段 agent 调度失败 | 保留已完成的 vote，提示手动重试 |
| close 校验失败 | 展示失败原因，提示使用 `--force` 或先完成必要步骤 |
