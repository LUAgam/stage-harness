# Feedback 轻量 Hard-Gate 与阶段回退闭环改造方案

## 背景

当前 `harness-feedback` 已经能完成 feedback 提交、证据收集、多角色 triage、人工确认和部分 hard-gate 阻断。

但在 `oms-docs` 缺失案例中暴露出一个关键问题：插件已经像“评审入口 + 硬门禁系统”，但还没有稳定成为“阶段回退重跑系统”。

理想目标不是让 Agent 在 feedback 后直接补丁式修改，而是：

```text
发现问题
→ 判断哪个阶段产物失效
→ 回到或停留在对应阶段
→ 复用该阶段原工作方式重新产出可信结果
→ 后续阶段按正常流程继续推进
→ VERIFY
→ feedback close
→ DONE
```

## 当前问题总结

以 `oms-docs` feedback 为例，前半段流程基本符合预期：

- 用户提出 `oms-docs` 是否需要调整；
- Agent 识别为计划遗漏；
- 用户选择“提交为 feedback 正式 triage”；
- 系统执行 `feedback submit`、`evidence-pack`、`council-triage`、多角色投票、`aggregate-triage`；
- triage 裁决为 `REOPEN_PLAN`；
- 因 epic 风险等级为 high，系统要求人工确认。

但后半段不符合预期：

- 当前 epic 已经处于 `PLAN`，但 `REOPEN_PLAN` 没有稳定进入 same-stage replan 闭环；
- `feedback re-plan` 成功后，没有形成可执行的 `pending_re_completion`；
- `feedback re-complete` 因缺少 `pending_re_completion` 无法执行；
- `feedback close` 正确阻断，但 Agent 开始尝试绕过流程；
- Agent 直接编辑 `.harness` 中的 feedback / tasks JSON，甚至尝试伪造状态字段；
- Bash hook 对读取 `.harness` 文件的命令出现误拦。

核心结论：

```text
当前 feedback 机制已经能把 Agent 从“直接修”拉回“先评审”，
但还不能稳定完成“评审后退回相应阶段、复用阶段流程、再顺序推进”的闭环。
```

## V2 收敛版结论

本方案不再追求“全 Harness 阶段产物全部强受控写入”。

最初引入 hard-gate 的原因，是 feedback 流程中出现了状态绕过、伪关闭、手工修改 `.harness` JSON 等问题。因此改造重点应收敛为：

```text
强控 feedback 相关状态推进，
强控 task done / feedback close / stage re-complete，
强校验最终证据链，
但允许阶段内容产物继续由原阶段 skill / command 生成。
```

换句话说，本次要解决的是：

- feedback 不能被 Agent 直接改成 closed / resolved；
- task 不能被 Agent 手工改成 done；
- `state.json` 不能被 Agent 手工改 `current_stage` / `pending_re_completion`；
- same-stage replan 不能再出现 `re-plan` 成功但无法 `re-complete` 的死锁；
- `feedback close` 不能在 task、receipt、VERIFY、stale artifact 未闭合时通过；
- Agent 读取 `.harness` 诊断信息不应被 hook 误拦。

本次不解决，也不应扩展为：

- 所有阶段产物都必须新增 `harnessctl xxx write` 命令；
- `feedback` 接管 CLARIFY / SPEC / PLAN / VERIFY 的内容生成；
- 为每个 JSON artifact 设计独立写入 CLI；
- 重写全 Harness 阶段 gate 架构。

核心边界：

```text
强控状态，放开内容；
强控 close/done/re-complete，放开阶段产物生成；
强控绕过路径，保留原阶段工作方式。
```

## 改造目标

本次改造目标是让 feedback 机制满足以下预期，同时避免过度改造成全阶段产物管理系统：

1. 发现问题后必须先进入 feedback / triage，而不是直接动手。
2. triage 必须判断失效阶段：CLARIFY、SPEC、PLAN、EXECUTE/FIX。
3. 若目标阶段早于当前阶段，应受控回退。
4. 若目标阶段等于当前阶段，应进入 same-stage continuation，而不是制造伪回退。
5. 回到目标阶段后，必须复用该阶段原工作方式重新产出可信产物。
6. stage re-complete 证明目标阶段产物重新可信。
7. feedback close 只在完整下游影响完成后发生。
8. Agent 不能通过手工 JSON、metadata、Bash 或直接 Edit 绕过状态机。
9. 错误提示必须告诉 Agent 下一步合法命令，避免猜命令或伪造状态。
10. 阶段内容产物仍由 CLARIFY / SPEC / PLAN / VERIFY 原阶段流程生成，不由 feedback 专门接管。

