# SKILL: work

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


EXECUTE 阶段开发执行技能（Worker 循环）。严格按序完成每个 task 的 5-Phase 内循环，确保实现与 spec 对齐，每个 task 有可验证的证据，新发现问题按规则分类处理。

---

## 触发条件

- 当前 epic state = `EXECUTE`
- 收到 `/harness:work` 命令
- 从 FIX 阶段回流

---

## 核心内循环

每个 task 严格按以下 5 个 Phase 执行，不允许跳步。

---

### Phase 1 — Re-anchor（重新定锚）

在开始任何实现前，完整加载当前上下文。

```bash
# 读取 task 详情
$HARNESSCTL task show <task-id> --json

# 读取 epic 当前状态
$HARNESSCTL state get <epic-id>

# 确认工作区状态
git status
git log -5 --oneline

# 读取相关 memory 记录
ls .harness/memory/
cat .harness/memory/<epic-id>-*.md 2>/dev/null || true
```

**Context Depth Loading（上下文深度加载）**：

在基础 re-anchor 之后，根据 task JSON 补充精确上下文：

```bash
# 读取 SPEC 中对应章节（根据 task 的 spec_refs 字段定位）
cat .harness/specs/<epic-id>.md  # 定向阅读 spec_refs 列出的 REQ/FR 段落

# 若 task 含 source_context_hint，读取原始需求对应段落
cat .harness/features/<epic-id>/source-materials.md  # 按 hint 定位行范围
```

加载规则：
- 若 task JSON 含 `spec_refs`（如 `["REQ-001", "REQ-003"]`），读取 SPEC 文件中对应编号的段落
- 若 task JSON 含 `source_context_hint`（如 `"SRC-001:L42-L58"`），读取 `source-materials.md` 中对应行范围
- 若 `requirement-index.json` 存在且 `input_density` 为 `rich` 但无 `source_context_hint`，快速浏览 `source-materials.md` 的 Inline Requirements 段落

**Contract Context Loading（接口契约加载）**：

若 `.harness/features/<epic-id>/contracts/` 目录存在且非空，检查当前 TASK 是否为某 contract 的 provider 或 consumer：

```bash
# 查找与当前 TASK 相关的 contract 文件
ls .harness/features/<epic-id>/contracts/ 2>/dev/null | grep -i "<task-id>" || true
```

加载规则：
- 若当前 TASK 是 contract 的 **provider**（提供数据/服务的一端）：
  - 实现时 response 结构必须符合 `contract.response_schema`
  - 共享枚举字段的取值必须属于 `contract.shared_enums` 定义的集合
  - 不得返回 contract 未声明的必填字段
- 若当前 TASK 是 contract 的 **consumer**（消费方）：
  - 实现时 request 构造必须包含 `contract.required_fields` 中列出的所有字段
  - 枚举字段赋值必须属于 `contract.shared_enums` 定义的集合
  - 不得假设 contract 未声明的响应字段存在
- 若当前 TASK 不涉及任何 contract → 跳过此步骤，无额外开销

Re-anchor 输出：
- 当前 task 目标（来自 task JSON 的 `acceptance_criteria`）
- 上下文摘要（依赖、承载面、已知风险）
- 相关 contracts 列表及当前 TASK 的角色（provider/consumer），若无则省略
- BASE_COMMIT（当前 HEAD）

---

### Phase 2 — Preflight 校验

在进入实现前验证所有前置条件。**任一失败则阻断，不进入实现。**

| 检查项 | 失败处理 |
|--------|---------|
| 依赖前置 task 是否全部 `done` | 阻断，等待依赖完成 |
| 工作区是否干净（无未提交修改） | 先提交或 stash |
| 基线测试是否通过 | 报告失败，回流 FIX |
| Task surface 是否在 in-scope 范围 | 核查 `.harness/features/<epic-id>/surface-routing.json`（CLARIFY 门禁必备）与 clarification-notes.md 范围边界章节 |

```bash
# 检查基线测试
<project-test-command>  # e.g., npm test / pytest / go test ./...
```

Preflight 结果写入 task receipt 的 `preflight` 字段。

---

### Phase 3 — 实现（TDD）

记录 BASE_COMMIT，然后严格按 TDD 顺序执行。

```bash
BASE_COMMIT=$(git rev-parse HEAD)
```

#### RED — 先写测试

- 根据 task 的 `acceptance_criteria` 编写测试
- 运行测试，**确认失败**（测试必须先失败）
- 测试文件命名遵循项目约定

#### GREEN — 最小实现

- 编写最小实现使测试通过
- 只实现 acceptance_criteria 要求的内容，不额外扩写
- 运行测试，**确认通过**

#### IMPROVE — 重构

- 消除重复代码
- 改善命名和可读性
- 确认测试仍然通过
- 检查是否引入新的技术债

实现中发现新问题时，分类（见"新发现问题处理"章节），不要就地修复超出当前 task 范围的问题。

---

### Phase 4 — Task Smoke

每个 task 完成后的最小可运行验证。

```bash
# 运行与当前 task 相关的测试
<test-command> --filter <task-related-pattern>

# 验证证据文件存在
ls <evidence_path>  # 来自 task JSON 的 evidence 字段
```

