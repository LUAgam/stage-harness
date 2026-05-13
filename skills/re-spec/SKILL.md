# Skill: re-spec

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

Incremental SPEC revision — amends epic specification based on upstream CLARIFY changes.

## Purpose

When re-clarify produces new requirements or surfaces, the SPEC must be updated to include acceptance criteria, constraints, and scope changes. This skill performs incremental spec amendment without rewriting the entire specification.

## Trigger

Invoked when:
1. CLARIFY stage re-amendment is complete
2. SPEC artifacts are marked `stale` in `artifact-status.json`
3. Epic stage has been advanced from CLARIFY to SPEC (or re-opened to SPEC)

## Input

- Amended CLARIFY artifacts (impact-scan.md, surface-routing.json, requirements-draft.md)
- Existing spec: `.harness/specs/<epic-id>.md` or `.harness/features/<epic-id>/epic-spec.md`
- Feedback context: `HFB-*.json`, `HFB-*.triage.json`, `revision-diff-HFB-*.md`
- `artifact-status.json` showing which spec artifacts are stale

## Flow

### Step 1 — Identify Spec Gaps

Compare amended CLARIFY output against existing spec:
- New requirements in `requirements-draft.md` not covered by spec
- New surfaces in `surface-routing.json` without acceptance criteria
- Changed scope items

### Step 2 — Amend Spec

For each new requirement/surface:
1. Add acceptance criteria section
2. Add constraints/non-functional requirements if applicable
3. Mark amendment clearly:

```markdown
<!-- Amendment: HFB-001 | 2026-05-12 -->
### AC-12: PostgreSQL Frontend Endpoint (Added)
- Given: User navigates to endpoint creation
- When: User selects PostgreSQL type
- Then: Form shows Host, Port, Username, Password, DB Name, Schema fields
- Verification: Already supported in oms-ui, no code change needed
<!-- /Amendment -->
```

### Step 3 — Update Coverage Matrix

If new acceptance criteria added:
```bash
$HARNESSCTL coverage map --epic-id <epic-id> --reset
```

### Step 4 — Artifact Status Update

```bash
$HARNESSCTL artifact-status set --epic-id <epic-id> \
  --path "specs/<epic-id>.md" \
  --status current --reason "Amended via re-spec for HFB-001"
```

### Step 5 — Downstream Assessment

Determine if PLAN/tasks need changes:
- New acceptance criteria that require new tasks → leave PLAN as `stale`
- Existing tasks already cover the new criteria → waiver

### Step 6 — Stage Gate

```bash
$HARNESSCTL stage-gate check SPEC --epic-id <epic-id>
```

## Output

| Artifact | Action |
|----------|--------|
| `specs/<epic-id>.md` or `epic-spec.md` | Amended with new ACs |
| `coverage-matrix.json` | Updated mappings |
| `artifact-status.json` | SPEC artifacts → current |
| `revision-diff-HFB-*.md` | Updated with spec changes |

## Exit Criteria

- All new requirements have corresponding acceptance criteria
- Coverage matrix updated
- SPEC stage gate passes
- Downstream impact stated (needs re-plan OR waiver)
