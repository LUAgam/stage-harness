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
| `submit` | 手动提交新 feedback | `/harness:feedback <epic-id> submit "前端页面需要适配"` |
| `triage` | 手动触发某个 HFB 的 triage 流程 | `/harness:feedback <epic-id> triage HFB-001` |
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
HFB-001   resolved   scope_gap_question    OMS前端页面不需要调整吗？
HFB-002   closed     scope_gap_question    [duplicate of HFB-001]
HFB-003   submitted  correction            议会发现问题不会回退...
──────────────────────────────────────────────────────────────
合计: 3 条 (resolved: 1, closed: 1, submitted: 1)
```

如果无任何 feedback，显示：`当前 epic 无 feedback 记录。`

### 子命令：submit

手动提交新的 feedback。

```bash
$HARNESSCTL feedback submit \
  --epic-id ${EPIC_ID} \
  --stage ${CURRENT_STAGE} \
  --text "${FEEDBACK_TEXT}" \
  --source manual \
  --json
```

提交后输出新 feedback 的 ID，并提示：

```
已提交 HFB-xxx。
  运行 /harness:feedback <epic-id> triage HFB-xxx 触发分诊流程。
```

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
