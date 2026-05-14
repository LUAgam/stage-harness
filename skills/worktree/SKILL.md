# Skill: worktree

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，先解析本地 CLI 路径：

```bash
if [ -z "${HARNESSCTL:-}" ]; then
  # 1. Read from .harness/config.json if available
  if [ -f ".harness/config.json" ]; then
    _cfg_path=$(python3 -c "import json,sys;print(json.load(open('.harness/config.json')).get('harnessctl_path',''))" 2>/dev/null)
    [ -n "$_cfg_path" ] && [ -x "$_cfg_path" ] && HARNESSCTL="$_cfg_path"
  fi

  # 2. Fallback: search common locations
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
fi

test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "harnessctl not found. Set HARNESSCTL or add harnessctl_path to .harness/config.json" >&2
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
