# Stage-Harness Feedback Hard-Gate 改造方案

## 1. 背景与结论

本方案来自一次 feedback 执行流程复盘。复盘中的 HFB-010 feedback 触发后，agent 虽然完成了业务代码改动，但后续通过手工编辑 `.harness` JSON 文件推进状态，包括 epic state、task status、feedback status、council verdict 等。

该流程不符合预期。

问题不在于业务代码是否修改正确，而在于 feedback 处理绕过了 harnessctl 的标准状态机、gate、trace、task receipt、runtime evidence 与 DONE gate。

因此，feedback 机制需要从“纠错命令 / 补丁入口”升级为“结构化、可审计、不可绕过的阶段失效归因与阶段重跑机制”。

---

## 2. 核心设计原则

### 2.1 feedback 不直接修代码

feedback 的职责不是直接进入代码修改，而是判断：

- 哪个阶段的产物失效；
- 需要回退到哪个阶段；
- 哪些下游产物需要重新生成；
- 哪些 task / runtime / verify 证据必须补齐。

代码修改仍应由正常 WORK / EXECUTE 流程完成。

### 2.2 feedback 负责阶段失效归因

feedback triage 的核心输出应是阶段路由：

- `REOPEN_CLARIFY`
- `REOPEN_SPEC`
- `REOPEN_PLAN`
- `STAY_EXECUTE`
- `NO_REOPEN_WITH_EVIDENCE`
- `INSUFFICIENT_EVIDENCE`
- `REJECT`
- `DEFER`

feedback 不应成为绕过阶段产物的快捷补丁通道。

### 2.3 回退后复用原阶段流程

回退到 CLARIFY / SPEC / PLAN / EXECUTE 后，应复用原阶段机制重新生产可信产物，而不是为 feedback 单独维护一条弱化流程。

标准链路：

```text
用户反馈
→ evidence-pack
→ 多角色 triage
→ 阶段路由
→ 上游产物修订
→ stage re-complete
→ 下游流程重跑
→ work 执行真实修改
→ task receipt
→ build / deploy / smoke
→ VERIFY
→ feedback close
→ DONE
```

### 2.4 feedback task 与普通 task 一视同仁

feedback 产生的新 task 必须进入普通 task graph。

要求：

- 有唯一 task id；
- 有依赖关系；
- 有 `added_by_feedback` 或 `source=feedback:HFB-xxx`；
- 不能通过手工 JSON 标记 done；
- done 前必须满足 task receipt / runtime receipt gate。

### 2.5 DONE 只看完整证据链

DONE 不能只看当前 stage 状态，而必须检查完整交付闭环：

- feedback 是否全部闭合；
- feedback 对应 task 是否完成；
- task receipt 是否存在；
- runtime receipt 是否满足；
- VERIFY 是否完成；
- release / delivery evidence 是否齐全；
- 是否仍存在 stale / invalidated / needs_amendment artifact。

---

## 3. Stage Re-complete 与 Feedback Close 的区别

### 3.1 Stage re-complete

`stage re-complete` 用于证明回退阶段产物已经重新可信。

例如：

- `REOPEN_CLARIFY` 后，CLARIFY 产物重新完成；
- `REOPEN_SPEC` 后，SPEC 产物重新完成；
- `REOPEN_PLAN` 后，PLAN 产物重新完成；
- `STAY_EXECUTE` 后，EXECUTE 内 continuation 被确认。

它应检查：

- 目标阶段 artifact 已更新；
- invalidated / stale artifact 已处理；
- revision manifest 或 revision diff 存在；
- `pending_re_completion` 已清除；
- 该阶段 gate 重新通过。

### 3.2 Feedback close

`feedback close` 用于证明该 feedback 的完整下游影响已经处理完毕。

它应检查：

