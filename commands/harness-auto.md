---
description: "自治模式：自动推进全流程（仅低/中风险 feature 适用）"
argument-hint: "<epic-id>"
---

# harness-auto

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


以自治模式运行指定 epic 的全流程，在中断预算范围内自动推进各阶段，最小化人工干预。

## 角色定义

自治模式 orchestrator。负责安全检查、阶段状态机驱动、循环推进。每次推进前必须通过 guard hooks 检查。**高风险 epic 禁止完全自治**——必须在特定阶段停下等待人工确认。

## 安全检查

读取 epic 风险等级：

```bash
$HARNESSCTL state get <epic-id> --field risk_level
```

**高风险（`risk_level: high`）禁止完全自治**：
- 展示警告：`此 epic 风险等级为 HIGH，自治模式受限`
- 自动推进允许：CLARIFY → SPEC → PLAN
- 强制暂停点：进入 EXECUTE 阶段前，必须消耗一次中断预算等待人工确认
- 若用户拒绝，终止自治模式

## 前置检查

```bash
$HARNESSCTL budget check --epic-id <epic-id>
```

若中断预算已耗尽，展示当前状态并终止。

## 自治循环

### 循环逻辑

```
LOOP:
  1. 检查 guard hooks
  2. 获取下一步动作：$HARNESSCTL state next --epic-id <epic-id>
  3. 按返回动作调用对应命令
  4. 检查停止条件
  5. 若无停止，继续循环
```

### 阶段到命令映射

| `$HARNESSCTL state next` 返回 | 调用命令 |
|---------------------------|---------|
| `run_clarify` | `/harness:clarify <epic-id>` |
| `run_spec` | `/harness:spec <epic-id>` |
| `run_plan` | `/harness:plan <epic-id>` |
| `run_execute` | `/harness:work <epic-id>` |
| `run_verify` | `/harness:review <epic-id>` |
| `run_done` | `/harness:done <epic-id>` |
| `wait_user` | 暂停，展示原因，消耗中断预算 |
| `complete` | 退出循环 |

### Guard Hooks（每次循环前检查）

在每次调用阶段命令前，运行 guard 检查：

```bash
$HARNESSCTL guard check --epic-id <epic-id> --stage <next-stage>
```

guard 检查内容：
- 前一阶段门禁是否通过
- 中断预算剩余是否 >= 1
- 无未处理的 CRITICAL 级别问题

任一检查失败则停止循环。

## 停止条件

**任一触发即立即停止循环：**

1. `must_confirm` 待处理 且 预算 >= 1 → 暂停，消耗预算，等待用户确认后继续
2. 安全/合规 reviewer 返回 FAIL → 强制停止，不允许继续
3. 同一 task 连续 3 次失败 → 停止，标注 task 为 `blocked`，展示失败原因
4. stage smoke 失败 → 停止，展示失败详情
5. 中断预算耗尽（`remaining = 0`） → 停止，展示当前状态
6. `$HARNESSCTL state next` 返回 `complete` → 正常退出

## 中断预算消耗规则

| 触发场景 | 消耗 |
|---------|------|
| must_confirm 暂停 | 1 次 |
| 高风险 epic 进入 EXECUTE 前确认 | 1 次 |
| task 连续失败阈值触发 | 1 次 |
| 用户手动确认后继续 | 0 次（已消耗） |

## 每次循环状态展示

每完成一个阶段，输出进度摘要：

```
[AUTO] 阶段完成: CLARIFY -> SPEC
      预算剩余: 3/5
      下一步: run_spec
```

## 产物要求

自治模式不产出额外产物，每个阶段的产物由对应 skill 负责生成（同手动模式）。

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| guard check 失败 | 停止循环，展示阻断原因 |
| 阶段命令失败 | 记录错误，停止循环，保留已完成产物 |
| `$HARNESSCTL state next` 返回未知动作 | 停止循环，报告未知状态 |
| 高风险强制暂停被拒绝 | 终止自治模式 |
