---
description: "自治模式：自动推进全流程（仅低/中风险 feature 适用）"
argument-hint: "<epic-id>"
---

# harness-auto

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
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

## 上下文恢复协议（硬性，无例外）

> **状态机是唯一真相源。** 无论会话历史、压缩摘要、或先前输出中声称"下一步是 X"，都**不得**作为阶段路由依据。每次进入自治循环（包括从 context compaction 恢复后），**第一个动作必须是** `$HARNESSCTL state next --epic-id <epic-id>`，并严格按其返回值路由。

违反此协议的典型表现：
- 从压缩摘要中读到"next step is DONE"后直接调用 `/harness:done`，跳过 BUILD/DEPLOY/E2E
- 从先前输出中推断"VERIFY 已通过，下一步是 DONE"而不查询状态机
- 在任何阶段完成后，凭记忆而非 `state next` 决定下一步

**恢复检查清单**（每次循环迭代开头、或从中断/压缩恢复时执行）：

```bash
# 1. 查询当前阶段（不信任记忆）
$HARNESSCTL state get <epic-id> --field current_stage

# 2. 查询下一步动作（唯一路由依据）
$HARNESSCTL state next --epic-id <epic-id>

# 3. 按返回值路由，不做任何跳跃

# 4. 必须通过 Skill 工具调用对应阶段插件（硬性，无例外）
#    禁止用 Bash/Agent/手动操作替代插件调用
```

> **⛔ 调度方式硬约束（最高优先级，不得违反）**
>
> 所有阶段推进**必须且只能**通过 `Skill` 工具调用对应的 harness 插件完成。
>
> **禁止的行为**：
> - 用 Bash 工具直接执行阶段工作内容（如手动 `docker compose up`、手动 `curl` 测试 API）
> - 用 Agent 工具派发通用代理来替代插件调用
> - 因为"知道该做什么"就跳过插件入口直接动手
> - 在 context compaction 恢复后，凭记忆中的"要做什么"直接执行，而不通过 Skill 调用插件
>
> **为什么**：每个阶段插件内部有标准化子流程（子代理调度、产物格式、验证逻辑）。
> 绕过插件 = 跳过子代理调度 + 跳过标准产物生成 + 跳过内置验证。
> 即使你完全清楚该阶段要做什么，也必须通过插件入口执行。
>
> **compaction 后特别注意**：context 压缩后你可能只记得"需要部署"或"需要测试"，
> 但忘记了"必须通过 Skill 调用插件"。此时请重新阅读本映射表，用 Skill 工具调用。

## 自治循环

### 循环逻辑

```
LOOP:
  1. 检查 guard hooks
  2. 获取下一步动作：$HARNESSCTL state next --epic-id <epic-id>
     ⚠️ 此步不可省略、不可用记忆替代、不可从摘要推断
  3. 按返回动作调用对应命令（严格映射，禁止跳跃）
  4. 检查停止条件
  5. 若无停止，继续循环
```

### 阶段到命令映射（命令式 — 必须严格执行）

> **执行方式**：收到 `state next` 返回值后，**立即**使用 `Skill` 工具调用下表中对应的插件。
> 不得在 Skill 调用前插入任何 Bash/Agent 工具调用来"手动完成"该阶段工作。
> 不得用任何其他方式替代 Skill 调用。

| `$HARNESSCTL state next` 返回 | 必须执行的 Skill 调用 |
|---------------------------|---------|
| `run_clarify` | `Skill(skill="stage-harness:harness-clarify", args="<epic-id>")` |
| `run_spec` | `Skill(skill="stage-harness:harness-spec", args="<epic-id>")` |
| `run_plan` | `Skill(skill="stage-harness:harness-plan", args="<epic-id>")` |
| `run_execute` | `Skill(skill="stage-harness:harness-work", args="<epic-id>")` |
| `run_verify` | **按 risk_level 分支(见下方 "VERIFY 跳过策略")** |
| `run_build` | `Skill(skill="stage-harness:harness-build", args="<epic-id>")` |
| `run_deploy` | `Skill(skill="stage-harness:harness-deploy", args="<epic-id>")` |
| `run_e2e` | `Skill(skill="stage-harness:harness-e2e-test", args="<epic-id>")` |
| `run_done` | `Skill(skill="stage-harness:harness-done", args="<epic-id>")` |
| `wait_user` | 暂停，展示原因，消耗中断预算（不调用 Skill） |
| `complete` | 退出循环（不调用 Skill） |

**示例 — 收到 `run_deploy` 时的正确执行**：
```
# 正确 ✅：通过 Skill 工具调用插件
Skill(skill="stage-harness:harness-deploy", args="sh-1-xxx")

# 错误 ❌：手动执行部署命令
Bash("docker compose up -d")
Bash("curl localhost:9000/health")

# 错误 ❌：用通用 Agent 替代
Agent(prompt="部署服务并验证", subagent_type="general-purpose")
```

