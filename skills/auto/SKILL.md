# Skill: auto

Autonomous execution mode — runs CLARIFY → SPEC → PLAN → EXECUTE → VERIFY → BUILD → DEPLOY → E2E → DONE without user interrupts (low/medium risk only).

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

Stage 5: VERIFY (conditional skip in auto mode)
  → If risk_level = high: run acceptance_council normally
     - If APPROVED / APPROVED_WITH_WARNINGS: proceed to BUILD
     - If REJECTED: pause, surface to user (consumes a budget unit)
  → If risk_level in [low, medium] AND config auto_skip_verify != false:
     - SKIP acceptance_council entirely
     - state transition: EXECUTE → VERIFY → BUILD (status log preserved)
     - export HARNESS_SKIP_VERIFY_GATE=1 so harness-build accepts EXECUTE receipts as proof
     - Proceed directly to BUILD

Stage 6: BUILD
  → Resolve build command via build skill (profile → code-aware infer → ask user)
  → Auto-proceed if build/build-receipt.json status is PASS or SKIPPED
  → If FAIL: state transition to FIX, surface error, exit loop

Stage 7: DEPLOY
  → Run deploy skill (multi sub-project aware: scan → infer → confirm → deploy)
  → Auto-proceed if deploy/deploy-receipt.json status is PASS or SKIPPED
  → If FAIL: state transition to FIX, then resume from BUILD on next loop

Stage 8: E2E-TEST
  → Run /stage-harness:harness-e2e-test (user-value-driven: generate-test-cases → verify-and-fix-cases)
  → Result from verify-cases/verify-receipt.json (three states: PASS / PARTIAL / FAIL)
  → If PASS: auto-proceed to DONE
  → If PARTIAL (P0 all passed, some P1/P2/P3 failed): pause, surface failed cases, consume budget unit
     - User accepts → proceed to DONE (record in delivery-summary.md known defects)
     - User rejects → treat as FAIL
  → If FAIL: synthesize verification.json from failed cases, state transition to FIX
     → harness-fix → resume from BUILD → DEPLOY → harness-e2e-test (max 3 rounds)

Stage 9: DONE
  → Run release_council
  → If RELEASE_READY / RELEASE_WITH_CONDITIONS: emit delivery-summary.md & release-notes.md, mark epic DONE
  → If NOT_READY: pause, surface to user (consumes a budget unit)
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
- VERIFY skip path: any task in EXECUTE remains `blocked` when entering BUILD (skipping VERIFY removes the human gate, so blocked tasks must abort instead of pass through)
- E2E-TEST FIX loop exceeds 3 rounds (BUILD → DEPLOY → harness-e2e-test cycle repeated 3 times without reaching PASS/PARTIAL)

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
  ○ BUILD pending
  ○ DEPLOY pending
  ○ E2E-TEST pending
  ○ DONE pending
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
