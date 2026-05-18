---
description: "端到端测试（生成测试 case → 逐个验证与修复），DEPLOY 之后执行；失败兜底走 FIX → BUILD"
argument-hint: "<epic-id>"
---

# harness-e2e-test

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

解析 `e2e-case-tracker.sh` 路径：

```bash
E2E_TRACKER="$(dirname "$HARNESSCTL")/e2e-case-tracker.sh"
test -x "$E2E_TRACKER" || {
  echo "e2e-case-tracker.sh not found at $E2E_TRACKER" >&2
  exit 1
}
```

执行用户价值驱动的端到端测试阶段：先基于需求与代码修改生成结构化测试 case 列表，再逐个验证并对失败 case 做就近修复。该命令是 `harness-e2e` 的用户价值驱动变体，专注于业务闭环验证而非纯运行时套件。

## 角色定义

E2E-TEST 阶段 orchestrator。负责依次调度 `generate-test-cases` 与 `verify-and-fix-cases` 两个 skill，通过 `e2e-case-tracker.sh` 脚本管理产物完整性，根据最终结果推进或回流到 FIX。

**最小上下文原则**：orchestrator 不直接生成 case、不直接执行测试、不直接修代码——这些由两个 skill 内部完成。orchestrator 只做门禁检查、脚本调度、状态路由。

**连续执行原则（硬性）**：整个 E2E-TEST 流程（Step 0 → Step 1 → Step 1.5 → Step 2 → Step 2.5 → Step 3 → 出口路由）是一个**不可分割的执行序列**。每个 skill 返回后，orchestrator 必须在**同一个响应**中立即执行下一步。禁止在步骤之间主动 end_turn 等待用户输入（唯一例外：AskUserQuestion 索取凭证）。若 skill 执行时间过长导致 turn 消息数接近上限，orchestrator 应在 skill 调度前输出简短状态提示，但 skill 返回后的后续步骤必须立即执行。

## 前置检查

验证 DEPLOY 阶段已通过：

```bash
$HARNESSCTL stage-gate check DEPLOY --epic-id <epic-id>
```

必须满足：
- `<feature_dir>/deploy-receipt.json` 存在且 `status` 为 `PASS` 或 `SKIPPED`
- `<feature_dir>/build-receipt.json` 存在且 `changed_files_checked` 非空
- 需求澄清文档（`clarification-notes.md` 或 `specs/<epic-id>.md`）可读

若检查失败，提示先完成 `/stage-harness:harness-deploy <epic-id>`，终止。

## 注册调度来源

前置检查通过后，立即注册 dispatch 记录：

```bash
$HARNESSCTL dispatch register <epic-id> E2E --via=skill:harness-e2e-test
```

## 最小上下文加载（硬性）

orchestrator 在调度 skill 前**只允许**读取以下文件用于路径拼接与门禁判断：
- `.harness/features/<epic-id>/build-receipt.json`（仅判断状态字段）
- `.harness/features/<epic-id>/deploy-receipt.json`（仅判断状态字段）
- `.harness/features/<epic-id>/verify-cases/case-tracker.json`（仅判断恢复状态）
- `.harness/features/<epic-id>/verify-cases/gen-checkpoints/`（仅检查目录是否存在，判断 Step 1 是否需要恢复）

**禁止**自行 `ls` epic 目录、读取需求文档/代码文件、扫描配置消费点等任何动作——这些由 skill 内部执行。

## 执行步骤

门禁通过后，按以下步骤执行。**必须立刻发出 skill 调度信号**，不得穿插任何额外探查。

### Step 0 — 断点恢复检测

```bash
# 检查是否存在已初始化的 tracker
if [ -f ".harness/features/<epic-id>/verify-cases/case-tracker.json" ]; then
  $E2E_TRACKER status <epic-id>
fi
```

路由逻辑：
- **case-tracker.json 存在且有 pending/in_progress case** → 恢复模式，跳过 Step 1 和 Step 1.5，直接进入 Step 2
- **test-cases.md 存在且 tracker 已初始化（有注册 case）** → 跳过 Step 1 和 Step 1.5，直接进入 Step 2
- **test-cases.md 存在但无 tracker** → 执行 Step 1.5（初始化 tracker 并注册），然后进入 Step 2
- **test-cases.md 不存在但 gen-checkpoints/ 存在** → generate-test-cases 中途崩溃，重新调度 Step 1（skill 内部会从 checkpoint 恢复）
- **test-cases.md 不存在且无 checkpoint** → 正常流程，从 Step 1 开始
- **所有 case 已处理（check-complete 返回 0）** → 直接进入 Step 3（产物验证）

