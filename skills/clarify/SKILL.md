# Skill: clarify

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


Multi-role CLARIFY engine — converts a raw idea into a structured, validated problem statement.

## Purpose

Before writing any spec, we must understand the problem deeply. The CLARIFY stage uses a Lead Orchestrator + **domain-scout** + specialist roles to surface requirements, risks, unknowns, and decisions — while respecting the Interrupt Budget.

**domain-scout** runs **before** codebase impact analysis on every epic (no opt-out).

## Agent Roles

| Role | Agent | Responsibility |
|------|-------|---------------|
| Lead | `lead-orchestrator` | Coordinates flow, owns Decision Bundle |
| Domain | `domain-scout` | Product/domain framing → `domain-frame.json` (no code reads) |
| Scenario | `scenario-expander` | Expands high-risk semantic signals → `generated-scenarios.json` |
| Analyst | `requirement-analyst` | Decomposes goals → requirements (consumes `domain-frame.json`) |
| Impact | `impact-analyst` | Finds affected surfaces + blast radius |
| Challenger | `challenger` | Stress-tests assumptions (consumes `domain-frame.json`) |
| Router | `project-surface-router` | Maps requirements → codebase surfaces |
| Specialist | `deep-dive-specialist` | Digs into ambiguous areas on demand |

## CLARIFY Flow

与 `agents/lead-orchestrator.md` 对齐：**先 Intake，再 Domain Scout，再并行四角色**。

### Step 1 — Idea Intake

Lead Orchestrator reads:
- Epic description from user
- `.harness/project-profile.yaml` (risk level, intensity)
- Existing unknowns in `unknowns-ledger.json` (if resuming)

Output: Structured idea summary with initial assumption list.

### Step 2 — Domain Scout（固定前置，在代码影响扫描之前）

- 调度 `domain-scout`：仅基于需求文案、`project-profile.yaml`、可选领域标签（可附带 Step 1 摘要）。
- Lead **必须真的调用** `stage-harness:domain-scout` agent；不得由 Lead 自己口头代替、不得只做 `mkdir` 或重复读取画像来冒充 Step 2 完成。
- 产出 `.harness/features/<epic-id>/domain-frame.json`（结构化，轻量；完整 schema 以 `agents/domain-scout.md` 为准）。
- **Step 0 门禁对齐**：顶层须含 `business_goals`、`domain_constraints`、`semantic_signals`、`candidate_edge_cases`、`candidate_open_questions`（与 `scripts/clarify_gate_shared.py` 的 `DOMAIN_FRAME_REQUIRED_KEYS` 一致）。不得用旧键名（如 `domain`、`subdomain`、`domain_signals`）顶替这些字段。
- Lead 将摘要合并进 `clarification-notes.md` 的 **Domain Frame** / **领域框架** 章节。
- 若运行时已提供 profile/state 摘要，Lead 不得在 Step 2 前反复做低价值状态探测；拿到最小必要上下文后应立即派发 `domain-scout`。

### Step 3 — Parallel Analysis（spawn 4 agents simultaneously）

Launch in parallel:

```
Agent 1 (requirement-analyst): Description: decompose requirements, Input includes domain-frame.json → requirements-draft.md
Agent 2 (impact-analyst):      Description: map codebase blast radius, Scan codebase surfaces + read project-profile.yaml → `impact-scan.md`；`workspace_mode: multi-repo` 时另写 `cross-repo-impact-index.json`（契约优先、深扫仓数受 `scan.max_repos_deep_scan` 约束）
Agent 3 (challenger):          Description: stress test assumptions, Input includes domain-frame.json → challenge-report.md
Agent 4 (scenario-expander):   Description: expand edge cases, Input includes domain-frame.json → generated-scenarios.json
```

Wait for all four to complete.

`impact-analyst` may internally use **agent teams / parallel subagents** only after a first-pass map and only when 3+ major modules are implicated, `risk_level` is `high`, or blast radius already appears broad/systemic. This does **not** change the outer CLARIFY contract: Step 3 still has four top-level roles, and the Lead waits only for the final consolidated `impact-scan.md`.

