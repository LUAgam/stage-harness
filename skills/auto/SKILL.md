# Skill: auto

Autonomous execution mode — runs CLARIFY → SPEC → PLAN → EXECUTE → VERIFY without user interrupts (low/medium risk only).

## Purpose

For epics where risk is `low` or `medium` and requirements are clear, `/harness:auto` allows the pipeline to run end-to-end with minimal user involvement. The Interrupt Budget still enforces hard limits, but stage gates are auto-approved.

## Eligibility Check

Before entering auto mode:
```
1. Read .harness/project-profile.yaml
2. Verify risk_level is "low" or "medium"
3. Verify epic state is IDEA or CLARIFY (not mid-execution)
4. Warn user: "Auto mode will proceed with minimal interrupts"
5. Get ONE explicit confirmation before starting
```

**BLOCKED for high risk** — auto mode cannot run for high-risk epics. User must use individual commands.

## Auto Mode Execution Flow

```
Stage 1: CLARIFY
  → Run clarify skill with interrupt budget = 1 (medium) or 0 (low)
  → If 0 budget: all decisions are assumable or deferrable
  → Write clarification-notes.md with assumption log

Stage 2: SPEC
  → Run /feature-planning (ShipSpec)
  → Auto-approve light_council if no CRITICAL verdict
  → If CRITICAL: pause and surface to user (consumes 1 interrupt if available)

Stage 3: PLAN
  → Run parallel scouts + plan skill
  → Auto-approve plan_council if verdict is APPROVED or APPROVED_WITH_WARNINGS
  → Log warnings in unknowns-ledger.json

Stage 4: EXECUTE
  → Run worker loop for each task
  → Workers never interrupt — BLOCKED tasks are deferred
  → Atomic commits per task

Stage 5: VERIFY
  → Run acceptance_council
  → If APPROVED: proceed to DONE
  → If APPROVED_WITH_WARNINGS: proceed with warning log
  → If REJECTED: pause, surface to user (this always consumes a budget unit)
```

## Auto Mode Safeguards

### Never auto-approve:
- Security-critical decisions (auth strategy, encryption)
- Data migration decisions (irreversible)
- API breaking changes
- Any challenger finding rated CRITICAL

### Always log assumptions:
Every assumed decision is written to `.harness/features/<epic-id>/auto-assumptions.md`:
```markdown
## Assumed: JWT token expiry = 1h
Reason: industry standard, easily configurable
Risk: low
Reversible: yes (config change)
```

### Auto-abort conditions:
- Task fails > 3 times with same error
- Security reviewer finds CRITICAL vulnerability
- Test coverage drops below 60%
- Any BLOCKED unknown rated `critical` impact

On abort: write `.harness/features/<epic-id>/auto-abort.md` with reason and last safe state.

## Progress Display

During auto mode, show real-time progress:
```
[AUTO] Epic: add-user-auth | Risk: medium
  ✓ CLARIFY complete (2 assumed, 1 deferred)
  ✓ SPEC complete (PRD: 5 req, SDD: 8 sections, TASKS: 7)
  ⟳ PLAN running... (scouts: 4/4 complete, council: reviewing)
  ○ EXECUTE pending
  ○ VERIFY pending
```

## Usage

```
Invoke skill: auto
Epic: <epic-name>
Pre-conditions:
  - risk_level in [low, medium]
  - User has confirmed auto mode
  - Epic in IDEA or CLARIFY state
```