### Step 0.5 — 门禁初始化

```bash
$E2E_TRACKER gate init <epic-id>
```

若 `e2e-gate-status.json` 已存在（断点恢复场景），复用已有状态，不重新初始化。

### Step 1 — 生成测试 case 列表

**REQUIRED: 通过 Agent 工具调度 `stage-harness:generate-test-cases` 子代理**

使用 `Agent` 工具启动子代理，`subagent_type` 设为 `stage-harness:generate-test-cases`。Agent 调用参数：

```
subagent_type: "stage-harness:generate-test-cases"
description: "生成 E2E 测试 case 列表"
prompt: |
  epic_id: <epic-id>
  feature_dir: .harness/features/<epic-id>/
  spec_path: .harness/specs/<epic-id>.md
  clarification_path: .harness/features/<epic-id>/clarification-notes.md
  build_receipt_path: .harness/features/<epic-id>/build-receipt.json
  deploy_receipt_path: .harness/features/<epic-id>/deploy-receipt.json
```

子代理内部会（方法论已内置于 agent 定义，无需外部 SKILL.md）：
1. 按 Phase A→B→C→D→E 顺序执行，每个 Phase 完成后写入 checkpoint
2. Phase D 将 test-cases.md 写入磁盘（含 Case 注册表）
3. Phase E 完成覆盖度自检
4. 执行 tracker 初始化（init + register-all + status）
5. 返回报告：生成的 case 数量、各维度分布、tracker 初始化状态

**为什么用 Agent 子代理**：generate-test-cases 执行时间长（5-10 分钟，100+ 条消息），内联 Skill 会导致：(1) 主会话 turn 过长触发 end_turn；(2) prompt cache 5 分钟 TTL 过期后冷启动中断。子代理有独立上下文窗口（从 0 开始），不受主会话 cache TTL 影响，且完成后主会话只需做轻量的门禁检查。

**预期产物**：`<feature_dir>/test-cases.md`（含 Case 注册表）+ tracker 已初始化

失败处理：子代理返回阻塞原因（必备输入缺失 / 覆盖度自检无法满足）→ 终止本命令，输出阻塞详情，等待人工补齐输入。**不**自动降级。

**⚠️ 防 turn 中断（硬性）**：Agent 工具返回后，orchestrator **必须立即继续产物门禁验证**，不得 end_turn。

### Step 1 完成后 — 产物门禁与重试（硬性）

子代理返回后，执行脚本化验证：

```bash
$E2E_TRACKER gate validate-step1 <epic-id>
```

路由逻辑：
- 返回 0（PASS）→ 进入 Step 1.5
- 返回非零（FAIL）→ 读取 gate 状态中 `step_1_generate.attempts`：
  - attempts < 3 → 重新调度 `stage-harness:generate-test-cases` 子代理
    （子代理内部从 gen-checkpoints 恢复）
  - attempts >= 3 → 终止，输出阻塞详情（含每次失败的 errors），等待人工介入

**C-NO-DEGRADE（硬性）**：orchestrator 严禁自行编写 test-cases.md 替代品。
`gate validate-step1` 是唯一能将 `step_1_generate.status` 置为 PASS 的通道。
即使 orchestrator 自行创建了文件，脚本仍会验证注册表格式和 case 数量。

### Step 1.5 — 初始化 tracker 并注册 case（门禁）

Step 1 完成后，**必须**执行以下脚本化操作：

```bash
# 验证 test-cases.md 存在且非空
test -s ".harness/features/<epic-id>/test-cases.md" || {
  echo "ERROR: test-cases.md is empty or missing" >&2
  exit 1
}

# 验证注册表存在
grep -q "E2E_CASE_REGISTRY_START" ".harness/features/<epic-id>/test-cases.md" || {
  echo "ERROR: Case registry not found in test-cases.md" >&2
  exit 1
}

# 初始化 tracker
$E2E_TRACKER init <epic-id>

# 从注册表批量注册所有 case
$E2E_TRACKER register-all <epic-id>

# 验证注册数量 > 0
$E2E_TRACKER status <epic-id>
```

若注册数量为 0，终止并报错。

注册成功后写入门禁状态：

