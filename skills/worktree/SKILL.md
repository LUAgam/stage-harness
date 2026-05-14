# Skill: worktree

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


Manage git worktrees for isolated epic execution.

## Purpose

Each epic can optionally run in a dedicated git worktree, giving workers an isolated branch without affecting the main workspace. This prevents in-progress work from contaminating the main branch and allows multiple epics to run concurrently.

## When to Use Worktrees

**Use worktree when:**
- Epic modifies shared infrastructure (auth, database, API contracts)
- Multiple epics are running simultaneously
- High risk epic where main branch must stay clean

**Skip worktree when:**
- Single quick epic (low risk, contained blast radius)
- No concurrent epics
- User explicitly opts out

## Worktree Operations

### Create Worktree for Epic

```bash
# Create worktree at .harness/worktrees/<epic-id>
git worktree add .harness/worktrees/<epic-id> -b harness/<epic-id>

# Record in epic metadata
$HARNESSCTL epic set-worktree <epic-id> .harness/worktrees/<epic-id>
```

The worktree branch naming: `harness/<epic-id>` (e.g., `harness/sh-3-add-auth`)

### Work in Worktree

Workers receive the worktree path in their task context. All file operations target the worktree path:
```
working_dir: .harness/worktrees/sh-3-add-auth/
```

### Merge Worktree After VERIFY

After acceptance_council approves:
```bash
# From main workspace
git checkout main
git merge --no-ff harness/<epic-id> -m "feat: <epic title>"

# Remove worktree
git worktree remove .harness/worktrees/<epic-id>
git branch -d harness/<epic-id>
```

### Worktree Conflict Resolution

If merge has conflicts:
1. Surface conflict list to user
2. User resolves manually or defers
3. Re-run verification after resolution

## Worktree Safety

### Pre-merge checks:
- All tests pass in worktree
- No BLOCKED tasks remain
- Acceptance council verdict: APPROVED

### Never auto-merge if:
- Any security reviewer finding rated CRITICAL
- Test coverage below threshold
- Uncommitted changes in worktree

## State Tracking

Worktree info is stored in epic metadata:
```json
{
  "worktree": {
    "enabled": true,
    "path": ".harness/worktrees/sh-3-add-auth",
    "branch": "harness/sh-3-add-auth",
    "base_commit": "abc1234",
    "created_at": "2024-01-15T10:00:00Z"
  }
}
```

## .gitignore

`.harness/worktrees/` should be in `.gitignore` if not already. The worktree directories are managed by git but the `.harness/` metadata directory is local-only.

## Usage

```
Invoke skill: worktree
Operation: create | switch | merge | remove
Epic: <epic-id>
```

After worktree creation, the harness-work command automatically routes workers to the worktree path.