## 保护边界重新划分

### 必须强控的对象

这些对象属于 feedback 核心风险面，必须只能由 `harnessctl` 受控命令改变：

- `.harness/features/*/state.json` 中的 `current_stage`、`stage_history`、`pending_re_completion`；
- `.harness/features/*/feedback/HFB-*.json` 中的 `status`、`resolution`、`closed_at`、`continuation`、`reopen_history`、伪造闭合标记；
- `.harness/tasks/*.json` 中的 task `status`；
- `feedback close`、`task done`、`feedback re-complete`、stage transition 这些状态推进动作；
- council final verdict / close evidence 这类会影响 gate 结果的最终状态证据。

这些对象的共同点是：一旦被手工修改，就会改变流程状态或绕过门禁。

### 不应过度强控的对象

这些对象更偏阶段内容产物，可以由对应 stage skill / reviewer / adapter 生成，但后续必须被 gate 校验：

- `domain-frame.json`、`surface-routing.json`、`scenario-coverage.json`；
- `task-graph.json`、`coverage-matrix.json`、`TASKS.md`；
- `verification.json`；
- stage markdown / docs / spec；
- amendment plan 内容；
- 普通阶段分析报告。

这些对象可以由 Agent 在阶段流程中生成或修改，但不能用来绕过 `close`、`done`、`re-complete`。

### 判断原则

```text
如果修改会直接改变流程状态或关闭门禁，则强控；
如果修改只是阶段内容产物，则允许原阶段流程生成，但必须被 gate 校验。
```

## 核心流程模型

```text
用户反馈
→ feedback submit
→ evidence-pack
→ council-triage / votes
→ aggregate-triage
→ 阶段路由
→ high risk 人工确认
→ 目标阶段重建产物
→ stage re-complete
→ 后续阶段正常推进
→ task receipt / runtime evidence
→ VERIFY
→ feedback close
→ DONE
```

## Feedback 生命周期状态机

需要把 feedback 生命周期明确成一条可执行链路：

```text
submitted
→ triaging
→ triaged
→ amendment_planned
→ approved
→ continuation_pending
→ amending
→ resolved
→ verified
→ closed
```

状态语义：

- `submitted`：用户或 Agent 提交了反馈。
- `triaging`：正在收集证据和投票。
- `triaged`：已形成 triage 裁决。
- `amendment_planned`：已生成修订计划。
- `approved`：修订计划已审批。
- `continuation_pending`：等待执行目标阶段重建。
- `amending`：正在重建目标阶段产物。
- `resolved`：目标阶段产物已重新可信。
- `verified`：完整下游影响已验证。
- `closed`：feedback 证据链闭合。

关键原则：

- `resolved` 不等于 `closed`。
- `resolved` 只表示目标阶段已经重新完成。
- `closed` 必须等待关联 task、receipt、runtime evidence、VERIFY 和 stale artifact 全部闭合。
- protected 状态字段只能由 `harnessctl` 受控命令修改。

## 阶段路由规则

triage 的核心输出应该是失效阶段归因：

- 如果反馈影响“用户到底要什么”，回到 `CLARIFY`。
- 如果反馈影响“什么算正确”，回到 `SPEC`。
- 如果反馈影响“如何实现、如何拆任务、如何验证”，回到 `PLAN`。
- 如果反馈只影响代码实现细节，留在 `EXECUTE/FIX`。

示例：

```text
E2E 发现失败
→ 评审发现是需求场景遗漏
→ REOPEN_CLARIFY
→ 重新执行 CLARIFY
→ 重做受影响 SPEC / PLAN
→ 正常 EXECUTE / VERIFY
```

## same-stage replan 语义

`oms-docs` 案例属于：

```text
current_stage = PLAN
target_stage = PLAN
decision = REOPEN_PLAN
```

这不应该视为真正的“向前或向后跳转”，而应视为 same-stage replan。

预期行为：