- triage 已完成；
- amendment plan 已审批；
- reopen history 已记录；
- stage re-complete 已完成；
- feedback 关联 task 已进入普通 task graph；
- task 已完成并有 receipt；
- `runtime_required=true` 的 task 有 build / deploy / smoke 证据或合规 waiver；
- VERIFY 已完成；
- 没有 stale / invalidated / needs_amendment artifact；
- feedback resolution 与实际证据匹配。

简化表达：

```text
re-complete 证明回退阶段产物重新可信；
close 证明 feedback 的完整下游影响已经闭合。
```

---

## 4. `.harness` 文件分级保护

### 4.1 A 类：状态机核心文件

A 类文件严禁 agent 通过 Write / Edit / MultiEdit / Bash 直接修改。

包括：

- `.harness/epics/*.json`
- `.harness/features/*/state.json`
- `.harness/tasks/*.json`
- `.harness/features/*/feedback/HFB-*.json`
- feedback status / resolution / reopen history
- stage history
- `pending_re_completion`
- task status
- DONE state

这些文件只能由 harnessctl 受控命令修改。

### 4.2 B 类：审计、裁决、运行证据、结构化 JSON

B 类文件默认受控，不能由 agent 直接写入。

包括：

- evidence-pack；
- triage votes；
- verdict；
- metadata；
- `artifact-status.json`；
- `coverage-matrix.json`；
- `task-graph.json`；
- `surface-routing.json`；
- `domain-frame.json`；
- runtime receipts；
- build / deploy / smoke receipts；
- verification result；
- release evidence；
- council verdicts。

原则：

- agent 不能直接 Write / Edit / MultiEdit；
- Bash 不能直接写；
- 必须通过 harnessctl 或受信 runtime adapter 生成；
- 每次写入必须 trace。

### 4.3 C 类：阶段内容产物

C 类主要是阶段内容类 Markdown 或说明文档。

允许在对应阶段由受控命令写入，但仍需：

- 阶段匹配；
- trace；
- artifact-status 更新；
- stage gate 校验。

---

## 5. Hard Gate 设计

### 5.1 Tool-level guard

需要覆盖：

- Write；
- Edit；
- MultiEdit；
- Bash。

目标：

- 禁止直接写 A / B 类受控产物；
- 对 protected path 做统一判定；
- 所有拦截行为写 trace。

### 5.2 Bash guard：路径 + 命令来源双判断

Bash guard 不应只靠危险命令 regex，而应采用：

```text
目标路径是否命中 A / B 类受控产物
+
当前命令是否来自受信入口
```

非受信 shell 写受控路径，一律阻断。

受信入口示例：

```text
harnessctl
scripts/harnessctl-build.sh
scripts/post-task-build-deploy.sh
scripts/post-deploy-verify.sh
scripts/smoke-check.sh
scripts/omsctl
```

即使是受信入口，内部仍必须：

- 校验参数；
- 写 trace；
- 产出 receipt；
- 接受 stage gate / DONE gate 检查。

### 5.3 harnessctl command-level gate

不能只依赖 hook。harnessctl 内部也必须有命令级 hard gate。

需要强化：

- `feedback close` gate；
- `task done` gate；
- state transition gate；
- DONE gate；
- reopen gate；
- re-complete gate；
- force policy；
- project-root / harness-root resolver。

### 5.4 Stage-gate / DONE gate

最终兜底规则：

- unresolved feedback 阻断 DONE；
- stale / invalidated artifacts 阻断 DONE；
- missing task receipt 阻断 DONE；
- missing runtime receipt 阻断 DONE；
- missing VERIFY evidence 阻断 DONE；
- `skipped` / `warn` / `partial` 不默认 pass。

---

## 6. `--force` 策略

`--force` 不能作为万能后门。

`--force` 不允许跳过：

- unresolved feedback；
- missing re-complete；
- missing task receipt；
- missing runtime receipt；
- security / data-loss gate；
- stale / invalidated artifact；
- required VERIFY evidence；
- feedback task 未闭合；
- DEFER 缺少 owner / target stage / revisit condition。

如确实需要强制推进，应满足：

