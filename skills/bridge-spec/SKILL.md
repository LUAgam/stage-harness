# SKILL: bridge-spec

ShipSpec → deep-plan 桥接技能。将 ShipSpec 产物（PRD、SDD、TASKS、unknowns-ledger）合并为 deep-plan 可接受的统一输入格式（bridge-spec.md）。

---

## 触发条件

- 收到 `/harness:bridge` 命令
- 在 PLAN 阶段开始前，需要将 ShipSpec 产出桥接到 stage-harness 体系时

---

## 桥接步骤

运行 `scripts/bridge-shipspec-to-deepplan.sh <feature-name> <epic-id>`：

```bash
./scripts/bridge-shipspec-to-deepplan.sh <feature-name> <epic-id>
```

### Step 1 — 从 PRD.md 提取需求摘要与优先级

读取 `.shipspec/planning/<feature>/PRD.md`，提取：
- 核心需求（User Stories / Acceptance Criteria）
- 功能优先级（P0/P1/P2 分层）
- 明确的 non-goals（排除范围）
- 关键约束（性能、兼容性、合规）

### Step 2 — 从 SDD.md 提取架构决策

读取 `.shipspec/planning/<feature>/SDD.md`，提取：
- 系统架构决策（ADRs）
- 接口设计（API 契约、数据协议）
- 数据模型（schema、状态机）
- 技术选型理由

### Step 3 — 从 TASKS.json 提取任务清单

读取 `.shipspec/planning/<feature>/TASKS.json`（如存在），提取：
- 任务列表与 ID
- 任务间依赖关系
- 每个任务的验收标准

### Step 4 — 从 unknowns-ledger.json 提取未闭环问题

读取 `.harness/features/<epic-id>/unknowns-ledger.json`，提取：
- 已知但未解答的问题（`status: open`）
- 每个问题的风险等级
- 已有的临时假设（assumptions）

### Step 5 — 合并为 bridge-spec.md

输出到 `.harness/features/<epic-id>/bridge-spec.md`，格式见下方。

---

## bridge-spec.md 输出格式

```markdown
# Bridge Spec: Implementation Plan Input

Generated from ShipSpec artifacts for deep-plan consumption.

## Requirements (from PRD)

[PRD 内容]

## Technical Design (from SDD)

[SDD 内容]

## Task Breakdown (from TASKS.json)

[TASKS.json 内容，JSON 格式]

## Open Unknowns (must be addressed in plan)

[unknowns-ledger.json 内容，JSON 格式]
```

---

## 前置条件检查

运行前验证以下文件存在：
- `.shipspec/planning/<feature>/PRD.md` — **必须存在**
- `.shipspec/planning/<feature>/SDD.md` — **必须存在**
- `.shipspec/planning/<feature>/TASKS.json` — 可选
- `.harness/features/<epic-id>/unknowns-ledger.json` — 可选

任何必须文件缺失时，脚本退出码 1，输出缺失文件路径。

---

## 后置验证

bridge-spec.md 生成后，确认：
- 文件非空（> 100 bytes）
- 包含 `## Requirements` 章节
- 包含 `## Technical Design` 章节
- 如果 unknowns-ledger 有 open 条目，确认 `## Open Unknowns` 章节存在

---

## 注意事项

- bridge-spec.md 是**只读参考文档**，PLAN 阶段不直接修改它
- 如果 ShipSpec 产物更新，重新运行脚本即可覆盖
- bridge-spec.md 的内容应在 PLAN 阶段 Step 3 生成 task 图谱时作为输入依据