```bash
$E2E_TRACKER gate set <epic-id> step_1_5_register PASS \
  --field registered_count=<实际注册数>
```

### Step 2 前置门禁（硬性）

```bash
$E2E_TRACKER gate check <epic-id> step_2_verify
```

**C-NO-INLINE-VERIFY（硬性）**：orchestrator 严禁自行执行 case 验证逻辑。
Step 2 的全部验证工作**必须且只能**通过调度 `verify-and-fix-cases` 技能完成。

违反判定：若 orchestrator 在 Step 1.5 之后、Step 2.5 之前出现以下任何行为，视为违规：
- 直接调用被测服务的 API 或接口
- 通过任何手段绕过服务认证层执行业务代码（如进入容器/进程内部直接调用函数）
- 使用不需要认证的接口替代需要认证的接口来"验证通过"
- 直接调用 e2e-case-tracker.sh 的 start/pass/fail/skip 命令修改 case 状态

上述行为即使在子代理失败、技能不可用等异常场景下也不允许。
正确做法是报告阻塞并终止。

### Step 2 — 逐个验证与修复 case

**REQUIRED SKILL:** Use `stage-harness:verify-and-fix-cases` skill

传入：
- `epic_id`
- `feature_dir`：`.harness/features/<epic-id>/`
- `test_cases_path`：`<feature_dir>/test-cases.md`
- `tracker_path`：`<feature_dir>/verify-cases/case-tracker.json`
- `spec_path`：`.harness/specs/<epic-id>.md`
- `build_receipt_path`：`<feature_dir>/build-receipt.json`
- `deploy_receipt_path`：`<feature_dir>/deploy-receipt.json`

**硬性约束**（orchestrator 调度前必须明确传达）：

1. **真实凭证不得编造**：需要登录态、JWT、API Key 时必须中断询问用户；占位 token、伪造手机号验证码一律禁止。
2. **凭证最大化复用**：用户已提供凭证后，后续 case 必须优先复用 `session-state.json` 中的句柄；仅在过期、换角色、验证登录本身时才再次询问。
3. **凭证依赖分批执行（防中断策略）**：先执行所有不需要凭证的 case，再集中处理需要凭证的 case。这样即使等待凭证时 session 中断，无凭证 case 的结果已持久化。向用户索取凭证时应一次性获取，避免多次中断。
4. **UI 必留截图**：UI / API+UI case 无论成败必须保留 `screenshots/final.png`，失败时另存 `screenshots/failure.png`。
5. **性能测试不可中断**：识别到的性能/质量技能必须从头跑完，禁止因耗时长或"看起来收敛"提前终止。
6. **单 case 修复闭环上限 3 次**：超过即标 `failed-after-max-retries`，不阻塞后续 case；外层由本命令决定是否走 FIX 兜底。
6. **跳过必须有理由**：仅允许跳过 case 本身错误、外部依赖确实不可用、与本次需求无关的前置无法满足；难测/耗时长不是合法理由。
7. **部署环境端口主动探测（硬性前置）**：禁止硬编码端口号。探测方式全面覆盖：`deploy-receipt.json` → `docker ps`/`docker-compose ps` → `ss -tlnp`/`netstat -tlnp` → `systemctl list-units` → `pm2 list` → `ps aux | grep` → nginx/Apache 配置检查。
8. **认证凭证严禁伪造（硬性）**：必须中断并向用户索取登录信息，严禁自行伪造。
9. **Playwright 不可用时必须尝试替代方案**：按优先级尝试 ① python+playwright库 ② python+selenium ③ 其他方案；全部不可用时方可 skip。
10. **质量/准确率测试必须完整执行**：不得抽样、截断或提前终止。
11. **状态变更必须通过 tracker 脚本**：所有 case 状态变更必须通过 `e2e-case-tracker.sh` 执行，禁止直接编辑 JSON。
12. **全量执行不可中断**：`check-complete` 返回非零时必须继续执行，不允许以任何理由终止。
13. **防 turn 中断（硬性）**：verify-and-fix-cases skill 返回后，orchestrator **必须在同一个响应中立即执行 Step 2.5**（check-complete + summary）。不得在 Step 2 和 Step 2.5 之间 end_turn 等待用户输入。整个 Step 0 → Step 1 → Step 1.5 → Step 2 → Step 2.5 → Step 3 → 出口路由 是一个**不可分割的执行序列**，中间任何位置都不允许主动 end_turn（除非需要向用户索取凭证的 AskUserQuestion）。

