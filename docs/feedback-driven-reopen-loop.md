# Feedback-driven Reopen Loop

> Proposal: evolve stage-harness from a mostly linear stage pipeline into a pipeline with a controlled, auditable feedback/reopen mechanism that matches how human product and engineering teams handle incorrect SPEC / PLAN outputs.

## Problem

In real agent-driven development, the most frequent failure mode is not only that EXECUTE finds a plan issue. More often, a human reviews SPEC or PLAN and finds that an upstream assumption is wrong:

- the requirement was misunderstood;
- the customer intent was not fully clarified;
- an important boundary scenario was missed;
- acceptance criteria are incomplete or wrong;
- the implementation plan is technically executable but solves the wrong problem;
- impact analysis missed a cross-surface or cross-repo dependency.

A simple `EXECUTE -> PLAN` rollback is not enough for this class of failures. The system needs to decide whether the feedback invalidates PLAN, SPEC, or CLARIFY, then rebuild only the affected downstream artifacts.

## Human-team pattern

A human team usually does not blindly restart the whole process. It follows a lightweight loop:

1. Capture the feedback.
2. Triage the feedback and identify the faulty layer.
3. Decide whether to reopen PLAN, SPEC, or CLARIFY.
4. Record why the stage is being reopened.
5. Preserve confirmed conclusions.
6. Invalidate stale downstream artifacts.
7. Rebuild the affected artifacts.
8. Produce a revision diff.
9. Review the revised version before continuing execution.

The key distinction is:

- if feedback changes **how to execute**, reopen PLAN;
- if feedback changes **what counts as done**, reopen SPEC;
- if feedback changes **what the user actually wants**, reopen CLARIFY.

## Proposed capability

Add a first-class Feedback-driven Reopen Loop:

```text
Human Feedback
  -> feedback submit
  -> feedback triage
  -> reopen decision
  -> artifact invalidation
  -> incremental rebuild
  -> revision diff
  -> review gate
  -> continue forward
```

This should complement, not replace, the existing forward stages:

```text
CLARIFY -> SPEC -> PLAN -> EXECUTE -> VERIFY -> DONE
   ^        ^       ^          ^
   |        |       |          |
   +--------+-------+----------+
        feedback triage / reopen loop
```

## Feedback categories

| Category | Meaning | Reopen target | Example |
| --- | --- | --- | --- |
| `plan_patch` | Task split, sequencing, dependencies, or test plan are wrong. | PLAN | Backend contract should be implemented before UI entry. |
| `spec_patch` | Acceptance criteria, interface contract, boundary, or scope definition is wrong. | SPEC | Acceptance criteria do not cover no-primary-key tables. |
| `clarify_patch` | Requirement semantics, customer intent, or business rule is unclear/wrong. | CLARIFY | Delete-then-insert semantics were never clarified. |
| `analysis_patch` | Impact/risk analysis missed a major dimension. | CLARIFY or SPEC | Insert conflict performance was not analyzed. |
| `scope_change` | User/customer scope changed after prior artifacts were generated. | CLARIFY | Customer now requires full-load rows to include `record_type`. |
| `execution_patch` | Implementation discovered the plan is not executable. | PLAN | The planned extension point does not exist in code. |

Triage rule:

```text
If feedback affects what to build, reopen CLARIFY.
If feedback affects what qualifies as correct, reopen SPEC.
If feedback affects how to implement or verify it, reopen PLAN.
If feedback only affects code mechanics, stay in EXECUTE/FIX.
```

## Proposed artifacts

### `feedback/HFB-*.json`

Captures raw human or reviewer feedback.

```json
{
  "id": "HFB-001",
  "epic_id": "sh-1",
  "stage_when_submitted": "PLAN",
  "source": "human",
  "content": "The plan does not clarify delete-then-insert semantics and no-primary-key row matching.",
  "severity": "high",
  "created_at": "2026-04-29T10:00:00+08:00",
  "status": "submitted"
}
```

### `feedback/HFB-*.triage.json`

Records classification, reason, reopen target, affected artifacts, and preserved conclusions.

```json
{
  "feedback_id": "HFB-001",
  "triage_result": "clarify_patch",
  "reason": "The feedback points to missing requirement semantics and boundary analysis, not just task decomposition.",
  "reopen_stage": "CLARIFY",
  "affected_artifacts": [
    "domain-frame.json",
    "generated-scenarios.json",
    "scenario-coverage.json",
    "clarification-notes.md",
    "unknowns-ledger.json",
    ".harness/specs/sh-1.md",
    "coverage-matrix.json",
    "tasks/*.json"
  ],
  "must_rebuild": ["CLARIFY", "SPEC", "PLAN"],
  "preserve": [
    "insert/update pass through unchanged",
    "target pipeline is oracle2obmysql"
  ],
  "status": "triaged"
}
```

### `artifact-status.json`

Tracks whether stage artifacts are current, stale, or invalidated.

```json
{
  "artifacts": [
    {
      "path": ".harness/features/sh-1/clarification-notes.md",
      "stage": "CLARIFY",
      "status": "invalidated",
      "invalidated_by": "HFB-001",
      "reason": "Missing delete-then-insert semantics."
    },
    {
      "path": ".harness/specs/sh-1.md",
      "stage": "SPEC",
      "status": "stale",
      "invalidated_by": "HFB-001",
      "reason": "Depends on invalidated CLARIFY artifacts."
    }
  ]
}
```