若 `primary_surfaces` hint 无效，`impact-analyst` 必须先做**有界重定向**（顶层浅扫 + 预算内缩圈），而不是退化为全仓宽扫；若预算内仍无法定位，必须显式报告 evidence gap / retarget required。

**沉淀规则**：`challenge-report.md` 中 Critical / Warnings 级发现须进入 `unknowns-ledger.json` 或 `decision-bundle.json`，不得仅停留在报告中。

### Step 4 — Semantic Reconciliation（语义归并）

Lead 在路由代码承载面之前，交叉核对 `domain-frame.json`、`generated-scenarios.json`、`requirements-draft.md`、`challenge-report.md`：合并矛盾语义、将未闭合组合升级为 **must_confirm / UNK / DEC**，并产出 `scenario-coverage.json`。`generated-scenarios.json` 必须使用 canonical `scenarios[]` 结构，且高/中置信度场景应带 `scenario_id`、`pattern`、`source_signals`、`scenario`、`why_it_matters`、`expected_followup`；`scenario-coverage.json` 则使用 canonical `{ epic_id, version, scenarios, signals? }`，记录每个 `SCN-xxx` 的覆盖状态与映射去向，并在需要时通过 `signals[]` 显式闭合高/中置信度语义信号。`clarification-notes.md` 中则追加简短 **Semantic Reconciliation / 语义归并** 小节（可与 Traceability 合并）。

### Step 5 — Surface Routing

- `project-surface-router` reads `requirements-draft.md` + `impact-scan.md`，将 REQ 映射到具体文件 → `surface-map.md`（按需）。
- Lead 或专用步骤按 `skills/project-surface/SKILL.md` 生成/更新 **`surface-routing.json`**（承载面、`repo_id`、`dive_strategy`、`scan_budget`、`evidence_level`）；`surfaces[]` 每项都必须显式包含 `type` 和 `path`；输入可含 **`cross-repo-impact-index.json`**（multi-repo 时由 `impact-analyst` 写出，且 full mode 下不应缺失）。
- 若 `.harness/project-profile.yaml` 声明了可选 `coupling_role_ids`，Lead 需要为本 epic 判断是否存在需要显式闭环的联动责任；需要时写出 `change-coupling-closure.json`，并在 `surface-routing.json.surfaces[].serves_roles` 或 `exemptions[].binds_to = DEC-* / UNK-*` 中闭环。

### Step 6 — Deep Dive (conditional)

If any requirement is rated `UNCLEAR` or `AMBIGUOUS` by challenger:
  → Spawn `deep-dive-specialist` for that requirement
  → Update unknowns-ledger.json with new UNK-xxx entries

### Step 7 — Decision Bundle Construction

Lead Orchestrator aggregates all findings into Decision Bundle (must_confirm / assumable / deferrable).

**Interrupt Budget rules:**
- `must_confirm` decisions → pack into Decision Packet → single user interrupt
- `assumable` decisions → auto-proceed with proposed_default, log in bundle
- `deferrable` decisions → defer to SPEC/PLAN stage, add to unknowns-ledger

Budget limits (from project-profile.yaml):
- low risk: max 1 user interrupt
- medium risk: max 2 user interrupts
- high risk: max 3 user interrupts

### Step 8 — CLARIFY Summary & Gate

Finalize `clarification-notes.md`（含 Domain Frame、REQ 列表、范围边界等）。

若使用 `## 六轴澄清覆盖`，六轴名称必须与 gate canonical 标签一致：`StateAndTime / 行为与流程`、`ConstraintsAndConflict / 规则与边界`、`CostAndCapacity / 规模与代价`、`CrossSurfaceConsistency / 多入口`、`OperationsAndRecovery / 运行与维护`、`SecurityAndIsolation / 权限与隔离`。不要改写成项目定制标签。

