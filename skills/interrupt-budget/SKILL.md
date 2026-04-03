# Skill: interrupt-budget

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


Track and enforce the hard limit on user interrupts per epic.

## Purpose

Autonomy is valuable only if it doesn't create more work. The Interrupt Budget is a hard constraint that forces the AI pipeline to batch questions, make reasonable assumptions, and avoid pestering the user — while preserving a guaranteed channel for genuinely critical decisions.

## Budget by Risk Level

| Risk Level | Total Budget | CLARIFY | SPEC | PLAN | EXECUTE |
|-----------|-------------|---------|------|------|---------|
| low | 1 | 0-1 | 0 | 0 | 0 |
| medium | 2 | 1 | 0-1 | 0 | 0 |
| high | 3 | 1-2 | 1 | 0-1 | 0 |

**EXECUTE never interrupts** — if blocked during execution, it logs to unknowns-ledger and completes what it can.

## Budget Storage

Budget state lives in `state.json` under the `interrupt_budget` field (NOT a separate file):

```json
// .harness/features/<epic-id>/state.json (relevant excerpt)
{
  "interrupt_budget": {
    "total": 2,
    "consumed": 0,
    "remaining": 2
  }
}
```

Access via CLI: `$HARNESSCTL budget check --epic-id <epic-id>`
Consume via CLI: `$HARNESSCTL budget consume --epic-id <epic-id>`

## Budget Consumption Rules

### When to consume a budget unit
- User is actually interrupted (shown a decision-packet.json)
- User responds with explicit answers or approvals

### When NOT to consume
- Auto-proceeding with assumable decisions (no user shown)
- Deferring decisions to unknowns-ledger (no user shown)
- Stage gate confirmations (these are progress notifications, not decisions)

## Budget Exhaustion Protocol

If `remaining == 0` and a new `must_confirm` decision arises:
```
1. Attempt reclassification as assumable with safe default
2. If reclassification not safe: add to unknowns-ledger as CRITICAL-BLOCKED
3. Proceed with safe default, mark task with ⚠️ ASSUMPTION flag
4. Surface all CRITICAL-BLOCKED items in harness-status output
5. Never exceed budget — the pipeline makes a best-effort decision
```

## Stage Gate vs Interrupt

Stage gates (end of CLARIFY, SPEC, PLAN) show summaries and ask "proceed?". These are:
- **NOT counted as budget interrupts** — they are progress checkpoints
- Required even at low risk level
- Can be skipped only with `/harness:auto` (medium risk or lower)

## Usage

The Lead Orchestrator calls this skill before each potential interrupt:

```
Check interrupt budget before presenting Decision Packet:
- Run: $HARNESSCTL budget check --epic-id <epic-id>
- If remaining > 0: present packet, then run: $HARNESSCTL budget consume --epic-id <epic-id>
- If remaining == 0: apply Budget Exhaustion Protocol
```
