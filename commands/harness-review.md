---
description: "审查与验收（技术review + spec compliance + 安全审查 + 对抗式补盲 + 验收议会）"
argument-hint: "<epic-id>"
---

# harness-review

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


执行审查与验收阶段。并行技术 review、spec compliance 检查、安全审查，通过对抗式补盲识别遗漏，最终由验收议会裁决。

## 角色定义

VERIFY 阶段 orchestrator。负责验证 EXECUTE 前置产物、调度 review skill 执行并行审查、编排验收议会。不直接做通过/拒绝决定——裁决由验收议会产出。

## 前置检查

验证 EXECUTE 产物完整：

```bash
$HARNESSCTL stage-gate check EXECUTE --epic-id <epic-id>
```

必须满足：
- `.harness/features/<epic-id>/receipts/` 目录下有 receipt 文件
- 所有任务 `status = done` 或 `blocked`（无 `in_progress` 或未处理的 `pending` 任务）

若检查失败，列出未完成任务，提示先完成 `/harness:work <epic-id>`，终止。

## 注册调度来源

前置检查通过后，立即注册 dispatch 记录：

```bash
$HARNESSCTL dispatch register <epic-id> VERIFY --via=skill:harness-review
```

## 执行步骤

**REQUIRED SKILL:** Use `harness:review` skill

向 skill 传入：
- `epic-id`
- `spec_path`: `.harness/specs/<epic-id>.md`
- `receipts_dir`: `.harness/features/<epic-id>/receipts/`
- `source_materials_path`: `.harness/features/<epic-id>/source-materials.md` — 若存在且 `requirement-index.json` 的 `input_density` 为 `rich`，传给 **runtime-auditor** 和 **logic-reviewer**，用于对照用户原始需求验证实现是否遗漏了明确陈述的功能点或约束
- （建议）`domain_frame_path`: `.harness/features/<epic-id>/domain-frame.json` — 若存在则一并传给 **logic-reviewer** / **test-reviewer**，用于核对 CLARIFY 阶段识别的边界场景是否在实现与测试中有证据
- （建议）`generated_scenarios_path`: `.harness/features/<epic-id>/generated-scenarios.json` — 若存在则传给 **logic-reviewer** / **test-reviewer**，用于核对系统展开的高风险场景是否在规格与实现中出现
- （建议）`scenario_coverage_path`: `.harness/features/<epic-id>/scenario-coverage.json` — 若存在则传给 **logic-reviewer** / **test-reviewer**，用于核对每个 `SCN-xxx` 是否有规格与测试证据

skill 内部执行并行审查：

### 并行 Reviewers

| Reviewer 角色 | 审查维度 |
|-------------|---------|
| code-reviewer | 代码质量、架构一致性、测试覆盖率 |
| logic-reviewer | 逻辑正确性、边界条件、错误路径；**规格中的场景矩阵/事件序列/时序**以及 `SCN-xxx` 覆盖是否与实现一致 |
| security-reviewer | 安全漏洞、权限控制、数据验证 |
| test-reviewer | 测试覆盖、验收标准映射、回归风险；**domain-frame、generated-scenarios、scenario-coverage 与 spec 中的高风险场景**是否有测试或 receipt 证据 |
| runtime-auditor | 实现与 spec 对齐、spec compliance、漂移与不变量（与 acceptance_council 核心成员一致） |
| quality-auditor | （可选）交付质量、回执完整性、残留风险 — 非 acceptance_council 必选五人组 |

所有 reviewer 并行执行，独立输出意见。

### 原始需求对照验证（硬性 — 新增步骤）

在并行审查完成后、对抗式补盲之前，执行原始需求对照验证。此步骤是防止上游信息压缩导致需求丢失的最后防线。

**Step A：定位原始需求文档**

从以下路径获取用户原始需求文档（按优先级）：
1. `.harness/features/<epic-id>/source-materials.md` 中引用的外部文件路径
2. `.harness/features/<epic-id>/requirement-index.json` 中的 `source_files` 字段
3. `.harness/features/<epic-id>/clarification-notes.md` 中「关联 PRD」或「需求来源」引用的文件路径

读取原始需求文档（PRD、交互设计文档等），提取所有验收标准、UI 文案要求、格式规则、状态枚举。

**Step B：读取项目代码进行实现验证**

**优先使用结构化 Checklist**：若 `.harness/features/<epic-id>/source-requirement-checklist.json` 存在，以该文件为逐条核对的结构化输入，替代从 PRD 自行提取验收标准的流程。Checklist 中每条已标注 `category`、`responsible_tasks`、`verification_hint`，可直接定位代码验证。

若 Checklist 不存在（如 `input_density` 非 `rich`），降级为以下原有流程：

对原始需求文档中的每条验收标准：
1. 根据 receipt 中的 `files_changed` 和 `acceptance_checklist` 定位实现代码文件
2. 读取对应代码，逐条检查：
   - UI 文案字符串是否与需求文档原文一致
   - 条件分支是否覆盖需求文档中枚举的所有状态
   - 数据格式（文件名、目录结构等）是否与需求文档规则一致
   - 交互行为（点击后的动作、自动消失、二次确认等）是否完整实现
3. 对每条验收标准标记 `MATCH` / `MISMATCH` / `MISSING`

