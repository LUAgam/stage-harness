---
description: "JIT 即时诊断与补丁工作流：分析刚才的运行偏差，生成候选补丁，支持应用与回滚"
argument-hint: "<epic-id>"
---

# harness-patch

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

## 角色定义

JIT 诊断与补丁 orchestrator。用于在运行受阻或人工中断后，即时分析偏差根因，生成并管理候选规则补丁，无需等待 epic 完成。

## 执行步骤

### Step 1：获取诊断包

```bash
$HARNESSCTL patch diagnose --epic-id <epic-id> --json
```

读取输出，注意以下关键信号：

- `failure_events`：gate_failed / guard_failed / task_triaged / hook_blocked
- `runtime_health.consecutive_failures`
- `gate_skips`
- `active_rules_count`（避免产出重复补丁）

若 `failure_events` 为空且 `consecutive_failures = 0`，输出：
> 当前 epic 没有检测到高价值失败信号。如果你认为系统出了问题，请描述具体情况。

### Step 2：查看已有候选补丁

```bash
$HARNESSCTL patch list --json
```

列出与当前 epic 相关的 patch（status=candidate 或 active_epic）。避免对同一问题重复生成补丁。

### Step 3：调用 system-observer 生成补丁

**REQUIRED AGENT:** Invoke agent `system-observer`

传入 epic_id 和诊断包输出，让 system-observer 完成分析和 patch 文件生成。

system-observer 会生成：
- `.harness/memory/candidate-patches/<patch-id>/candidate-patch.md`
- `.harness/memory/candidate-patches/<patch-id>/meta.json`
- `.harness/logs/epics/<epic-id>/incident-summary-<ts>.json`

### Step 4：展示补丁给用户

```bash
$HARNESSCTL patch show <patch-id>
```

展示生成的补丁内容，告知用户：

```
✅ 诊断完成 — 候选补丁已生成

补丁 ID: <patch-id>
偏差类型: <deviation_type>
建议规则: <proposed_rule 摘要>

用户操作选项:
  1. 查看并编辑补丁: .harness/memory/candidate-patches/<patch-id>/candidate-patch.md
  2. 应用补丁 (epic-local): harnessctl patch apply <patch-id>
  3. 直接继续（不应用）: /harness:auto <epic-id>
```

### Step 5（可选）：应用补丁

若用户确认应用：

```bash
$HARNESSCTL patch apply <patch-id> [--scope epic|project]
```

应用后提示：
> 规则已加载。下次 session 启动或 prompt 提交时自动注入。
> 继续 epic：/harness:auto <epic-id>

## 工作流（快捷指引）

```
模型跑偏/被拦截/死循环
  → 用户中断 (Ctrl+C)
  → 新 session，输入: /harness:patch <epic-id>
  → system-observer 分析并输出候选补丁
  → 用户 Review 并可手动编辑 candidate-patch.md
  → harnessctl patch apply <patch-id>
  → 继续 /harness:auto <epic-id>
  → 补丁在新 session 中自动通过 additionalContext 注入
```

## 产物要求

| 产物 | 路径 |
|------|------|
| 诊断包（只读） | `harnessctl patch diagnose --epic-id <id> --json` |
| 候选补丁 | `.harness/memory/candidate-patches/<patch-id>/candidate-patch.md` |
| 补丁元数据 | `.harness/memory/candidate-patches/<patch-id>/meta.json` |
| 事故摘要 | `.harness/logs/epics/<epic-id>/incident-summary-<ts>.json` |

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| 无失败信号 | 提示用户描述问题，或直接继续 `/harness:auto` |
| system-observer 无法生成补丁 | 展示诊断包，建议用户手动在 `rules/epic-local/<epic-id>/` 下写规则 |
| patch apply 失败 | 展示错误，建议手动复制文件到规则目录 |