### Step 2 完成后 — 写入门禁状态

verify-and-fix-cases 技能返回后，写入门禁状态：

```bash
$E2E_TRACKER gate set <epic-id> step_2_verify PASS \
  --field dispatched_via=skill:verify-and-fix-cases \
  --field credential_groups_total=<凭证组数> \
  --field credential_groups_resolved=<已解决组数>
```

`dispatched_via` 字段由后续 `gate check step_2_5_complete` 校验，
必须以 `skill:` 前缀开头。内联执行不会产生该字段。

### Step 2.5 — 完成门禁（强制）

```bash
$E2E_TRACKER gate check <epic-id> step_2_5_complete
```

verify-and-fix-cases skill 返回后，orchestrator **必须**执行以下验证：

```bash
# 检查所有 case 都已处理（无 pending/in_progress）
$E2E_TRACKER check-complete <epic-id>
if [ $? -ne 0 ]; then
  echo "ERROR: Not all cases processed. Re-dispatching verify-and-fix-cases skill." >&2
  # 重新调度 skill 处理剩余 case（恢复模式）
  # → 回到 Step 2
fi

# 自动生成 verify-receipt.json 和 verify-summary.md
$E2E_TRACKER summary <epic-id>

# 验证产物存在
test -s ".harness/features/<epic-id>/verify-cases/verify-receipt.json" || {
  echo "ERROR: verify-receipt.json not generated" >&2
  exit 1
}
test -s ".harness/features/<epic-id>/verify-cases/verify-summary.md" || {
  echo "ERROR: verify-summary.md not generated" >&2
  exit 1
}
```

若 `check-complete` 失败，**必须重新调度 verify-and-fix-cases skill**（恢复模式），直到所有 case 处理完毕。最多重试 3 次调度，仍有未处理 case 则标记为系统异常并报告用户。

Step 2.5 验证通过后写入门禁状态：

```bash
$E2E_TRACKER gate set <epic-id> step_2_5_complete PASS \
  --field all_cases_processed=true
```

### Step 3 — 产物完整性验证

```bash
$E2E_TRACKER gate check <epic-id> step_3_artifacts
```

```bash
# 验证所有必须产物存在
test -s ".harness/features/<epic-id>/test-cases.md"
test -s ".harness/features/<epic-id>/verify-cases/verify-receipt.json"
test -s ".harness/features/<epic-id>/verify-cases/case-tracker.json"
test -s ".harness/features/<epic-id>/verify-cases/verify-summary.md"
```

产物验证通过后写入门禁状态：

```bash
$E2E_TRACKER gate set <epic-id> step_3_artifacts PASS \
  --field artifacts_verified=test-cases.md,verify-receipt.json,case-tracker.json,verify-summary.md
```

## 产物要求

| 产物 | 路径 |
|------|------|
| 测试用例文档 | `.harness/features/<epic-id>/test-cases.md` |
| Case 追踪器 | `.harness/features/<epic-id>/verify-cases/case-tracker.json` |
| 验证总结 | `.harness/features/<epic-id>/verify-cases/verify-summary.md` |
| 验证回执 | `.harness/features/<epic-id>/verify-cases/verify-receipt.json` |
| Case 级产物 | `.harness/features/<epic-id>/verify-cases/<case_id>/` |

`verify-receipt.json` 整体 `status` 三态：
- `PASS`：全部通过或所有 skipped 均合理
- `PARTIAL`：有 `failed-after-max-retries`，但所有 P0 已通过
- `FAIL`：P0 有未通过

## 出口条件

### `status == PASS`

```bash
$HARNESSCTL state transition <epic-id> DONE
```

提示下一步：`/stage-harness:harness-done <epic-id>`

### `status == PARTIAL`

展示未通过的 P1/P2/P3 case 列表，询问用户：
- A：接受当前结果推进到 DONE（记录在 `delivery-summary.md` 的已知缺陷区）
- B：走 FIX 兜底（按 FAIL 处理）

### `status == FAIL`

1. 将 `verify-receipt.json` 中所有失败 case 合成为 harness-fix 兼容的 `verification.json`：

   ```json
   {
     "acceptance_council": "REJECTED",
     "fix_source_stage": "E2E_TEST",
     "critical_issues": [
       {
         "id": "<case_id>",
         "title": "<case 标题>",
         "description": "<failure_reason>",
         "evidence": "verify-cases/<case_id>/"
       }
     ],
     "high_issues": []
   }
   ```