**接口契约对照验证**：若 `.harness/features/<epic-id>/contracts/` 目录存在且非空，额外执行：
1. 读取所有 contract 文件
2. 对每份 contract，检查 provider 端和 consumer 端的实现代码：
   - `shared_enums` 中定义的枚举值集合是否在双方代码中一致
   - `required_fields` 中的字段是否在 consumer 端的请求构造中全部包含
   - `response_schema` 中的字段是否在 provider 端的响应中全部返回
3. 不一致项标记为 `MISMATCH`，写入 compliance_gaps

**Step C：生成 compliance_gaps 报告**

将所有 `MISMATCH` 和 `MISSING` 项汇总为 `compliance_gaps` 列表：

```json
{
  "compliance_gaps": [
    {
      "ac_id": "<REQ-id>.<AC-id>",
      "requirement_text": "<原始需求文档中的验收标准原文>",
      "expected_behavior": "<需求文档要求的行为描述>",
      "actual_behavior": "<代码实际实现的行为描述>",
      "gap_type": "MISMATCH",
      "file_path": "<实现文件相对路径>",
      "line_number": "<对应行号>"
    }
  ]
}
```

**Step D：compliance_gaps 路由决策**

- `compliance_gaps` 为空 → 继续进入对抗式补盲
- `compliance_gaps` 非空 → 每个 gap 视为 CRITICAL 问题，写入 `verification.json` 的 `critical_issues`，最终议会裁决为 `REJECTED`，触发 FIX 阶段

**对照源优先级（硬性）**：
```
原始需求文档（PRD/交互设计） > requirements-draft > bridge-spec > specs/<epic-id>.md
```
当多个来源存在冲突时，以原始需求文档为准。

### 对抗式补盲

在并行审查完成后，执行对抗式补盲：
- 指定一个 adversarial-reviewer 角色
- 专门寻找"其他 reviewer 可能遗漏"的问题
- 重点关注：边界条件、并发问题、错误路径

### 验收议会

汇总所有 reviewer 意见，运行验收议会裁决：

```bash
$HARNESSCTL council run acceptance_council --epic-id <epic-id>
```

裁决规则：
- 任何 CRITICAL 问题 → `REJECTED`，必须修复后重新审查
- HIGH 问题 >= 3 → `CONDITIONAL_PASS`，需在 done 阶段处理
- 无 CRITICAL 且 HIGH < 3 → `PASS`

## 产物要求

| 产物 | 路径 |
|------|------|
| 验收结果 | `.harness/features/<epic-id>/verification.json` |
| 议会裁决 | `.harness/features/<epic-id>/councils/verdict-acceptance_council.json` |
| 审查汇总 | `.harness/features/<epic-id>/review-summary.md` |
| 需求对照报告 | `.harness/features/<epic-id>/compliance-gaps.json`（仅当存在 gap 时生成） |

`verification.json` 必须包含：
- `acceptance_council`: `PASS` / `CONDITIONAL_PASS` / `REJECTED`
- `code_review` / `logic_review` / `test_review` / `security` / `spec_compliance`：各并行 reviewer 的汇总结论（与 `review/SKILL.md` 示例一致时可简化）
- `requirement_compliance`: `PASS` / `FAIL` — 原始需求对照验证的结果
- `compliance_gaps`: 不符合项列表（PASS 时为空数组）
- `reviewer_verdicts`: 各 reviewer 的意见列表（可选细化）
- `critical_issues`: CRITICAL 级别问题（PASS 时为空数组）— **compliance_gaps 中的每个 MISMATCH/MISSING 项自动计入 critical_issues**
- `high_issues`: HIGH 级别问题列表
- `verified_at`: ISO 时间戳

## 出口条件（门禁规则）

```bash
$HARNESSCTL stage-gate check VERIFY --epic-id <epic-id>
```

通过条件：
- `verification.json` 存在
- `acceptance_council` 或 `council_verdict` 为 `PASS` 或 `CONDITIONAL_PASS`（与 `harnessctl` 的 `_verification_passed` 一致）
- 若文件中写有 `code_review` / `logic_review` / `test_review` / `security` / `spec_compliance`，任一为 `FAIL` 则 `$HARNESSCTL stage-gate check VERIFY` **不通过**
- 无未处理的 CRITICAL 问题（`critical_issues` 非空则失败）

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| EXECUTE 门禁未通过 | 终止，展示未完成任务列表 |
| security-reviewer FAIL | 强制终止，标注为 CRITICAL，不允许继续 |
| 议会 REJECTED | 列出 CRITICAL 问题，触发 FIX 阶段状态转换 |
| CONDITIONAL_PASS | 记录 HIGH 问题到待处理列表，允许继续到 done 阶段 |
| compliance_gaps 非空 | 将每个 gap 写入 critical_issues，议会自动裁决为 REJECTED，触发 FIX 阶段。FIX 完成后重新进入 VERIFY，再次执行原始需求对照验证，直到 compliance_gaps 为空 |
| 原始需求文档不可达 | 降级使用 requirements-draft 作为对照源，在 review-summary.md 中标注「原始需求文档不可达，使用 requirements-draft 作为对照基准」 |
| FIX → VERIFY 循环超过 3 次 | 暂停，展示仍未解决的 compliance_gaps，等待人工干预 |
