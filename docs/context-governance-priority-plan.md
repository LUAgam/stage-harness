# Context Governance Priority Plan

## 背景

大模型和 AI coding agent 都存在上下文窗口限制。Claude Code / Codex 可以通过 `CLAUDE.md`、`AGENTS.md`、compact、subagent、skills、MCP、工具调用等方式缓解上下文压力，但这些机制主要解决“会话级上下文管理”。

stage-harness 的定位应进一步上移：把上下文治理固化为阶段化流程能力，确保长任务在跨阶段、compact、session resume、feedback reopen、build/test 验证后仍能保持需求、验收标准、决策和证据不丢失。

当前 stage-harness 已具备较好的基础：

- 阶段化流水线：`IDEA -> CLARIFY -> SPEC -> PLAN -> EXECUTE -> VERIFY -> DONE`，包含 `FIX` 回路。
- 结构化产物：已有 clarify/spec/plan/work/review/done 等阶段产物要求。
- 门禁机制：已有 `stage-gate check`、receipt、verification、council 等校验机制。
- feedback 机制：已有 feedback submit、evidence-pack、council-triage、write-vote、aggregate、continue、reopen、re-complete 等流程。
- 上下文恢复基础：已有 session-start context 注入、stop hook handoff、execution-trace.jsonl、transcript archive 等。
- 受控产物保护：已有 PreToolUse write guard，阻止 agent 手工写入关键 `.harness` 结构化产物。

但从上下文限制治理角度看，还需要从“有很多产物”升级为“每个阶段有明确的上下文装载策略、恢复策略和证据压缩策略”。

---

## 总体原则

| 原则 | 说明 |
|---|---|
| 上下文是工作内存，不是长期记忆 | 不依赖 Claude Code / Codex 会话自然记住关键约束 |
| 关键状态必须外置 | 需求、验收标准、决策、feedback、运行证据必须落盘 |
| 每阶段只加载最小充分上下文 | 避免全量读仓库、全量读日志、全量读历史讨论 |
| compact 后必须可恢复 | compact / clear / 新 session 后能基于结构化产物恢复任务语义 |
| feedback 必须可回放 | feedback 不是普通聊天，而是 evidence -> triage -> reopen -> replay |
| 验证替代记忆 | 用 test/build/review/acceptance gate 兜底模型遗忘 |

---

## 优先级总览

| 优先级 | 改造项 | 当前基础 | 主要缺口 | 目标 |
|---|---|---|---|---|
| P0 | `context-manifest.json` | 已有 state/spec/plan/coverage/surface-routing 等产物 | 缺少每阶段统一上下文装载清单 | 明确 must_load / optional_load / forbidden_by_default |
| P0 | compact / session checkpoint | 已有 `handoff.md`、session-start、stop hook | handoff 更偏会话交接，不是阶段级恢复包 | 支持 compact / clear / 新 session 后恢复 |
| P0 | `acceptance-index.json` | 验收标准分散在 spec/task/coverage/verification | 缺少统一 AC Source of Truth | WORK / VERIFY / feedback 统一引用验收标准 |
| P0 | feedback orchestration 硬化 | 已有 feedback-triage、council、continue、gate-check | 部分步骤仍依赖主会话自觉续跑 | 减少 submit 后停在半流程状态的风险 |
| P1 | feedback `replay-context` | 已有 evidence-pack、amendment、reopen、re-complete | 缺少回退目标阶段的上下文恢复包 | reopen 后目标阶段可确定性恢复 |
| P1 | run log + summary | receipt/build/smoke 有设计 | 缺统一 runs 目录、失败摘要和日志切片索引 | 避免 build/test 长日志污染上下文 |
| P1 | context budget | 已有 surface-routing、codemap、source_probe_results | 缺少读取预算和片段规模约束 | 控制每阶段文件/日志/代码片段加载规模 |
| P2 | subagent 调度硬化 | council/review/feedback 已有多 agent 设计 | 调度仍偏提示执行 | 增加 missing-vote gate、result schema、dispatch 校验 |
| P2 | runtime adapter 强化 | profile/build_tool 有基础 | 复杂多仓 build/deploy/e2e 不够稳定 | 项目运行流程外置配置化 |
| P3 | trace / audit 视图 | 已有 trace、metrics、handoff、archive | 缺快速问题复盘视图 | 识别上下文污染、compact 丢失、feedback 断链 |
| P3 | 自学习闭环 | 已有 skill-miner / patch trace 基础 | 闭环仍不完整 | 失败样本沉淀为规则或 skill |

