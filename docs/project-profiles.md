# Project Profiles

Stage-Harness detects your project type and adjusts its behavior accordingly. Understanding profiles helps you override the detection when needed.

## Profile Types

### application
**Signals:** main entry point + GUI, user-facing pages, mixed frontend/backend
**Examples:** Electron app, full-stack web app, mobile app
**Default risk:** medium
**Intensity:** parallelism=3, council=3

### backend-service
**Signals:** HTTP server, REST/gRPC endpoints, Dockerfile, no frontend
**Examples:** Express API, FastAPI service, Go HTTP server
**Default risk:** medium
**Intensity:** parallelism=3, council=3

### frontend
**Signals:** React/Vue/Svelte components, build pipeline (vite/webpack), CSS files dominant
**Examples:** React SPA, Next.js app, Vue dashboard
**Default risk:** low
**Intensity:** parallelism=2, council=2

### library
**Signals:** No binary entry point, package.json `exports`, extensive type definitions
**Examples:** npm package, Python library, Go module
**Default risk:** high (breaking changes affect all consumers)
**Intensity:** parallelism=4, council=5

### data-pipeline
**Signals:** ETL scripts, Airflow DAGs, Jupyter notebooks, batch jobs
**Examples:** Data warehouse ETL, ML training pipeline, data sync job
**Default risk:** high (data integrity concerns)
**Intensity:** parallelism=3, council=4

### infra
**Signals:** Terraform/Pulumi/Helm files dominant, IaC patterns, cloud provider resources
**Examples:** AWS infrastructure, Kubernetes cluster config, CI/CD setup
**Default risk:** high (outages possible)
**Intensity:** parallelism=4, council=5

### plugin
**Signals:** `.claude-plugin/` directory, extension manifest, slash commands directory
**Examples:** Claude Code plugin, VS Code extension, browser extension
**Default risk:** medium
**Intensity:** parallelism=3, council=3

### docs
**Signals:** Majority Markdown/RST/AsciiDoc, minimal runnable code
**Examples:** Documentation site, API reference, architecture docs
**Default risk:** low
**Intensity:** parallelism=2, council=2

## Overriding Detection

If auto-detection is wrong, override in `.harness/project-profile.yaml`:

```yaml
profile_type: library     # Override detected type
risk_default: high        # Override default risk
intensity:
  agent_parallelism: 4
  council_size: 5
  harness_strength: strict
```

Or use harnessctl:
```bash
harnessctl profile set type=library risk=high
```

## Risk Level Impact

### low risk
- Interrupt budget: 1 total
- Stage gates: auto-approved (with `/harness:auto`)
- Council: 2 agents
- Harness: minimal checks

### medium risk
- Interrupt budget: 2 total
- Stage gates: require confirmation
- Council: 3 agents
- Harness: standard checks

### high risk
- Interrupt budget: 3 total
- Stage gates: require confirmation + summary review
- Council: 5 agents
- Harness: strict checks (pre-flight + smoke + adversarial)
- Auto mode: DISABLED

## Workspace mode and scan budgets

For large or multi-repo workspaces, set in `.harness/project-profile.yaml` (see `templates/project-profile.yaml`):

- **`workspace_mode`**: `single-repo` | `monorepo` | `multi-repo` | `docs-heavy` | `infra-heavy` — steers CLARIFY impact analysis and PLAN scout scope.
- **`scan`**: `max_repos_deep_scan`, `max_files_deep_read_per_scout`, `max_subagents_wave` — hard caps for deep reads and parallel fan-out.

When `workspace_mode: multi-repo`, add `.harness/repo-catalog.yaml` from `stage-harness/templates/repo-catalog.yaml`. CLARIFY produces `cross-repo-impact-index.json` and (with `project-surface`) `surface-routing.json`. Hotspot notes may live under `.harness/memory/codemaps/` (see `skills/memory/SKILL.md`).

## Per-Epic Risk Override

You can override risk for a specific epic without changing the project default:

```
/harness:start
> Epic: "Refactor payment processing"
> Risk: high  ← override for this epic only
```

Or:
```bash
harnessctl epic create "Refactor payment processing" --risk high
```
