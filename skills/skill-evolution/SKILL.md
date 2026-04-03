# Skill: skill-evolution

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


Candidate skill lifecycle: mine → shadow validate → auto-refine → human promotion.

## Purpose

Skills improve over time through evidence from real epics. Rather than writing skills manually, stage-harness mines patterns from completed work, validates them in shadow mode, refines them automatically, and only presents them to a human when they've proven reliable.

## Evolution Lifecycle

```
[mine] → [candidate] → [shadow-validate] → [auto-refine] → [promote?]
                             ↑                                    |
                             └──────── (iterate) ─────────────────┘
```

### Stage 1: Mine (skill-miner agent)
After each epic DONE, `skill-miner` scans:
- What implementation patterns were used?
- Which challenger findings were correct?
- Which worker approaches succeeded on first try?

A pattern becomes a candidate when seen ≥ 2 times.

Candidate is written to `.harness/memory/candidate-skills/<slug>/candidate-skill.md` using the template.

### Stage 2: Shadow Validate
On the next relevant epic, the candidate skill runs in "shadow mode":
- System does its normal work
- Candidate skill also runs in parallel (via Task tool)
- Its output is compared to actual outcome

Shadow metrics tracked in `observations.jsonl`:
```jsonl
{"ts": "...", "epic": "...", "prediction": "...", "actual": "...", "match": true, "notes": "..."}
{"ts": "...", "epic": "...", "prediction": "...", "actual": "...", "match": false, "notes": "diverged on edge case"}
```

### Stage 3: Auto-Refine
After N shadow runs (configurable, default 3):
- If match rate ≥ 80%: skill is marked `ready_for_promotion`
- If match rate 60-79%: skill is auto-refined (prompt rewritten to handle failures)
- If match rate < 60%: skill is archived (not promoted)

Auto-refine: `skill-miner` reads failed observations, identifies common failure patterns, rewrites the candidate-skill.md to address them.

### Stage 4: Human Promotion
When a candidate reaches `ready_for_promotion`:
1. `/harness:done` surfaces it: "1 skill ready for promotion: jwt-auth-pattern (95% match over 4 epics)"
2. User reviews candidate-skill.md
3. On approval: skill is moved to `skills/<slug>/SKILL.md` and plugin.json updated
4. Candidate files are archived

## Candidate Skill Schema

```markdown
---
status: candidate | shadow_validating | ready_for_promotion | archived
shadow_runs: 4
match_rate: 0.95
first_seen: 2024-01-20
epics: [add-user-auth, refresh-token-rotation]
---
# Skill: <slug>
...
```

## Eval Metrics

Track per-candidate:
- `shadow_runs`: number of shadow validations
- `match_rate`: fraction where prediction matched actual
- `divergence_cases`: list of epic+reason where it failed
- `auto_refine_count`: how many times auto-refined

## $HARNESSCTL commands

```bash
$HARNESSCTL skill list              # show all candidates + status
$HARNESSCTL skill show <slug>       # show candidate details + metrics
$HARNESSCTL skill promote <slug>    # promote ready candidate to skills/
$HARNESSCTL skill archive <slug>    # archive failed candidate
```

## Usage

```
Invoke skill: skill-evolution
Operation: mine | shadow_validate | auto_refine | promote
Epic: <completed epic name>
```
