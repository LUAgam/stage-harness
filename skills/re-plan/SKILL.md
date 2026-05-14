# Skill: re-plan

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```

Incremental PLAN revision — amends task graph based on upstream SPEC changes.

## Purpose

When re-spec adds new acceptance criteria or changes scope, the task plan must be updated. This skill performs task graph merge: adding new tasks, adjusting dependencies, and marking completed tasks that need amendment.

## Trigger

Invoked when:
1. SPEC re-amendment is complete
2. PLAN artifacts (tasks/, coverage-matrix) are marked `stale`
3. Epic stage is at PLAN (via reopen or natural progression)

## Input

- Amended spec with new acceptance criteria
- Existing tasks: `.harness/tasks/<epic-id>.*.json`
- Coverage matrix: `.harness/features/<epic-id>/coverage-matrix.json`
- Feedback context: amendment-plan, revision-diff

## Flow

### Step 1 — Gap Analysis

Compare amended spec against existing tasks:
- New ACs without corresponding tasks
- Changed ACs that invalidate existing task definitions
- Existing completed tasks that may need amendment

### Step 2 — Task Graph Merge

For new requirements:

1. **Create new tasks** with proper structure:
```bash
$HARNESSCTL task create --epic-id <epic-id> \
  --title "Implement X" \
  --depends-on <existing-task-id>
```

2. **Compute dependencies**:
   - Does the new task depend on existing tasks?
   - Do existing pending tasks depend on the new task?
   - Reorder if needed

3. **Check impact on completed tasks**:
   - If a completed task's acceptance criteria changed → mark `needs_amendment`
   - If a completed task is unaffected → leave as `done`

### Step 3 — Dependency Reordering

New tasks should not simply append to the end. Determine correct position:

```
Existing: T1(done) → T2(done) → T3(pending) → T4(pending)
New task T5 depends on T2, and T4 depends on T5:
Result:  T1(done) → T2(done) → T5(pending) → T3(pending) → T4(pending)
```

### Step 4 — Coverage Matrix Update

```bash
$HARNESSCTL coverage map --epic-id <epic-id> --reset
```

Ensure new tasks map to new acceptance criteria.

### Step 5 — Artifact Status Update

```bash
$HARNESSCTL artifact-status set --epic-id <epic-id> \
  --path "features/<epic-id>/tasks/" \
  --status current --reason "Re-planned via HFB-001"

$HARNESSCTL artifact-status set --epic-id <epic-id> \
  --path "features/<epic-id>/coverage-matrix" \
  --status current --reason "Re-planned via HFB-001"
```

### Step 6 — Completion Marker

```bash
# Mark re-plan as completed (REQUIRED — guard will block EXECUTE without this)
$HARNESSCTL feedback re-complete --epic-id <epic-id> \
  --feedback-id <HFB-xxx> --stage PLAN \
  --artifacts "tasks/,coverage-matrix.json"
```

### Step 7 — Stage Gate

```bash
$HARNESSCTL stage-gate check PLAN --epic-id <epic-id>
```

## Task Amendment Rules

| Scenario | Action |
|----------|--------|
| New AC, no existing task covers it | Create new task |
| Existing pending task partially covers new AC | Amend task description |
| Existing done task's AC changed | Mark task `needs_amendment`, create follow-up task |
| Existing done task unaffected | Leave as `done` |
| New task has upstream dependency on done task | Just set `depends_on` |
| New task blocks existing pending task | Insert before, update dependency chain |

## Output

| Artifact | Action |
|----------|--------|
| `.harness/tasks/<epic-id>.*.json` | New/amended tasks |
| `coverage-matrix.json` | Updated |
| `artifact-status.json` | PLAN artifacts → current |
| `revision-diff-HFB-*.md` | Updated with plan changes |

## Exit Criteria

- Every acceptance criterion has at least one mapped task
- Task dependency graph is acyclic
- No orphan tasks (every task traces to an AC)
- Coverage matrix complete
- PLAN stage gate passes
- All `stale` PLAN artifacts resolved to `current`