1. `feedback continue` 发现 target stage 等于 current stage。
2. 系统进入 `same_stage_replan`。
3. 写入 `reopen_history`，但标记 `same_stage=true`。
4. 创建 `pending_re_completion`。
5. 要求执行 `/harness:plan --reopen` 产出结构化 amendment plan。
6. `feedback re-plan` 受控更新计划产物。
7. `feedback re-complete --stage PLAN` 校验 revision manifest / revision diff / PLAN gate。
8. 清除 `pending_re_completion`。
9. feedback 进入 `resolved`，等待后续任务执行和 VERIFY。

这能避免当前死锁：

```text
re-plan 成功
但没有 pending_re_completion
→ re-complete 无法执行
→ close 又要求 re-completion marker
```

## 跨阶段 reopen 语义

如果 target stage 早于 current stage，应走真正的受控回退。

示例：

```text
current_stage = VERIFY
target_stage = CLARIFY
```

预期行为：

1. 记录 reopen history。
2. 将 current stage 回退到 CLARIFY。
3. 标记 CLARIFY 之后的下游产物 stale / invalidated。
4. 要求重新执行 CLARIFY 原阶段流程。
5. CLARIFY re-complete 后，继续 SPEC、PLAN、EXECUTE、VERIFY。

## 阶段原流程复用

feedback 不应有一条“弱化版修补流程”。

不同 target stage 应复用对应阶段能力：

- `REOPEN_CLARIFY`：执行 `/harness:clarify --reopen`，重新产出澄清产物。
- `REOPEN_SPEC`：执行 `/harness:spec --reopen`，重新产出规格产物。
- `REOPEN_PLAN`：执行 `/harness:plan --reopen`，重新产出计划产物。
- `STAY_EXECUTE`：进入普通 task/work/FIX 流程。

这意味着 feedback 负责“路由和门禁”，不负责替代阶段本身：

- CLARIFY 内容仍由 CLARIFY skill 生成；
- SPEC 内容仍由 SPEC skill 生成；
- PLAN 内容仍由 PLAN skill 或 `feedback re-plan` 的确定性 merge 生成；
- VERIFY 证据仍由 VERIFY/reviewer 流程生成；
- feedback 只要求这些产物在 gate 时可验证。

Agent 不能直接编辑这些状态推进文件或控制字段：

- `.harness/features/*/state.json`
- `.harness/features/*/feedback/HFB-*.json`
- `.harness/tasks/*.json`
- task status、feedback status、stage status、close evidence 等核心状态字段

但 Agent 可以在对应阶段流程中生成或修改阶段内容产物，例如计划草案、coverage 内容、verification 内容。它们最终由 stage gate、DONE gate、feedback close gate 检查，而不是由 hook 一刀切禁止写入。

## Amendment Plan 契约

当前存在一个契约不一致：

- `plan-amendment` 生成 markdown 模板；
- `re-plan` 实际需要 `HFB-xxx.amendment-plan.json`；
- Agent 因此开始手工补 JSON。

这里不应扩展成“feedback 负责生成所有 PLAN 内容”。更合理的边界是：

- `/harness:plan --reopen` 或 PLAN skill 负责语义规划；
- `feedback re-plan` 只负责把结构化结果确定性合并进 task graph / coverage / summary；
- `feedback` 不猜测任务内容，不替代 planner。

理想契约应区分：

### 人类 review 产物

`HFB-xxx.amendment-plan.md`

用途：

- 说明保留哪些结论；
- 要修改哪些计划；
- 哪些下游产物失效；
- 是否需要人工确认；
- 供人类 review。

### 机器执行产物

`HFB-xxx.amendment-plan.json`

用途：

- `tasks_to_add`
- `tasks_to_update`
- `coverage_updates`
- `dependency_updates`
- `invalidate`
- `preserve`
- `confirmed`

`approve-amendment` 应校验 JSON schema，而不仅仅检查 markdown 存在。

如果 JSON 不存在，应提示：

```text
Run /harness:plan --reopen to produce HFB-xxx.amendment-plan.json
```

而不是让 Agent 手工创建 JSON。

最小 schema 应只包含 `re-plan` 必须消费的字段，不要求覆盖所有 PLAN 阶段内部细节：