- 仅 human actor 可用；
- 必须提供 reason；
- 必须写 trace；
- 必须留下 waiver artifact；
- waiver 不能覆盖安全 / 数据破坏类 gate；
- waiver 不能让 missing runtime evidence 默认通过。

---

## 7. Worktree / Project Root 解析

worktree 下 harnessctl 如果找不到主仓库 `.harness`，容易诱导 agent 手工修改状态文件。

因此该问题必须进入 P0。

要求：

- harnessctl 能从 worktree 定位主仓库 `.harness`；
- 支持 `--project-root` / `--harness-root`；
- Epic not found 时输出明确 recovery command；
- 禁止因 Epic not found 而手工修改 `.harness` 状态。

---

## 8. Runtime Receipt 最小 Gate

runtime receipt 不能推迟到后期才做，至少需要在 Phase 2 建立最小闭环。

当 task 标记为 `runtime_required=true` 时，必须满足：

```text
runtime_required=true
→ 必须有 affected_repos
→ 必须有 build_status
→ 必须有 verify/smoke_status
→ skipped / warn / partial 不能默认 pass
```

示例：

- `tsc not available` 不能视为通过；
- 没有 build 工具时，应记录为 `skipped + tool_unavailable`；
- 若无人工 waiver，应阻断 task done / feedback close / DONE。

---

## 9. 分阶段实施计划

### Phase 0：Root resolver 和 recovery

优先解决 worktree/project-root 问题。

交付项：

- harnessctl root resolver；
- `--project-root` / `--harness-root` 支持；
- Epic not found recovery command；
- worktree 环境测试。

### Phase 1：封死绕过路径

交付项：

- 确认并注册 MultiEdit guard；
- 扩展 Write / Edit / MultiEdit protected patterns；
- 扩展 Bash guard 为“路径 + 命令来源”双判断；
- 增加 harnessctl 命令级校验；
- 限制 `--force`；
- 所有 blocked attempt 写 trace。

### Phase 2：最小证据链 gate

交付项：

- `feedback close` 检查 re-complete、task、runtime；
- `task done` 检查 task receipt；
- `runtime_required=true` task 必须有 affected_repos；
- 必须有 build_status；
- 必须有 verify / smoke_status；
- `skipped` / `warn` / `partial` 不默认 pass；
- DONE gate 检查 feedback / task / runtime / VERIFY 基础链路。

### Phase 3：结构化 continuation 和 artifact invalidation

交付项：

- continuation 字段；
- failed_stage；
- target_stage；
- required_recompletion；
- allowed / blocked commands；
- artifact stale / invalidated / needs_amendment；
- pending_re_completion；
- revision manifest；
- stage re-complete enforcement。

### Phase 4：OMS runtime adapter

交付项：

- oms-ui runtime adapter；
- ghana runtime adapter；
- jdbc-connector runtime adapter；
- etransfer runtime adapter；
- xlog runtime adapter；
- build receipt；
- deploy / hot-update receipt；
- smoke receipt；
- verify receipt；
- waiver 规则。

---

## 10. 验收用例

必须覆盖以下场景：

1. direct Edit 写 `.harness/epics/*.json` 被阻断；
2. MultiEdit 写 `.harness/tasks/*.json` 被阻断；
3. Bash `sed -i` 写受控 JSON 被阻断；
4. 非受信 Bash 写 feedback JSON 被阻断；
5. harnessctl 受信命令可写并产出 trace；
6. HFB amending 未完成时 close 被阻断；
7. `REOPEN_PLAN` 缺少 re-complete 时 DONE 被阻断；
8. feedback task 无 receipt 时 close / DONE 被阻断；
9. `runtime_required=true` task 无 build / smoke receipt 时 task done / DONE 被阻断；
10. `tsc not available` 无 waiver 时不能通过；
11. DEFER 缺少 owner / target / revisit 条件时 DONE 被阻断；
12. worktree 中 Epic not found 返回 recovery command；
13. agent 使用 `--force` 绕过关键 gate 被阻断；
14. human waiver 可记录，但不能绕过安全 / 数据破坏 gate。