---

## P0：优先落地项

### P0-1：新增 `context-manifest.json`

#### 问题

当前 `.harness` 中已经有很多结构化产物，但缺少一个统一的上下文装载清单来告诉 agent：

- 当前阶段必须读什么；
- 可选读什么；
- 默认禁止读什么；
- 日志和源码读取预算是多少；
- compact 时必须保留哪些语义。

没有这个清单时，长任务中容易出现“产物都在，但模型不知道先看哪个”的问题。

#### 建议产物

路径：

```text
.harness/features/<epic-id>/context-manifest.json
```

建议结构：

```json
{
  "epic_id": "<epic-id>",
  "current_stage": "PLAN",
  "updated_at": "<iso8601>",
  "must_load": [
    ".harness/features/<epic-id>/state.json",
    ".harness/specs/<epic-id>.md",
    ".harness/features/<epic-id>/acceptance-index.json"
  ],
  "optional_load": [
    ".harness/features/<epic-id>/surface-routing.json",
    ".harness/features/<epic-id>/coverage-matrix.json",
    ".harness/features/<epic-id>/decision-bundle.json"
  ],
  "forbidden_by_default": [
    ".harness/features/<epic-id>/runs/*/raw.log",
    ".harness/logs/sessions/*.transcript"
  ],
  "compact_preserve": [
    "user requirements",
    "acceptance criteria",
    "confirmed decisions",
    "rejected options",
    "unresolved feedback",
    "failed checks"
  ],
  "context_budget": {
    "max_files_per_stage": 20,
    "max_log_lines": 200,
    "max_probe_snippet_lines": 200,
    "prefer_summary_over_raw_log": true
  }
}
```

#### 集成点

| 位置 | 动作 |
|---|---|
| stage transition 后 | 更新 `current_stage` 与 must_load |
| `/harness:auto` 每轮开始 | 读取 manifest 决定上下文加载范围 |
| feedback reopen 后 | 将 `replay-context` 合入 manifest |
| stop/session-start hook | 优先注入 manifest 摘要，而不是只注入 stage/status |

---

### P0-2：新增阶段级 compact / session checkpoint

#### 问题

当前 stop hook 会写 `handoff.md`，并记录 session stop / abnormal stop / transcript archive。但 `handoff.md` 更偏“会话停止后的下一步提示”，不等价于“阶段级可恢复上下文包”。

长任务中，真正需要的是：

- compact 前后能恢复当前任务语义；
- `/clear` 或新 session 后能恢复关键需求、决策、剩余工作；
- feedback reopen 后不会丢失原始判断依据。

#### 建议产物

路径：

```text
.harness/features/<epic-id>/checkpoints/<STAGE>.checkpoint.md
.harness/features/<epic-id>/checkpoints/<STAGE>.checkpoint.json
```

建议内容：

```json
{
  "epic_id": "<epic-id>",
  "stage": "PLAN",
  "created_at": "<iso8601>",
  "stage_goal": "当前阶段目标",
  "must_preserve": {
    "requirements": [],
    "acceptance_criteria": [],
    "confirmed_decisions": [],
    "rejected_options": [],
    "open_questions": [],
    "pending_feedback": []
  },
  "current_artifacts": [],
  "next_actions": [],
  "known_risks": [],
  "resume_command": "/stage-harness:harness-plan <epic-id>"
}
```

#### 集成点

| 位置 | 动作 |
|---|---|
| 每个阶段出口 | 生成 checkpoint |
| stop hook | handoff 引用最新 checkpoint |
| session-start hook | 注入 checkpoint 摘要 |
| `/compact` 建议文本 | 使用 checkpoint 中的 `must_preserve` |

---

### P0-3：新增统一 `acceptance-index.json`

#### 问题

当前验收标准可能分散在：

- source materials；
- requirement-index；
- spec；
- task acceptance criteria；
- coverage matrix；
- review compliance gaps；
- verification.json。

