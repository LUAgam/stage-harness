# Adapters & Integrations

Stage-Harness integrates with several tools in the Claude Code ecosystem. This document explains each integration.

## ShipSpec (SPEC Stage)

ShipSpec provides the PRD → SDD → TASKS pipeline used in the SPEC stage.

### Integration Points

| Stage-Harness | ShipSpec | How |
|--------------|----------|-----|
| `/stage-harness:harness-spec` | `/feature-planning` | Invokes ShipSpec command |
| SPEC quality gate | TASKS.json | Validates ShipSpec output |
| light_council | PRD.md + SDD.md | Reviews artifacts |
| Bridge script | TASKS.json | Converts to bridge-spec.md |

### Disabled ShipSpec Hooks

Stage-Harness disables ShipSpec's 3 Stop hooks to prevent loop conflicts:
- `task-loop-hook.sh` — replaced by stage-harness worker loop
- `feature-retry-hook.sh` — replaced by harness runtime retry
- `planning-refine-hook.sh` — replaced by SPEC quality gate

To verify hooks are not active, check `.claude/settings.json` — the ShipSpec hooks should NOT be listed under `hooks.stop`.

### ShipSpec Artifacts Location

ShipSpec writes to `.shipspec/planning/<feature>/`. Stage-Harness references these directly or bridges them via `bridge-spec` skill.

## Deep Plan (PLAN Stage)

The `bridge-spec` skill converts ShipSpec artifacts into the format expected by deep-plan patterns.

### bridge-spec.md Format

The bridge script (`scripts/bridge-shipspec-to-deepplan.sh`) reads:
- `.shipspec/planning/<epic>/PRD.md`
- `.shipspec/planning/<epic>/SDD.md`
- `.shipspec/planning/<epic>/TASKS.json`
- `.harness/features/<epic-id>/unknowns-ledger.json`

And writes `.harness/features/<epic-id>/bridge-spec.md` with:
- Executive summary
- Full requirements (from PRD)
- Architecture decisions (from SDD)
- Task breakdown with dependencies
- Open unknowns

The PLAN stage parallel scouts read `bridge-spec.md` as their primary input document.

## ECC Agents (Everything-Claude-Code)

Stage-Harness reviewer agents extend ECC's reviewer patterns.

| Stage-Harness Agent | ECC Equivalent | Extension |
|--------------------|---------------|-----------|
| `code-reviewer.md` | `code-reviewer` | Adds harness receipt output |
| `security-reviewer.md` | `security-reviewer` | Adds OWASP checklist gate |
| `test-reviewer.md` | `tdd-guide` | Adds coverage matrix check |
| `plan-reviewer.md` | `planner` | Adds council verdict format |

ECC agents can be used directly in stage-harness contexts — they share the same tool interfaces.

## harnessctl CLI

`harnessctl` is the Python CLI that manages harness state. It has no external dependencies.

### Setup for Agent Use

Agents can call harnessctl for state management:
```bash
harnessctl state transition <epic> SPEC
harnessctl task start <task-id>
harnessctl task done <task-id>
```

### Setup for Human Use

```bash
# Make executable (already set in repo)
chmod +x scripts/harnessctl

# Or run directly
python3 scripts/harnessctl.py --help
```

### Available Commands

```
harnessctl init                     Initialize .harness/
harnessctl profile detect           Auto-detect project profile
harnessctl profile show             Show current profile
harnessctl epic create <title>      Create new epic
harnessctl epic list                List all epics
harnessctl epic show <id>           Show epic details
harnessctl task create <epic> <title>
harnessctl task start <task-id>
harnessctl task done <task-id>
harnessctl task fail <task-id> <reason>
harnessctl task block <task-id> <reason>
harnessctl state get <epic>
harnessctl state transition <epic> <target-stage>
harnessctl state get <epic>
harnessctl status                   Show all epic statuses
harnessctl validate                 Validate .harness/ structure
```

## Git Integration

Stage-Harness uses git for:
- Atomic commits per task (worker skill)
- Optional worktrees per epic (worktree skill)
- Merge after acceptance council approves

The harness itself does NOT auto-push — push remains a manual user action.

## Claude Code Hooks

Three hooks manage session continuity:

| Hook | Event | Action |
|------|-------|--------|
| `session-start.sh` | SessionStart | Detect active epics, show status |
| `pre-tool-use.sh` | PreToolUse (Bash) | Guard dangerous commands |
| `stop.sh` | Stop | Write handoff.md for active epics |

Hooks are registered in `hooks/hooks.json` and must be copied to `.claude/settings.json` to activate.