---

## 11. 当前实现 Review 结果与差距

### 11.1 Review 结论

结合当前 `stage-harness` 实现看，feedback 主流程已经具备可运行基础，但还没有达到本文档要求的 hard-gate 标准。

已有能力主要集中在：

- `harnessctl feedback submit / evidence-pack / council-triage / write-vote / aggregate-triage / continue`；
- `harnessctl reopen` 受控回退；
- `feedback re-complete`、`revision-manifest`、`pending_re_completion`；
- `artifact-status` stale / invalidated 跟踪；
- `feedback gate-check` 对 submitted / triaging / triaged / reopened / deferred 等状态做基础阻断；
- hook 层对少数 feedback 核心产物的 Write / Edit / Bash 写入做了拦截。

当前核心问题不是“没有 feedback 流程”，而是“流程可以被绕过”。现有实现更接近可编排流程，还不是不可绕过的证据链系统。

### 11.2 已实现能力

当前实现与方案匹配较好的部分：

- feedback triage outcome 已覆盖 `REOPEN_CLARIFY`、`REOPEN_SPEC`、`REOPEN_PLAN`、`STAY_EXECUTE`、`NO_REOPEN_WITH_EVIDENCE`、`INSUFFICIENT_EVIDENCE`、`REJECT`、`DEFER`；
- `aggregate-triage` 能基于多角色 vote 聚合 verdict，并兼容旧 vote 格式；
- `related-gap-scan` 已作为 REOPEN / scope gap / vote related gaps 的前置条件接入 `approve-amendment`；
- `reopen` 要求 feedback 已 approved、triage 要求 reopen、target stage 匹配，且不能回退到当前或更晚阶段；
- `reopen` 会写入 `reopen_history`、`pending_re_completion`，并标记下游 artifact stale；
- `re-complete` 已支持 `revision-manifest` 校验，且能生成 re-completion marker；
- `guard check EXECUTE` 会检查 unresolved feedback、stale upstream artifact、reopened without re-completion；
- 当前 feedback 相关测试可覆盖 submit、triage、reopen、gate-check、related-gap-scan、re-complete、source-probe 等主路径。

### 11.3 关键缺口

#### A / B 类 `.harness` 文件保护不足

现有 `pre-tool-use-write-guard.sh` 主要保护：

- evidence-pack；
- triage votes；
- verdict；
- metadata；
- triage JSON。

但以下 A / B 类核心文件仍未被全面保护：

- `.harness/epics/*.json`；
- `.harness/features/*/state.json`；
- `.harness/tasks/*.json`；
- `.harness/features/*/feedback/HFB-*.json` 主记录；
- `artifact-status.json`；
- `coverage-matrix.json`；
- `task-graph.json`；
- runtime / build / smoke / verify receipts；
- release evidence；
- council verdicts。

此外，当前 hook 注册只覆盖 Write / Edit / Bash，未确认覆盖 MultiEdit。该缺口会允许 agent 通过 MultiEdit 或未覆盖路径直接推进状态。

#### Bash guard 仍偏 regex 防御

现有 Bash guard 已能阻断部分危险命令和少数 feedback 产物写入，但仍没有实现本文档要求的：

```text
protected path 命中
+
command source 是否为受信入口
```

因此，`sed -i`、脚本内 `open(..., "w")`、复杂 shell pipeline、间接路径拼接等写法仍可能绕过保护。

#### `task done` gate 不足

当前 `task done` 主要是状态更新。它没有在 done 前强制检查：

- task receipt 是否存在；
- receipt 是否有效；
- `runtime_required=true` 时 runtime receipt 是否存在；
- affected repos 是否声明；
- build / smoke / verify 是否真实通过；
- `skipped` / `warn` / `partial` 是否被 waiver 明确处理。

这会导致 task graph 表面完成，但缺少执行证据。

#### `feedback close` 与 `close-all` 仍是高风险后门

