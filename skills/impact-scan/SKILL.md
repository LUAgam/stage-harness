# Skill: impact-scan

Identify all codebase surfaces affected by an incoming change request.

## Purpose

Before writing a spec, we need to know: what already exists that this epic will touch, modify, or depend on? The impact scan produces a blast-radius map that prevents missing cross-cutting concerns.

## Scan Categories

### 1. High Impact Surfaces
Files/modules the epic will definitely modify:
- Identified by requirement routing
- Existing code that will change behavior
- Usually tagged `P0`

### 2. Medium Impact Surfaces
Files that depend on directly-impacted modules:
- Importers of changed exports
- Configuration that references changed components
- Tests that cover changed behavior
- Usually tagged `P1`

### 3. Low / Peripheral Surfaces
Files that may need minor updates:
- Documentation referencing changed APIs
- Type definitions / schemas
- CI/CD configuration
- Usually tagged `P2`

### 4. New Surfaces (CREATE)
Files/modules that don't exist yet and will be created:
- New endpoints, components, services
- New test files
- New configuration

## Scan Process

Respect `.harness/project-profile.yaml`：`workspace_mode`、`risk_level`、`scan.max_repos_deep_scan`、`scan.max_files_deep_read_per_scout`、`scan.max_subagents_wave`.

```
1. Read clarification-notes.md / requirements-draft.md requirements list
2. If workspace_mode is multi-repo:
   a. Read .harness/repo-catalog.yaml; build cross-repo-impact-index.json (contracts in interfaces[] first)
   b. Deep-scan at most max_repos_deep_scan repos; if more candidates → stop and flag for Lead/user scope convergence
3. For each requirement (and each in-scope repo path):
   a. Search codebase for related symbols (Grep) within routed scope only
   b. Identify existing implementations
   c. Classify impact level
4. Build dependency graph (who imports what)
5. Identify test coverage gaps
6. Flag integration points with external systems
7. Score total blast radius: contained / moderate / broad / systemic
```

Authoritative agent behavior: `agents/impact-analyst.md`. Templates: `templates/cross-repo-impact-index.json`, `templates/repo-catalog.yaml`.

## Blast Radius Scoring

| Score | Description | Risk Modifier |
|-------|-------------|---------------|
| contained | ≤3 files, isolated module | -1 risk level |
| moderate | 4-10 files, single domain | no change |
| broad | 11-30 files, multiple domains | +1 risk level |
| systemic | >30 files or core infrastructure | force high risk |

## Output Format

This output format is the authoritative contract for `impact-scan.md` and should stay aligned with `commands/harness-clarify.md`.

```markdown
# Impact Scan: <epic-name>

## Blast Radius Summary
- **Blast Radius:** moderate
- **Risk Escalation:** none | +1 medium→high
- <2-3 sentence overview of what will change>

## High Impact Surfaces
| Surface / File | Change Type | Notes | Priority |
|----------------|-------------|-------|----------|
| `src/auth/middleware.ts` | modify | Add new permission check | P0 |
| `src/api/users.ts` | modify | Extend user endpoint | P0 |

## Medium Impact Surfaces
| Surface / File | Reason | Risk | Priority |
|----------------|--------|------|----------|
| `src/api/index.ts` | re-export new handler | low | P1 |
| `tests/auth.test.ts` | existing tests may break | medium | P1 |

## Low / Peripheral Surfaces
| Surface / File | Reason | Priority |
|----------------|--------|----------|
| `docs/auth.md` | docs may need update | P2 |

## New Surfaces (CREATE)
| Path | Purpose | Priority |
|------|---------|----------|
| `src/auth/rbac.ts` | new RBAC module | P0 |
| `tests/rbac.test.ts` | unit tests | P1 |

## Integration Points
| System | Type | Impact |
|--------|------|--------|
| Auth0 | external | token validation contract may change |
| PostgreSQL | database | schema change required |

## Risk Flags
- ⚠️ Auth middleware change affects ALL authenticated routes
- ⚠️ Database migration required — irreversible

## Files NOT Impacted
<list key files explicitly ruled out, to prevent over-scoping>
```

## Usage

```
Invoke skill: impact-scan
Epic: <epic-name>
Requirements: <list from clarification-notes.md>
Output: .harness/features/<epic-id>/impact-scan.md
Optional (multi-repo): .harness/features/<epic-id>/cross-repo-impact-index.json
```

After scan, `impact-analyst` reviews and may escalate risk level in project-profile.yaml.
