# Skill: spec

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


Generate structured PRD + SDD + TASKS via ShipSpec, with Stop hooks disabled.

## Purpose

The SPEC stage converts CLARIFY's problem statement into machine-parseable task artifacts using ShipSpec's proven 7-phase workflow. stage-harness wraps ShipSpec and manages the output — it does NOT replace ShipSpec's planning logic.

## ShipSpec Integration Contract

### Invoke ShipSpec
```
/feature-planning
```

ShipSpec's 7 phases:
1. Description — feature description from epic
2. Setup — workspace initialization
3. Requirements Gathering — PRD requirements elicitation (prd-gatherer agent)
4. PRD Generation — `.shipspec/planning/<feature>/PRD.md`
5. Technical Decisions — architecture questions (design-architect agent)
6. SDD Generation — `.shipspec/planning/<feature>/SDD.md`
7. Task Generation — `TASKS.json` + `TASKS.md` (task-planner agent)

### CRITICAL: Disable ShipSpec Stop Hooks

ShipSpec ships 3 Stop hooks that implement the Ralph Loop auto-retry system. These **MUST be inactive** during stage-harness operation to prevent conflicting loop control.

Before invoking `/feature-planning`, verify hooks are not active:
```bash
# Check if shipspec hooks exist in .claude/settings.json
# If present, they will be listed under hooks.stop[]
# stage-harness's own Stop hook handles session continuity instead
```

The 3 hooks to keep inactive:
- `task-loop-hook.sh` — per-task retry loop
- `feature-retry-hook.sh` — feature-wide retry
- `planning-refine-hook.sh` — large task auto-refinement

stage-harness's `hooks/scripts/stop.sh` handles session handoff instead.

### Feature Name Mapping

Epic name → ShipSpec feature name:
```
epic-name: "add-user-auth"
→ /feature-planning feature name: "add-user-auth"
→ artifacts: .shipspec/planning/add-user-auth/PRD.md
```

## SPEC Outputs

After this skill completes, the following files must exist:

**ShipSpec internal outputs** (used by bridge-spec and PLAN stage):

| File | Location | Purpose |
|------|----------|---------|
| PRD.md | `.shipspec/planning/<feature>/` | Product requirements |
| SDD.md | `.shipspec/planning/<feature>/` | Technical design |
| TASKS.json | `.shipspec/planning/<feature>/` | Machine-parseable tasks |
| TASKS.md | `.shipspec/planning/<feature>/` | Human-readable tasks |

**Harness gate outputs** (checked by `$HARNESSCTL stage-gate check SPEC`):

| File | Location | Purpose |
|------|----------|---------|
| `<epic-id>.md` | `.harness/specs/` | Harness-native consolidated spec |
| `spec-council-notes.md` | `.harness/features/<epic-id>/` | Light council review verdict |

## SPEC Quality Gate

After ShipSpec completes, run the SPEC gate:

```
1. Verify all 4 files exist and are non-empty
2. Parse TASKS.json — validate structure matches expected schema
3. Check task count: must be ≥ 3 (too few = under-specified)
4. Check task sizes: flag any task > 5 points (trigger refinement)
5. Verify PRD has REQ-xxx requirements
6. Verify SDD has all 8 Atlassian sections
7. Check coverage: all PRD REQ-xxx referenced in at least one task
8. Cross-check: unknowns-ledger CRITICAL items appear in TASKS.json
```

### Task Size Auto-Refinement
Tasks > 5 story points (Fibonacci) are too large. If found:
```
1. Identify oversized tasks
2. Invoke planning-validator agent to suggest splits
3. Manual split in TASKS.json (task-manager agent)
4. Do NOT activate planning-refine-hook.sh
```

## light_council Review

After structural gate passes, **light_council** uses the same three roles as `harness-spec` / `architecture`:

```
Spawn parallel:
  Agent 1 (challenger): Conflict / scope / missing edge cases
  Agent 2 (requirement-analyst): REQ coverage vs spec, AC testability
  Agent 3 (impact-analyst): Blast radius & dependencies reflected in spec
```

### 概念一致性检查（light_council 必检项）

CLARIFY 决策中使用的关键术语，在 SDD 中的实现必须与术语的实际含义一致。

检查方法：
1. 读取 `decision-bundle.json` 中所有 `resolved` 状态的决策
2. 对每个决策的 `resolution` 中出现的技术术语（如"subagent"、"event-driven"、"plugin"等），检查 SDD 中对应的架构描述是否真正实现了该术语的含义
3. 如果发现术语标签与实际实现不匹配（例如：决策写"subagent 模式"但 SDD 实际描述的是 subprocess 调用），标记为 **high finding**，verdict 降为 REVISE

此检查由 challenger 角色承担，作为其 scope 挑战的一部分。

Aggregated notes written to `.harness/features/<epic-id>/spec-council-notes.md`.

`$HARNESSCTL stage-gate check SPEC` 通过后仍会打印 **语义提示**（stderr，非阻断），例如建议补充「场景矩阵」— 见 `scripts/harnessctl.py` 中 `_spec_semantic_warnings`。

## SPEC → PLAN Transition

After harness spec and council notes are written, run `/harness:bridge` to generate
`bridge-spec.md` from the ShipSpec artifacts for the PLAN stage:

```bash
# bridge reads .shipspec/planning/<feature>/{PRD.md,SDD.md,TASKS.json}
# and writes .harness/features/<epic-id>/bridge-spec.md
scripts/bridge-shipspec-to-deepplan.sh <feature-name> <epic-id>
```

## Usage

```
Invoke skill: spec
Epic: <epic-name>
Pre-conditions:
  - .harness/features/<epic-id>/clarification-notes.md exists
  - .harness/features/<epic-id>/decision-bundle.json exists (all must_confirm resolved)
  - ShipSpec Stop hooks are NOT active
Steps:
  1. Run /feature-planning → produces .shipspec/planning/<epic>/{PRD.md,SDD.md,TASKS.json,TASKS.md}
  2. Run SPEC quality gate (verify the 4 ShipSpec files above)
  3. Write harness-native spec to .harness/specs/<epic-id>.md
  4. Run light_council review
  5. Write council notes to .harness/features/<epic-id>/spec-council-notes.md
  6. Run bridge-shipspec-to-deepplan.sh → .harness/features/<epic-id>/bridge-spec.md
```