当前 `feedback close` 已有部分校验，但 `--force` 仍可能绕过关键错误。

更高风险的是 `feedback close-all`：它会批量把 open feedback 标记为 closed，并写入 forced closure。这与本文档目标冲突，因为 feedback close 必须证明完整下游影响闭合，而不能只是批量改状态。

#### DONE gate 不是完整交付闭环

当前 DONE gate 主要检查 release artifacts 与 release council verdict。它尚未完整兜底检查：

- unresolved feedback；
- feedback 对应 task 是否完成；
- task receipt 是否存在；
- runtime receipt 是否满足；
- VERIFY evidence 是否有效；
- stale / invalidated / needs_amendment artifact 是否仍存在；
- `skipped` / `warn` / `partial` 是否被错误放行。

因此，即使前面流程存在证据缺口，DONE 仍可能被推进。

#### Worktree / root resolver 仍需增强

当前实现已有 `--project-root` 和自动查找 `.harness`，但还缺少明确的 `--harness-root` 语义，以及 worktree 场景下的 recovery command。

当 agent 在 worktree 下遇到 Epic not found / `.harness` not found 时，应被引导使用受控命令恢复，而不是手工创建或修改 `.harness` JSON。

### 11.4 风险优先级

P0 风险：

- A 类状态机文件可被直接修改；
- MultiEdit 未纳入保护；
- `feedback close-all` 可批量强关；
- `--force` 可绕过关键 gate；
- `task done` 不要求 receipt；
- DONE gate 未检查完整证据链；
- worktree root 解析失败时缺少明确 recovery path。

P1 风险：

- Bash guard 没有统一的 protected path + trusted source 判定；
- B 类结构化证据产物保护不完整；
- runtime receipt schema 和 waiver 策略未成型；
- `re-complete` 与 `feedback close` 的语义边界还需进一步收紧。

P2 风险：

- runtime adapter 尚未覆盖 OMS 多 repo；
- repeated feedback 的统计、pitfall、skills 沉淀仍偏后续增强；
- legacy `revision-diff` 兼容路径未来需要逐步降级。

### 11.5 建议落地顺序

第一批改造应优先封死状态绕过路径：

1. 增加 `--harness-root` 与 worktree recovery command；
2. 注册 MultiEdit guard；
3. 扩展 A / B 类 protected patterns；
4. 将 Bash guard 改为 protected path + trusted source 双判断；
5. 禁用或重写 `feedback close-all`；
6. 收紧 `feedback close --force`；
7. `task done` 强制 task receipt；
8. DONE gate 增加 feedback / task / runtime / VERIFY / artifact-status 兜底检查。

第二批改造再补 runtime 最小闭环：

1. 定义 runtime receipt schema；
2. 支持 `runtime_required=true`；
3. 检查 affected repos；
4. 检查 build / smoke / verify status；
5. 将 `skipped` / `warn` / `partial` 默认设为阻断；
6. 引入合规 waiver artifact。

第三批改造再完善 continuation、runtime adapter 与长期度量：

1. 强化 continuation allowlist；
2. 完善 artifact invalidation 与 revision manifest；
3. 接入 OMS runtime adapters；
4. 输出 reopen stats / pitfall patterns；
5. 将重复 feedback 沉淀为规则、skills 或 commands。

---

## 12. 最终目标

改造完成后，feedback 应具备以下能力：

- 能准确判断反馈影响哪个阶段；
- 能结构化地产生 evidence、triage、verdict、continuation、re-complete、task、runtime、verify 证据；
- 能禁止 agent 直接修改 `.harness` 状态；
- 能防止通过 Bash、Write、Edit、MultiEdit 绕过；
- 能在 worktree 中正确定位主 harness root；
- 能确保 feedback task 与普通 task 一样执行、验证和闭合；
- 能通过 DONE gate 保证最终交付证据链完整。

最终目标不是让 feedback 更会“补丁式修复”，而是让 feedback 成为可信阶段系统的一部分。