- `tasks_to_add` / `tasks_to_update`；
- `coverage_updates`；
- `dependency_updates`；
- `preserve`；
- `invalidate`；
- `confirmed`。

这样可以避免把 feedback 改造成大型计划编辑器。

## re-plan 的职责边界

`feedback re-plan` 只表示 PLAN 产物被受控修订，不表示 feedback 已完成。

它可以做：

- 更新 task graph；
- 更新 coverage matrix；
- 更新 TASKS.md；
- 生成 backing task；
- 生成 revision manifest；
- 生成 revision diff；
- 记录 trace。

它不能做：

- 标记 feedback closed；
- 标记 feedback task done；
- 跳过 VERIFY；
- 伪造 stage re-complete；
- 直接证明文档或代码已完成。

以 `oms-docs` 为例，`re-plan` 后 T17 进入普通任务池。文档还没有写完，因此 feedback 不应 close。

## re-complete 与 close 的区别

### re-complete

证明目标阶段产物重新可信。

例如：

```text
PLAN re-complete
→ T17 已进入 task graph
→ coverage 已补 FR-011
→ revision manifest/diff 存在
→ PLAN gate 通过
```

### close

证明 feedback 的完整下游影响已经闭合。

例如：

```text
T17 文档任务已执行
→ receipt 已写
→ VERIFY 已通过
→ stale artifact 已清除
→ feedback close
```

因此 `re-complete` 可以发生在 T17 执行前；`close` 必须发生在 T17 完成并验证后。

## 错误提示改造

当前问题之一是 Agent 遇到错误后开始猜命令。

理想错误提示应提供明确下一步：

- 缺 amendment plan JSON：提示执行 `/harness:plan --reopen`。
- 缺 pending re-completion：提示执行 `feedback continue --execute` 或进入 same-stage continuation。
- 缺 re-completion marker：提示执行 `feedback re-complete --stage <target>`。
- feedback task pending：提示执行 `task next`、work、receipt、task done。
- 缺 verification：提示进入 VERIFY 并生成 `verification.json`。

目标是让 Agent 不再尝试：

- `update-metadata` 修改 protected 字段；
- 直接编辑 `HFB-xxx.json`；
- 手工写 state history；
- 伪造 verification。

## Tool / Hook 保护目标

保护机制需要从“全结构化产物强拦截”收缩为“状态绕过强拦截”。

核心原则：

```text
Hook 防止 Agent 伪造状态；
Gate 校验 Agent 生成的内容产物。
```

保护机制必须区分“读”和“写”。

应阻断：

- Write/Edit/MultiEdit 修改 `state.json`；
- Write/Edit/MultiEdit 修改 `feedback/HFB-*.json` 的控制字段；
- Write/Edit/MultiEdit 修改 `.harness/tasks/*.json` 的 task status；
- Bash 对上述状态文件做重定向写；
- `sed -i`、`tee`、`python open(..., 'w')` 等写入状态推进文件；
- 通过 `update-metadata` 写入 `status`、`continuation`、`reopen_history`、`pending_re_completion`、`closed_at`、`re_completion_done` 等控制字段。

不应阻断：

- `cat` 读取 `.harness` 文件；
- `jq` 查看 `.harness` 文件；
- `python -c` 解析只读输入；
- `ls` / `test -f` / `grep` 等只读检查。
- stage skill 在对应阶段写内容产物；
- `/harness:plan --reopen` 生成 amendment plan；
- `/harness:verify` 或 reviewer 流程生成 verification 内容；
- PLAN 流程生成 task graph / coverage 内容。

当前出现的 `cat revision-manifest.json | python3 ...` 被拦截，属于读取误拦，应修正。

## 不做的事

本次改造明确不做以下事项：

- 不为所有 `.harness` JSON 设计独立 `harnessctl write-*` 命令；
- 不要求 `verification.json`、`domain-frame.json`、`surface-routing.json` 都只能由 harnessctl 写；
- 不重写 CLARIFY / SPEC / PLAN / VERIFY 的阶段产物生成机制；
- 不扩大到全插件架构重构；
- 不把 `feedback` 改造成通用 artifact editor。

这些事项可以作为长期演进方向，但不是解决当前 feedback 伪关闭和 same-stage deadlock 的必要条件。

## 实施优先级

### P0：修闭环和防绕过

