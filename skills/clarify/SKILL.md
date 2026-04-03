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
- 产出 `.harness/features/<epic-id>/domain-frame.json`（结构化，轻量）。
- Lead 将摘要合并进 `clarification-notes.md` 的 **Domain Frame** / **领域框架** 章节。

### Step 3 — Parallel Analysis（spawn 4 agents simultaneously）

Launch in parallel:

```
Agent 1 (requirement-analyst): Input includes domain-frame.json → requirements-draft.md
Agent 2 (impact-analyst):       Scan codebase surfaces + read project-profile.yaml → `impact-scan.md`；`workspace_mode: multi-repo` 时另写 `cross-repo-impact-index.json`（契约优先、深扫仓数受 `scan.max_repos_deep_scan` 约束）
Agent 3 (challenger):           Input includes domain-frame.json → challenge-report.md
Agent 4 (scenario-expander):    Input includes domain-frame.json → generated-scenarios.json
```

Wait for all four to complete.

`impact-analyst` may internally use **agent teams / parallel subagents** only after a first-pass map and only when 3+ major modules are implicated, `risk_level` is `high`, or blast radius already appears broad/systemic. This does **not** change the outer CLARIFY contract: Step 3 still has four top-level roles, and the Lead waits only for the final consolidated `impact-scan.md`.

**沉淀规则**：`challenge-report.md` 中 Critical / Warnings 级发现须进入 `unknowns-ledger.json` 或 `decision-bundle.json`，不得仅停留在报告中。

### Step 4 — Semantic Reconciliation（语义归并）

Lead 在路由代码承载面之前，交叉核对 `domain-frame.json`、`generated-scenarios.json`、`requirements-draft.md`、`challenge-report.md`：合并矛盾语义、将未闭合组合升级为 **must_confirm / UNK / DEC**，并产出 `scenario-coverage.json`。该文件记录每个 `SCN-xxx` 的覆盖状态与映射去向；`clarification-notes.md` 中则追加简短 **Semantic Reconciliation / 语义归并** 小节（可与 Traceability 合并）。

### Step 5 — Surface Routing

- `project-surface-router` reads `requirements-draft.md` + `impact-scan.md`，将 REQ 映射到具体文件 → `surface-map.md`（按需）。
- Lead 或专用步骤按 `skills/project-surface/SKILL.md` 生成/更新 **`surface-routing.json`**（承载面、`repo_id`、`dive_strategy`、`scan_budget`、`evidence_level`）；输入可含 **`cross-repo-impact-index.json`**（multi-repo 时由 `impact-analyst` 写出）。

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
| `cross-repo-impact-index.json` | impact-analyst | multi-repo 时：契约优先的仓级影响索引（可选；单仓可缺省） |
| `surface-routing.json` | Lead / project-surface 流程 | 承载面路由与扫描预算（与 `surface-map.md` 配合） |
| `challenge-report.md` | challenger | 挑战报告（须含 `## Summary`） |
| `scenario-coverage.json` | Lead 汇总 | `SCN-xxx` 到 REQ/CHK/DEC/UNK 的结构化映射 |
| `surface-map.md` | project-surface-router | 需求→代码路由（若执行路由步骤） |
| `clarification-notes.md` | Lead 汇总 | 澄清笔记（**须含 `## Domain Frame` 或 `## 领域框架`**） |
| `unknowns-ledger.json` | `unknowns-ledger-update.sh init/add` | 未知问题台账 |
| `decision-bundle.json` | `decision-bundle.sh generate/add` | 全量决策分类 |
| `decision-packet.json` | `decision-bundle.sh packet` | must_confirm 打包 |

> `interrupt-budget.json` 不再作为独立产物文件，预算状态通过 `$HARNESSCTL budget check` 从 `state.json` 读取。

## Usage

```
Invoke skill: clarify
Epic: <epic-name>
Risk level: medium
Input: <user's raw idea>
```