2. 输出失败摘要（按维度分组：UI / API / API+UI / 性能）
3. 触发 FIX 循环：

   ```bash
   $HARNESSCTL state transition <epic-id> FIX
   ```

   提示下一步：`/stage-harness:harness-fix <epic-id>`

   FIX 完成后按 `fix_source_stage = E2E_TEST` 路由回 BUILD → DEPLOY → harness-e2e-test 完整重试。

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| DEPLOY 门禁未通过 | 终止，提示先完成部署阶段 |
| `test-cases.md` 已存在但 epic 代码已变更 | 提示用户决定复用还是重生成；默认重生成 |
| generate-test-cases 阻塞 | 终止，输出阻塞详情，**不**降级 |
| Case 注册表为空 | 终止，提示 generate-test-cases 产物不合规 |
| verify-and-fix-cases 返回但 check-complete 失败 | 重新调度 skill（恢复模式），最多 3 次 |
| 用户拒绝提供凭证 | 涉及该凭证的 case 标 `skipped`，其他 case 继续 |
| 被测服务端口不通 | 全面端口探测后修正目标重试；穷尽手段确认服务未启动则标 fail |
| 鉴权失败 / 401 | 中断向用户索取登录信息，严禁伪造 |
| Playwright 不可用 | 按优先级尝试替代方案；全部不可用时方可 skip |
| 单 case 连续 3 次修复仍失败 | skill 内部标 `failed-after-max-retries` |
| 性能测试被提前中断 | 视为 case 未完成，重新全量执行 |
| 连续 3 轮 harness-fix 兜底仍 FAIL | 暂停，展示未解决 case，等待人工干预 |

## 与其他阶段的关系

```
DEPLOY (PASS/SKIPPED)
  → /stage-harness:harness-e2e-test
      ├─ Step 0: 断点恢复检测
      ├─ Step 1: generate-test-cases skill → test-cases.md
      ├─ Step 1.5: e2e-case-tracker.sh init + register-all（门禁）
      ├─ Step 2: verify-and-fix-cases skill（逐 case 执行 + tracker 持久化）
      ├─ Step 2.5: check-complete + summary（完成门禁）
      └─ Step 3: 产物完整性验证
      ├─ PASS    → DONE → /stage-harness:harness-done
      ├─ PARTIAL → 用户决策（DONE 或 FAIL 兜底）
      └─ FAIL    → 合成 verification.json → FIX
                   → /stage-harness:harness-fix
                   → BUILD → DEPLOY → harness-e2e-test（完整重试，最多 3 轮）
```

**两层修复策略**：
- **内层（skill 内）**：单 case 失败时就近修代码 + 重编译部署 + 重跑该 case，最多 3 次。处理"小幅偏差"。
- **外层（FIX 阶段）**：内层兜不住的失败合成 CRITICAL issues 走 harness-fix，由 work skill 在 fix 模式下做更系统的修复，再从 BUILD 重新走完整链路。处理"系统性问题"。

**结构性保障机制**：
- **脚本化产物写入**：所有 case 状态通过 `e2e-case-tracker.sh` 原子写入，不依赖 Agent 行为正确性
- **门禁枚举检查**：Step 1.5 和 Step 2.5 分别验证产物完整性，缺失即阻断
- **断点恢复**：Step 0 检测 tracker 状态，中途崩溃后可从断点继续
- **全量执行强制**：`check-complete` 确保无 case 被遗漏，未处理则重新调度

## 硬性约束（门禁相关）

- **C-NO-DEGRADE**：generate-test-cases 子代理未产出合规的 test-cases.md 时，orchestrator 严禁自行生成替代品。唯一合法操作是重新调度子代理或终止报错。`gate validate-step1` 未通过即为判定依据。
- **C-GATE-MANDATORY**：每个 Step 完成后必须调用对应的 `gate set` 命令写入状态，下一个 Step 开始前必须调用 `gate check` 验证前置。跳过门禁写入/检查视为违规。
- **C-NO-INLINE-VERIFY**：Step 2 的验证工作必须通过技能调度完成，`gate check step_2_5_complete` 会校验 `dispatched_via` 字段以 `skill:` 开头。orchestrator 内联执行验证逻辑视为违规。