**示例 — 收到 `run_e2e` 时的正确执行**：
```
# 正确 ✅：通过 Skill 工具调用插件
Skill(skill="stage-harness:harness-e2e-test", args="sh-1-xxx")

# 错误 ❌：手动写测试用例并执行
Agent(prompt="执行E2E测试...", subagent_type="general-purpose")
Bash("curl localhost:9000/api/v1/...")
```

### VERIFY 跳过策略（auto 模式专属）

收到 `run_verify` 时，按 epic 风险等级派发：

```bash
RISK_LEVEL=$($HARNESSCTL state get <epic-id> --field risk_level)

if [ "$RISK_LEVEL" = "high" ]; then
  # 高风险：必须完整审查，不跳过
  # 执行：Skill(skill="stage-harness:harness-review", args="<epic-id>")
else
  # low/medium：跳过 VERIFY 议会，直接进入 BUILD
  $HARNESSCTL state transition <epic-id> VERIFY
  $HARNESSCTL state transition <epic-id> BUILD
  export HARNESS_SKIP_VERIFY_GATE=1
  # 执行：Skill(skill="stage-harness:harness-build", args="<epic-id>")
fi
```

**说明**：
- 该跳过仅在 auto 自治循环内生效。手动调用 `/harness:review` 或 `/stage-harness:harness-build` 不受影响。
- 跳过时不写 `verification.json`，但状态机正常经过 VERIFY → BUILD（保留 state log 可追溯）。
- `HARNESS_SKIP_VERIFY_GATE=1` 仅用于让 `harness-build` 前置检查放宽 VERIFY 产物校验，改查 EXECUTE 产物。
- 用户可通过 `.harness/config.json` 设置 `auto_skip_verify: false` 关闭该跳过（默认开启）；关闭时即使 low/medium 也走完整 VERIFY。

### E2E-TEST 结果处理策略（auto 模式专属）

收到 `run_e2e` 时，调用 `Skill(skill="stage-harness:harness-e2e-test", args="<epic-id>")`，完成后读取 `verify-cases/verify-receipt.json` 的 `status` 字段：

```bash
E2E_STATUS=$(cat .harness/features/<epic-id>/verify-cases/verify-receipt.json | jq -r '.status')

case "$E2E_STATUS" in
  PASS)
    # 全部通过，继续循环（下一步 run_done）
    ;;
  PARTIAL)
    # P0 全通过但有 P1/P2/P3 失败
    # 暂停，展示未通过 case 列表，消耗 1 次中断预算
    # 用户选择：
    #   A: 接受推进 DONE（失败 case 记入 delivery-summary.md 已知缺陷区）
    #   B: 走 FIX 兜底（按 FAIL 处理）
    ;;
  FAIL)
    # harness-e2e-test 已合成 verification.json 并转 FIX
    # auto 循环从 FIX 完成后重新进入 BUILD → DEPLOY → E2E-TEST
    # 最多 3 轮，超过则停止循环等待人工干预
    ;;
esac
```

**说明**：
- `harness-e2e-test` 内部已处理 FAIL 的 `verification.json` 合成和状态转 FIX，auto 循环只需跟随 `harnessctl state next` 的返回值继续推进。
- PARTIAL 是唯一需要 auto 循环主动暂停的 E2E 结果——因为需要用户决策是否接受部分缺陷交付。
- FIX 回流路径：`Skill(skill="stage-harness:harness-fix")` → `Skill(skill="stage-harness:harness-build")` → `Skill(skill="stage-harness:harness-deploy")` → `Skill(skill="stage-harness:harness-e2e-test")`（完整重试），由 `fix_source_stage = E2E_TEST` 路由。

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
5. 编译失败（BUILD FAIL）→ 停止，展示编译错误，等待 FIX 后继续
6. 部署失败（DEPLOY FAIL）→ 停止，展示部署错误，等待 FIX 后继续
7. e2e 测试失败（E2E FAIL）→ 合成 `verification.json`，状态转 FIX，调用 `Skill(skill="stage-harness:harness-fix", args="<epic-id>")`；FIX 完成后从 BUILD → DEPLOY → E2E-TEST 完整重试（最多 3 轮）
8. e2e 测试部分通过（E2E PARTIAL）→ 暂停，展示未通过的 P1/P2/P3 case，消耗中断预算等待用户选择：接受推进 DONE 或走 FIX 兜底
8. 中断预算耗尽（`remaining = 0`） → 停止，展示当前状态
9. `$HARNESSCTL state next` 返回 `complete` → 正常退出

## 中断预算消耗规则

| 触发场景 | 消耗 |
|---------|------|
| must_confirm 暂停 | 1 次 |
| 高风险 epic 进入 EXECUTE 前确认 | 1 次 |
| task 连续失败阈值触发 | 1 次 |
| E2E PARTIAL 暂停等待用户决策 | 1 次 |
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
