---
description: "问题修复（针对 VERIFY REJECTED 的问题循环修复 + 重新审查）"
argument-hint: "<epic-id>"
---

# harness-fix

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


针对验收阶段 REJECTED 的问题执行修复。从 `verification.json` 读取 CRITICAL 问题列表，驱动修复工作，完成后自动触发重新审查（`/harness:review`）。

## 角色定义

FIX 阶段 orchestrator。负责从 verification.json 提取 CRITICAL 问题、逐一分配修复任务、确认修复完成、触发重新审查。不直接修改代码——修复工作由 worker agent 执行，review skill 负责验证。

## 前置检查

验证当前 epic 处于 FIX 阶段（或 VERIFY REJECTED 状态）：

```bash
$HARNESSCTL state get <epic-id> --field current_stage
```

必须满足以下任一条件：
- `current_stage = FIX`
- `verification.json` 存在且 `acceptance_council = REJECTED`

若不满足，提示使用场景：
- 正常流程通过 `/harness:review` 触发（议会 REJECTED 时自动转 FIX）
- 手动执行时需先确认 epic 处于 FIX 状态

## 执行步骤

### Step 1：提取待修复问题

```bash
cat .harness/features/<epic-id>/verification.json
```

从 `verification.json` 中提取：
- `critical_issues`：CRITICAL 级别问题（**必须全部修复**）
- `high_issues`：HIGH 级别问题（**强烈建议修复**）
- `reviewer_verdicts`：各 reviewer 的详细意见

输出问题摘要，让用户确认修复优先级。

### Step 2：创建修复任务

针对每个 CRITICAL 问题创建修复 task：

```bash
$HARNESSCTL task create <epic-id> "FIX: <问题描述>"
```

### Step 3：执行修复

**REQUIRED SKILL:** Use `work` skill（修复模式）

向 skill 传入：
- `epic-id`
- `fix_issues`: CRITICAL 问题列表（从 verification.json 提取）
- `spec_path`: `.harness/specs/<epic-id>.md`（确保修复不破坏规格）
- `mode`: `fix`（限制修改范围，避免引入新问题）

修复模式特殊约束：
- 每个修复任务**只修改**与问题相关的代码，不做额外重构
- 修复完成后写入 receipt（可在内容中标记为 `fix` 类型）
- 保存修复说明到 `.harness/features/<epic-id>/fix-notes.md`

### Step 4：确认修复完成

验证所有 CRITICAL 修复任务已完成：

```bash
$HARNESSCTL task list <epic-id> --status pending
```

若仍有未完成的修复任务，展示列表并等待。

### Step 5：触发重新审查

修复完成后，自动转换状态并触发 review：

```bash
$HARNESSCTL state transition <epic-id> VERIFY
```

然后调用：`/harness:review <epic-id>`

## 产物要求

| 产物 | 路径 |
|------|------|
| 修复说明 | `.harness/features/<epic-id>/fix-notes.md` |
| 修复 receipts | `.harness/features/<epic-id>/receipts/<task-id>.json`（type=fix） |
| 更新后的 verification | `.harness/features/<epic-id>/verification.json`（由重新审查覆盖） |

`fix-notes.md` 格式：
```markdown
## Fix Session: <timestamp>

### CRITICAL Issues Fixed
- <issue-id>: <描述> → <修复方案>

### HIGH Issues Fixed (optional)
- <issue-id>: <描述> → <修复方案>

### Scope Boundary
修复仅涉及以下文件：<文件列表>
```

## 出口条件

- 所有 CRITICAL 问题修复任务 `status = done`
- `fix-notes.md` 存在且记录了修复方案
- 重新审查通过（`/harness:review` 返回 PASS 或 CONDITIONAL_PASS）

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| verification.json 不存在 | 提示先运行 `/harness:review <epic-id>` |
| 无 CRITICAL 问题 | 展示所有 HIGH 问题，询问是否需要修复 HIGH 问题后重新审查 |
| 修复任务超时或失败 | 保留已完成的修复，记录未完成项，等待手动干预 |
| 重新审查再次 REJECTED | 展示新的 CRITICAL 问题，可再次运行 `/harness:fix <epic-id>` |
| 修复引入新问题 | 审查会检测到，不允许继续，需回退相关修改 |

## 与其他阶段的关系

```
VERIFY (REJECTED) → $HARNESSCTL state transition <epic-id> FIX
                   → /harness:fix <epic-id>
                   → (内部) /harness:review <epic-id>
                   → PASS → DONE
                   → REJECTED → /harness:fix <epic-id> (再次)
```

最多允许 3 轮 FIX 循环。超过 3 轮时，升级为人工干预，展示未解决的 CRITICAL 问题并暂停。