校验清单：
- [ ] 测试输出文件存在于预期路径
- [ ] 测试全部通过
- [ ] 没有新增的编译/类型错误
- [ ] 证据完整性（`evidence` 字段中列出的文件均存在）
- [ ] 接口契约一致性（若存在相关 contract）：
  - provider 端：代码中 response 结构的字段名/类型与 `contract.response_schema` 一致
  - consumer 端：代码中 request 构造包含 `contract.required_fields` 的所有字段
  - 双方：代码中对共享枚举字段的赋值属于 `contract.shared_enums` 定义的集合（通过 grep/静态分析验证）
  - 无相关 contract 时跳过此项

Task Smoke 失败：
- 记录失败信息
- 失败计数 +1
- 如果连续失败 3 次，自动执行 triage（见"红线"章节）

---

### Phase 5 — Commit + Receipt

原子提交，写 receipt，标记 task done。

```bash
# 原子提交（只提交当前 task 的变更）
git add <task-related-files>
git commit -m "feat(<surface>): <task-title>

task: <task-id>
epic: <epic-id>"

HEAD_COMMIT=$(git rev-parse HEAD)

# 写入 runtime receipt
$HARNESSCTL receipt write <task-id> \
  --base-commit "$BASE_COMMIT" \
  --head-commit "$HEAD_COMMIT" \
  --smoke-passed true

# 标记 task done
$HARNESSCTL task done <task-id>
```

Receipt 文件路径：`.harness/features/<epic-id>/receipts/<task-id>.json`

Receipt 格式（参考模板）：

```json
{
  "task_id": "<task-id>",
  "phase": "EXECUTE",
  "preflight": {"passed": true, "checks": []},
  "implementation": {
    "base_commit": "<sha>",
    "head_commit": "<sha>",
    "files_changed": 0
  },
  "smoke": {"passed": true, "commands": []},
  "build": {
    "executed": true,
    "command": "<build-command>",
    "exit_code": 0,
    "passed": true
  },
  "evidence": {},
  "new_risks": [],
  "timestamp": "<iso8601>"
}
```

---

## Phase 5.5 — Build & Deploy（项目运行时适配）

在 Phase 5 commit 之后执行项目构建验证。

```bash
# 读取项目 profile 获取构建信息
$HARNESSCTL profile show --json
```

根据 `project-profile.yaml` 中的 `build_tool` 自动选择：

| build_tool | 构建命令 |
|-----------|---------|
| npm | `npm run build` 或 `npx tsc --noEmit` |
| maven | `mvn compile -q` |
| gradle | `./gradlew build` |
| go | `go build ./...` |
| cargo | `cargo build` |

```bash
# 使用 harnessctl build（如可用）
$HARNESSCTL build --epic-id <epic-id> --task-id <task-id> --json
```

构建结果写入 receipt 的 `build` 字段。构建失败视为 smoke 失败，消耗重试预算。

---

## 循环推进

完成一个 task 后：

```bash
# 获取下一个 ready task（status=pending，依赖全部 done）
$HARNESSCTL task list <epic-id> --status pending --json
```

选择依赖全部满足的 task，重新从 Phase 1 开始。

---

## 新发现问题处理规则

在实现过程中发现计划外问题时，按以下分类处理：

| 分类 | 条件 | 处理方式 |
|------|------|---------|
| `local_fix` | 当前 task 内可修复，不影响其他 task | 直接修复，记录到 receipt 的 `new_risks` |
| `plan_patch` | 需要新增/修改/删除其他 task | 停止，回流 PLAN |
| `spec_patch` | 发现 spec 与实现现实不符 | 停止，回流 SPEC |

回流命令：

```bash
# 回流 PLAN
$HARNESSCTL state transition <epic-id> PLAN

# 回流 SPEC（需要从 PLAN 再回 SPEC）
$HARNESSCTL state transition <epic-id> PLAN
# 在 PLAN 中再触发 SPEC 回流
```

---

## 每个 task 完成前必须回答

在写 receipt 前，明确回答以下问题：

> 本次实现是否暴露了新的**语义风险**（行为与预期不符）、**兼容风险**（破坏现有接口）、**运维风险**（影响部署/监控/告警）？

- 有 → 写入 `new_risks`，分类为 `local_fix` / `plan_patch` / `spec_patch`
- 无 → `new_risks: []`

---

## 红线（绝对禁止）

1. **不允许计划之外的临场扩写静默混入**——所有超出 acceptance_criteria 的代码必须走 `plan_patch` 流程
2. **不允许顺手改一批而不更新 evidence**——每次代码变更必须对应 receipt 更新
3. **连续失败 3 次自动 triage**：
   ```bash
   # 自动生成 triage 报告
   $HARNESSCTL triage <epic-id> <task-id> \
     --reason "consecutive_failures" \
     --failures 3
   # 停止执行，等待人工干预或回流 PLAN
   ```

---

## EXECUTE 出口

所有 tasks 状态均为 `done` 时，验证出口门禁后进入 VERIFY：

```bash
# 验证所有 tasks 完成
$HARNESSCTL task list <epic-id> --json | jq '.[] | select(.status != "done")'

# 验证所有 receipt 包含 build 结果
$HARNESSCTL receipt list <epic-id> --json
```

出口门禁检查清单：
- [ ] 所有 tasks 状态为 `done`
- [ ] 每个 task 有对应的 receipt 文件
- [ ] 每个 receipt 的 `smoke.passed` 为 `true`
- [ ] 每个 receipt 的 `build.passed` 为 `true`（如 `build.executed` 为 `true`）
- [ ] 无未处理的 feedback（status 非 closed/rejected/deferred）

```bash
# 触发状态转换
$HARNESSCTL state transition <epic-id> VERIFY
```
