# SKILL: plan

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


PLAN 阶段计划生成技能。将 SPEC 产物转化为可执行的任务图谱，建立覆盖矩阵，确保每个已知风险都有对应的 task、验证手段和证据要求。

---

## 触发条件

- 当前 epic state = `PLAN`
- 收到 `/harness:plan` 命令
- 从 EXECUTE 回流（`$HARNESSCTL state transition <epic-id> PLAN`）

---

## 核心流程

### Step 1 — 承载面缩圈复核

```bash
$HARNESSCTL state get <epic-id>
```

**必须**存在 `.harness/features/<epic-id>/surface-routing.json`（`stage-gate check CLARIFY` / `PLAN` 已要求）。读取并确认后续调研范围：

```bash
test -f .harness/features/<epic-id>/surface-routing.json || {
  echo "error: surface-routing.json missing — complete CLARIFY surface routing first" >&2
  exit 1
}
cat .harness/features/<epic-id>/surface-routing.json
```

确认：
- 哪些承载面（surfaces）被标记为 in-scope
- 哪些已在 SPEC 阶段排除
- 跨承载面边界是否已在 spec 中明确
- `repo_id` / `scan_budget` / `evidence_level` 是否与 `cross-repo-impact-index.json`（如有）一致。`fanout_decision` 为 CLARIFY 产出的 PLAN 输入决策；multi-repo 且 `fanout_decision.mode == repo_wave` 时，PLAN 出口前必须写 `.harness/features/<epic-id>/repo-fanin-summary.json`（见 `templates/repo-fanin-summary.json`）；`single_agent` 不要求。

建议先对相关缓存运行，并将结果落盘为本轮 PLAN 产物：

```bash
harnessctl memory codemap-audit .harness/memory/codemaps/<repo_id> --epic-id <epic-id> --json
```

若结果显示 `stale > 0`、`invalid > 0` 或目标条目 `reason != ok`，在调度 scout 时明确要求**以源码/契约为准，仅将 codemap 作为低置信背景**。若提供了 `--epic-id`，CLI 会额外写出 `.harness/features/<epic-id>/codemap-audit.json`，应将该文件作为 scouts 的辅助输入。

### Step 2 — 并行 scouts 调研

通过 Task 工具**并行**调度 scout agents（**仅**以 `surface-routing.json` 的 `scout_assignments` / `assigned_to` 与 `surfaces[]` 为准；禁止因“路由不全”自行扩大到未登记路径）。**每个 scout 须先**查看 `.harness/features/<epic-id>/codemap-audit.json`（如有）与 `.harness/memory/codemaps/` 下相关模块笔记，再对源码做定点阅读。

| Scout | 职责 |
|-------|------|
| repo-router | 代码结构、模块边界、入口 |
| docs-scout | CLARIFY/SPEC 文档与意图对齐 |
| design-scout | 架构与接口约定 |
| config-scout | 配置、环境、部署约束 |
| symbol-navigator | 符号与调用点 |
| dependency-mapper | 依赖与 import 链 |

每个 scout 输出：已知实体清单 + 发现的约束/风险；**不得**在未登记路径上做大范围盲扫。

### Step 3 — 生成 task 图谱

批量创建 tasks，每个 task 必须包含：
- `surface` 字段（隶属哪个承载面）
- `acceptance_criteria`（可验证的完成标准）
- `dependencies`（前置 task IDs）
- `evidence`（需要产出的证据文件/测试结果）
- `spec_refs`（对应的 SPEC 章节或 REQ 编号列表，如 `["REQ-001", "REQ-003"]`）

```bash
# 为每个 task 运行
$HARNESSCTL task create <epic-id> "<task-title>" --surface <surface-name>
```

**Task 精度要求（强制）**：

1. **`acceptance_criteria` 非空**：每个 task 必须至少有 1 条可验证的 AC。禁止留空或写"见 SPEC"等间接引用。AC 应从 `requirements-draft.md` 的对应 REQ 条目中提取具体验收条件。
2. **`spec_refs` 必填**：每个 task 必须标注其对应的 REQ/FR 编号，建立 task → spec 的双向追溯。
3. **`source_context_hint`（可选）**：当 `requirement-index.json` 的 `input_density` 为 `rich` 时，建议为复杂 task 附加一个 `source_context_hint` 字段，指向 `source-materials.md` 中的相关段落（如 `"SRC-001:L42-L58"`），帮助 Worker 在实现时快速定位原始需求上下文。

跨承载面 task 必须在 task JSON 中写明：
- `boundary`：承载面边界描述
- `deps_cross_surface`：跨面依赖说明
- `integration_points`：联调点清单

**Source Requirement Checklist（条件生成）**：