这会导致 WORK、VERIFY、feedback triage 在不同上下文下引用不同的验收来源。

#### 建议产物

路径：

```text
.harness/features/<epic-id>/acceptance-index.json
```

建议结构：

```json
{
  "epic_id": "<epic-id>",
  "items": [
    {
      "ac_id": "AC-001",
      "source": "source-materials.md#SRC-001:L42-L58",
      "requirement_text": "原始需求文本",
      "normalized_expectation": "标准化验收描述",
      "responsible_tasks": ["TASK-001"],
      "verification_methods": ["unit_test", "integration_test", "manual_review"],
      "evidence_paths": [],
      "status": "pending"
    }
  ]
}
```

#### 集成点

| 阶段 | 使用方式 |
|---|---|
| SPEC | 生成或更新 AC 条目 |
| PLAN | 每个 task 必须引用 AC ID |
| WORK | receipt 必须写入覆盖的 AC ID 和证据 |
| VERIFY | 逐 AC 验证，不只按 reviewer 自由判断 |
| feedback | evidence-pack 关联 violated / impacted AC ID |

---

### P0-4：feedback orchestration 继续硬化

#### 问题

当前 feedback 机制已经具备较完整设计，但仍存在一个上下文风险：部分流程依赖主会话按文档继续执行。

理想目标是：

```text
submit -> evidence-pack -> council init -> dispatch votes -> aggregate -> related-gap-scan -> continue --execute
```

尽量减少中间由模型“记得继续做”的部分。

#### 建议调整

| 调整点 | 说明 |
|---|---|
| `run-triage --execute` 返回强结构 | 返回 agents、required_commands、next_action、blocked_until |
| vote completeness gate | 6 个 agent 投票未齐，不允许 aggregate |
| aggregate 后强制 next_action | verdict 产出后必须进入 continue 或 close |
| continuation_pending 产物化 | 将 allowed_commands、category、target_stage 写入 feedback JSON |
| gate-check 覆盖半流程状态 | submitted / triaging / triaged / continuation_pending / reopened 都必须阻断无关动作 |

---

## P1：上下文污染治理

### P1-1：feedback `replay-context`

#### 问题

feedback reopen 后，目标阶段需要重新加载哪些上下文，当前更多是隐含在文档和流程里。

#### 建议产物

```text
.harness/features/<epic-id>/feedback/HFB-001.replay-context.md
.harness/features/<epic-id>/feedback/HFB-001.replay-context.json
```

建议内容：

```json
{
  "feedback_id": "HFB-001",
  "target_stage": "PLAN",
  "why_reopened": "回退原因摘要",
  "must_load": [
    "HFB-001.evidence-pack.json",
    "HFB-001.verdict.json",
    "acceptance-index.json",
    "PLAN.md 或 task-graph.json"
  ],
  "must_fix": [],
  "must_not_repeat": [],
  "resume_command": "/stage-harness:harness-plan <epic-id> --reopen HFB-001"
}
```

---

### P1-2：run log + summary

#### 问题

build/test/deploy/e2e 日志如果直接进入模型上下文，会快速污染上下文。当前 receipt 中已有 build/smoke 字段，但缺少统一日志治理。

#### 建议目录

```text
.harness/features/<epic-id>/runs/<run-id>/
  command.txt
  raw.log
  failure-summary.md
  run-summary.json
  excerpts/
    error-001.log
```

#### 规则

| 内容 | 是否进入上下文 |
|---|---|
| `raw.log` | 默认禁止 |
| `failure-summary.md` | 默认允许 |
| `run-summary.json` | 默认允许 |
| `excerpts/*.log` | 按需读取 |

---

### P1-3：context budget

#### 问题

即使有 surface-routing / codemap / source_probe_results，也需要明确读取预算，否则 agent 仍可能读太多文件或日志。

#### 建议预算项

```json
{
  "context_budget": {
    "max_files_per_stage": 20,
    "max_files_per_task": 8,
    "max_log_lines": 200,
    "max_raw_log_read": false,
    "max_probe_snippet_lines": 200,
    "prefer_codemap_before_source": true
  }
}
```

---

## P2：流程增强