**User focus points（通用，非项目定制）**：若用户在对话中点名了必须单独验收的关注点，在笔记中增加 `## Focus Points`（或 `## 用户关注点` / `## 用户点名关注`），每条一行且行内必须出现 `REQ-` / `CHK-` / `SCN-` / `DEC-` / `UNK-` 之一；或使用可选 `focus-points.json`（`items[].maps_to` 等字段指向上述编号）。未点名则不要添加空壳小节；一旦添加，`stage-gate check CLARIFY` 会校验闭环。

**Full 模式下的场景驱动 Focus（与 `clarify_gate_shared` 信号一致）**：当 closure 模式为 **full** 时，对 `generated-scenarios.json` 中 **high** 置信度、在 `scenario-coverage.json` 中已登记且非 `dropped_invalid` 的 `SCN-xxx`，若文本命中 **StateAndTime** 或 **ConstraintsAndConflict** 相关信号，必须在 Focus 小节或 `focus-points.json`（`maps_to` / `closure_ref` / `mapped_to` / `trace`）中**显式出现该 `SCN` 编号**。**notes_only** 不应用此规则。

当 conflict / retry / rewrite / amplification / performance / capacity 语义出现时，Lead 还应把对应的代价/性能风险沉淀到 `CostAndCapacity / 规模与代价` 轴，并闭合到 `SCN` / `REQ` / `DEC` / `UNK`，而不是仅停留在 prose。

Before proceeding to SPEC:
- `$HARNESSCTL stage-gate check CLARIFY --epic-id <epic-id>` 必须通过（含 `domain-frame.json`、`challenge-report.md`、笔记中的 Domain Frame 标题）
- All `must_confirm` decisions resolved (via Decision Packet)
- No BLOCKED items without mitigation

## Outputs

所有文件路径均为 `.harness/features/<epic-id>/`：

| File | 生成方式 | Description |
|------|---------|-------------|
| `domain-frame.json` | domain-scout | 领域框架结构化草稿（Step 2） |
| `generated-scenarios.json` | scenario-expander | 基于 domain-frame 的高风险场景展开结果 |
| `requirements-draft.md` | requirement-analyst | 需求草案 |
| `impact-scan.md` | impact-analyst | 影响面扫描 |
| `cross-repo-impact-index.json` | impact-analyst | multi-repo 时：契约优先的仓级影响索引（必需；单仓可缺省） |
| `surface-routing.json` | Lead / project-surface 流程 | 承载面路由与扫描预算（与 `surface-map.md` 配合） |
| `change-coupling-closure.json` | Lead（可选） | 项目已声明 `coupling_role_ids` 时，用于记录本 epic 的 `required_role_ids` 与 `exemptions`；未启用 taxonomy 时可缺省 |
| `challenge-report.md` | challenger | 挑战报告（须含 `## Summary`） |
| `scenario-coverage.json` | Lead 汇总 | `SCN-xxx` 到 REQ/CHK/DEC/UNK 的结构化映射 |
| `surface-map.md` | project-surface-router | 需求→代码路由（若执行路由步骤） |
| `clarification-notes.md` | Lead 汇总 | 澄清笔记（**须含 `## Domain Frame` 或 `## 领域框架`**） |
| `unknowns-ledger.json` | `unknowns-ledger-update.sh init/add` | 未知问题台账 |
| `decision-bundle.json` | `decision-bundle.sh generate/add` | 全量决策分类 |
| `decision-packet.json` | `decision-bundle.sh packet` | must_confirm 打包 |
| `focus-points.json` | Lead / 用户关注点归档（可选） | 用户点名关注点 → REQ/CHK/SCN/DEC/UNK 的结构化映射；与笔记中 Focus Points 小节二选一或并存 |

> `interrupt-budget.json` 不再作为独立产物文件，预算状态通过 `$HARNESSCTL budget check` 从 `state.json` 读取。

## Usage

```
Invoke skill: clarify
Epic: <epic-name>
Risk level: medium
Input: <user's raw idea>
```