当 `requirement-index.json` 的 `input_density` 为 `rich` 时，必须从原始需求文档中提取所有**具体的、可逐字验证的**细节要求，生成结构化 checklist：

```bash
# 产出路径
.harness/features/<epic-id>/source-requirement-checklist.json
```

```json
{
  "epic_id": "<epic-id>",
  "source_files": ["<原始需求文档路径>"],
  "checklist": [
    {
      "id": "SRC-CHK-001",
      "source_location": "<文件名>:L42-L45",
      "requirement_text": "<原文摘录>",
      "category": "ui_text|behavior|format|state|constraint|enum_value",
      "responsible_tasks": ["TASK-005", "TASK-006"],
      "verification_hint": "<如何验证：检查什么文件的什么字段/文案/枚举>"
    }
  ]
}
```

提取规则：
1. 只提取有明确正确答案的细节：UI 文案原文、枚举值集合、数字阈值、文件命名格式、交互行为（点击后动作、自动消失时间、二次确认文案等）
2. 不提取概括性描述（如"用户体验好"、"性能足够快"）
3. 每条标注 `category` 和 `responsible_tasks`
4. 当一条需求的验证需要多个 TASK 协作时，所有相关 TASK 都列入 `responsible_tasks`

当 `input_density` 非 `rich` 时，跳过此步骤。REVIEW 阶段将降级为从 spec 自行提取验收标准。

### Step 3.5 — 跨表面接口契约

当 task graph 中存在以下任一情况时，**必须**生成 interface contract 文件：
- TASK-A.surface ≠ TASK-B.surface 且 B `depends_on` A（或 A `depends_on` B）
- 两个不同 surface 的 TASK 共同负责同一 AC

```bash
# 产出路径（每对跨 surface 依赖一份）
.harness/features/<epic-id>/contracts/<provider-task>--<consumer-task>.json
```

```json
{
  "contract_id": "<provider-task>--<consumer-task>",
  "provider": "<task-id>",
  "consumer": "<task-id>",
  "ac_refs": ["<AC-id>"],
  "protocol": "http|event|props|store|file",
  "endpoint": "<method path | event-name | prop-interface>",
  "request_schema": {
    "type": "object",
    "properties": {},
    "required": []
  },
  "response_schema": {
    "type": "object",
    "properties": {}
  },
  "shared_enums": {
    "<field-name>": ["<allowed-value-1>", "<allowed-value-2>"]
  },
  "required_fields": ["<field-name>"],
  "invariants": ["<双方必须遵守的不变量描述>"]
}
```

规则：
1. 每对跨 surface 依赖有且仅有一份 contract，provider 是提供数据/服务的一端，consumer 是消费方
2. `shared_enums` 必须穷举双方约定的枚举值集合——防止 provider 与 consumer 对同一字段使用不同的枚举表示
3. `required_fields` 列出 consumer 调用时必须提供的字段——防止必填参数遗漏
4. `invariants` 描述双方必须共同遵守的约束（如命名规范、数据格式、编码方式等）
5. 无跨 surface 依赖的纯单表面项目，此步骤产出为空目录，不引入额外开销

### Step 4 — 构建 coverage matrix

```bash
$HARNESSCTL coverage map  # 如已实现；否则手动构建
```

构建规则：

1. 读取 `.harness/features/<epic-id>/unknowns-ledger.json`
2. 对每条 unknown 条目，映射到：
   - 对应的 task ID
   - 验证手段（测试/日志/人工确认）
   - 证据文件路径
3. 无法映射的风险写入 `coverage-matrix.json` 的 `unmapped_risks` 字段

**接缝所有权验证（强制）**：

对 coverage-matrix 中每个 AC 条目执行接缝检查：

1. 若该 AC 只映射到 1 个 TASK → 正常通过，无需额外声明
2. 若该 AC 映射到 N≥2 个 TASK → **必须**在 `coverage-matrix.json` 中声明 `seam_coverage` 条目：

```json
{
  "seam_coverage": [
    {
      "ac": "<AC-id>",
      "tasks": ["TASK-A", "TASK-B"],
      "seam_owner": "TASK-A",
      "contract_ref": "TASK-A--TASK-B.json",
      "integration_description": "<seam_owner 负责验证的具体接口行为描述>"
    }
  ]
}
```

规则：
- `seam_owner` 是负责确保接缝正确的 TASK，其 `acceptance_criteria` 中必须包含对接缝验证的描述（如"验证请求参数与后端接口定义一致"）
- `contract_ref` 指向 Step 3.5 生成的 contract 文件（若存在跨 surface 依赖）
- 若所有 AC 均为单 TASK 覆盖，`seam_coverage` 为空数组，不引入额外开销
- plan-council 检查时，存在多 TASK AC 但无 `seam_coverage` → 阻塞，verdict = `REQUEST_CHANGES`

