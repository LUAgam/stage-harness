# Skill: decision-bundle

Compress all decisions from CLARIFY into a minimal user interrupt set.

## Purpose

The most disruptive part of AI-driven development is constant interruptions. This skill implements the Decision Bundle pattern: collect ALL pending decisions, classify them, and condense `must_confirm` items into a single structured packet — maximizing autonomy while preserving control on what matters.

## Decision Categories

### must_confirm
Decisions where:
- Wrong assumption causes irreversible damage (data loss, security hole, API contract break)
- User's intent is genuinely ambiguous and no safe default exists
- Regulatory/compliance requirement demands explicit acknowledgment

→ **Pack into Decision Packet for single user interrupt**

### assumable
Decisions where:
- A reasonable default exists and is clearly correct for the project type
- Wrong assumption is cheap to fix (a few lines, no migration)
- Industry convention is unambiguous (e.g., "use UTC timestamps")

→ **Auto-proceed with proposed_default, log in bundle**

### deferrable
Decisions where:
- Answer depends on later-stage discoveries (PLAN, EXECUTE)
- Decision only matters if a specific branch is taken
- Premature optimization or speculative concern

→ **Add to unknowns-ledger.json, revisit at appropriate stage**

## Bundle Construction Process

```
1. Collect all decisions from:
   - requirement-analyst findings
   - impact-analyst blast radius flags
   - challenger questions
   - deep-dive-specialist memos
2. For each decision:
   a. Assign category (must_confirm / assumable / deferrable)
   b. Assign risk_if_wrong (low / medium / high / critical)
   c. Write proposed_default and why_now
3. Count must_confirm items vs interrupt budget
4. If must_confirm count > budget:
   a. Re-evaluate: can any be reclassified as assumable?
   b. If not: bundle remaining into one packet (don't split across multiple interrupts)
5. Write decision-bundle.json (all decisions)
6. Write decision-packet.json (only must_confirm for user)
```

## Interrupt Budget Enforcement

```
budget = interrupt_budget.json → remaining_interrupts

if must_confirm_count > budget:
  → Combine all into ONE well-structured interrupt
  → Never exceed budget by splitting across turns

if must_confirm_count == 0:
  → No interrupt needed; log "0 interrupts used" in budget
```

## decision-bundle.json Schema

```json
{
  "epic": "epic-name",
  "stage": "CLARIFY",
  "created_at": "2024-01-15T10:00:00Z",
  "summary": {
    "must_confirm": 2,
    "assumable": 8,
    "deferrable": 3,
    "interrupts_consumed": 1
  },
  "decisions": [
    {
      "id": "DEC-001",
      "question": "Should the API use JWT or session cookies?",
      "context": "New auth endpoint being added",
      "risk_if_wrong": "high",
      "category": "must_confirm",
      "proposed_default": "JWT with 1h expiry",
      "why_now": "Blocks SPEC security section",
      "status": "pending | resolved | deferred",
      "resolution": null
    }
  ]
}
```

## decision-packet.json Schema

```json
{
  "epic": "epic-name",
  "interrupt_number": 1,
  "total_interrupts_in_budget": 2,
  "questions": [
    {
      "id": "DEC-001",
      "question": "Should the API use JWT or session cookies?",
      "why_now": "Blocks SPEC security section — wrong choice requires full rewrite",
      "options": ["JWT (recommended)", "Session cookies", "Both"],
      "default_action": "JWT with 1h expiry",
      "deadline": "before SPEC generation"
    }
  ]
}
```

## Usage

```
Invoke skill: decision-bundle
Epic: <epic-name>
Input: findings from requirement-analyst, impact-analyst, challenger
Output:
  - .harness/features/<epic-id>/decision-bundle.json
  - .harness/features/<epic-id>/decision-packet.json (if must_confirm > 0)
```
