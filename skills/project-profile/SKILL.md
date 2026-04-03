# Skill: project-profile

Detect and describe the project's profile from codebase signals.

## Purpose

Classify the project into one of 8 profile types and extract key tech-stack facts that all downstream stages (CLARIFY → SPEC → PLAN) rely on.

## Profile Types

| Type | Signals |
|------|---------|
| `application` | main entry point, GUI, user-facing pages |
| `backend-service` | HTTP server, REST/gRPC endpoints, Dockerfile |
| `frontend` | framework components (React/Vue/Svelte), build pipeline |
| `library` | no binary entry, exports API, package.json `main`/`exports` |
| `data-pipeline` | ETL scripts, DAGs, notebook, batch jobs |
| `infra` | Terraform/Pulumi/Helm, IaC files dominant |
| `plugin` | `.claude-plugin/` or extension manifest |
| `docs` | majority Markdown/RST, no runnable code |

## Detection Algorithm

```
1. Read root file listing (non-recursive, first 50 entries)
2. Read package.json / pyproject.toml / go.mod / Cargo.toml if present
3. Check for Dockerfile, docker-compose.yml, *.tf, *.yaml (k8s)
4. Check for test directory structure (tests/, spec/, __tests__/)
5. Check for .claude-plugin/ directory
6. Score each profile type based on signals
7. Select highest-scoring type; if tie → prefer more specific
```

## Output Schema

```yaml
# .harness/project-profile.yaml
profile_type: backend-service          # one of 8 types
primary_language: typescript           # dominant language
secondary_languages: [sql, bash]
framework: express                     # main framework if any
build_tool: npm                        # npm / cargo / go / poetry / gradle
test_framework: jest                   # test runner
has_database: true
has_auth: false
has_docker: true
has_ci: true
estimated_size: medium                 # small / medium / large / xlarge
risk_default: medium                   # low / medium / high (default for new epics)
intensity:
  agent_parallelism: 3                 # how many parallel workers
  council_size: 3                      # reviewers per council
  harness_strength: standard           # minimal / standard / strict
notes: "Express API, PostgreSQL, Jest, Docker Compose"

# --- Scan routing (optional; aligns with templates/project-profile.yaml) ---
workspace_mode: single-repo            # single-repo | monorepo | multi-repo | docs-heavy | infra-heavy
scan:
  max_repos_deep_scan: 5
  max_files_deep_read_per_scout: 20
  max_subagents_wave: 4
```

### workspace_mode

| Value | Meaning |
|-------|---------|
| `single-repo` | One app root; directory-level scoping |
| `monorepo` | packages/apps/libs; scope to affected packages first |
| `multi-repo` | Sibling repos; use `.harness/repo-catalog.yaml` (see `templates/repo-catalog.yaml`) |
| `docs-heavy` | Mostly docs; prefer README, ADR, indexes — minimal code scan |
| `infra-heavy` | IaC/CI dominant; prefer modules, env, pipelines |

When `workspace_mode: multi-repo`, maintain `.harness/repo-catalog.yaml` so `impact-analyst` can narrow repos before deep scan.

## Risk → Intensity Mapping

| Risk Level | Parallelism | Council Size | Harness |
|-----------|-------------|--------------|---------|
| low | 2 | 2 | minimal |
| medium | 3 | 3 | standard |
| high | 4 | 5 | strict |

## Usage

Invoke at the start of `/harness:start` or when profile is stale:

```
Invoke skill: project-profile
Purpose: Detect project type and set intensity controls for this session.
Output file: .harness/project-profile.yaml
```

After detection, surface findings to user for confirmation before proceeding.