```json
// .harness/features/<epic-id>/coverage-matrix.json
{
  "version": "1.0",
  "epic_id": "<epic-id>",
  "mappings": [
    {
      "unknown_id": "U-001",
      "task_id": "sh-1.3",
      "validation": "integration test",
      "evidence_path": "test-results/auth-flow.json"
    }
  ],
  "unmapped_risks": [
    {
      "unknown_id": "U-005",
      "reason": "需要外部服务配合，无法在当前 sprint 验证",
      "mitigation": "文档记录，下期处理"
    }
  ]
}
```

### Step 5 — 技术 plan-review

调度 `plan-reviewer` agent 审查计划：

```
Task: plan-reviewer
Input: {
  "epic_id": "<epic-id>",
  "tasks_dir": ".harness/tasks/",
  "coverage_matrix": ".harness/features/<epic-id>/coverage-matrix.json",
  "spec_path": ".harness/specs/<epic-id>.md",
  "contracts_dir": ".harness/features/<epic-id>/contracts/"
}
```

plan-reviewer 审查维度（在原有维度基础上新增）：

**接口契约完整性审查**：
- 所有跨 surface 依赖（TASK-A.surface ≠ TASK-B.surface 且存在 depends_on 关系）是否都有对应 contract 文件
- contract 的 `shared_enums` 是否覆盖了 spec 中定义的所有相关状态值/枚举
- contract 的 `required_fields` 是否与 spec 的接口定义一致
- 缺失 contract → verdict = `BLOCK`

**接缝所有权审查**：
- coverage-matrix 中所有映射到 ≥2 个 TASK 的 AC 是否都有 `seam_coverage` 条目
- `seam_owner` 的 acceptance_criteria 中是否包含接缝验证描述
- 缺失 seam_coverage → verdict = `BLOCK`

plan-reviewer 输出 JSON verdict，写入 `.harness/features/<epic-id>/plan-review.json`。

如果 verdict = `BLOCK`，停止流程，修复后重新执行 Step 3。

### Step 6 — 计划议会

调用 `council/SKILL.md`，参数：

```
council_type: plan_council
epic_id: <epic-id>
context: {
  tasks_count: <N>,
  coverage_matrix: <path>,
  plan_review_verdict: <verdict>
}
```

议会 verdict 写入 `.harness/features/<epic-id>/councils/verdict-plan_council.json`。

### Step 7 — Decision Bundle / Packet

调用 `decision-bundle/SKILL.md`，处理本阶段产生的所有决策点。

所有 `must_confirm` 项必须在阶段出口前处理完毕。

---

## 出口条件（全部满足）

- [ ] `plan-review.json` verdict = `READY`
- [ ] `verdict-plan_council.json` verdict = `READY` 或 `READY_WITH_CONDITIONS`
- [ ] `coverage-matrix.json` 已生成，`unmapped_risks` 已显性暴露
- [ ] 若存在跨 surface 依赖：`contracts/` 目录下有对应 contract 文件，且 plan-review 的契约完整性审查通过
- [ ] 若存在多 TASK 共担 AC：`coverage-matrix.json` 的 `seam_coverage` 已声明，且 seam_owner 的 AC 包含接缝验证描述
- [ ] 若 `input_density` 为 `rich`：`source-requirement-checklist.json` 已生成
- [ ] 所有 `must_confirm` 决策已处理
- [ ] `decision-packet.json` 已更新

出口命令：

```bash
$HARNESSCTL state transition <epic-id> EXECUTE
```

---

## 硬规则

1. 不能只有功能拆分，没有风险与验证拆分——每个 unknown 必须有对应 task
2. 任何无法映射到 task 的风险必须在 `unmapped_risks` 显性暴露，不允许静默忽略
3. PLAN 是后半程控制中心——EXECUTE 发现的新问题必须回流 PLAN，不允许就地扩写
4. 跨承载面 task 必须写明边界、依赖和联调点，不允许隐含耦合
5. 当存在跨承载面 task 时，必须生成接口契约（Step 3.5）并在 coverage matrix 中标注 `seam_owner`——无契约或无 seam_owner 的跨面 AC 视为计划不完整
6. 当 `input_density == rich` 时，必须生成 Source Requirement Checklist——REVIEW 阶段依赖该清单逐项验证，缺失视为计划不完整

---

## 回流处理

EXECUTE 阶段回流时：

1. 读取 EXECUTE 产生的 triage 报告（`.harness/features/<epic-id>/triage-<timestamp>.json`）
2. 识别回流原因：`plan_patch`（计划变更）或 `spec_patch`（规格变更）
3. 仅修改受影响的 tasks，不重写整个计划
4. 重新执行 Step 4–7
