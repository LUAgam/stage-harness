# Skill: re-clarify

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，校验环境变量 `HARNESSCTL` 是否已配置：

```bash
test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "ERROR: HARNESSCTL 环境变量未设置或不可执行。请先执行: export HARNESSCTL=/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```

Incremental CLARIFY re-run — amends existing CLARIFY artifacts based on feedback without full re-execution.

## Purpose

When a feedback-driven reopen targets CLARIFY, this skill performs an incremental amendment rather than re-running the full 8-step CLARIFY flow. It preserves valid conclusions, amends gaps, performs sibling scan, and re-validates the stage gate.

## Trigger

This skill is invoked when:
1. `harnessctl reopen` has set the epic stage back to CLARIFY
2. A feedback item (HFB-*) with `target_stage: CLARIFY` exists in `reopened` status

## Input

- Feedback text and triage from `.harness/features/<epic-id>/feedback/HFB-*.json` and `.triage.json`
- Amendment plan from `.harness/features/<epic-id>/feedback/HFB-*.amendment-plan.md`
- Existing CLARIFY artifacts (impact-scan.md, surface-routing.json, domain-frame.json, etc.)

## Flow

### Step 1 — Load Context

Read:
- The triggering feedback (text + triage + amendment-plan)
- All existing CLARIFY artifacts
- `project-profile.yaml` for repo/component context

Identify:
- What was the original gap (from feedback text)
- Which artifacts need amendment (from amendment-plan)

### Step 2 — Point Fix

Address the specific feedback:
- If `requirement_gap`: analyze the missing surface/component, update `impact-scan.md` and `surface-routing.json`
- If `scope_change`: update `requirements-draft.md` with new scope items
- If `correction`: fix the incorrect conclusion in the relevant artifact

### Step 3 — Sibling Scan

Do NOT only fix the user's specific point. Check for similar gaps:
- If user pointed out a missing frontend component, also check:
  - API contracts
  - Permission/auth surfaces
  - Menu/routing entries
  - Configuration items
  - i18n/localization
  - E2E test coverage
  - Documentation

Update artifacts with any additional findings.

### Step 4 — Update Artifacts

For each amended artifact:
1. Preserve existing valid content
2. Add new sections clearly marked with amendment metadata:

```markdown
<!-- Amendment: HFB-001 | 2026-05-12 -->
### Frontend Impact (Added)
...
<!-- /Amendment -->
```

3. Update `unknowns-ledger.json` if new unknowns discovered
4. Update `surface-routing.json` if new surfaces identified

### Step 5 — Artifact Status Update

```bash
$HARNESSCTL artifact-status set --epic-id <epic-id> \
  --path "features/<epic-id>/impact-scan.md" \
  --status current --reason "Amended via HFB-001"
```

For each amended artifact, set status back to `current`.

### Step 6 — Downstream Impact Assessment

Determine if SPEC/PLAN/tasks need changes:

- If amendment adds new requirements → SPEC needs update → leave SPEC artifacts as `stale`
- If amendment confirms no impact → write `revision-diff-HFB-*.md` with waiver conclusion → set downstream to `current` via waiver

```bash
$HARNESSCTL artifact-status waiver --epic-id <epic-id> \
  --path "features/<epic-id>/specs/" \
  --reason "Re-clarify confirmed no spec impact"
```

### Step 7 — Stage Gate Re-validation

```bash
$HARNESSCTL stage-gate check CLARIFY --epic-id <epic-id>
```

Must pass before proceeding.

### Step 8 — Feedback Status Update & Completion Marker

Update feedback status to `amending` → `implemented` and register re-completion:

```bash
# Mark re-clarify as completed (REQUIRED — guard will block EXECUTE without this)
$HARNESSCTL feedback re-complete --epic-id <epic-id> \
  --feedback-id <HFB-xxx> --stage CLARIFY \
  --artifacts "impact-scan.md,surface-routing.json"
```

This creates `HFB-xxx.re-completion.json` which the reopen guard checks before allowing EXECUTE entry.

## Output

| Artifact | Action |
|----------|--------|
| `impact-scan.md` | Amended with new findings |
| `surface-routing.json` | Updated if new surfaces |
| `requirements-draft.md` | Updated if new requirements |
| `unknowns-ledger.json` | Updated if new unknowns |
| `revision-diff-HFB-*.md` | Written with amendment summary |
| `artifact-status.json` | Updated statuses |

## Exit Criteria

- All amended artifacts pass content validation
- Stage gate CLARIFY passes
- `revision-diff-HFB-*.md` exists documenting changes
- Downstream impact clearly stated (needs re-spec OR waiver applied)

## Sibling Scan Checklist

When a gap is found in one area, systematically check these siblings:

| Category | Check |
|----------|-------|
| Frontend | Pages, components, routes, menus |
| Backend | APIs, services, repositories, models |
| Data | Schema, migrations, seed data |
| Auth | Permissions, roles, access control |
| Config | Environment vars, feature flags |
| i18n | Translations, locale files |
| Tests | Unit, integration, E2E coverage |
| Docs | API docs, user guides, changelogs |
| Infra | Deployment, CI/CD, monitoring |