### `reopen-summary.md`

Human-readable record of why the workflow moved backward.

Required sections:

- feedback id;
- original stage;
- reopen stage;
- reason;
- invalidated artifacts;
- preserved conclusions;
- required rebuild chain.

### `revision-diff.md`

Generated after rebuilding affected artifacts.

Required sections:

- compared baseline;
- changed requirements / SPEC / PLAN items;
- added, removed, or modified tasks;
- coverage-matrix changes;
- feedback items resolved;
- remaining risks.

## Proposed commands

Minimal CLI surface:

```bash
harnessctl feedback submit <epic-id> --stage PLAN --file feedback.md
harnessctl feedback triage <epic-id> --feedback-id HFB-001
harnessctl reopen <epic-id> CLARIFY --feedback-id HFB-001
```

Optional convenience command:

```bash
harnessctl feedback apply <epic-id> --feedback-id HFB-001
```

`feedback apply` can run triage, create the reopen summary, invalidate downstream artifacts, and move the state to the reopen target.

## Controlled state transitions

Do not simply allow arbitrary backward transitions through `state transition`.

Recommended rule:

- `harnessctl state transition` handles normal forward progress.
- `harnessctl reopen` handles backward movement.
- Backward movement must reference a triaged feedback item.

Proposed transition capability:

```python
TRANSITIONS = {
    "IDEA": ["CLARIFY"],
    "CLARIFY": ["SPEC"],
    "SPEC": ["PLAN", "CLARIFY"],
    "PLAN": ["EXECUTE", "SPEC", "CLARIFY"],
    "EXECUTE": ["VERIFY", "PLAN", "SPEC", "CLARIFY"],
    "VERIFY": ["FIX", "DONE", "PLAN", "SPEC", "CLARIFY"],
    "FIX": ["VERIFY", "PLAN", "SPEC", "CLARIFY"],
    "DONE": []
}
```

But any backward transition should be accepted only through `reopen`, not direct `state transition`.

## Artifact invalidation rules

| Reopen target | Mark stale or invalidated |
| --- | --- |
| CLARIFY | SPEC, PLAN, tasks, coverage, receipts, verification |
| SPEC | PLAN, tasks, coverage, receipts, verification |
| PLAN | tasks, coverage, receipts, verification |
| EXECUTE | receipts, verification |
| VERIFY | verification, release notes |

Propagation examples:

```text
CLARIFY changed
  -> SPEC stale
  -> coverage-matrix stale
  -> tasks stale
  -> receipts stale
  -> verification stale

SPEC changed
  -> coverage-matrix stale
  -> tasks stale
  -> verification stale

PLAN changed
  -> receipts stale
  -> verification stale
```

## Gate changes

### CLARIFY exit gate

Block if:

- unresolved feedback with `clarify_patch` exists;
- CLARIFY artifacts are invalidated;
- high-risk feedback is not reflected in unknowns / scenarios / coverage;
- revision diff is missing after reopen.

### SPEC exit gate

Block if:

- unresolved `spec_patch` or upstream `clarify_patch` exists;
- SPEC is older than the latest CLARIFY reopen;
- acceptance criteria do not cover added scenarios / unknowns.

### PLAN exit gate

Block if:

- unresolved `plan_patch`, `spec_patch`, or `clarify_patch` exists;
- coverage-matrix is older than latest SPEC;
- tasks are older than latest coverage matrix;
- plan council was not rerun after feedback-driven revision.

### EXECUTE entry gate

Block if:

- unresolved feedback exists;
- any upstream artifact is stale or invalidated;
- latest revision diff is missing;
- latest plan council did not pass;
- risk level requires human review and no approval exists.

## Human review policy

Recommended defaults:

| Risk level | CLARIFY review | SPEC review | PLAN review |
| --- | --- | --- | --- |
| low | AI self-check | AI council | AI council |
| medium | human optional, recommended | human recommended | human recommended |
| high | human required | human required | human required |

For customer-facing or ambiguous pre-sales requirements, CLARIFY and SPEC review should be stronger than EXECUTE review, because executing the wrong requirement is more expensive than fixing code mechanics.

## Minimum implementation slice

P0:

1. Add feedback submit / triage / reopen commands.
2. Add controlled backward transition through `reopen` only.
3. Add artifact invalidation tracking.
4. Add EXECUTE entry gate for unresolved feedback and stale upstream artifacts.
5. Add revision diff requirement after reopen.

P1:

1. Add human review gate policy by risk level.
2. Add partial rebuild support.
3. Add feedback closure mapping into coverage matrix.
4. Add audit events for feedback submit / triage / reopen / resolved.

P2:

1. Mine repeated feedback into project-local pitfalls or candidate skills.
2. Add reopen metrics, including reopen rate by stage and root-cause category.
3. Add replay checks to verify that promoted rules would have caught past feedback earlier.

## Success signals

- A human can reject SPEC or PLAN without manually editing state files.
- The system can explain why it reopened a stage.
- Stale downstream artifacts cannot be used to enter EXECUTE.
- Rebuilt artifacts include a clear revision diff.
- Repeated reopen causes are visible and can feed memory / candidate skills.

## Design principle

Stage-harness should not assume earlier stages are always correct. It should support forward progress plus structured deviation recovery:

```text
forward pipeline + feedback triage + auditable reopen + incremental rebuild
```