### P2-1：subagent 调度硬化

当前 feedback/review/council 已有多 agent 设计。后续重点不是增加更多 agent，而是让 agent 结果更可控。

建议：

- 每个 agent 输出统一 schema；
- 缺少任一必需 agent 结果时阻断；
- 每个 vote 必须引用 evidence；
- aggregate 前校验 `_managed=true`；
- 将 agent 调度状态写入 council metadata。

### P2-2：runtime adapter 强化

复杂项目可能包括：

- 多 Maven 子仓；
- RPM 打包；
- Docker 镜像构建；
- 部署到测试环境；
- E2E 验证。

不应只靠 `build_tool` 推断。建议新增：

```text
.harness/runtime-adapter.yaml
```

示例：

```yaml
build:
  command: ./scripts/build-all.sh
  log: .harness/features/${EPIC_ID}/runs/${RUN_ID}/build.log

deploy:
  command: ./scripts/deploy-test-env.sh

e2e:
  command: npx playwright test

summary:
  error_patterns:
    - ERROR
    - FAILURE
    - Exception
    - Caused by
```

---

## P3：观测与自学习增强

### P3-1：trace / audit report

已有 trace 事件后，可以新增报告命令：

```bash
$HARNESSCTL audit context --epic-id <epic-id> --json
```

报告内容：

- 哪些阶段上下文增长最快；
- 哪些日志进入了上下文；
- 哪些 feedback 卡在半流程；
- 哪些阶段 compact / stop / resume 后发生漂移；
- 哪些文件被反复读取但没有形成 codemap。

### P3-2：自学习闭环

在基础上下文治理稳定后，再把失败样本沉淀为：

- project-local rule；
- skill 改进建议；
- stage gate 新校验；
- context-manifest 默认规则。

---

## 推荐实施顺序

| 顺序 | 改造项 | 目标 |
|---:|---|---|
| 1 | `context-manifest.json` | 解决每阶段加载什么的问题 |
| 2 | `stage-checkpoint.md/json` | 解决 compact / clear / 新 session 后恢复问题 |
| 3 | `acceptance-index.json` | 解决验收标准分散问题 |
| 4 | feedback orchestration 硬化 | 减少反馈处理断链 |
| 5 | feedback `replay-context.md/json` | 解决 reopen 后目标阶段上下文恢复问题 |
| 6 | `runs/<run-id>/run-summary.json` + `failure-summary.md` | 解决日志污染上下文问题 |
| 7 | context budget | 控制代码、日志、文档读取规模 |
| 8 | subagent result/gate 硬化 | 提升多 agent 流程稳定性 |
| 9 | runtime adapter | 提升真实项目 build/deploy/e2e 稳定性 |
| 10 | trace audit report | 支持复盘和优化 |
| 11 | 自学习闭环 | 将失败模式沉淀为规则或 skill |

---

## 不建议优先做的方向

| 方向 | 原因 |
|---|---|
| 继续堆更多全局规则 | 会增加上下文负担，且不一定提升遵循率 |
| 一开始就做复杂多 agent council | 没有 evidence / checkpoint / manifest 时，多 agent 只是放大不稳定性 |
| 先做自学习闭环 | 基础上下文产物不稳定时，学习样本质量不可控 |
| 把完整日志交给模型分析 | 最容易污染上下文，应先做 summary 和 excerpt |
| 依赖 Claude Code `/compact` 自然保留重点 | compact 不是无损存档，必须配合 checkpoint |

---

## 最终目标

stage-harness 不应尝试“突破模型上下文窗口”，而应把上下文限制转化为工程化约束：

```text
阶段产物外置
+ 上下文清单显式化
+ compact 恢复包
+ feedback 可回放
+ 日志摘要化
+ 验收索引统一化
+ gate 证据化
```

最终效果：

- 模型上下文被清理后，任务仍能恢复；
- feedback reopen 后，目标阶段知道该加载什么；
- build/test 长日志不会挤占需求和验收标准；
- VERIFY 不依赖模型记忆，而依赖统一 acceptance index 和证据；
- 多 agent 探索不会污染主流程上下文；
- stage-harness 的通用性保留，项目差异通过 adapter / manifest / profile 外置。