1. 修复 same-stage replan：`continue -> pending_re_completion -> re-plan -> re-complete` 必须闭合。
2. 收紧 `update-metadata`：禁止写入所有控制流字段，不仅是 `status`。
3. `feedback close` 保持严格，但错误提示必须给出下一条合法命令。
4. Hook 区分读写：允许只读诊断，阻断状态伪造写入。

### P1：统一命令契约

1. `plan-amendment` / `/harness:plan --reopen` / `re-plan` 的 markdown 与 JSON 契约统一。
2. `feedback gate-check` 对 `continuation_pending` / `reopened` / `amending` 的提示可直接执行。
3. `re-complete` 对缺失 marker、stage 不匹配、manifest 不合格给出明确恢复路径。

### P2：体验和覆盖增强

1. 增加 stage reminder 中的下一步提示。
2. 对 record-only、defer、reject、all-cancelled task 等边界补充测试。
3. 后续再评估是否需要针对个别高风险 evidence 文件新增受控写入命令。

## 端到端验收场景

### 场景 1：PLAN 阶段 same-stage replan

输入：

```text
当前 stage = PLAN
feedback = oms-docs 缺失
triage = REOPEN_PLAN
```

期望：

- high risk 时等待人工确认；
- 进入 `same_stage_replan`；
- `re-plan` 生成 T17、coverage、revision manifest、revision diff；
- `re-complete --stage PLAN` 成功；
- feedback 进入 `resolved`；
- T17 未完成前 `feedback close` 阻断。

### 场景 2：VERIFY / E2E 发现 CLARIFY 漏需求

输入：

```text
当前 stage = VERIFY
feedback = E2E 暴露需求分析遗漏
triage = REOPEN_CLARIFY
```

期望：

- 回退 CLARIFY；
- 下游 SPEC / PLAN / EXECUTE / VERIFY 产物标记 stale；
- 重新执行 CLARIFY；
- 再按正常顺序推进后续阶段；
- 最后 VERIFY 和 feedback close。

### 场景 3：Agent 尝试绕过

输入：

```text
Agent 直接编辑 HFB-xxx.json 或 tasks JSON
```

期望：

- 被 hook 拦截；
- 错误提示给出合法 harnessctl 命令；
- 不允许伪造状态。

### 场景 4：Bash 读取 `.harness`

输入：

```bash
cat .harness/features/.../feedback/HFB-xxx.revision-manifest.json | jq .
```

期望：

- 不被拦截；
- 只读命令允许执行。

### 场景 5：阶段内容产物允许由原阶段流程生成

输入：

```text
PLAN 阶段需要更新 coverage 或 task graph 内容
```

期望：

- 原 PLAN skill 或 `feedback re-plan` 可以生成内容产物；
- hook 不因为“这是结构化 JSON”而一刀切阻断；
- 后续 gate 检查这些产物是否满足 schema、coverage、trace、revision evidence；
- 如果产物不合格，gate 阻断，而不是禁止阶段流程生成。

### 场景 6：直接伪造状态被阻断

输入：

```text
Agent 尝试把 feedback status 改成 closed
Agent 尝试把 task status 改成 done
Agent 尝试手工补 pending_re_completion / re_completion_done / closed_at
```

期望：

- `update-metadata` 拒绝控制字段；
- Write/Edit/MultiEdit/Bash 写状态推进文件被拦截；
- 错误提示指向合法命令：`feedback continue`、`feedback re-complete`、`task done`、`feedback close`。

## 最终预期

改造完成后，Harness Feedback 应具备完整闭环：

```text
评审入口
+ 阶段失效归因
+ 受控回退 / same-stage continuation
+ 原阶段流程复用
+ revision evidence
+ 普通任务执行
+ VERIFY
+ close hard gate
```

同时，本方案刻意保持轻量：

```text
不把所有阶段产物都纳入强写保护，
不要求每个 evidence 文件都有专门 harnessctl write 命令，
只强控能改变流程状态或绕过 close/done/re-complete 的关键路径。
```

一句话总结：

```text
feedback 不是补丁入口，
而是把发现的问题纳入正式阶段系统，
并在正确阶段重新建立可信产物的机制。
```

补充一句：

```text
hard-gate 的重点是防止伪造完成，
不是禁止 Agent 在正确阶段生成内容。
```
