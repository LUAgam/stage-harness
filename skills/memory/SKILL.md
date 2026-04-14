# Skill: memory

Persist, retrieve, and evolve harness knowledge across sessions and epics.

## Purpose

The memory system enables stage-harness to improve over time: patterns from completed epics are preserved, common mistakes are avoided, and successful approaches are promoted to reusable skills.

## Memory Storage Layout

```
.harness/memory/
├── project-patterns.json    # Patterns learned from this project
├── codemaps/                # Hotspot module notes (reuse across epics); templates/codemap-module.md
│   └── <repo_id>/
│       └── <module_slug>.md
├── epic-outcomes/           # Per-epic summary after DONE
│   └── <epic-id>.json
├── candidate-skills/        # Skills awaiting promotion
│   └── <slug>/
│       ├── candidate-skill.md
│       └── observations.jsonl
└── handoffs/                # Session continuity files
    └── <epic-id>-handoff.md
```

### CodeMap (codemaps/)

- After deep reads of recurring or cross-cutting modules, scouts may write short structured notes under `codemaps/<repo_id>/<module_slug>.md` (see template). **Not a source of truth** — re-read source if `confidence` is low or `verified_commit` is stale.
- CLI: `harnessctl memory codemap-init <repo_id> <module_slug> --source-path <path> [--source-path ...]` scaffolds a standard CodeMap file from the template with consistent frontmatter.
- CLI: `harnessctl memory codemap-probe <path-to-codemap.md> [--write] [--json]` compares `source_paths` between `verified_commit` and `HEAD` (project-root git); stale → exit 1; `--write` updates frontmatter (`codemap_probe_at`, `codemap_stale`, may downgrade `confidence`).
- CLI: `harnessctl memory codemap-audit [path] [--write] [--epic-id <id>] [--json]` batch-audits one CodeMap file or a whole codemap directory tree; summary includes `fresh` / `stale` / `missing_verified_commit` / `invalid`.
- Prefer hotspots only; do not mirror the whole tree.

## Memory Operations

### 1. Save Epic Outcome
At `/harness:done` completion, write a structured outcome:

```json
{
  "epic": "add-user-auth",
  "completed_at": "2024-01-20T15:00:00Z",
  "risk_level": "medium",
  "profile_type": "backend-service",
  "stats": {
    "tasks_total": 7,
    "tasks_completed": 7,
    "interrupts_consumed": 1,
    "auto_assumptions": 3,
    "iterations_to_verify": 1
  },
  "what_worked": ["JWT strategy", "parallel scouts fast", "challenger caught auth bypass"],
  "what_didnt": ["test setup took 2 retries"],
  "skills_mined": ["jwt-auth-pattern"],
  "notes": "Standard RBAC pattern — reusable for future auth epics"
}
```

### 2. Load Context on Session Start
When SessionStart hook fires and `.harness/` exists:

```
1. Read .harness/memory/project-patterns.json
2. List active epics (state != DONE)
3. For each active epic, read handoff.md
4. Surface summary to user:
   "Resuming: add-user-auth (EXECUTE, task 3/7)"
```

### 3. Pattern Extraction
After each completed epic, `skill-miner` agent scans:
- What implementation approaches were reused?
- What did the challenger catch repeatedly?
- What council verdicts appeared multiple times?

Patterns with ≥ 2 occurrences become candidate-skills.

### 4. Project Patterns
`project-patterns.json` accumulates project-level knowledge:

```json
{
  "project": "my-api",
  "last_updated": "2024-01-20",
  "patterns": [
    {
      "id": "P001",
      "title": "JWT auth follows express-jwt pattern",
      "source": "epic add-user-auth",
      "confidence": "high",
      "applies_to": ["auth", "middleware"]
    }
  ],
  "avoid": [
    {
      "id": "A001",
      "title": "Don't use bcrypt sync in request handlers",
      "reason": "Blocks event loop — use bcrypt.hash() instead",
      "source": "epic add-user-auth, VERIFY failure"
    }
  ]
}
```

## Memory Retrieval

At the start of CLARIFY for a new epic:
```
1. Read project-patterns.json
2. Find patterns matching the epic's domain
3. Inject relevant patterns into clarification-notes.md under "## Known Patterns"
4. Give workers a "head start" by referencing successful past approaches
```

## Privacy
- `.harness/` is project-local (in `.gitignore` by default)
- Handoff files contain session state, NOT code
- Candidate skills are reviewed before promotion — no auto-promotion

## Usage

```
Invoke skill: memory
Operation: save_outcome | load_context | extract_patterns
Epic: <epic-name>
```
