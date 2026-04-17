#!/usr/bin/env python3
"""harnessctl — stage-harness CLI controller.

Zero external dependencies. Uses only Python standard library.
Manages .harness/ directory structure, epics, tasks, and state machine.
"""

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HARNESSCTL_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = _HARNESSCTL_DIR.parent
INSTALL_LIFECYCLE_CLI = PLUGIN_ROOT / ".cursor" / "scripts" / "install-lifecycle-cli.js"
if str(_HARNESSCTL_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESSCTL_DIR))
from clarify_gate_shared import (
    change_coupling_closure_errors,
    change_coupling_closure_warnings,
    clarify_focus_point_closure_errors,
    clarify_state_constraint_signal_scn_focus_errors,
    coupling_role_ids_from_profile,
    domain_frame_missing_required_keys,
    generated_scenarios_strict_errors,
    profile_coupling_role_errors,
    scenario_coverage_strict_errors,
    surface_routing_coupling_errors,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HARNESS_DIR = ".harness"
CONFIG_FILE = "config.json"
PROFILE_FILE = "project-profile.yaml"
REPO_CATALOG_FILE = "repo-catalog.yaml"
VERSION = "4.6"

STAGES = ["IDEA", "CLARIFY", "SPEC", "PLAN", "EXECUTE", "VERIFY", "FIX", "DONE"]

TRANSITIONS = {
    "IDEA":    ["CLARIFY"],
    "CLARIFY": ["SPEC"],
    "SPEC":    ["PLAN"],
    "PLAN":    ["EXECUTE"],
    "EXECUTE": ["VERIFY", "PLAN"],
    "VERIFY":  ["FIX", "DONE"],
    "FIX":     ["VERIFY", "PLAN"],
    "DONE":    [],
}

TASK_STATUSES = ["pending", "in_progress", "done", "failed", "blocked"]
PROFILE_UNKNOWN = "unknown"
PROFILE_NEUTRAL_DEFAULTS = {
    "type": PROFILE_UNKNOWN,
    "primary_language": PROFILE_UNKNOWN,
    "build_tool": PROFILE_UNKNOWN,
    "test_framework": PROFILE_UNKNOWN,
    "has_database": None,
    "has_auth": None,
    "has_docker": None,
    "has_ci": None,
    "estimated_size": PROFILE_UNKNOWN,
    "workspace_mode": PROFILE_UNKNOWN,
    "primary_surfaces": [],
    "check_focus": [],
    "coupling_role_ids": [],
}
LEGACY_PROFILE_TEMPLATE_DEFAULTS = {
    "type": "backend-service",
    "primary_language": "typescript",
    "build_tool": "npm",
    "test_framework": "jest",
    "has_database": True,
    "has_auth": False,
    "has_docker": True,
    "has_ci": True,
    "estimated_size": "medium",
    "workspace_mode": "single-repo",
    "primary_surfaces": ["src/"],
    "check_focus": ["api_contract", "state_idempotency"],
}
PROFILE_REPO_MARKERS = (
    ".git",
    "package.json",
    "go.mod",
    "pyproject.toml",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "CMakeLists.txt",
    "Makefile",
)
PROFILE_SCAN_IGNORE_DIRS = {
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
}

RISK_LEVELS = ["low", "medium", "high"]
ACCEPTANCE_STATUSES = ["met", "partial", "not_met"]
KNOWN_ROI_METRICS = [
    "cache_hit_rate",
    "source_reread_rate",
    "avg_tokens_clarify_plan",
    "avg_latency_clarify_plan",
    "routing_correction_rate",
]
KNOWN_ACCEPTANCE_CRITERIA = [
    "mvp_no_blind_scan",
    "routing_auditable",
    "codemap_reuse_visible",
]

TASK_STATUS_ALIASES = {
    "completed": "done",
    "ready": "pending",
}

PROFILE_DETECT_RULES = [
    ("package.json",  "frontend"),
    ("go.mod",        "backend"),
    ("setup.py",      "library"),
    ("pyproject.toml","library"),
    ("Dockerfile",    "backend"),
]

PROFILE_DETECT_GLOB_RULES = [
    ("*.tf",  "infra"),
]

SUBDIRS = [
    "surfaces",
    "features",
    "epics",
    "specs",
    "tasks",
    "memory",
    "metrics",
    "logs",
    "rules",
]

DEFAULT_CONFIG = {
    "version": VERSION,
    "risk_level": "medium",
    "interrupt_budget": 2,
    "auto_advance": False,
    "council_required": True,
    # When True, SPEC stage-gate fails if _spec_semantic_warnings() returns any hint.
    "spec_semantic_hints_strict": False,
    # JIT Evolution: enable/disable trace recording
    "jit_patch_enabled": True,
    # Whether to store a short excerpt of user prompt in trace (privacy opt-in)
    "trace_store_prompt_excerpt": False,
    # Whether to store bash command body in trace (privacy opt-in)
    "trace_store_bash_command_body": False,
    # Minimum live shadow observations before a patch can be promoted to project scope
    "patch_shadow_min_observations": 2,
    # CLARIFY: "full" = ledger + JSON artifacts (default); "notes_only" = closure only in clarification-notes.md
    "clarify_closure_mode": "full",
    # Coupling closure gate: off | warn | strict. Warn/strict only apply when project declares coupling_role_ids.
    "coupling_closure_gate_mode": "warn",
    # Enhancement layer: when True, use domain/scenario signals to require stronger coverage on selected axes.
    "clarify_signal_gate_enabled": True,
    # Enhancement layer: suggest / enforce deep-dive when high-risk signals coexist with ambiguous requirements.
    "clarify_deep_dive_enabled": True,
    # When True, missing deep-dive memo becomes a blocking CLARIFY gate error instead of a warning.
    "clarify_deep_dive_gate_strict": False,
}

CLARIFY_AXES: list[tuple[str, str, str]] = [
    ("StateAndTime", r"StateAndTime|行为与流程", "StateAndTime / 行为与流程"),
    ("ConstraintsAndConflict", r"ConstraintsAndConflict|规则与边界", "ConstraintsAndConflict / 规则与边界"),
    ("CostAndCapacity", r"CostAndCapacity|规模与代价", "CostAndCapacity / 规模与代价"),
    ("CrossSurfaceConsistency", r"CrossSurfaceConsistency|多入口|多阶段一致性", "CrossSurfaceConsistency / 多入口"),
    ("OperationsAndRecovery", r"OperationsAndRecovery|运行与维护", "OperationsAndRecovery / 运行与维护"),
    ("SecurityAndIsolation", r"SecurityAndIsolation|权限与隔离", "SecurityAndIsolation / 权限与隔离"),
]

CLARIFY_SIGNAL_RULES: list[dict] = [
    {
        "id": "state-flow",
        "regex": r"(?i)state\s*transition|workflow|phase|stage|order|sequence|retry|replay|reinsert|re-entry|reentry|idempot|delete-to-update|行为|流程|顺序|状态|重试|重复|阶段",
        "axes": ["StateAndTime"],
        "summary": "state / workflow / replay semantics",
    },
    {
        "id": "constraints-identity",
        "regex": r"(?i)primary\s*key|no-primary-key|no primary key|unique|uniqueness|locator|predicate|multi-match|ambiguous|constraint|conflict|identity reconstruction|唯一|主键|约束|冲突|匹配多个|匹配零个",
        "axes": ["ConstraintsAndConflict"],
        "summary": "identity / uniqueness / constraint conflict",
    },
    {
        "id": "cost-capacity",
        "regex": r"(?i)scale|capacity|performance|fan-?out|amplification|billable|resource|latency|吞吐|性能|容量|成本|放大",
        "axes": ["CostAndCapacity"],
        "summary": "scale / cost / amplification",
    },
    {
        "id": "cross-surface-contract",
        "regex": r"(?i)cross-stage|cross stage|cross-surface|ui|backend|api|schema|migration|downstream|contract|interface|entry|coherence|shared|同步|多入口|跨阶段|契约|接口|下游|一致性",
        "axes": ["CrossSurfaceConsistency"],
        "summary": "cross-surface / contract coherence",
    },
    {
        "id": "ops-recovery",
        "regex": r"(?i)recovery|rollback|repair|partial\s*failure|runtime|operat|degrade|restore|ops|恢复|回滚|补偿|失败|运维|恢复 active",
        "axes": ["OperationsAndRecovery"],
        "summary": "failure / recovery / runtime operations",
    },
    {
        "id": "security-isolation",
        "regex": r"(?i)auth|authorization|permission|tenant|credential|secret|sensitive|security|isolation|权限|鉴权|认证|隔离|敏感",
        "axes": ["SecurityAndIsolation"],
        "summary": "auth / isolation / security boundary",
    },
]


# ---------------------------------------------------------------------------
# JIT Evolution — Trace & Patch helpers
# ---------------------------------------------------------------------------

def _trace_dir_for_epic(h: Path, epic_id: str) -> Path:
    return h / "logs" / "epics" / epic_id

def _session_log_dir(h: Path) -> Path:
    return h / "logs" / "sessions"

def _patch_candidates_dir(h: Path) -> Path:
    return h / "memory" / "candidate-patches"

def _active_epic_rules_dir(h: Path, epic_id: str) -> Path:
    return h / "rules" / "epic-local" / epic_id

def _project_rules_dir(h: Path) -> Path:
    return h / "rules" / "project-active"

def _rules_index_path(h: Path) -> Path:
    return h / "rules" / "index.json"

def _incidents_index_path(h: Path, epic_id: str) -> Path:
    return _trace_dir_for_epic(h, epic_id) / "incident-index.json"


def _trace_field_empty(val) -> bool:
    """True for missing trace fields: None, JSON null, or blank string (not string 'None')."""
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


def _normalize_trace_event_write(event: dict) -> dict:
    """Normalize on append/write: fill ts with current time when missing."""
    if not isinstance(event, dict):
        return event
    out = dict(event)
    if _trace_field_empty(out.get("ts")):
        out["ts"] = now_iso()
    if _trace_field_empty(out.get("status")):
        et = str(out.get("event_type") or "").strip()
        if et.endswith("_failed"):
            out["status"] = "blocked"
        else:
            out["status"] = "ok"
    if _trace_field_empty(out.get("event_id")):
        basis = {k: v for k, v in out.items() if k != "event_id"}
        canonical = json.dumps(basis, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        out["event_id"] = f"evt_{digest}"
    return out


def _normalize_trace_event_read(event: dict, line_index: int) -> dict:
    """Normalize when loading trace from disk: stable ts/event_id (no wall-clock ts for legacy rows)."""
    if not isinstance(event, dict):
        return event
    out = dict(event)
    if _trace_field_empty(out.get("ts")):
        out["ts"] = f"legacy_ts:{line_index}"
    if _trace_field_empty(out.get("status")):
        et = str(out.get("event_type") or "").strip()
        if et.endswith("_failed"):
            out["status"] = "blocked"
        else:
            out["status"] = "ok"
    if _trace_field_empty(out.get("event_id")):
        basis = {k: v for k, v in out.items() if k != "event_id"}
        canonical = json.dumps(basis, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        out["event_id"] = f"evt_{digest}"
    return out


def _compact_audit_trace_event(e: dict | None) -> dict | None:
    if not e:
        return None
    return {
        "event_type": e.get("event_type"),
        "ts": e.get("ts"),
        "stage": e.get("stage"),
        "status": e.get("status"),
        "summary": e.get("summary"),
        "event_id": e.get("event_id"),
    }


def _pick_latest_gate_event(events: list[dict]) -> dict | None:
    """Latest gate-related event in trace order (checked vs pass/fail does not override chronology)."""
    last: dict | None = None
    for e in events:
        et = str(e.get("event_type") or "").strip()
        if et in ("stage_gate_passed", "stage_gate_failed", "stage_gate_checked"):
            last = e
    return last


def _pick_latest_guard_event(events: list[dict]) -> dict | None:
    """Latest guard-related event in trace order."""
    last: dict | None = None
    for e in events:
        et = str(e.get("event_type") or "").strip()
        if et in ("guard_passed", "guard_failed", "guard_checked"):
            last = e
    return last


def _task_summary_from_events(events: list[dict]) -> dict:
    task_latest: dict[str, str] = {}
    last_change: dict | None = None
    for e in events:
        if str(e.get("event_type", "")).strip() != "task_status_changed":
            continue
        payload = e.get("payload", {}) if isinstance(e.get("payload"), dict) else {}
        tid = str(payload.get("task_id") or e.get("task_id") or "").strip()
        nst = str(payload.get("new_status") or "").strip()
        if not tid or not nst:
            continue
        task_latest[tid] = nst
        last_change = {
            "task_id": tid,
            "new_status": nst,
            "ts": e.get("ts"),
            "event_type": e.get("event_type"),
            "summary": e.get("summary"),
        }
    by_status = {s: 0 for s in TASK_STATUSES}
    for nst in task_latest.values():
        if nst in by_status:
            by_status[nst] += 1
    return {"by_status": by_status, "latest_change": last_change}


def append_trace_event(h: Path, event: dict) -> None:
    """Append a structured trace event to the epic's execution-trace.jsonl.

    Silently no-ops when jit_patch_enabled is False or no epic_id supplied.
    """
    cfg = merged_harness_config(h)
    if not cfg.get("jit_patch_enabled", True):
        return
    epic_id = event.get("epic_id")
    if not epic_id:
        return
    event = _normalize_trace_event_write(event)
    trace_dir = _trace_dir_for_epic(h, epic_id)
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "execution-trace.jsonl"
    line = json.dumps(event, ensure_ascii=False)
    with trace_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        _write_execution_summary(h, epic_id)
    except SystemExit:
        pass


def _make_trace_event(
    epic_id: str,
    event_type: str,
    *,
    stage: str = "",
    source: str = "harnessctl",
    actor: str = "harnessctl",
    status: str = "ok",
    task_id: str = "",
    patch_id: str = "",
    command_name: str = "",
    summary: str = "",
    payload: dict = None,
    artifact_paths: list = None,
) -> dict:
    return _normalize_trace_event_write({
        "ts": now_iso(),
        "epic_id": epic_id,
        "stage": stage,
        "source": source,
        "actor": actor,
        "event_type": event_type,
        "status": status,
        "task_id": task_id or "",
        "patch_id": patch_id or "",
        "command_name": command_name,
        "summary": summary,
        "payload": payload or {},
        "artifact_paths": artifact_paths or [],
    })


def _load_trace_events(h: Path, epic_id: str) -> list[dict]:
    """Load trace events for an epic, skipping malformed lines."""
    trace_path = _trace_dir_for_epic(h, epic_id) / "execution-trace.jsonl"
    if not trace_path.exists():
        return []
    events: list[dict] = []
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _load_bundle_optional(h: Path, epic_id: str) -> dict | None:
    """Load decision-bundle.json if present."""
    bundle_path = h / "features" / epic_id / "decision-bundle.json"
    if not bundle_path.exists():
        return None
    try:
        return load_json(bundle_path)
    except SystemExit:
        return None


def _normalize_pending_decision(decision: dict, fallback_id: str) -> dict:
    """Normalize a pending decision into the state.json shape."""
    risk_if_wrong = str(decision.get("risk_if_wrong") or decision.get("severity") or "high").lower()
    if risk_if_wrong not in ("critical", "high", "medium", "low"):
        risk_if_wrong = "high"
    severity = str(decision.get("severity") or risk_if_wrong).lower()
    if severity not in ("critical", "high", "medium", "low"):
        severity = risk_if_wrong
    return {
        "id": str(decision.get("id") or fallback_id),
        "question": str(decision.get("question", "")).strip(),
        "category": str(decision.get("category", "must_confirm")).strip() or "must_confirm",
        "severity": severity,
        "risk_if_wrong": risk_if_wrong,
        "status": str(decision.get("status", "pending")).strip() or "pending",
        "source_ref": str(decision.get("source_ref", "")).strip(),
        "source_artifact": str(decision.get("source_artifact", "decision-bundle.json")).strip(),
        "why_now": str(decision.get("why_now", "")).strip(),
        "options": decision.get("options", []) if isinstance(decision.get("options", []), list) else [],
        "default_action": str(decision.get("proposed_default", "")).strip(),
    }


def _pending_decisions_from_bundle(bundle: dict | None) -> list[dict]:
    """Return normalized pending must_confirm items from a decision bundle."""
    if not isinstance(bundle, dict):
        return []
    decisions = bundle.get("decisions")
    if not isinstance(decisions, list):
        return []
    pending: list[dict] = []
    for idx, decision in enumerate(decisions, start=1):
        if not isinstance(decision, dict):
            continue
        if str(decision.get("category", "")).strip() != "must_confirm":
            continue
        if str(decision.get("status", "pending")).strip() != "pending":
            continue
        pending.append(_normalize_pending_decision(decision, f"DEC-{idx:03d}"))
    return pending


def _effective_pending_decisions(h: Path, state: dict) -> list[dict]:
    """Use state pending_decisions first, then fall back to decision-bundle.json."""
    pending = state.get("pending_decisions", [])
    if isinstance(pending, list) and pending:
        return pending
    epic_id = str(state.get("epic_id", "")).strip()
    if not epic_id:
        return []
    return _pending_decisions_from_bundle(_load_bundle_optional(h, epic_id))


def _write_execution_summary(h: Path, epic_id: str) -> dict:
    """Derive a concise execution summary from trace + state."""
    trace_dir = _trace_dir_for_epic(h, epic_id)
    trace_dir.mkdir(parents=True, exist_ok=True)
    raw_trace = _load_trace_events(h, epic_id)
    events = [
        _normalize_trace_event_read(e, idx) if isinstance(e, dict) else e
        for idx, e in enumerate(raw_trace)
    ]
    latest_run_id = ""
    latest_run_start = -1
    for idx, event in enumerate(events):
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        run_id = str(payload.get("run_id", "")).strip()
        if str(event.get("event_type", "")).strip() == "clarify_run_started" and run_id:
            latest_run_id = run_id
            latest_run_start = idx
    if latest_run_start >= 0:
        relevant_events = events[latest_run_start:]
    else:
        relevant_events = events

    latest_run_id = ""
    steps_completed: list[str] = []
    steps_seen: set[str] = set()
    parallel_waves_completed = 0
    repo_fanout_waves_completed = 0
    legacy_fanout_used = False
    legacy_fanout_children_count = 0
    repo_scope_wave_payloads: list[dict] = []
    decision_packet_generated = False
    pending_decisions_synced = False
    latest_pause_reason = ""

    for event in relevant_events:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        run_id = str(payload.get("run_id", "")).strip()
        if latest_run_id and run_id and run_id != latest_run_id:
            continue
        if run_id:
            latest_run_id = run_id
        event_type = str(event.get("event_type", "")).strip()
        if event_type == "step_completed":
            step_name = (
                str(payload.get("step", "")).strip()
                or str(payload.get("agent_role", "")).strip()
                or str(event.get("actor", "")).strip()
            )
            if step_name and step_name not in steps_seen:
                steps_seen.add(step_name)
                steps_completed.append(step_name)
            if payload.get("fanout_used") or str(payload.get("execution_mode", "")).strip() == "fan_out_team":
                legacy_fanout_used = True
            try:
                legacy_fanout_children_count = max(
                    legacy_fanout_children_count,
                    int(payload.get("fanout_children_count", 0) or 0),
                )
            except (TypeError, ValueError):
                pass
        elif event_type == "parallel_wave_completed":
            parallel_waves_completed += 1
            if str(payload.get("scope_type", "")).strip() == "repo":
                repo_fanout_waves_completed += 1
                repo_scope_wave_payloads.append(payload)
        elif event_type == "decision_packet_generated":
            decision_packet_generated = True
        elif event_type == "pending_decisions_synced":
            pending_decisions_synced = True
        elif event_type == "guard_failed":
            issues = payload.get("issues", [])
            if isinstance(issues, list) and issues:
                latest_pause_reason = "; ".join(str(issue) for issue in issues[:3])
        elif event_type == "next_action_evaluated":
            if str(payload.get("next_action", "")).strip() == "wait_user" and payload.get("has_pending_confirms"):
                latest_pause_reason = "waiting_on_pending_decisions"

    try:
        state = load_state(h, epic_id)
    except SystemExit:
        state = {}
    pending_decisions = _effective_pending_decisions(h, state)
    bundle = _load_bundle_optional(h, epic_id)
    bundle_pending = _pending_decisions_from_bundle(bundle)
    packet_path = h / "features" / epic_id / "decision-packet.json"
    budget = state.get("interrupt_budget", {}) if isinstance(state, dict) else {}
    remaining = budget.get("remaining", budget.get("total", 0) - budget.get("consumed", 0))
    if packet_path.exists():
        decision_packet_generated = True
    if bundle is not None and isinstance(state.get("pending_decisions", []), list) and state.get("pending_decisions", []) == bundle_pending:
        pending_decisions_synced = True
    if pending_decisions and int(remaining or 0) > 0 and not latest_pause_reason:
        latest_pause_reason = "waiting_on_pending_decisions"

    if not latest_run_id:
        features_dir = h / "features" / epic_id
        artifact_step_hints = (
            ("domain-frame.json", "domain-scout"),
            ("requirements-draft.md", "requirement-analyst"),
            ("impact-scan.md", "impact-analyst"),
            ("challenge-report.md", "challenger"),
            ("generated-scenarios.json", "scenario-expander"),
            ("scenario-coverage.json", "semantic-reconciliation"),
            ("surface-routing.json", "surface-routing"),
            ("clarification-notes.md", "clarification-notes"),
        )
        for artifact_name, step_name in artifact_step_hints:
            if _artifact_step_is_observable(features_dir / artifact_name) and step_name not in steps_seen:
                steps_seen.add(step_name)
                steps_completed.append(step_name)

    gate_ev = _pick_latest_gate_event(events)
    guard_ev = _pick_latest_guard_event(events)
    task_summary = _task_summary_from_events(events)

    repo_wave_children_count = 0
    for wp in repo_scope_wave_payloads:
        try:
            fc = int(wp.get("fanout_children_count", 0) or 0)
        except (TypeError, ValueError):
            fc = 0
        rids = wp.get("repo_ids")
        n_repo = len(rids) if isinstance(rids, list) else 0
        wave_n = fc if fc > 0 else n_repo
        repo_wave_children_count = max(repo_wave_children_count, wave_n)

    artifact_fanout_used = False
    artifact_fanout_children_count = 0
    if _workspace_mode(h) == "multi-repo":
        cri_path = h / "features" / epic_id / "cross-repo-impact-index.json"
        if cri_path.exists():
            try:
                cri_obj = json.loads(cri_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cri_obj = None
            if isinstance(cri_obj, dict):
                fd = cri_obj.get("fanout_decision")
                if isinstance(fd, dict) and str(fd.get("mode", "")).strip() == "repo_wave":
                    artifact_fanout_used = True
                    rids = fd.get("repo_ids")
                    artifact_fanout_children_count = len(rids) if isinstance(rids, list) else 0

    fanout_used = bool(repo_scope_wave_payloads) or artifact_fanout_used or legacy_fanout_used
    fanout_children_count = max(
        legacy_fanout_children_count,
        repo_wave_children_count,
        artifact_fanout_children_count,
    )

    summary = {
        "epic_id": epic_id,
        "current_stage": state.get("current_stage", "") if isinstance(state, dict) else "",
        "latest_run_id": latest_run_id,
        "steps_completed": steps_completed,
        "parallel_waves_completed": parallel_waves_completed,
        "repo_fanout_waves_completed": repo_fanout_waves_completed,
        "fanout_used": fanout_used,
        "fanout_children_count": fanout_children_count,
        "decision_packet_generated": decision_packet_generated,
        "pending_decisions_synced": pending_decisions_synced,
        "pending_decisions_count": len(pending_decisions),
        "latest_pause_reason": latest_pause_reason,
        "latest_gate": _compact_audit_trace_event(gate_ev),
        "latest_guard": _compact_audit_trace_event(guard_ev),
        "task_summary": task_summary,
        "updated_at": now_iso(),
    }
    atomic_write_json(trace_dir / "execution-summary.json", summary)
    return summary


def _sync_pending_decisions_from_bundle(
    h: Path,
    epic_id: str,
    *,
    emit_trace: bool = False,
    run_id: str = "",
) -> list[dict]:
    """Synchronize pending must_confirm decisions into state.json."""
    try:
        state = load_state(h, epic_id)
    except SystemExit:
        return []
    pending = _pending_decisions_from_bundle(_load_bundle_optional(h, epic_id))
    updated_state = dict(state)
    updated_state["pending_decisions"] = pending
    updated_state["updated_at"] = now_iso()
    save_state(h, updated_state)
    if emit_trace:
        append_trace_event(
            h,
            _make_trace_event(
                epic_id,
                "pending_decisions_synced",
                stage=updated_state.get("current_stage", ""),
                source="decision-bundle",
                actor="decision-bundle",
                summary=f"Synced {len(pending)} pending decision(s) into state",
                payload={"run_id": run_id, "pending_count": len(pending)},
                artifact_paths=[
                    str(h / "features" / epic_id / "state.json"),
                    str(h / "features" / epic_id / "decision-bundle.json"),
                ],
            ),
        )
    else:
        _write_execution_summary(h, epic_id)
    return pending


def _load_active_rules(h: Path, epic_id: str = "", stage: str = "") -> list[dict]:
    """Return all active rule patches relevant to the given epic/stage."""
    rules: list[dict] = []

    def _read_patch_meta(patch_dir: Path) -> dict | None:
        meta_path = patch_dir / "meta.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    proj_dir = _project_rules_dir(h)
    if proj_dir.exists():
        for md_file in sorted(proj_dir.glob("*.md")):
            rules.append({"scope": "project-active", "path": str(md_file), "stages": []})

    if epic_id:
        epic_dir = _active_epic_rules_dir(h, epic_id)
        if epic_dir.exists():
            for md_file in sorted(epic_dir.glob("*.md")):
                patch_id = md_file.stem
                meta = _read_patch_meta(_patch_candidates_dir(h) / patch_id)
                stages = meta.get("stages", []) if meta else []
                if not stage or not stages or stage in stages:
                    rules.append({"scope": "epic-local", "path": str(md_file), "stages": stages})

    return rules


def _rules_summary_for_context(h: Path, epic_id: str = "", stage: str = "") -> str:
    """Return a compact text block of active rules for additionalContext injection."""
    rules = _load_active_rules(h, epic_id=epic_id, stage=stage)
    if not rules:
        return ""

    summary_lines = ["[Stage-Harness 激活规则]"]
    for r in rules:
        try:
            text = Path(r["path"]).read_text(encoding="utf-8").strip()
            # Skip frontmatter, take first heading after it
            file_lines = text.splitlines()
            in_fm = False
            first_line = ""
            for i, line in enumerate(file_lines):
                if i == 0 and line.strip() == "---":
                    in_fm = True
                    continue
                if in_fm and line.strip() == "---":
                    in_fm = False
                    continue
                if in_fm:
                    continue
                stripped = line.strip()
                if stripped.startswith("#"):
                    first_line = stripped.lstrip("#").strip()
                    break
                if stripped:
                    first_line = stripped
                    break
            summary_lines.append(f"  [{r['scope']}] {first_line}")
        except OSError:
            pass
    return "\n".join(summary_lines)


def merged_harness_config(h: Path) -> dict:
    """Merge `.harness/config.json` over DEFAULT_CONFIG; tolerate missing/invalid JSON."""
    cfg = dict(DEFAULT_CONFIG)
    path = h / CONFIG_FILE
    if not path.exists():
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except (json.JSONDecodeError, OSError):
        pass
    return cfg


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    """Convert text to lowercase slug with hyphens."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text[:40]


def atomic_write(path: Path, content: str) -> None:
    """Write content atomically via a .tmp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


def atomic_write_json(path: Path, data: dict) -> None:
    """Serialize data as JSON and write atomically."""
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_json(path: Path) -> dict:
    """Load and parse a JSON file, raising SystemExit on error."""
    if not path.exists():
        err(f"File not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        err(f"Invalid JSON in {path}: {exc}")


def err(message: str) -> None:
    """Print error to stderr and exit with code 1."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def out_json(data) -> None:
    """Print data as JSON to stdout."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _git(project_root: Path, *git_args: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run git in project_root; return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git", *git_args],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 99, "", str(exc)


def find_harness_root(start: Path = None) -> Path:
    """Find .harness in the current directory, or within the current git root."""
    current = (start or Path.cwd()).resolve()
    git_root = _find_git_toplevel(current)
    search_roots = [current]
    if git_root is not None:
        for parent in current.parents:
            search_roots.append(parent)
            if parent == git_root:
                break

    for directory in search_roots:
        if (directory / HARNESS_DIR).is_dir():
            return directory
    if git_root is not None:
        return git_root
    return current


def _find_git_toplevel(start: Path = None) -> Path | None:
    """Return git toplevel for start, or None when outside a git worktree."""
    current = (start or Path.cwd()).resolve()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(current),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    root = proc.stdout.strip()
    if proc.returncode != 0 or not root:
        return None
    return Path(root).resolve()


def _dir_is_writable(path: Path) -> bool:
    """Best-effort writability check for a directory."""
    try:
        return path.is_dir() and os.access(path, os.W_OK | os.X_OK)
    except OSError:
        return False


def _is_permission_like_os_error(exc: OSError) -> bool:
    """Return True only for permission or read-only filesystem failures."""
    return getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM, errno.EROFS}


def find_bootstrap_root(start: Path = None) -> Path:
    """Return current .harness root, else git root, else cwd for bootstrapping."""
    current = (start or Path.cwd()).resolve()
    git_root = _find_git_toplevel(current)
    search_roots = [current]
    if git_root is not None:
        for parent in current.parents:
            search_roots.append(parent)
            if parent == git_root:
                break

    for directory in search_roots:
        if (directory / HARNESS_DIR).is_dir():
            return directory
    if git_root is not None:
        return git_root
    return current


def harness_path(project_root: Path = None) -> Path:
    """Return the .harness/ path for the given (or found) project root."""
    root = project_root or find_harness_root()
    return root / HARNESS_DIR


def _metrics_dir(h: Path) -> Path:
    return h / "metrics"


def _metrics_event_log_path(h: Path) -> Path:
    return _metrics_dir(h) / "scan-roi.jsonl"


def _epic_metrics_path(h: Path, epic_id: str) -> Path:
    return h / "features" / epic_id / "scan-metrics.json"


def _default_epic_metrics(epic_id: str) -> dict:
    return {
        "version": VERSION,
        "epic_id": epic_id,
        "roi_metrics": {},
        "acceptance_checks": {},
        "updated_at": now_iso(),
    }


def load_epic_metrics(h: Path, epic_id: str) -> dict:
    path = _epic_metrics_path(h, epic_id)
    if not path.exists():
        return _default_epic_metrics(epic_id)
    data = load_json(path)
    if not isinstance(data, dict):
        err(f"Invalid metrics file: {path}")
    return data


def save_epic_metrics(h: Path, epic_id: str, data: dict) -> None:
    payload = dict(data)
    payload["version"] = VERSION
    payload["epic_id"] = epic_id
    payload["updated_at"] = now_iso()
    atomic_write_json(_epic_metrics_path(h, epic_id), payload)


def append_metrics_event(h: Path, event: dict) -> None:
    path = _metrics_event_log_path(h)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _parse_metric_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _repo_worktrees_from_epic(epic: dict) -> dict:
    repo_worktrees = epic.get("repo_worktrees", {})
    return repo_worktrees if isinstance(repo_worktrees, dict) else {}


def _codemap_template_path() -> Path:
    return Path(__file__).parent.parent / "templates" / "codemap-module.md"


# ---------------------------------------------------------------------------
# Epic helpers
# ---------------------------------------------------------------------------

def next_epic_number(h: Path) -> int:
    """Return the next available epic sequential number."""
    epics_dir = h / "epics"
    if not epics_dir.exists():
        return 1
    existing = list(epics_dir.glob("sh-*.json"))
    if not existing:
        return 1
    numbers = []
    for f in existing:
        m = re.match(r"sh-(\d+)-", f.stem)
        if m:
            numbers.append(int(m.group(1)))
    return max(numbers, default=0) + 1


def make_epic_id(n: int, title: str) -> str:
    """Create an epic ID like sh-1-feature-name."""
    return f"sh-{n}-{slugify(title)}"


def load_epic(h: Path, epic_id: str) -> dict:
    """Load an epic JSON file."""
    path = h / "epics" / f"{epic_id}.json"
    if not path.exists():
        err(f"Epic not found: {epic_id}")
    return load_json(path)


def save_epic(h: Path, epic: dict) -> None:
    """Save an epic JSON file atomically."""
    atomic_write_json(h / "epics" / f"{epic['id']}.json", epic)


def load_state(h: Path, epic_id: str) -> dict:
    """Load state JSON for an epic."""
    path = h / "features" / epic_id / "state.json"
    if not path.exists():
        err(f"State not found for epic: {epic_id}")
    return load_json(path)


def save_state(h: Path, state: dict) -> None:
    """Save state JSON atomically."""
    epic_id = state["epic_id"]
    atomic_write_json(h / "features" / epic_id / "state.json", state)


# ---------------------------------------------------------------------------
# Task helpers
# ---------------------------------------------------------------------------

def next_task_number(h: Path, epic_id: str) -> int:
    """Return next task number for an epic."""
    tasks_dir = h / "tasks"
    if not tasks_dir.exists():
        return 1
    prefix = f"{epic_id}."
    existing = [f for f in tasks_dir.glob(f"{prefix}*.json")]
    if not existing:
        return 1
    numbers = []
    for f in existing:
        stem = f.stem[len(prefix):]
        if stem.isdigit():
            numbers.append(int(stem))
    return max(numbers, default=0) + 1


def make_task_id(epic_id: str, n: int) -> str:
    """Create task id like sh-1.2."""
    # Extract numeric prefix from epic_id
    m = re.match(r"sh-(\d+)-", epic_id)
    if m:
        return f"sh-{m.group(1)}.{n}"
    return f"{epic_id}.{n}"


def load_task(h: Path, task_id: str) -> tuple:
    """Load a task by id. Returns (task_dict, path)."""
    tasks_dir = h / "tasks"
    # task_id is like sh-1.2; file is stored as {epic_id}.{n}.json
    # We need to reconstruct the filename: epic_id = sh-N-slug, n = last number
    # Search all task files for matching id
    if tasks_dir.exists():
        for f in tasks_dir.glob("*.json"):
            try:
                data = load_json(f)
                if data.get("id") == task_id:
                    return data, f
            except SystemExit:
                continue
    err(f"Task not found: {task_id}")


def normalize_task_status(status: str) -> str:
    """Normalize legacy or derived task status values to canonical ones."""
    return TASK_STATUS_ALIASES.get(status, status)


def task_status_matches(status: str, expected: str) -> bool:
    """Return True if a task status matches an expected status semantically."""
    return normalize_task_status(status) == normalize_task_status(expected)


def iter_task_files(h: Path, epic_id: str):
    """Yield task files for an epic."""
    tasks_dir = h / "tasks"
    if not tasks_dir.exists():
        return
    yield from tasks_dir.glob(f"{epic_id}.*.json")


def receipt_dirs_for_epic(h: Path, epic_id: str) -> list[Path]:
    """Return all supported receipt directories for an epic."""
    features_dir = h / "features" / epic_id
    return [
        features_dir / "receipts",
        features_dir / "runtime-receipts",
        features_dir / "runs",
    ]


def canonical_receipts_dir(h: Path, epic_id: str) -> Path:
    """Return the canonical receipt directory for new writes."""
    return h / "features" / epic_id / "receipts"


def spec_path_for_epic(h: Path, epic_id: str) -> Path:
    """Return the canonical spec path for an epic."""
    return h / "specs" / f"{epic_id}.md"


def council_verdict_path(h: Path, epic_id: str, council_type: str) -> Path:
    """Return the verdict file path for a council."""
    return h / "features" / epic_id / "councils" / f"verdict-{council_type}.json"


def _spec_has_acceptance_criteria(spec_path: Path) -> bool:
    """Detect whether a spec includes an acceptance criteria section."""
    if not spec_path.exists():
        return False
    text = spec_path.read_text(encoding="utf-8")
    patterns = [
        r"(?im)^#{1,6}\s+acceptance criteria\b",
        r"(?im)^#{1,6}\s+验收标准\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _clarify_semantic_warnings(features_dir: Path) -> list[str]:
    """Require generated scenarios to be structurally covered in CLARIFY artifacts."""
    prose_parts: list[str] = []
    for name in (
        "requirements-draft.md",
        "challenge-report.md",
        "clarification-notes.md",
    ):
        p = features_dir / name
        if p.exists():
            prose_parts.append(p.read_text(encoding="utf-8", errors="replace"))
    prose = "\n".join(prose_parts)

    gen_path = features_dir / "generated-scenarios.json"
    coverage_path = features_dir / "scenario-coverage.json"
    if not gen_path.exists():
        return []
    try:
        generated = json.loads(gen_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["generated-scenarios.json is invalid JSON."]
    scenarios = generated.get("scenarios") if isinstance(generated, dict) else None
    if not isinstance(scenarios, list):
        return ["generated-scenarios.json must contain a scenarios array."]
    relevant_ids: list[str] = []
    for item in scenarios:
        if (
            isinstance(item, dict)
            and str(item.get("confidence", "")).lower() in ("high", "medium")
            and str(item.get("scenario_id", "")).strip()
        ):
            relevant_ids.append(str(item["scenario_id"]).strip())
    if not relevant_ids:
        return []
    if not coverage_path.exists():
        return [
            "存在高/中置信度 `SCN-xxx` 条目，但缺少 `scenario-coverage.json`：须显式记录每个场景的覆盖状态与映射去向。"
        ]
    try:
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["scenario-coverage.json is invalid JSON."]
    covered_items = coverage.get("scenarios") if isinstance(coverage, dict) else None
    if not isinstance(covered_items, list):
        return ["scenario-coverage.json must contain a scenarios array."]
    covered_map: dict[str, dict] = {}
    for item in covered_items:
        if isinstance(item, dict) and str(item.get("scenario_id", "")).strip():
            covered_map[str(item["scenario_id"]).strip()] = item

    closure_re = re.compile(
        r"(?i)traceability|追溯|语义归并|semantic\s*reconciliation|DEC-\d+|UNK-\d+|"
        r"must_confirm|决策包|decision[- ]bundle|mapped\s+to\s+(?:REQ|CHK|DEC|UNK)-\d+|"
        r"映射到\s*(?:REQ|CHK|DEC|UNK)-\d+"
    )
    missing_ids = [sid for sid in relevant_ids if sid not in covered_map]
    if missing_ids:
        return [
            "以下高/中置信度 `SCN-xxx` 条目尚未进入 `scenario-coverage.json`："
            + ", ".join(missing_ids)
        ]
    unresolved_ids: list[str] = []
    for sid in relevant_ids:
        item = covered_map[sid]
        status = str(item.get("status", "")).strip()
        mapped_to = item.get("mapped_to")
        mapped_ok = isinstance(mapped_to, list) and len(mapped_to) > 0
        if status not in ("covered", "needs_decision", "deferred", "dropped_invalid"):
            unresolved_ids.append(sid)
            continue
        if status != "dropped_invalid" and not mapped_ok:
            unresolved_ids.append(sid)
    if unresolved_ids:
        return [
            "以下 `SCN-xxx` 条目在 `scenario-coverage.json` 中缺少有效状态或映射去向："
            + ", ".join(unresolved_ids)
        ]
    if closure_re.search(prose):
        return []
    return [
        "已存在结构化场景覆盖文件，但澄清产物中未见对应的追溯矩阵、语义归并说明或 DEC/UNK 引用：请补充 prose 级闭合说明。"
    ]


def _clarify_notes_only_closure_errors(features_dir: Path) -> list[str]:
    """Validate clarification-notes.md for CLARIFY six-axis/closure structure."""
    errors: list[str] = []
    cn = features_dir / "clarification-notes.md"
    if not cn.exists():
        return [f"{cn}: missing (CLARIFY requires this file for six-axis/closure summary)"]
    if cn.is_file() and cn.stat().st_size == 0:
        return [f"{cn}: empty"]

    text = cn.read_text(encoding="utf-8", errors="replace")

    if not re.search(
        r"(?im)^#{1,4}\s*(?:domain\s*frame|领域框架|需求上下文)\b",
        text,
    ):
        errors.append(
            f"{cn.name}: add heading «## Domain Frame», «## 领域框架» or «## 需求上下文» "
            "(context must live in this file when JSON ledger is absent)"
        )

    minimal_heading = re.search(
        r"(?im)^#{1,4}\s*(?:极简澄清绕行|极简澄清模式|minimal\s*clarify)\b",
        text,
    )
    minimal_signal = re.search(r"(?i)极简澄清绕行|minimal\s*clarify\s*bypass", text) and re.search(
        r"(?i)not_applicable|全局[^\n]{0,40}不适用|不适用[^\n]{0,40}全局",
        text,
    )
    minimal_ok = bool(minimal_heading or minimal_signal)

    axis_section = re.search(
        r"(?im)^#{1,4}\s*(?:六轴澄清覆盖|six[- ]axis\s*clarification|澄清必答覆盖)\b",
        text,
    )
    if not minimal_ok and not axis_section:
        errors.append(
            f"{cn.name}: add «## 六轴澄清覆盖» (per-axis covered|not_applicable|unknown) "
            "OR «## 极简澄清绕行» with global not_applicable + one-line reason"
        )

    tri_re = re.compile(
        r"(?i)\b(covered|not_applicable|not\s+applicable|unknown|已覆盖|不适用|尚不清楚)\b"
    )
    # Only scan per-axis lines when the doc claims a six-axis section (avoid duplicate noise).
    if not minimal_ok and axis_section:
        axis_specs: list[tuple[str, str]] = [
            (r"StateAndTime|行为与流程", "StateAndTime / 行为与流程"),
            (r"ConstraintsAndConflict|规则与边界", "ConstraintsAndConflict / 规则与边界"),
            (r"CostAndCapacity|规模与代价", "CostAndCapacity / 规模与代价"),
            (r"CrossSurfaceConsistency|多入口|多阶段一致性", "CrossSurfaceConsistency / 多入口"),
            (r"OperationsAndRecovery|运行与维护", "OperationsAndRecovery / 运行与维护"),
            (r"SecurityAndIsolation|权限与隔离", "SecurityAndIsolation / 权限与隔离"),
        ]
        for pattern, label in axis_specs:
            m = re.search(pattern, text)
            if not m:
                errors.append(f"{cn.name}: six-axis missing row for «{label}»")
                continue
            start = max(0, m.start() - 120)
            chunk = text[start : m.end() + 500]
            if not tri_re.search(chunk):
                errors.append(
                    f"{cn.name}: near «{label}» state must be covered|not_applicable|unknown (or 已覆盖/不适用/尚不清楚)"
                )

    closure_heading = re.search(
        r"(?im)^#{1,4}\s*(?:unknowns?\s*与\s*待确认|待确认决策|决策闭环|unknown\s*closure|closures?)\b",
        text,
    )
    closure_inline = re.search(
        r"(?i)\b(UNK-\d+|DEC-\d+|must_confirm)\b",
        text,
    )
    closure_none = re.search(
        r"(?i)无待确认|无\s*must_confirm|无\s*unknown\s*项|closure:\s*none|本轮\s*无\s*待确认",
        text,
    )
    if not closure_heading and not closure_inline and not closure_none:
        errors.append(
            f"{cn.name}: add «## Unknowns 与待确认决策» (or UNK-/DEC-/must_confirm list) "
            "or state «无待确认»"
        )

    return errors


def _clarify_minimal_mode_and_axis_states(text: str) -> tuple[bool, bool, dict[str, str]]:
    """Return (minimal_ok, axis_section_present, axis_states)."""
    minimal_heading = re.search(
        r"(?im)^#{1,4}\s*(?:极简澄清绕行|极简澄清模式|minimal\s*clarify)\b",
        text,
    )
    minimal_signal = re.search(r"(?i)极简澄清绕行|minimal\s*clarify\s*bypass", text) and re.search(
        r"(?i)not_applicable|全局[^\n]{0,40}不适用|不适用[^\n]{0,40}全局",
        text,
    )
    minimal_ok = bool(minimal_heading or minimal_signal)
    axis_section = bool(
        re.search(
            r"(?im)^#{1,4}\s*(?:六轴澄清覆盖|six[- ]axis\s*clarification|澄清必答覆盖)\b",
            text,
        )
    )
    axis_states: dict[str, str] = {}
    not_applicable_re = re.compile(r"(?i)\b(not_applicable|not\s+applicable|不适用)\b")
    unknown_re = re.compile(r"(?i)\b(unknown|尚不清楚)\b")
    covered_re = re.compile(r"(?i)\b(covered|已覆盖)\b")
    for axis_id, axis_pattern, _label in CLARIFY_AXES:
        m = re.search(axis_pattern, text)
        if not m:
            axis_states[axis_id] = ""
            continue
        chunk = text[max(0, m.start() - 120): m.end() + 500]
        state = ""
        if not_applicable_re.search(chunk):
            state = "not_applicable"
        elif unknown_re.search(chunk):
            state = "unknown"
        elif covered_re.search(chunk):
            state = "covered"
        axis_states[axis_id] = state
    return minimal_ok, axis_section, axis_states


def _iter_high_medium_signal_texts(features_dir: Path) -> list[dict]:
    """Collect high/medium confidence signal texts from domain-frame and generated scenarios."""
    rows: list[dict] = []
    df_path = features_dir / "domain-frame.json"
    if df_path.exists():
        try:
            data = json.loads(df_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            key_specs = [
                ("semantic_signals", ("signal", "rationale")),
                ("candidate_edge_cases", ("scenario", "rationale")),
                ("candidate_open_questions", ("question", "why_it_matters")),
                ("state_transition_scenarios", ("transition", "rationale")),
                ("constraint_conflicts", ("conflict", "rationale")),
            ]
            for key, fields in key_specs:
                items = data.get(key)
                if not isinstance(items, list):
                    continue
                for idx, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    confidence = str(item.get("confidence", "")).lower()
                    if confidence not in ("high", "medium"):
                        continue
                    parts = [str(item.get(f, "")).strip() for f in fields if str(item.get(f, "")).strip()]
                    if not parts:
                        continue
                    rows.append(
                        {
                            "source": f"{key}[{idx}]",
                            "kind": key,
                            "confidence": confidence,
                            "text": " | ".join(parts),
                            "item": item,
                        }
                    )
    gen_path = features_dir / "generated-scenarios.json"
    if gen_path.exists():
        try:
            data = json.loads(gen_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        scenarios = data.get("scenarios") if isinstance(data, dict) else None
        if isinstance(scenarios, list):
            for idx, item in enumerate(scenarios):
                if not isinstance(item, dict):
                    continue
                confidence = str(item.get("confidence", "")).lower()
                if confidence not in ("high", "medium"):
                    continue
                parts = [
                    str(item.get("pattern", "")).strip(),
                    str(item.get("scenario", "")).strip(),
                    str(item.get("why_it_matters", "")).strip(),
                    str(item.get("expected_followup", "")).strip(),
                ]
                parts = [p for p in parts if p]
                if not parts:
                    continue
                rows.append(
                    {
                        "source": str(item.get("scenario_id", "")).strip() or f"generated_scenarios[{idx}]",
                        "kind": "generated_scenarios",
                        "confidence": confidence,
                        "text": " | ".join(parts),
                        "item": item,
                    }
                )
    return rows


def _clarify_signal_gate_summary(features_dir: Path) -> dict:
    """Map semantic signals to axes that require explicit non-N/A treatment."""
    required_axes: dict[str, list[str]] = {}
    hits: list[dict] = []
    deep_dive_candidates: list[str] = []
    for row in _iter_high_medium_signal_texts(features_dir):
        txt = row["text"]
        row_axes: list[str] = []
        row_summaries: list[str] = []
        for rule in CLARIFY_SIGNAL_RULES:
            if re.search(rule["regex"], txt):
                row_axes.extend(rule["axes"])
                row_summaries.append(str(rule["summary"]))
        row_axes = sorted({x for x in row_axes})
        row_summaries = sorted({x for x in row_summaries})
        if not row_axes:
            continue
        for axis in row_axes:
            reasons = required_axes.setdefault(axis, [])
            reasons.extend(row_summaries)
        hits.append(
            {
                "source": row["source"],
                "kind": row["kind"],
                "confidence": row["confidence"],
                "axes": row_axes,
                "summaries": row_summaries,
            }
        )
        item = row.get("item", {})
        expected_followup = str(item.get("expected_followup", "")).upper()
        if (
            row["confidence"] == "high"
            and row["kind"] in ("candidate_open_questions", "constraint_conflicts", "generated_scenarios")
            and (expected_followup in ("DEC", "UNK", "REQ") or row["kind"] != "generated_scenarios")
        ):
            desc = str(item.get("question") or item.get("conflict") or item.get("scenario") or txt).strip()
            if desc:
                deep_dive_candidates.append(desc)
    for axis, reasons in required_axes.items():
        required_axes[axis] = sorted({r for r in reasons})
    deep_dive_candidates = sorted({x for x in deep_dive_candidates})[:8]
    return {
        "required_axes": required_axes,
        "hits": hits,
        "deep_dive_candidates": deep_dive_candidates,
    }


def _clarify_signal_gate_errors(features_dir: Path) -> list[str]:
    """Signal-driven CLARIFY gate: only strengthen axes when high/medium signals justify it."""
    summary = _clarify_signal_gate_summary(features_dir)
    required_axes = summary["required_axes"]
    if not required_axes:
        return []
    cn = features_dir / "clarification-notes.md"
    if not cn.exists() or (cn.is_file() and cn.stat().st_size == 0):
        return []
    text = cn.read_text(encoding="utf-8", errors="replace")
    minimal_ok, axis_section, axis_states = _clarify_minimal_mode_and_axis_states(text)
    labels = {axis_id: label for axis_id, _pat, label in CLARIFY_AXES}
    errors: list[str] = []
    if minimal_ok:
        needed = ", ".join(labels.get(axis, axis) for axis in required_axes)
        errors.append(
            "CLARIFY signal gate: 命中高/中置信度语义信号时不可使用全局极简绕行；"
            f"请显式覆盖以下轴：{needed}"
        )
        return errors
    if not axis_section:
        return []
    for axis, reasons in sorted(required_axes.items()):
        state = axis_states.get(axis, "")
        if state == "not_applicable":
            errors.append(
                "CLARIFY signal gate: "
                f"«{labels.get(axis, axis)}» 命中语义信号（{', '.join(reasons)}），"
                "不应标记为 not_applicable；请改为 covered 或 unknown。"
            )
    return errors


def _clarify_signal_closure_errors(features_dir: Path) -> list[str]:
    """Require high/medium semantic signals to close via scenario or signal mapping."""
    df_path = features_dir / "domain-frame.json"
    if not df_path.exists():
        return []
    try:
        domain_frame = json.loads(df_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(domain_frame, dict):
        return []

    relevant_refs: list[str] = []
    for key in ("semantic_signals", "state_transition_scenarios", "constraint_conflicts"):
        items = domain_frame.get(key)
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if (
                isinstance(item, dict)
                and str(item.get("confidence", "")).lower() in ("high", "medium")
            ):
                relevant_refs.append(f"{key}[{idx}]")
    if not relevant_refs:
        return []

    coverage_path = features_dir / "scenario-coverage.json"
    gen_path = features_dir / "generated-scenarios.json"
    if not coverage_path.exists():
        return [
            "存在高/中置信度语义信号，但缺少 `scenario-coverage.json`："
            "须显式记录信号或场景的闭环去向。"
        ]

    try:
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["scenario-coverage.json is invalid JSON."]
    if not isinstance(coverage, dict):
        return ["scenario-coverage.json root must be a JSON object."]

    generated = {}
    if gen_path.exists():
        try:
            generated = json.loads(gen_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            generated = {}

    scenario_sources: dict[str, set[str]] = {}
    scenarios = generated.get("scenarios") if isinstance(generated, dict) else None
    if isinstance(scenarios, list):
        for item in scenarios:
            if not isinstance(item, dict):
                continue
            scenario_id = str(item.get("scenario_id", "")).strip().upper()
            source_signals = item.get("source_signals")
            if not scenario_id or not isinstance(source_signals, list):
                continue
            scenario_sources[scenario_id] = {
                str(source).strip()
                for source in source_signals
                if str(source).strip()
            }

    def _entry_is_closed(entry: dict) -> bool:
        status = str(entry.get("status", "")).strip()
        mapped_to = entry.get("mapped_to")
        if status not in ("covered", "needs_decision", "deferred", "dropped_invalid"):
            return False
        if status == "dropped_invalid":
            return True
        return isinstance(mapped_to, list) and len(mapped_to) > 0

    closed_refs: set[str] = set()
    covered_scenarios = coverage.get("scenarios")
    if isinstance(covered_scenarios, list):
        for item in covered_scenarios:
            if not isinstance(item, dict) or not _entry_is_closed(item):
                continue
            scenario_id = str(item.get("scenario_id", "")).strip().upper()
            for source_ref in scenario_sources.get(scenario_id, set()):
                closed_refs.add(source_ref)

    coverage_signals = coverage.get("signals")
    if coverage_signals is not None and not isinstance(coverage_signals, list):
        return ["scenario-coverage.json field `signals` must be a JSON array when present."]
    if isinstance(coverage_signals, list):
        for item in coverage_signals:
            if not isinstance(item, dict):
                continue
            source_ref = str(item.get("signal_ref", "")).strip()
            if source_ref and _entry_is_closed(item):
                closed_refs.add(source_ref)

    unresolved = [source_ref for source_ref in relevant_refs if source_ref not in closed_refs]
    if unresolved:
        return [
            "以下高/中置信度语义信号尚未在 `scenario-coverage.json` 中完成闭环："
            + ", ".join(unresolved)
        ]
    return []


def _clarify_deep_dive_hints(features_dir: Path) -> list[str]:
    """Suggest deep-dive when high-risk signals coexist with ambiguous requirements."""
    summary = _clarify_deep_dive_summary(features_dir)
    if not summary.get("should_escalate"):
        return []
    sample = "; ".join(summary.get("candidates", [])[:3])
    reqs = ", ".join(summary.get("ambiguous_requirements", [])[:4]) or "REQ-?"
    return [
        "CLARIFY deep-dive hint: requirements-draft 中存在 UNCLEAR/AMBIGUOUS，且命中高风险语义信号，"
        f"建议触发 `deep-dive-specialist` 调查这些主题：{sample}（相关需求：{reqs}）"
    ]


def _clarify_ambiguous_requirement_ids(req_text: str) -> list[str]:
    """Extract REQ ids whose status is UNCLEAR / AMBIGUOUS."""
    req_ids: list[str] = []
    current_req = ""
    for line in req_text.splitlines():
        m = re.match(r"(?im)^###\s+(REQ-\d+)\b", line.strip())
        if m:
            current_req = m.group(1)
            continue
        if current_req and re.match(r"(?im)^\*\*Status:\*\*\s*(?:UNCLEAR|AMBIGUOUS)\b", line.strip()):
            req_ids.append(current_req)
            current_req = ""
    return sorted({x for x in req_ids})


def _clarify_deep_dive_summary(features_dir: Path) -> dict:
    """Return deep-dive escalation state derived from signals + ambiguous requirements."""
    summary = _clarify_signal_gate_summary(features_dir)
    candidates = summary.get("deep_dive_candidates", [])
    if not candidates:
        return {
            "should_escalate": False,
            "candidates": [],
            "ambiguous_requirements": [],
            "existing_memos": [],
        }
    req_path = features_dir / "requirements-draft.md"
    if not req_path.exists():
        return {
            "should_escalate": False,
            "candidates": candidates,
            "ambiguous_requirements": [],
            "existing_memos": [],
        }
    req_text = req_path.read_text(encoding="utf-8", errors="replace")
    ambiguous_requirements = _clarify_ambiguous_requirement_ids(req_text)
    existing_memos = sorted(p.name for p in features_dir.glob("deep-dive-*.md"))
    should_escalate = bool(candidates and ambiguous_requirements and not existing_memos)
    return {
        "should_escalate": should_escalate,
        "candidates": candidates,
        "ambiguous_requirements": ambiguous_requirements,
        "existing_memos": existing_memos,
    }


def _clarify_deep_dive_gate_errors(features_dir: Path) -> list[str]:
    """Blocking deep-dive gate for teams that opt into strict escalation."""
    summary = _clarify_deep_dive_summary(features_dir)
    if not summary.get("should_escalate"):
        return []
    reqs = ", ".join(summary.get("ambiguous_requirements", [])[:4]) or "REQ-?"
    sample = "; ".join(summary.get("candidates", [])[:3])
    return [
        "CLARIFY deep-dive gate: 命中高风险语义信号且 requirements-draft 存在 "
        f"UNCLEAR/AMBIGUOUS（{reqs}），但尚无 `deep-dive-*.md` 备忘录；"
        f"请触发 `deep-dive-specialist` 调查：{sample}"
    ]


def _domain_frame_has_notable_state_or_constraint(df_path: Path) -> bool:
    """True if domain-frame lists high/medium confidence state or constraint items."""
    if not df_path.exists():
        return False
    try:
        data = json.loads(df_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    for key in ("state_transition_scenarios", "constraint_conflicts"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for it in items:
            if (
                isinstance(it, dict)
                and str(it.get("confidence", "")).lower() in ("high", "medium")
            ):
                return True
    return False


def _generated_scenarios_has_notable(gen_path: Path) -> bool:
    """True if generated scenarios contain high/medium confidence entries."""
    if not gen_path.exists():
        return False
    try:
        data = json.loads(gen_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    scenarios = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(scenarios, list):
        return False
    for item in scenarios:
        if (
            isinstance(item, dict)
            and str(item.get("confidence", "")).lower() in ("high", "medium")
        ):
            return True
    return False


def _spec_semantic_warnings(spec_path: Path) -> list[str]:
    """Non-blocking hints for spec quality (FR/AC closure, scenario coverage)."""
    if not spec_path.exists():
        return []
    text = spec_path.read_text(encoding="utf-8")
    warnings: list[str] = []
    epic_stem = spec_path.stem
    features_dir = spec_path.resolve().parent.parent / "features" / epic_stem
    df_path = features_dir / "domain-frame.json"
    gen_path = features_dir / "generated-scenarios.json"
    coverage_path = features_dir / "scenario-coverage.json"
    if _domain_frame_has_notable_state_or_constraint(df_path) or _generated_scenarios_has_notable(gen_path):
        scenario_structure_re = re.compile(
            r"(?i)场景矩阵|scenario\s*matrix|事件序列|时序|状态表|组合场景|state\s*transition|SCN-\d+"
        )
        closure_language_re = re.compile(
            r"(?i)闭合|closure|行为定义|expected\s+behavior|决策|resolution|冲突处理"
        )
        if coverage_path.exists():
            try:
                coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
                coverage_items = coverage.get("scenarios") if isinstance(coverage, dict) else None
                if isinstance(coverage_items, list):
                    expected = [
                        str(item.get("scenario_id", "")).strip()
                        for item in coverage_items
                        if isinstance(item, dict)
                        and str(item.get("status", "")).strip() != "dropped_invalid"
                        and str(item.get("scenario_id", "")).strip()
                    ]
                    missing_refs = [sid for sid in expected if sid not in text]
                    if missing_refs:
                        warnings.append(
                            "规格未显式覆盖以下 `scenario-coverage.json` 场景标识："
                            + ", ".join(missing_refs[:8])
                        )
            except json.JSONDecodeError:
                warnings.append("scenario-coverage.json 无法解析，无法完成规格场景覆盖检查。")
        if not scenario_structure_re.search(text):
            warnings.append(
                "与 CLARIFY 中已标出的高/中置信度场景条目相对应，建议在规格中提供结构化的场景或时序表达，并写清可验证的闭合行为。"
            )
        elif not closure_language_re.search(text):
            warnings.append(
                "规格中已有场景或时序类结构，但未见明确的闭合行为或决策表述："
                "请对关键路径给出可验证的期望结果。"
            )
    ac_m = re.search(
        r"(?is)^#{1,6}\s*(?:验收标准|Acceptance Criteria)\b.*?(?=^#{1,2}\s|\Z)",
        text,
        re.MULTILINE,
    )
    if ac_m:
        ac_block = ac_m.group(0)
        ac_items = re.findall(r"(?m)^\s*-\s*\[[ xX]\]\s*(.+)$", ac_block)
        fr_ids = set(re.findall(r"\bFR-\d{2}(?:-\d+)?\b", text))
        if len(ac_items) >= 5 and len(fr_ids) == 0:
            warnings.append(
                "验收标准条目较多，但正文未出现 FR-xx 标识：建议在功能需求中为条目编号，"
                "并在 AC 或设计段落中引用对应 FR，便于 PLAN 覆盖矩阵映射。"
            )
    return warnings


def _coverage_pct(matrix: dict) -> float | None:
    """Return coverage percentage if it can be inferred."""
    raw = matrix.get("coverage_pct")
    if isinstance(raw, (int, float)):
        return float(raw)

    mappings = matrix.get("mappings", [])
    unmapped = matrix.get("unmapped_risks", [])
    total = len(mappings) + len(unmapped)
    if total == 0:
        return None
    return (len(mappings) / total) * 100.0


def _verification_passed(verification: dict) -> bool:
    """Return True if verification data indicates an acceptable verdict."""
    acceptable = {"PASS", "CONDITIONAL_PASS"}
    for key in ("acceptance_council", "council_verdict"):
        verdict = verification.get(key)
        if isinstance(verdict, str) and verdict in acceptable:
            return True
    return False


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------

def _initialize_harness(project_root: Path, *, force: bool = False) -> Path:
    h = project_root / HARNESS_DIR
    if h.exists() and not force:
        err(f".harness/ already exists at {h}. Use --force to reinitialize.")

    # Create subdirectories
    for sub in SUBDIRS:
        (h / sub).mkdir(parents=True, exist_ok=True)

    # Write default config
    config_path = h / CONFIG_FILE
    if not config_path.exists() or force:
        atomic_write_json(config_path, DEFAULT_CONFIG)

    # Write project-profile placeholder
    profile_path = h / PROFILE_FILE
    if not profile_path.exists() or force:
        template_path = Path(__file__).parent.parent / "templates" / "project-profile.yaml"
        if template_path.exists():
            content = template_path.read_text(encoding="utf-8")
        else:
            content = _default_profile_yaml()
        atomic_write(profile_path, content)
    return h


def cmd_init(args, project_root: Path) -> None:
    h = _initialize_harness(project_root, force=args.force)

    if args.json:
        out_json({"status": "ok", "harness_dir": str(h)})
    else:
        print(f"Initialized .harness/ at {h}")
        for sub in SUBDIRS:
            print(f"  created {sub}/")


# ---------------------------------------------------------------------------
# setup / doctor / repair
# ---------------------------------------------------------------------------

def _status_rank(status: str) -> int:
    return {"ok": 0, "warning": 1, "error": 2}.get(status, 2)


def _combine_status(*statuses: str) -> str:
    ranked = max((_status_rank(status) for status in statuses), default=0)
    for candidate in ("ok", "warning", "error"):
        if _status_rank(candidate) == ranked:
            return candidate
    return "error"


def _runtime_available(name: str) -> str | None:
    return shutil.which(name)


def _required_script_paths() -> list[Path]:
    scripts_dir = PLUGIN_ROOT / "scripts"
    script_paths = [
        scripts_dir / "harnessctl",
        scripts_dir / "harnessctl.py",
        *sorted(scripts_dir.glob("*.sh")),
    ]
    deduped: list[Path] = []
    for path in script_paths:
        if path not in deduped:
            deduped.append(path)
    return deduped


def _set_executable(path: Path) -> bool:
    current_mode = path.stat().st_mode
    next_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if next_mode == current_mode:
        return False
    path.chmod(next_mode)
    return True


def _is_executable(path: Path) -> bool:
    return path.exists() and os.access(path, os.X_OK)


def _build_plugin_health(plugin_root: Path) -> dict:
    plugin_json = plugin_root / ".claude-plugin" / "plugin.json"
    script_checks = []
    issues = []

    if not plugin_json.exists():
        issues.append({"severity": "error", "code": "missing-plugin-json", "message": f"Missing {plugin_json}"})

    if not INSTALL_LIFECYCLE_CLI.exists():
        issues.append(
            {
                "severity": "warning",
                "code": "missing-install-cli",
                "message": f"Missing install lifecycle bridge: {INSTALL_LIFECYCLE_CLI}",
            }
        )

    for script_path in _required_script_paths():
        exists = script_path.exists()
        executable = _is_executable(script_path) if exists else False
        script_checks.append(
            {
                "path": str(script_path),
                "exists": exists,
                "executable": executable,
            }
        )
        if not exists:
            issues.append(
                {
                    "severity": "error",
                    "code": "missing-script",
                    "message": f"Missing required script: {script_path}",
                }
            )
        elif not executable:
            issues.append(
                {
                    "severity": "warning",
                    "code": "script-not-executable",
                    "message": f"Script is not executable: {script_path}",
                }
            )

    runtimes = {}
    for runtime_name in ("python3", "bash", "node"):
        resolved = _runtime_available(runtime_name)
        runtimes[runtime_name] = resolved
        if resolved is None:
            severity = "warning" if runtime_name == "node" else "error"
            issues.append(
                {
                    "severity": severity,
                    "code": "missing-runtime",
                    "message": f"Runtime `{runtime_name}` not found in PATH",
                }
            )

    status = "ok"
    if any(issue["severity"] == "error" for issue in issues):
        status = "error"
    elif issues:
        status = "warning"

    return {
        "status": status,
        "plugin_root": str(plugin_root),
        "plugin_json": str(plugin_json),
        "script_checks": script_checks,
        "runtimes": runtimes,
        "issues": issues,
    }


def _build_project_health(project_root: Path) -> dict:
    harness_dir = project_root / HARNESS_DIR
    harness_exists = harness_dir.is_dir()
    writable = _dir_is_writable(project_root)
    issues = []
    if not writable:
        issues.append(
            {
                "severity": "warning",
                "code": "project-root-not-writable",
                "message": f"Project root is not writable: {project_root}",
            }
        )

    current_harnessctl = os.environ.get("HARNESSCTL", "").strip()
    recommended_harnessctl = str(PLUGIN_ROOT / "scripts" / "harnessctl")
    harnessctl_resolved = Path(current_harnessctl).resolve() if current_harnessctl else None
    recommended_resolved = Path(recommended_harnessctl).resolve()
    if current_harnessctl and harnessctl_resolved != recommended_resolved:
        issues.append(
            {
                "severity": "warning",
                "code": "harnessctl-env-mismatch",
                "message": f"HARNESSCTL points to {current_harnessctl}, recommended {recommended_harnessctl}",
            }
        )

    status = "ok"
    if any(issue["severity"] == "error" for issue in issues):
        status = "error"
    elif issues:
        status = "warning"

    return {
        "status": status,
        "project_root": str(project_root),
        "harness_dir": str(harness_dir),
        "harness_exists": harness_exists,
        "can_initialize_harness": writable and not harness_exists,
        "writable": writable,
        "current_harnessctl": current_harnessctl or None,
        "recommended_harnessctl": recommended_harnessctl,
        "recommended_plugin_dir_command": f"claude --plugin-dir {PLUGIN_ROOT}",
        "issues": issues,
    }


def _run_install_lifecycle(command: str, project_root: Path, *, apply: bool = False) -> dict:
    node_path = _runtime_available("node")
    if not node_path:
        return {
            "status": "warning",
            "mode": "unavailable",
            "message": "Node.js not found in PATH; install-state checks are unavailable",
        }
    if not INSTALL_LIFECYCLE_CLI.exists():
        return {
            "status": "warning",
            "mode": "unavailable",
            "message": f"Install lifecycle bridge not found: {INSTALL_LIFECYCLE_CLI}",
        }

    command_line = [
        node_path,
        str(INSTALL_LIFECYCLE_CLI),
        command,
        "--repo-root",
        str(PLUGIN_ROOT),
        "--project-root",
        str(project_root),
        "--json",
    ]
    if apply:
        command_line.append("--apply")

    proc = subprocess.run(
        command_line,
        capture_output=True,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip() or f"{command} bridge failed"
        try:
            parsed = json.loads(proc.stderr or "{}")
            message = parsed.get("message", message)
        except json.JSONDecodeError:
            pass
        return {
            "status": "warning",
            "mode": "unavailable",
            "message": message,
        }

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {
            "status": "warning",
            "mode": "unavailable",
            "message": f"Invalid JSON from install lifecycle bridge: {exc}",
        }

    if command == "doctor":
        summary = payload.get("summary", {})
        status = "ok"
        if summary.get("errorCount", 0) > 0:
            status = "error"
        elif summary.get("warningCount", 0) > 0 or payload.get("manifestMode") == "recorded-only":
            status = "warning"
        return {
            "status": status,
            "mode": payload.get("manifestMode", "unknown"),
            "report": payload,
        }

    summary = payload.get("summary", {})
    status = "ok"
    if summary.get("errorCount", 0) > 0:
        status = "error"
    elif summary.get("plannedRepairCount", 0) > 0:
        status = "warning"
    return {
        "status": status,
        "mode": payload.get("manifestMode", "unknown"),
        "report": payload,
    }


def cmd_setup(args, project_root: Path) -> None:
    fixed_permissions = []
    permission_errors = []

    for script_path in _required_script_paths():
        if not script_path.exists() or _is_executable(script_path):
            continue
        try:
            if _set_executable(script_path):
                fixed_permissions.append(str(script_path))
        except OSError as exc:
            permission_errors.append(f"{script_path}: {exc}")

    initialized = False
    init_skipped = False
    init_error = None
    if getattr(args, "init_project", False):
        if (project_root / HARNESS_DIR).is_dir():
            init_skipped = True
        else:
            try:
                _initialize_harness(project_root, force=False)
                initialized = True
            except SystemExit:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                init_error = str(exc)

    plugin_health = _build_plugin_health(PLUGIN_ROOT)

    status = _combine_status(
        plugin_health["status"],
        "error" if permission_errors else "ok",
        "error" if init_error else "ok",
    )

    payload = {
        "status": status,
        "plugin_root": str(PLUGIN_ROOT),
        "project_root": str(project_root),
        "fixed_permissions": fixed_permissions,
        "permission_errors": permission_errors,
        "plugin_health": plugin_health,
        "recommended_harnessctl": str(PLUGIN_ROOT / "scripts" / "harnessctl"),
        "recommended_plugin_dir_command": f"claude --plugin-dir {PLUGIN_ROOT}",
        "export_harnessctl_command": f"export HARNESSCTL={PLUGIN_ROOT / 'scripts' / 'harnessctl'}",
        "project_initialized": initialized,
        "project_init_skipped": init_skipped,
        "init_error": init_error,
        "next_steps": [
            f"claude --plugin-dir {PLUGIN_ROOT}",
            f"export HARNESSCTL={PLUGIN_ROOT / 'scripts' / 'harnessctl'}",
        ],
    }
    if getattr(args, "json", False):
        out_json(payload)
        return

    print(f"Setup status: {status.upper()}")
    print(f"Plugin root: {PLUGIN_ROOT}")
    if fixed_permissions:
        print("Fixed script permissions:")
        for item in fixed_permissions:
            print(f"  [FIXED] {item}")
    if permission_errors:
        print("Permission errors:")
        for item in permission_errors:
            print(f"  [ERROR] {item}")
    if initialized:
        print(f"Initialized project harness at {project_root / HARNESS_DIR}")
    elif init_skipped:
        print(f"Project harness already exists at {project_root / HARNESS_DIR}; skipped initialization")
    elif init_error:
        print(f"[ERROR] failed to initialize project harness: {init_error}")
    print(f"Recommended plugin command: claude --plugin-dir {PLUGIN_ROOT}")
    print(f"Recommended HARNESSCTL export: export HARNESSCTL={PLUGIN_ROOT / 'scripts' / 'harnessctl'}")


def cmd_doctor(args, project_root: Path) -> None:
    plugin_health = _build_plugin_health(PLUGIN_ROOT)
    project_health = _build_project_health(project_root)
    install_state_health = _run_install_lifecycle("doctor", project_root)
    status = _combine_status(
        plugin_health["status"],
        project_health["status"],
        install_state_health["status"],
    )

    payload = {
        "status": status,
        "plugin_root": str(PLUGIN_ROOT),
        "project_root": str(project_root),
        "checks": {
            "plugin": plugin_health,
            "project": project_health,
            "install_state": install_state_health,
        },
    }
    if getattr(args, "json", False):
        out_json(payload)
        return

    print(f"Doctor status: {status.upper()}")
    print(f"Plugin: {plugin_health['status'].upper()}")
    for issue in plugin_health["issues"]:
        print(f"  [{issue['severity'].upper()}] {issue['message']}")
    print(f"Project: {project_health['status'].upper()}")
    for issue in project_health["issues"]:
        print(f"  [{issue['severity'].upper()}] {issue['message']}")
    print(f"Install-state: {install_state_health['status'].upper()}")
    if install_state_health.get("message"):
        print(f"  {install_state_health['message']}")
    elif install_state_health.get("report"):
        report = install_state_health["report"]
        print(
            "  "
            f"mode={report.get('manifestMode', 'unknown')} "
            f"checked={report.get('summary', {}).get('checkedCount', 0)} "
            f"errors={report.get('summary', {}).get('errorCount', 0)} "
            f"warnings={report.get('summary', {}).get('warningCount', 0)}"
        )


def cmd_repair(args, project_root: Path) -> None:
    planned_permissions = []
    applied_permissions = []
    permission_errors = []
    for script_path in _required_script_paths():
        if not script_path.exists() or _is_executable(script_path):
            continue
        planned_permissions.append(str(script_path))
        if getattr(args, "apply", False):
            try:
                if _set_executable(script_path):
                    applied_permissions.append(str(script_path))
            except OSError as exc:
                permission_errors.append(f"{script_path}: {exc}")

    install_state_repair = _run_install_lifecycle(
        "repair",
        project_root,
        apply=getattr(args, "apply", False),
    )
    status = _combine_status(
        "warning" if planned_permissions and not getattr(args, "apply", False) else "ok",
        "error" if permission_errors else "ok",
        install_state_repair["status"],
    )

    payload = {
        "status": status,
        "apply": bool(getattr(args, "apply", False)),
        "plugin_root": str(PLUGIN_ROOT),
        "project_root": str(project_root),
        "permission_repairs": {
            "planned": planned_permissions,
            "applied": applied_permissions,
            "errors": permission_errors,
        },
        "install_state": install_state_repair,
    }
    if getattr(args, "json", False):
        out_json(payload)
        return

    mode = "APPLY" if getattr(args, "apply", False) else "DRY-RUN"
    print(f"Repair status: {status.upper()} ({mode})")
    if planned_permissions:
        print("Script permission repairs:")
        for item in applied_permissions if getattr(args, "apply", False) else planned_permissions:
            prefix = "[FIXED]" if getattr(args, "apply", False) else "[PLAN]"
            print(f"  {prefix} {item}")
    if permission_errors:
        for item in permission_errors:
            print(f"  [ERROR] {item}")
    if install_state_repair.get("message"):
        print(f"Install-state: {install_state_repair['status'].upper()} - {install_state_repair['message']}")
    elif install_state_repair.get("report"):
        report = install_state_repair["report"]
        print(
            "Install-state: "
            f"{install_state_repair['status'].upper()} "
            f"(mode={report.get('manifestMode', 'unknown')}, "
            f"planned={report.get('summary', {}).get('plannedRepairCount', 0)}, "
            f"repaired={report.get('summary', {}).get('repairedCount', 0)}, "
            f"errors={report.get('summary', {}).get('errorCount', 0)})"
        )


# ---------------------------------------------------------------------------
# config commands
# ---------------------------------------------------------------------------

def cmd_config_get(args, h: Path) -> None:
    config = load_json(h / CONFIG_FILE)
    key = args.key
    if key not in config:
        err(f"Key not found: {key}")
    if args.json:
        out_json({key: config[key]})
    else:
        print(f"{key} = {json.dumps(config[key])}")


def cmd_config_set(args, h: Path) -> None:
    config = load_json(h / CONFIG_FILE)
    key = args.key
    raw_value = args.value
    # Try to parse as JSON, fall back to string
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    config[key] = value
    atomic_write_json(h / CONFIG_FILE, config)
    if args.json:
        out_json({"status": "ok", "key": key, "value": value})
    else:
        print(f"Set {key} = {json.dumps(value)}")


def cmd_config_list(args, h: Path) -> None:
    config = load_json(h / CONFIG_FILE)
    if args.json:
        out_json(config)
    else:
        for k, v in config.items():
            print(f"{k} = {json.dumps(v)}")


# ---------------------------------------------------------------------------
# profile commands
# ---------------------------------------------------------------------------

def _default_profile_yaml() -> str:
    return (
        "type: unknown\n"
        "risk_level: medium\n"
        "primary_language: unknown\n"
        "framework: \"\"\n"
        "build_tool: unknown\n"
        "test_framework: unknown\n"
        "has_database: null\n"
        "has_auth: null\n"
        "has_docker: null\n"
        "has_ci: null\n"
        "estimated_size: unknown\n"
        "intensity: {}\n"
        "notes: \"\"\n"
        "workspace_mode: unknown\n"
        "scan: {}\n"
        "primary_surfaces: []\n"
        "check_focus: []\n"
        "coupling_role_ids: []\n"
        "detected_at: \"\"\n"
        "confidence: 0.0\n"
        "overrides: {}\n"
    )


def _parse_simple_yaml_scalar(val: str):
    """Parse one scalar / inline-list token from the lightweight YAML subset."""
    text = val.strip()
    if text == "":
        return ""
    if text.lower() in ("null", "~", "none"):
        return None
    if text.startswith("{") and text.endswith("}") and len(text) >= 2:
        inner = text[1:-1].strip()
        if not inner:
            return {}
        result = {}
        for part in inner.split(","):
            if ":" not in part:
                return text
            sub_key, _, sub_val = part.partition(":")
            result[sub_key.strip()] = _parse_simple_yaml_scalar(sub_val.strip())
        return result
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1]
        return [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
    if text.startswith("\"") and text.endswith("\"") and len(text) >= 2:
        return text[1:-1]
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1]
    if text == "{}":
        return {}
    if text == "[]":
        return []
    if text in ("true", "false"):
        return text == "true"
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def _strip_yaml_comment_preserving_quotes(line: str) -> str:
    in_single = False
    in_double = False
    prev = ""
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double and prev != "\\":
            in_single = not in_single
        elif ch == '"' and not in_single and prev != "\\":
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and idx > 0 and line[idx - 1].isspace():
            return line[:idx].rstrip()
        prev = ch
    return line.rstrip()


def _parse_simple_yaml(text: str) -> dict:
    """Parse a small YAML subset used by stage-harness without extra deps."""
    lines = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = _strip_yaml_comment_preserving_quotes(raw_line)
        if line.strip():
            lines.append(line)

    result = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line:
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        if val != "":
            result[key] = _parse_simple_yaml_scalar(val)
            i += 1
            continue

        nested = []
        j = i + 1
        while j < len(lines):
            next_line = lines[j]
            next_indent = len(next_line) - len(next_line.lstrip(" "))
            if next_indent <= indent:
                break
            nested.append(next_line)
            j += 1

        if not nested:
            result[key] = []
            i = j
            continue

        first_nested = nested[0].strip()
        if first_nested.startswith("- "):
            items = []
            for item_line in nested:
                item_indent = len(item_line) - len(item_line.lstrip(" "))
                if item_indent <= indent:
                    continue
                item_stripped = item_line.strip()
                if item_stripped.startswith("- "):
                    items.append(_parse_simple_yaml_scalar(item_stripped[2:].strip()))
            result[key] = items
        else:
            sub = {}
            for sub_line in nested:
                sub_indent = len(sub_line) - len(sub_line.lstrip(" "))
                if sub_indent <= indent:
                    continue
                sub_stripped = sub_line.strip()
                if ":" not in sub_stripped:
                    continue
                sub_key, _, sub_val = sub_stripped.partition(":")
                sub[sub_key.strip()] = _parse_simple_yaml_scalar(sub_val.strip())
            result[key] = sub
        i = j
    return result


def _workspace_mode(h: Path) -> str:
    """Return project-profile workspace_mode; default single-repo if unset."""
    prof = h / PROFILE_FILE
    if not prof.exists():
        return "single-repo"
    try:
        data = _parse_simple_yaml(prof.read_text(encoding="utf-8"))
        wm = data.get("workspace_mode") or "single-repo"
        return str(wm).strip() if wm else "single-repo"
    except OSError:
        return "single-repo"


def _write_profile_yaml(h: Path, data: dict) -> None:
    """Write profile data back to YAML text without yaml library."""
    def _yaml_scalar_text(value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(str(value), ensure_ascii=False)

    lines = []
    for key, val in data.items():
        if isinstance(val, list):
            if val:
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {_yaml_scalar_text(item)}")
            else:
                lines.append(f"{key}: []")
        elif isinstance(val, dict):
            if val:
                lines.append(f"{key}:")
                for k2, v2 in val.items():
                    lines.append(f"  {k2}: {_yaml_scalar_text(v2)}")
            else:
                lines.append(f"{key}: {{}}")
        else:
            lines.append(f"{key}: {_yaml_scalar_text(val)}")
    atomic_write(h / PROFILE_FILE, "\n".join(lines) + "\n")


def _detect_workspace_mode(project_root: Path, profile_type: str) -> str:
    """Infer workspace layout so scanning can choose the right narrowing strategy."""
    top_dirs = [
        p.name
        for p in project_root.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in PROFILE_SCAN_IGNORE_DIRS
    ]
    if profile_type == "docs":
        return "docs-heavy"
    if profile_type == "infra":
        return "infra-heavy"
    monorepo_markers = {"apps", "packages", "libs", "services"}
    if len(monorepo_markers.intersection(set(top_dirs))) >= 2:
        return "monorepo"
    repo_like_children = 0
    nested_git_children = 0
    for dirname in top_dirs:
        child = project_root / dirname
        has_git = (child / ".git").exists()
        has_marker = any((child / marker).exists() for marker in PROFILE_REPO_MARKERS if marker != ".git")
        if has_git:
            nested_git_children += 1
        if has_git or has_marker:
            repo_like_children += 1
    if nested_git_children >= 2:
        return "multi-repo"
    if repo_like_children >= 2:
        return "monorepo"
    return "single-repo"


def _detect_primary_surfaces(project_root: Path, workspace_mode: str) -> list[str]:
    """Derive conservative surface hints without binding to a specific tech stack."""
    top_dirs = [
        p
        for p in project_root.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in PROFILE_SCAN_IGNORE_DIRS
    ]
    if workspace_mode == "multi-repo":
        surfaces = []
        for child in top_dirs:
            if (child / ".git").exists() or any(
                (child / marker).exists() for marker in PROFILE_REPO_MARKERS if marker != ".git"
            ):
                surfaces.append(f"{child.name}/")
        return sorted(surfaces)
    if workspace_mode == "monorepo":
        monorepo_markers = ["apps", "packages", "libs", "services"]
        marker_surfaces = [f"{name}/" for name in monorepo_markers if (project_root / name).is_dir()]
        if marker_surfaces:
            return marker_surfaces
        return sorted(
            f"{child.name}/"
            for child in top_dirs
            if any((child / marker).exists() for marker in PROFILE_REPO_MARKERS if marker != ".git")
        )

    common_single_repo_surfaces = [
        "src",
        "app",
        "lib",
        "cmd",
        "pkg",
        "internal",
        "server",
        "client",
        "backend",
        "frontend",
        "web",
        "api",
    ]
    surfaces = [f"{name}/" for name in common_single_repo_surfaces if (project_root / name).is_dir()]
    return surfaces[:4]


def _profile_override_keys(existing: dict) -> set[str]:
    overrides = existing.get("overrides", {})
    if not isinstance(overrides, dict):
        return set()
    keys: set[str] = set()
    for key, value in overrides.items():
        if value not in ("", None, False, [], {}):
            keys.add(str(key).strip())
    return keys


def _looks_like_legacy_profile_template(existing: dict) -> bool:
    confidence = existing.get("confidence", 0.0)
    try:
        low_confidence = float(confidence or 0.0) <= 0.05
    except (TypeError, ValueError):
        low_confidence = True
    if not low_confidence:
        return False

    matched = 0
    for key, legacy_value in LEGACY_PROFILE_TEMPLATE_DEFAULTS.items():
        if existing.get(key) == legacy_value:
            matched += 1
    return matched >= 5


def _neutralize_legacy_profile_defaults(existing: dict, project_root: Path, detected_workspace_mode: str) -> dict:
    """Clear legacy biased template values so fresh detection can replace them."""
    sanitized = dict(existing)
    override_keys = _profile_override_keys(existing)
    if not _looks_like_legacy_profile_template(existing):
        for key, neutral_value in PROFILE_NEUTRAL_DEFAULTS.items():
            sanitized.setdefault(key, neutral_value if not isinstance(neutral_value, list) else list(neutral_value))
        return sanitized

    primary_surfaces = sanitized.get("primary_surfaces")
    invalid_surfaces = (
        isinstance(primary_surfaces, list)
        and primary_surfaces
        and all(not (project_root / str(surface).rstrip("/")).exists() for surface in primary_surfaces)
    )
    has_template_sentinel = (
        str(sanitized.get("detected_at") or "").strip() == ""
        and str(sanitized.get("notes") or "").strip() == ""
        and str(sanitized.get("framework") or "").strip() == ""
        and sanitized.get("overrides") in ({}, None)
    )
    if not invalid_surfaces and not has_template_sentinel:
        for key, neutral_value in PROFILE_NEUTRAL_DEFAULTS.items():
            sanitized.setdefault(key, neutral_value if not isinstance(neutral_value, list) else list(neutral_value))
        return sanitized

    for key, legacy_value in LEGACY_PROFILE_TEMPLATE_DEFAULTS.items():
        if key in override_keys:
            continue
        if sanitized.get(key) == legacy_value:
            neutral_value = PROFILE_NEUTRAL_DEFAULTS.get(key)
            if isinstance(neutral_value, list):
                sanitized[key] = list(neutral_value)
            else:
                sanitized[key] = neutral_value

    sanitized["_legacy_defaults_cleared"] = True

    for key, neutral_value in PROFILE_NEUTRAL_DEFAULTS.items():
        sanitized.setdefault(key, neutral_value if not isinstance(neutral_value, list) else list(neutral_value))

    return sanitized


def _artifact_step_is_observable(path: Path) -> bool:
    """Treat an artifact as observable progress only when it exists and is minimally valid."""
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return False
    if path.suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        def _has_non_empty_surface_route(data: dict) -> bool:
            surfaces = data.get("surfaces")
            if not isinstance(surfaces, list) or len(surfaces) == 0:
                return False
            return any(
                isinstance(item, dict)
                and str(item.get("type", "")).strip()
                and str(item.get("path", "")).strip()
                for item in surfaces
            )

        def _has_minimal_generated_scenario(data: dict) -> bool:
            scenarios = data.get("scenarios")
            if not isinstance(scenarios, list) or len(scenarios) == 0:
                return False
            return any(
                isinstance(item, dict)
                and str(item.get("confidence", "")).strip().lower() in ("high", "medium")
                and re.fullmatch(r"(?i)SCN-\d+", str(item.get("scenario_id", "")).strip()) is not None
                and str(item.get("scenario", "")).strip()
                for item in scenarios
            )

        def _has_minimal_scenario_coverage(data: dict) -> bool:
            if not data.get("epic_id") or not data.get("version"):
                return False
            scenarios = data.get("scenarios")
            if not isinstance(scenarios, list) or len(scenarios) == 0:
                return False
            return any(
                isinstance(item, dict)
                and re.fullmatch(r"(?i)SCN-\d+", str(item.get("scenario_id", "")).strip()) is not None
                and str(item.get("status", "")).strip() in {
                    "covered",
                    "needs_decision",
                    "deferred",
                    "dropped_invalid",
                }
                for item in scenarios
            )

        validators = {
            "domain-frame.json": lambda data: bool(data.get("epic_id")) and bool(data.get("version")),
            "generated-scenarios.json": _has_minimal_generated_scenario,
            "scenario-coverage.json": _has_minimal_scenario_coverage,
            "surface-routing.json": _has_non_empty_surface_route,
        }
        validator = validators.get(path.name)
        return validator(payload) if validator else bool(payload)
    try:
        return bool(path.read_text(encoding="utf-8", errors="replace").strip())
    except OSError:
        return False


def _default_scan_budget_for_workspace_mode(workspace_mode: str) -> dict:
    """Provide conservative scan caps by workspace shape."""
    if workspace_mode == "multi-repo":
        return {
            "max_repos_deep_scan": 5,
            "max_files_deep_read_per_scout": 15,
            "max_subagents_wave": 4,
        }
    if workspace_mode == "monorepo":
        return {
            "max_repos_deep_scan": 3,
            "max_files_deep_read_per_scout": 18,
            "max_subagents_wave": 4,
        }
    if workspace_mode in ("docs-heavy", "infra-heavy"):
        return {
            "max_repos_deep_scan": 2,
            "max_files_deep_read_per_scout": 12,
            "max_subagents_wave": 2,
        }
    return {
        "max_repos_deep_scan": 3,
        "max_files_deep_read_per_scout": 20,
        "max_subagents_wave": 3,
    }


def _normalize_profile_data(data: dict) -> dict:
    """Fold legacy flattened keys back into nested project-profile sections."""
    normalized = dict(data)

    intensity = normalized.get("intensity")
    if not isinstance(intensity, dict):
        intensity = {}
    for key in ("agent_parallelism", "council_size", "harness_strength"):
        if key in normalized:
            if key not in intensity:
                intensity[key] = normalized[key]
            normalized.pop(key, None)
    if intensity:
        normalized["intensity"] = intensity
    elif "intensity" in normalized and normalized["intensity"] == []:
        normalized["intensity"] = {}

    scan = normalized.get("scan")
    if not isinstance(scan, dict):
        scan = {}
    for key in (
        "max_repos_deep_scan",
        "max_files_deep_read_per_scout",
        "max_subagents_wave",
    ):
        if key in normalized:
            if key not in scan:
                scan[key] = normalized[key]
            normalized.pop(key, None)
    if scan:
        normalized["scan"] = scan
    elif "scan" in normalized and normalized["scan"] == []:
        normalized["scan"] = {}

    return normalized


def _detect_profile_data(h: Path, project_root: Path) -> dict:
    detected_type = "unknown"
    confidence = 0.0

    # Check explicit file rules
    for filename, ptype in PROFILE_DETECT_RULES:
        if (project_root / filename).exists():
            detected_type = ptype
            confidence = 0.9
            break

    # Check glob rules
    if detected_type == "unknown":
        for pattern, ptype in PROFILE_DETECT_GLOB_RULES:
            matches = list(project_root.glob(pattern))
            if matches:
                detected_type = ptype
                confidence = 0.8
                break

    # If still unknown, check if mostly .md files
    if detected_type == "unknown":
        all_files = [f for f in project_root.iterdir() if f.is_file()]
        md_files = [f for f in all_files if f.suffix == ".md"]
        if all_files and len(md_files) / len(all_files) > 0.5:
            detected_type = "docs"
            confidence = 0.7

    # Map type to profile_type string
    type_map = {
        "frontend":  "frontend",
        "backend":   "backend-service",
        "library":   "library",
        "infra":     "infra",
        "docs":      "docs",
        "unknown":   "unknown",
    }
    profile_type = type_map.get(detected_type, "unknown")
    workspace_mode = _detect_workspace_mode(project_root, profile_type)
    scan_defaults = _default_scan_budget_for_workspace_mode(workspace_mode)

    # Build check_focus from type
    focus_map = {
        "frontend":        ["ui_correctness", "accessibility"],
        "backend-service": ["api_contract", "state_idempotency"],
        "library":         ["api_stability", "backward_compat"],
        "infra":           ["idempotency", "drift_detection"],
        "docs":            ["completeness", "accuracy"],
        "unknown":         [],
    }

    # Load existing profile
    profile_path = h / PROFILE_FILE
    if profile_path.exists():
        existing = _normalize_profile_data(
            _parse_simple_yaml(profile_path.read_text(encoding="utf-8"))
        )
    else:
        existing = {}
    had_workspace_mode = "workspace_mode" in existing
    had_primary_surfaces = "primary_surfaces" in existing
    had_type = "type" in existing
    had_check_focus = "check_focus" in existing
    had_scan = "scan" in existing
    existing = _neutralize_legacy_profile_defaults(existing, project_root, workspace_mode)
    override_keys = _profile_override_keys(existing)
    legacy_cleared = bool(existing.pop("_legacy_defaults_cleared", False))
    detected_primary_surfaces = _detect_primary_surfaces(project_root, workspace_mode)
    initial_workspace_mode = existing.get("workspace_mode")

    current_type = existing.get("type")
    if "type" in override_keys and current_type:
        existing["type"] = current_type
    elif legacy_cleared or not had_type or current_type in (None, "", PROFILE_UNKNOWN):
        existing["type"] = profile_type
    existing["risk_level"] = existing.get("risk_level", "medium")
    if "workspace_mode" not in override_keys:
        current_workspace_mode = existing.get("workspace_mode")
        if legacy_cleared or not had_workspace_mode or current_workspace_mode in (None, "", PROFILE_UNKNOWN):
            existing["workspace_mode"] = workspace_mode
    else:
        existing["workspace_mode"] = str(existing.get("workspace_mode") or workspace_mode).strip() or workspace_mode
    if "scan" not in override_keys or not existing.get("scan"):
        current_scan = existing.get("scan")
        if legacy_cleared or not had_scan or not current_scan:
            existing["scan"] = scan_defaults
    if "primary_surfaces" not in override_keys:
        current_surfaces = existing.get("primary_surfaces", [])
        if (
            legacy_cleared
            or not had_primary_surfaces
            or (
                current_surfaces == []
                and initial_workspace_mode in (None, "", PROFILE_UNKNOWN)
            )
        ):
            existing["primary_surfaces"] = detected_primary_surfaces
    else:
        existing["primary_surfaces"] = existing.get("primary_surfaces", [])
    if "check_focus" in override_keys:
        existing["check_focus"] = existing.get("check_focus")
    elif legacy_cleared or not had_check_focus or existing.get("check_focus") in (None, []):
        existing["check_focus"] = focus_map.get(profile_type, [])
    existing["detected_at"] = now_iso()
    existing["confidence"] = confidence
    if "overrides" not in existing:
        existing["overrides"] = {}
    for key, neutral_value in PROFILE_NEUTRAL_DEFAULTS.items():
        if key not in existing:
            existing[key] = neutral_value if not isinstance(neutral_value, list) else list(neutral_value)

    _write_profile_yaml(h, existing)
    return {
        "type": existing.get("type", profile_type),
        "workspace_mode": existing.get("workspace_mode", workspace_mode),
        "primary_surfaces": existing.get("primary_surfaces", []),
        "scan": existing.get("scan", {}),
        "confidence": confidence,
        "detected_at": existing["detected_at"],
    }


def cmd_profile_detect(args, h: Path, project_root: Path) -> None:
    profile = _detect_profile_data(h, project_root)
    if args.json:
        out_json(profile)
    else:
        print(f"Detected project type: {profile['type']} (confidence: {profile['confidence']})")
        print(f"Workspace mode: {profile['workspace_mode']}")
        print(f"Written to: {h / PROFILE_FILE}")


def cmd_profile_show(args, h: Path) -> None:
    profile_path = h / PROFILE_FILE
    if not profile_path.exists():
        err(f"Profile not found. Run 'harnessctl profile detect' first.")
    content = profile_path.read_text(encoding="utf-8")
    if args.json:
        out_json(_normalize_profile_data(_parse_simple_yaml(content)))
    else:
        print(content, end="")


def _parse_repo_catalog_scalar(val: str):
    v = val.strip()
    if v.startswith('"') and v.endswith('"') and len(v) >= 2:
        v = v[1:-1]
    elif v.startswith("'") and v.endswith("'") and len(v) >= 2:
        v = v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1]
        return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
    if v == "[]":
        return []
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def parse_repo_catalog(path: Path) -> dict:
    """Parse .harness/repo-catalog.yaml (template-shaped; no external YAML lib)."""
    text = path.read_text(encoding="utf-8")
    data: dict = {"version": 1, "workspace_mode": "multi-repo", "repos": [], "notes": ""}
    state = "top"
    cur_repo = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped.startswith("#") or stripped == "":
            i += 1
            continue
        if " #" in raw and not raw.lstrip().startswith("#"):
            stripped = raw.split(" #", 1)[0].strip()
        if state == "top":
            if stripped.startswith("repos:"):
                state = "repos"
                i += 1
                continue
            if ":" in stripped and not stripped.startswith("-"):
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip()
                if k == "version":
                    try:
                        data["version"] = int(v)
                    except ValueError:
                        data["version"] = v
                elif k == "workspace_mode":
                    data["workspace_mode"] = v
                elif k == "notes":
                    data["notes"] = _parse_repo_catalog_scalar(v) if v.startswith(("[", "{")) else v.strip('"').strip("'")
            i += 1
            continue
        if state == "repos":
            if raw and not raw[0].isspace() and ":" in stripped and not stripped.startswith("-"):
                if cur_repo:
                    data["repos"].append(cur_repo)
                    cur_repo = None
                state = "top"
                continue
            if stripped.startswith("- "):
                if cur_repo:
                    data["repos"].append(cur_repo)
                cur_repo = {}
                rest = stripped[2:].strip()
                if ":" in rest:
                    k, _, v = rest.partition(":")
                    cur_repo[k.strip()] = _parse_repo_catalog_scalar(v.strip())
                i += 1
                continue
            if cur_repo is not None and (raw.startswith("    ") or (raw.startswith("  ") and not stripped.startswith("-"))):
                if ":" in stripped:
                    k, _, v = stripped.partition(":")
                    cur_repo[k.strip()] = _parse_repo_catalog_scalar(v.strip())
                i += 1
                continue
        i += 1
    if cur_repo:
        data["repos"].append(cur_repo)
    return data


def _format_yaml_inline_list(items: list) -> str:
    parts = []
    for x in items:
        if isinstance(x, (int, float)):
            parts.append(str(x))
        else:
            s = str(x)
            if re.match(r"^[\w./@+-]+$", s):
                parts.append(s)
            else:
                parts.append(json.dumps(s, ensure_ascii=False))
    return "[" + ", ".join(parts) + "]"


def write_repo_catalog(path: Path, data: dict) -> None:
    """Write repo-catalog.yaml in template order."""
    lines = [
        "# Multi-repo workspace catalog (optional).",
        "# Place at .harness/repo-catalog.yaml when workspace_mode is multi-repo.",
        "# Copy from stage-harness/templates/repo-catalog.yaml and fill in repos.",
        "",
        f"version: {data.get('version', 1)}",
        f"workspace_mode: {data.get('workspace_mode', 'multi-repo')}",
        "repos:",
    ]
    key_order = [
        "path",
        "primary_language",
        "framework",
        "domain_tags",
        "role",
        "owner",
        "package_aliases",
        "import_prefixes",
    ]
    for r in data.get("repos", []):
        rid = r.get("repo_id", "unknown")
        lines.append(f"  - repo_id: {rid}")
        for k in key_order:
            if k not in r or k == "repo_id":
                continue
            v = r[k]
            if isinstance(v, list):
                lines.append(f"    {k}: {_format_yaml_inline_list(v)}")
            elif isinstance(v, bool):
                lines.append(f"    {k}: {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"    {k}: {v}")
            elif v == "" or v is None:
                lines.append(f'    {k}: ""')
            else:
                lines.append(f"    {k}: {v}")
        for k in sorted(r.keys()):
            if k in key_order or k == "repo_id":
                continue
            v = r[k]
            if isinstance(v, list):
                lines.append(f"    {k}: {_format_yaml_inline_list(v)}")
            elif isinstance(v, bool):
                lines.append(f"    {k}: {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"    {k}: {v}")
            elif v == "" or v is None:
                lines.append(f'    {k}: ""')
            else:
                lines.append(f"    {k}: {v}")
    notes = data.get("notes", "")
    lines.append(f"notes: {json.dumps(notes, ensure_ascii=False)}")
    lines.append("")
    atomic_write(path, "\n".join(lines))


def _merge_unique_str_lists(base: list, extra: list) -> list:
    seen: set[str] = set()
    out: list[str] = []
    for seq in (base, extra):
        if not isinstance(seq, list):
            continue
        for x in seq:
            if not isinstance(x, str):
                continue
            s = x.strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
    return out


def _discover_aliases_at_repo_root(root: Path) -> tuple[list[str], list[str]]:
    """Heuristic package names and import/module prefixes for a repo root."""
    packages: list[str] = []
    prefixes: list[str] = []
    pj = root / "package.json"
    if pj.is_file():
        try:
            obj = json.loads(pj.read_text(encoding="utf-8"))
            n = obj.get("name")
            if isinstance(n, str) and n.strip():
                packages.append(n.strip())
        except (json.JSONDecodeError, OSError):
            pass
    gm = root / "go.mod"
    if gm.is_file():
        try:
            for line in gm.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("module "):
                    mod = s[7:].strip().split()[0] if s[7:].strip() else ""
                    if mod:
                        prefixes.append(mod.rstrip("/"))
                    break
        except OSError:
            pass
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        try:
            txt = cargo.read_text(encoding="utf-8")
            m = re.search(r'^\s*name\s*=\s*"([^"]+)"', txt, re.MULTILINE)
            if not m:
                m = re.search(r"^\s*name\s*=\s*'([^']+)'", txt, re.MULTILINE)
            if m:
                packages.append(m.group(1))
        except OSError:
            pass
    ppt = root / "pyproject.toml"
    if ppt.is_file():
        try:
            txt = ppt.read_text(encoding="utf-8")
            in_project = False
            for line in txt.splitlines():
                if re.match(r"^\s*\[project\]\s*$", line):
                    in_project = True
                    continue
                if line.strip().startswith("[") and "]" in line.strip():
                    if not re.match(r"^\s*\[project", line):
                        in_project = False
                if in_project:
                    m = re.match(r'^\s*name\s*=\s*"([^"]+)"', line) or re.match(
                        r"^\s*name\s*=\s*'([^']+)'", line
                    )
                    if m:
                        packages.append(m.group(1))
                        break
                    m = re.match(r"^\s*name\s*=\s*([A-Za-z0-9_.-]+)\s*$", line)
                    if m:
                        packages.append(m.group(1))
                        break
        except OSError:
            pass
    pom = root / "pom.xml"
    if pom.is_file():
        try:
            txt = pom.read_text(encoding="utf-8")
            m = re.search(r"<artifactId>\s*([^<]+?)\s*</artifactId>", txt)
            if m:
                aid = m.group(1).strip()
                if aid and "${" not in aid:
                    packages.append(aid)
        except OSError:
            pass
    return packages, prefixes


def cmd_profile_discover_repo_aliases(args, h: Path, project_root: Path) -> None:
    """Scan repo roots for package.json / go.mod / etc. and merge into repo-catalog."""
    catalog = h / REPO_CATALOG_FILE
    if not catalog.is_file():
        err(f"Missing {catalog}. Copy from stage-harness/templates/repo-catalog.yaml")
    data = parse_repo_catalog(catalog)
    report = []
    root_resolved = project_root.resolve()
    for r in data.get("repos", []):
        rid = r.get("repo_id", "")
        rel = r.get("path", "")
        sub = (root_resolved / str(rel)).resolve() if rel else root_resolved
        pkgs, prefs = _discover_aliases_at_repo_root(sub)
        old_pa = r.get("package_aliases", [])
        old_ip = r.get("import_prefixes", [])
        if not isinstance(old_pa, list):
            old_pa = []
        if not isinstance(old_ip, list):
            old_ip = []
        new_pa = _merge_unique_str_lists(old_pa, pkgs)
        new_ip = _merge_unique_str_lists(old_ip, prefs)
        report.append(
            {
                "repo_id": rid,
                "path": rel,
                "scanned_root": str(sub),
                "discovered_package_aliases": pkgs,
                "discovered_import_prefixes": prefs,
                "package_aliases_after": new_pa,
                "import_prefixes_after": new_ip,
            }
        )
        r["package_aliases"] = new_pa
        r["import_prefixes"] = new_ip
    if args.write:
        write_repo_catalog(catalog, data)
    if args.json:
        out_json({"status": "ok", "wrote": bool(args.write), "repos": report})
    else:
        for row in report:
            print(
                f"{row['repo_id']}: package_aliases={row['package_aliases_after']} "
                f"import_prefixes={row['import_prefixes_after']}"
            )
        if args.write:
            print(f"Wrote {catalog}")
        else:
            print("(dry-run; use --write to save)")


def cmd_metrics_record(args, h: Path) -> None:
    """Record a numeric/string ROI metric for an epic."""
    epic_id = args.epic_id
    load_epic(h, epic_id)  # validate
    metric = args.metric.strip()
    value = _parse_metric_value(args.value)

    metrics = load_epic_metrics(h, epic_id)
    roi_metrics = dict(metrics.get("roi_metrics", {}))
    roi_metrics[metric] = {
        "value": value,
        "stage": getattr(args, "stage", "") or "",
        "notes": getattr(args, "notes", "") or "",
        "known_metric": metric in KNOWN_ROI_METRICS,
        "updated_at": now_iso(),
    }
    metrics["roi_metrics"] = roi_metrics
    save_epic_metrics(h, epic_id, metrics)

    append_metrics_event(
        h,
        {
            "timestamp": now_iso(),
            "epic_id": epic_id,
            "event_type": "roi_metric_recorded",
            "metric": metric,
            "value": value,
            "stage": getattr(args, "stage", "") or "",
        },
    )

    payload = {"status": "ok", "epic_id": epic_id, "metric": metric, "value": value}
    if args.json:
        out_json(payload)
    else:
        print(f"Recorded ROI metric for {epic_id}: {metric}={json.dumps(value, ensure_ascii=False)}")


def cmd_metrics_check(args, h: Path) -> None:
    """Record acceptance status for a scan-framework criterion."""
    epic_id = args.epic_id
    load_epic(h, epic_id)  # validate
    criterion = args.criterion.strip()
    status = args.status

    metrics = load_epic_metrics(h, epic_id)
    acceptance_checks = dict(metrics.get("acceptance_checks", {}))
    acceptance_checks[criterion] = {
        "status": status,
        "notes": getattr(args, "notes", "") or "",
        "known_criterion": criterion in KNOWN_ACCEPTANCE_CRITERIA,
        "updated_at": now_iso(),
    }
    metrics["acceptance_checks"] = acceptance_checks
    save_epic_metrics(h, epic_id, metrics)

    append_metrics_event(
        h,
        {
            "timestamp": now_iso(),
            "epic_id": epic_id,
            "event_type": "acceptance_check_recorded",
            "criterion": criterion,
            "status": status,
        },
    )

    payload = {"status": "ok", "epic_id": epic_id, "criterion": criterion, "acceptance": status}
    if args.json:
        out_json(payload)
    else:
        print(f"Recorded acceptance check for {epic_id}: {criterion} -> {status}")


def cmd_metrics_derive(args, h: Path) -> None:
    """Derive a small set of acceptance checks from stage artifacts."""
    epic_id = args.epic_id
    load_epic(h, epic_id)
    features_dir = h / "features" / epic_id
    metrics = load_epic_metrics(h, epic_id)
    acceptance_checks = dict(metrics.get("acceptance_checks", {}))

    surface_status = "not_met"
    surface_notes = "surface-routing.json missing or invalid"
    sr_path = features_dir / "surface-routing.json"
    sr_data = {}
    if sr_path.exists():
        try:
            sr_data = load_json(sr_path)
            surfaces = sr_data.get("surfaces")
            if isinstance(surfaces, list) and surfaces:
                surface_status = "met"
                surface_notes = "surface-routing.json present with non-empty surfaces"
            else:
                surface_status = "partial"
                surface_notes = "surface-routing.json present but surfaces missing/empty"
        except SystemExit:
            surface_status = "partial"
            surface_notes = "surface-routing.json present but invalid"

    mvp_status = surface_status
    mvp_notes = surface_notes
    if _workspace_mode(h) == "multi-repo":
        cri_path = features_dir / "cross-repo-impact-index.json"
        if cri_path.exists():
            try:
                cri_data = load_json(cri_path)
                cri_errors = _cross_repo_impact_index_errors(cri_data)
                if not cri_errors:
                    if surface_status == "met":
                        mvp_status = "met"
                        mvp_notes = "routing + cross-repo-impact-index present"
                    else:
                        mvp_status = "partial"
                        mvp_notes = "cross-repo-impact-index present but routing incomplete"
                else:
                    mvp_status = "partial"
                    mvp_notes = f"cross-repo-impact-index present but {cri_errors[0]}"
            except SystemExit:
                mvp_status = "partial"
                mvp_notes = "cross-repo-impact-index present but invalid"
        else:
            mvp_status = "partial"
            mvp_notes = "multi-repo workspace without cross-repo-impact-index.json"

    codemap_status = "not_met"
    codemap_notes = "no codemap evidence recorded"
    audit_path = features_dir / "codemap-audit.json"
    codemap_root = h / "memory" / "codemaps"
    if audit_path.exists():
        try:
            audit = load_json(audit_path)
            summary = audit.get("summary", {}) if isinstance(audit, dict) else {}
            total = int(summary.get("total", 0) or 0)
            stale = int(summary.get("stale", 0) or 0)
            invalid = int(summary.get("invalid", 0) or 0)
            missing_verified = int(summary.get("missing_verified_commit", 0) or 0)
            if total > 0 and stale == 0 and invalid == 0:
                codemap_status = "met"
                codemap_notes = "codemap-audit present and all audited CodeMaps are usable"
            elif total > 0:
                codemap_status = "partial"
                codemap_notes = (
                    f"codemap-audit present but stale={stale}, invalid={invalid}, "
                    f"missing_verified_commit={missing_verified}"
                )
        except SystemExit:
            codemap_status = "partial"
            codemap_notes = "codemap-audit.json present but invalid"
    elif codemap_root.exists() and any(codemap_root.rglob("*.md")):
        codemap_status = "not_met"
        codemap_notes = "codemap files exist but no codemap-audit.json was recorded for this epic"

    derived = {
        "routing_auditable": {"status": surface_status, "notes": surface_notes},
        "mvp_no_blind_scan": {"status": mvp_status, "notes": mvp_notes},
        "codemap_reuse_visible": {"status": codemap_status, "notes": codemap_notes},
    }

    for criterion, payload in derived.items():
        acceptance_checks[criterion] = {
            "status": payload["status"],
            "notes": payload["notes"],
            "known_criterion": criterion in KNOWN_ACCEPTANCE_CRITERIA,
            "updated_at": now_iso(),
            "derived": True,
        }
        append_metrics_event(
            h,
            {
                "timestamp": now_iso(),
                "epic_id": epic_id,
                "event_type": "acceptance_check_derived",
                "criterion": criterion,
                "status": payload["status"],
            },
        )

    metrics["acceptance_checks"] = acceptance_checks
    save_epic_metrics(h, epic_id, metrics)

    payload = {"status": "ok", "epic_id": epic_id, "derived": derived}
    if args.json:
        out_json(payload)
    else:
        print(f"Derived acceptance checks for {epic_id}:")
        for criterion, data in derived.items():
            print(f"  {criterion}: {data['status']} ({data['notes']})")


def cmd_metrics_show(args, h: Path) -> None:
    """Show ROI metrics / acceptance checks for one epic or all epics."""
    epic_id = getattr(args, "epic_id", "") or ""
    if epic_id:
        load_epic(h, epic_id)  # validate
        metrics = load_epic_metrics(h, epic_id)
        if args.json:
            out_json(metrics)
        else:
            print(json.dumps(metrics, indent=2, ensure_ascii=False))
        return

    summaries = []
    features_dir = h / "features"
    if features_dir.exists():
        for path in sorted(features_dir.glob("*/scan-metrics.json")):
            try:
                summaries.append(load_json(path))
            except SystemExit:
                continue
    aggregate_metrics = {}
    aggregate_acceptance = {}
    for entry in summaries:
        roi_metrics = entry.get("roi_metrics", {})
        if isinstance(roi_metrics, dict):
            for metric_name, metric_payload in roi_metrics.items():
                if not isinstance(metric_payload, dict):
                    continue
                bucket = aggregate_metrics.setdefault(metric_name, {"count": 0, "numeric_count": 0, "sum": 0.0})
                bucket["count"] += 1
                value = metric_payload.get("value")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bucket["numeric_count"] += 1
                    bucket["sum"] += float(value)
        acceptance_checks = entry.get("acceptance_checks", {})
        if isinstance(acceptance_checks, dict):
            for criterion, check_payload in acceptance_checks.items():
                if not isinstance(check_payload, dict):
                    continue
                status = check_payload.get("status")
                bucket = aggregate_acceptance.setdefault(criterion, {"met": 0, "partial": 0, "not_met": 0})
                if status in bucket:
                    bucket[status] += 1
    aggregate_metrics_out = {}
    for metric_name, bucket in aggregate_metrics.items():
        payload = {"count": bucket["count"], "numeric_count": bucket["numeric_count"]}
        if bucket["numeric_count"] > 0:
            payload["avg"] = bucket["sum"] / bucket["numeric_count"]
        aggregate_metrics_out[metric_name] = payload
    payload = {
        "epics": summaries,
        "aggregate_metrics": aggregate_metrics_out,
        "aggregate_acceptance": aggregate_acceptance,
    }
    if args.json:
        out_json(payload)
    else:
        if not summaries:
            print("No scan metrics recorded.")
            return
        for entry in summaries:
            print(f"{entry.get('epic_id','?')}:")
            print(f"  roi_metrics: {len(entry.get('roi_metrics', {}))}")
            print(f"  acceptance_checks: {len(entry.get('acceptance_checks', {}))}")
            print(f"  updated_at: {entry.get('updated_at','')}")
        if aggregate_metrics_out:
            print("\nAggregate ROI metrics:")
            for metric_name, metric_payload in sorted(aggregate_metrics_out.items()):
                avg = metric_payload.get("avg")
                if avg is None:
                    print(f"  {metric_name}: count={metric_payload['count']}")
                else:
                    print(
                        f"  {metric_name}: count={metric_payload['count']} "
                        f"avg={avg:.4f}"
                    )
        if aggregate_acceptance:
            print("\nAggregate acceptance checks:")
            for criterion, counts in sorted(aggregate_acceptance.items()):
                print(
                    f"  {criterion}: met={counts['met']} "
                    f"partial={counts['partial']} not_met={counts['not_met']}"
                )


# ---------------------------------------------------------------------------
# epic commands
# ---------------------------------------------------------------------------

def _derive_start_title(requirements: str, explicit_title: str = "") -> str:
    """Build a concise epic title from a fuzzy requirement."""
    source = explicit_title if explicit_title.strip() else requirements
    title = re.sub(r"\s+", " ", source).strip()
    if not title:
        err("Requirement text is empty. Provide a short problem statement or use --title.")
    title = title[:60].rstrip(" ,.;:-")
    return title or "untitled epic"


def _create_epic(h: Path, title: str, risk_level: str, description: str = "") -> dict:
    """Create epic metadata and initial state, then persist both."""
    config = load_json(h / CONFIG_FILE)
    if risk_level not in RISK_LEVELS:
        err(f"Invalid risk_level: {risk_level}. Must be one of {RISK_LEVELS}")

    # Detect profile type from project profile
    profile_path = h / PROFILE_FILE
    profile_type = "unknown"
    if profile_path.exists():
        parsed = _parse_simple_yaml(profile_path.read_text(encoding="utf-8"))
        profile_type = parsed.get("type", "unknown")

    n = next_epic_number(h)
    epic_id = make_epic_id(n, title)
    interrupt_budget_total = config.get("interrupt_budget", 2)

    epic = {
        "id": epic_id,
        "title": title,
        "description": description,
        "state": "CLARIFY",
        "risk_level": risk_level,
        "profile_type": profile_type,
        "created_at": now_iso(),
        "interrupt_budget": {
            "total": interrupt_budget_total,
            "consumed": 0,
        },
        "tasks": [],
        "repo_worktrees": {},
    }

    # Save epic
    save_epic(h, epic)

    # Create features/{id}/state.json
    state = {
        "version": VERSION,
        "current_stage": "CLARIFY",
        "epic_id": epic_id,
        "risk_level": risk_level,
        "project_profile": profile_type,
        "interrupt_budget": {
            "total": interrupt_budget_total,
            "consumed": 0,
            "remaining": interrupt_budget_total,
        },
        "stage_history": [
            {
                "from": None,
                "to": "CLARIFY",
                "at": now_iso(),
                "actor": "harnessctl",
            }
        ],
        "pending_decisions": [],
        "runtime_health": {
            "consecutive_failures": 0,
            "drift_detected": False,
            "last_smoke_pass": None,
        },
        "updated_at": now_iso(),
    }
    save_state(h, state)
    return epic


def _next_action_for_state(state: dict) -> str:
    """Mirror auto-mode next action resolution for the current state."""
    budget_remaining = state.get("interrupt_budget", {}).get("remaining", 0)
    has_pending_confirms = len(state.get("pending_decisions", [])) > 0
    if has_pending_confirms and budget_remaining > 0:
        return "wait_user"
    return _STAGE_NEXT_ACTION.get(state.get("current_stage", ""), "wait_user")


def cmd_start(args, project_root: Path) -> None:
    """Bootstrap stage-harness and create the first epic from a fuzzy requirement."""
    project_root = project_root.resolve()
    original_project_root = project_root
    h = project_root / HARNESS_DIR
    initialized = False
    bootstrap_retry = None
    if not h.is_dir():
        try:
            h = _initialize_harness(project_root, force=False)
            initialized = True
        except OSError as exc:
            cwd_root = Path.cwd().resolve()
            can_retry_in_cwd = (
                not getattr(args, "project_root", None)
                and _is_permission_like_os_error(exc)
                and cwd_root != project_root
                and _dir_is_writable(cwd_root)
                and not (original_project_root / HARNESS_DIR).exists()
            )
            if not can_retry_in_cwd:
                err(f"failed to initialize {project_root / HARNESS_DIR}: {exc}")
            retry_reason = (
                f"failed to initialize {project_root / HARNESS_DIR}: {exc}; "
                f"retrying bootstrap in current directory {cwd_root}"
            )
            print(f"warning: {retry_reason}", file=sys.stderr)
            try:
                h = _initialize_harness(cwd_root, force=False)
            except OSError as retry_exc:
                err(
                    f"failed to initialize {project_root / HARNESS_DIR}: {exc}; "
                    f"retry at {cwd_root / HARNESS_DIR} also failed: {retry_exc}"
                )
            project_root = cwd_root
            initialized = True
            bootstrap_retry = {
                "from": str(original_project_root),
                "to": str(cwd_root),
                "reason": str(exc),
            }

    profile = _detect_profile_data(h, project_root)

    config = load_json(h / CONFIG_FILE)
    risk_level = getattr(args, "risk_level", None) or config.get("risk_level", "medium")
    title = _derive_start_title(args.requirements, getattr(args, "title", ""))
    epic = _create_epic(h, title, risk_level, args.requirements.strip())
    state = load_state(h, epic["id"])
    next_action = _next_action_for_state(state)
    next_command = f"/harness:auto {epic['id']}" if next_action == "run_clarify" else next_action
    manual_next_command = f"/harness:clarify {epic['id']}" if next_action == "run_clarify" else next_action

    append_trace_event(h, _make_trace_event(
        epic["id"], "start_bootstrapped",
        stage=state.get("current_stage", ""),
        command_name="harnessctl start",
        summary=f"Bootstrapped harness and created epic {epic['id']}",
        payload={
            "initialized": initialized,
            "title": title,
            "requirements_excerpt": re.sub(r"\s+", " ", args.requirements).strip()[:200],
            "next_action": next_action,
            "project_root": str(project_root),
            **({"bootstrap_retry": bootstrap_retry} if bootstrap_retry else {}),
        },
        artifact_paths=[
            str(h / PROFILE_FILE),
            str(h / "epics" / f"{epic['id']}.json"),
            str(h / "features" / epic["id"] / "state.json"),
        ],
    ))

    payload = {
        "status": "ok",
        "project_root": str(project_root),
        "harness_dir": str(h),
        "initialized": initialized,
        "epic_id": epic["id"],
        "title": title,
        "current_stage": state.get("current_stage", ""),
        "next_action": next_action,
        "next_command": next_command,
        "manual_next_command": manual_next_command,
        "profile": {
            "type": profile.get("type", "unknown"),
            "workspace_mode": profile.get("workspace_mode", "single-repo"),
            "confidence": profile.get("confidence", 0.0),
        },
    }
    if bootstrap_retry:
        payload["bootstrap_retry"] = bootstrap_retry
    if args.json:
        out_json(payload)
    else:
        print("Stage-Harness bootstrap complete")
        print(f"  project_root:   {project_root}")
        print(f"  initialized:    {'yes' if initialized else 'no'}")
        print(f"  profile:        {payload['profile']['type']} ({payload['profile']['workspace_mode']})")
        print(f"  epic:           {epic['id']} | {title}")
        print(f"  current_stage:  {payload['current_stage']}")
        print(f"  next_action:    {next_action}")
        print(f"  next_step:      {next_command}")
        if manual_next_command != next_command:
            print(f"  manual_step:    {manual_next_command}")


def cmd_epic_create(args, h: Path) -> None:
    title = (getattr(args, "title_flag", "") or getattr(args, "title", "")).strip()
    if not title:
        err("Epic title is required. Pass it positionally or via --title.")
    description = getattr(args, "description", "").strip()
    config = load_json(h / CONFIG_FILE)
    risk_level = getattr(args, "risk_level", None) or config.get("risk_level", "medium")
    epic = _create_epic(h, title, risk_level, description)

    if args.json:
        out_json(epic)
    else:
        print(f"Created epic: {epic['id']}")
        print(f"  title:      {title}")
        if description:
            print(f"  description:{' ' * 4}{description}")
        print(f"  state:      CLARIFY")
        print(f"  risk_level: {risk_level}")


def cmd_epic_show(args, h: Path) -> None:
    epic = load_epic(h, args.id)
    if args.json:
        out_json(epic)
    else:
        print(json.dumps(epic, indent=2, ensure_ascii=False))


def cmd_epic_list(args, h: Path) -> None:
    epics_dir = h / "epics"
    epics = []
    if epics_dir.exists():
        for f in sorted(epics_dir.glob("sh-*.json")):
            try:
                epics.append(load_json(f))
            except SystemExit:
                continue
    if args.json:
        out_json(epics)
    else:
        if not epics:
            print("No epics found.")
            return
        header = f"{'ID':<30} {'STATE':<10} {'RISK':<8} TITLE"
        print(header)
        print("-" * 80)
        for ep in epics:
            print(f"{ep['id']:<30} {ep['state']:<10} {ep['risk_level']:<8} {ep['title']}")


# ---------------------------------------------------------------------------
# task commands
# ---------------------------------------------------------------------------

def cmd_task_create(args, h: Path) -> None:
    epic_id = args.epic_id
    title = args.title

    # Validate epic exists
    epic = load_epic(h, epic_id)

    n = next_task_number(h, epic_id)
    task_id = make_task_id(epic_id, n)
    surface = getattr(args, "surface", "") or ""

    task = {
        "id": task_id,
        "epic_id": epic_id,
        "title": title,
        "status": "pending",
        "surface": surface,
        "dependencies": [],
        "acceptance_criteria": [],
        "evidence": {},
        "receipts": [],
    }

    # Save task file
    task_path = h / "tasks" / f"{epic_id}.{n}.json"
    atomic_write_json(task_path, task)

    # Update epic task list (immutable update)
    updated_epic = dict(epic)
    updated_epic["tasks"] = list(epic.get("tasks", [])) + [task_id]
    save_epic(h, updated_epic)

    if args.json:
        out_json(task)
    else:
        print(f"Created task: {task_id}")
        print(f"  epic:   {epic_id}")
        print(f"  title:  {title}")
        print(f"  status: pending")


def _update_task_status(args, h: Path, new_status: str) -> None:
    task, task_path = load_task(h, args.task_id)
    updated = dict(task)
    updated["status"] = new_status
    atomic_write_json(task_path, updated)
    # Emit trace event
    append_trace_event(h, _make_trace_event(
        task.get("epic_id", ""),
        "task_status_changed",
        task_id=args.task_id,
        command_name=f"harnessctl task {new_status}",
        summary=f"Task {args.task_id} -> {new_status}",
        payload={"task_id": args.task_id, "new_status": new_status},
    ))
    if args.json:
        out_json(updated)
    else:
        print(f"Task {args.task_id} status -> {new_status}")


def cmd_task_start(args, h: Path) -> None:
    _update_task_status(args, h, "in_progress")


def cmd_task_done(args, h: Path) -> None:
    _update_task_status(args, h, "done")


def cmd_task_fail(args, h: Path) -> None:
    _update_task_status(args, h, "failed")


def cmd_task_block(args, h: Path) -> None:
    _update_task_status(args, h, "blocked")


# ---------------------------------------------------------------------------
# state commands
# ---------------------------------------------------------------------------

def cmd_state_get(args, h: Path) -> None:
    state = load_state(h, args.epic_id)
    field = getattr(args, "field", None)
    if field:
        # Navigate dotted path
        parts = field.split(".")
        val = state
        for p in parts:
            if isinstance(val, dict) and p in val:
                val = val[p]
            else:
                err(f"Field not found: {field}")
        if args.json:
            out_json({field: val})
        else:
            print(val)
        return
    if args.json:
        out_json(state)
    else:
        print(json.dumps(state, indent=2, ensure_ascii=False))


def _set_nested(d: dict, dotted_key: str, value) -> None:
    """Set a nested dict value by dotted key path, creating intermediate dicts."""
    parts = dotted_key.split(".")
    for p in parts[:-1]:
        if p not in d or not isinstance(d[p], dict):
            d[p] = {}
        d = d[p]
    d[parts[-1]] = value


def cmd_state_patch(args, h: Path) -> None:
    """Patch specific fields in epic state using --set key=value syntax."""
    epic_id = args.epic_id
    state = load_state(h, epic_id)
    updated_state = dict(state)

    for assignment in args.set:
        if "=" not in assignment:
            err(f"Invalid --set syntax: '{assignment}'. Expected key=value")
        key, _, raw_val = assignment.partition("=")
        # Auto-convert to appropriate type
        if raw_val.lower() in ("true", "false"):
            value = raw_val.lower() == "true"
        elif raw_val.isdigit():
            value = int(raw_val)
        else:
            try:
                value = float(raw_val)
            except ValueError:
                value = raw_val
        _set_nested(updated_state, key, value)

    updated_state["updated_at"] = now_iso()
    save_state(h, updated_state)

    if args.json:
        out_json({"status": "ok", "epic_id": epic_id})
    else:
        print(f"Patched state for {epic_id}")
        for assignment in args.set:
            print(f"  {assignment}")


# Stage → next action mapping for harness-auto
_STAGE_NEXT_ACTION = {
    "CLARIFY": "run_clarify",
    "SPEC": "run_spec",
    "PLAN": "run_plan",
    "EXECUTE": "run_execute",
    "VERIFY": "run_verify",
    "FIX": "run_verify",
    "DONE": "complete",
}


def cmd_state_next(args, h: Path) -> None:
    """Return the next action to take for an epic in auto mode."""
    epic_id = args.epic_id
    state = load_state(h, epic_id)
    current = state["current_stage"]

    # If EXECUTE and all tasks done, suggest moving to VERIFY
    if current == "EXECUTE":
        not_done = []
        for f in iter_task_files(h, epic_id) or []:
            try:
                t = load_json(f)
                status = normalize_task_status(t.get("status", "pending"))
                if status not in ("done", "blocked"):
                    not_done.append(t["id"])
            except SystemExit:
                continue
        if not not_done:
            action = "run_verify"
        else:
            action = "run_execute"
    else:
        action = _STAGE_NEXT_ACTION.get(current, "wait_user")

    budget_remaining = state.get("interrupt_budget", {}).get("remaining", 0)
    has_pending_confirms = len(_effective_pending_decisions(h, state)) > 0

    if has_pending_confirms and budget_remaining > 0:
        action = "wait_user"

    append_trace_event(h, _make_trace_event(
        epic_id, "next_action_evaluated",
        stage=current,
        command_name="harnessctl state next",
        summary=f"Next action for {current}: {action}",
        payload={
            "current_stage": current,
            "next_action": action,
            "budget_remaining": budget_remaining,
            "has_pending_confirms": has_pending_confirms,
        },
    ))

    if args.json:
        out_json({
            "epic_id": epic_id,
            "current_stage": current,
            "next_action": action,
            "budget_remaining": budget_remaining,
        })
    else:
        print(action)


def cmd_state_transition(args, h: Path) -> None:
    epic_id = args.epic_id
    new_stage = args.new_stage.upper()

    if new_stage not in STAGES:
        err(f"Unknown stage: {new_stage}. Valid stages: {STAGES}")

    state = load_state(h, epic_id)
    current = state["current_stage"]

    allowed = TRANSITIONS.get(current, [])
    if new_stage not in allowed:
        err(
            f"Invalid transition: {current} -> {new_stage}. "
            f"Allowed from {current}: {allowed}"
        )

    # Build transition log entry
    log_entry = {
        "from": current,
        "to": new_stage,
        "at": now_iso(),
        "actor": "harnessctl",
    }

    # Immutable update of state
    updated_state = dict(state)
    updated_state["current_stage"] = new_stage
    updated_state["stage_history"] = list(state.get("stage_history", [])) + [log_entry]
    updated_state["updated_at"] = now_iso()

    save_state(h, updated_state)

    # Emit trace event
    append_trace_event(h, _make_trace_event(
        epic_id, "state_transitioned",
        stage=new_stage,
        command_name="harnessctl state transition",
        summary=f"{current} -> {new_stage}",
        payload={"from": current, "to": new_stage, "actor": "harnessctl"},
    ))

    # Also update epic state field
    try:
        epic = load_epic(h, epic_id)
        updated_epic = dict(epic)
        updated_epic["state"] = new_stage
        save_epic(h, updated_epic)
    except SystemExit:
        pass  # Epic file may not exist in edge cases

    if args.json:
        out_json({"epic_id": epic_id, "from": current, "to": new_stage, "at": log_entry["at"]})
    else:
        print(f"Transitioned {epic_id}: {current} -> {new_stage}")


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

def cmd_status(args, h: Path) -> None:
    epics_dir = h / "epics"
    epics = []
    if epics_dir.exists():
        for f in sorted(epics_dir.glob("sh-*.json")):
            try:
                epics.append(load_json(f))
            except SystemExit:
                continue

    if args.json:
        rows = []
        for ep in epics:
            # Count tasks
            task_counts = _count_tasks(h, ep["id"])
            rows.append({
                "id": ep["id"],
                "title": ep["title"],
                "stage": ep["state"],
                "risk_level": ep["risk_level"],
                "tasks": task_counts,
            })
        out_json({"epics": rows, "total": len(rows)})
        return

    if not epics:
        print("No epics found. Run 'harnessctl epic create <title>' to begin.")
        return

    print(f"{'ID':<30} {'STAGE':<10} {'RISK':<8} {'TASKS':<20} TITLE")
    print("-" * 90)
    for ep in epics:
        task_counts = _count_tasks(h, ep["id"])
        done = task_counts.get("done", 0)
        total = task_counts.get("total", 0)
        tasks_str = f"{done}/{total}"
        print(f"{ep['id']:<30} {ep['state']:<10} {ep['risk_level']:<8} {tasks_str:<20} {ep['title']}")


def _count_tasks(h: Path, epic_id: str) -> dict:
    """Return task count summary for an epic."""
    counts = {"total": 0, "pending": 0, "in_progress": 0, "done": 0, "failed": 0, "blocked": 0}
    for f in iter_task_files(h, epic_id) or []:
        try:
            t = load_json(f)
            counts["total"] += 1
            status = normalize_task_status(t.get("status", "pending"))
            if status in counts:
                counts[status] += 1
        except SystemExit:
            continue
    return counts


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

def cmd_validate(args, h: Path) -> None:
    issues = []

    # Check all required subdirs
    for sub in SUBDIRS:
        if not (h / sub).is_dir():
            issues.append(f"missing directory: {sub}/")

    # Check config
    config_path = h / CONFIG_FILE
    if not config_path.exists():
        issues.append("missing config.json")
    else:
        try:
            load_json(config_path)
        except SystemExit:
            issues.append("config.json is invalid JSON")

    # Check profile
    profile_path = h / PROFILE_FILE
    if not profile_path.exists():
        issues.append("missing project-profile.yaml")

    # Check epic/state consistency
    epics_dir = h / "epics"
    if epics_dir.exists():
        for f in epics_dir.glob("sh-*.json"):
            try:
                ep = load_json(f)
            except SystemExit:
                issues.append(f"invalid JSON in epic: {f.name}")
                continue
            eid = ep.get("id", "")
            state_path = h / "features" / eid / "state.json"
            if not state_path.exists():
                issues.append(f"missing state for epic: {eid}")

    if args.json:
        out_json({"valid": len(issues) == 0, "issues": issues})
    else:
        if not issues:
            print("Validation passed.")
        else:
            print(f"Validation failed with {len(issues)} issue(s):")
            for issue in issues:
                print(f"  - {issue}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# task show / list / next helpers
# ---------------------------------------------------------------------------

def cmd_task_show(args, h: Path) -> None:
    task, _ = load_task(h, args.task_id)
    if args.json:
        out_json(task)
    else:
        print(json.dumps(task, indent=2, ensure_ascii=False))


def cmd_task_list(args, h: Path) -> None:
    """List tasks for an epic, optionally filtered by status."""
    epic_id = args.epic_id
    status_filter = getattr(args, "status", None)

    tasks = []
    normalized_filter = normalize_task_status(status_filter) if status_filter else None
    for f in sorted(iter_task_files(h, epic_id) or []):
        try:
            t = load_json(f)
            t["status"] = normalize_task_status(t.get("status", "pending"))
            if normalized_filter and t.get("status") != normalized_filter:
                continue
            tasks.append(t)
        except SystemExit:
            continue

    if args.json:
        out_json(tasks)
    else:
        if not tasks:
            print(f"No tasks found for {epic_id}" + (f" (status={status_filter})" if status_filter else ""))
            return
        header = f"{'ID':<20} {'STATUS':<12} TITLE"
        print(header)
        print("-" * 60)
        for t in tasks:
            print(f"{t['id']:<20} {t.get('status','?'):<12} {t.get('title','')}")


def cmd_task_next(args, h: Path) -> None:
    """Return the next pending/unblocked task for an epic."""
    epic_id = args.epic_id
    candidates = []

    for f in sorted(iter_task_files(h, epic_id) or []):
        try:
            t = load_json(f)
            t["status"] = normalize_task_status(t.get("status", "pending"))
            if t.get("status") == "pending":
                candidates.append(t)
        except SystemExit:
            continue

    if not candidates:
        if args.json:
            out_json({"task_id": None, "message": "no pending tasks"})
        else:
            print("No pending tasks remaining.")
        return

    # Find task whose dependencies are all done
    done_ids: set = set()
    for f in iter_task_files(h, epic_id) or []:
        try:
            t = load_json(f)
            if normalize_task_status(t.get("status", "pending")) == "done":
                done_ids.add(t["id"])
        except SystemExit:
            continue

    for t in candidates:
        deps = t.get("dependencies", [])
        if all(d in done_ids for d in deps):
            if args.json:
                out_json(t)
            else:
                print(f"Next task: {t['id']}  {t.get('title','')}")
            return

    if args.json:
        out_json({"task_id": None, "message": "all remaining tasks are blocked by dependencies"})
    else:
        print("All remaining tasks are blocked by unresolved dependencies.")


# ---------------------------------------------------------------------------
# stage-gate command
# ---------------------------------------------------------------------------

# Stage gate artifact requirements (authoritative — verify-artifacts.sh must stay in sync)
STAGE_GATE_ARTIFACTS = {
    "CLARIFY": [
        "{features_dir}/domain-frame.json",         # domain-scout（CLARIFY Step 0）
        "{features_dir}/generated-scenarios.json",  # scenario-expander
        "{features_dir}/scenario-coverage.json",    # Semantic Reconciliation coverage ledger
        "{features_dir}/requirements-draft.md",     # requirement-analyst
        "{features_dir}/challenge-report.md",       # challenger 落盘
        "{features_dir}/clarification-notes.md",   # 澄清笔记（含 Domain Frame）
        "{features_dir}/impact-scan.md",            # 代码库影响扫描
        "{features_dir}/surface-routing.json",    # 承载面路由与扫描预算（project-surface / Lead）
        "{features_dir}/unknowns-ledger.json",      # 未知问题台账
        "{features_dir}/decision-bundle.json",      # 全量决策分类
        "{features_dir}/decision-packet.json",      # must_confirm 打包
    ],
    "SPEC": [
        ".harness/specs/{epic_id}.md",              # harness 规格文档（harness-spec 产出）
        "{features_dir}/spec-council-notes.md",     # 轻议会意见（harness-spec 产出）
        "{features_dir}/scenario-coverage.json",    # 场景覆盖台账供 spec/review 消费
    ],
    "PLAN": [
        "{features_dir}/bridge-spec.md",
        "{features_dir}/coverage-matrix.json",
        "{features_dir}/surface-routing.json",  # 须与 CLARIFY 产物一致，供 scouts 强约束
    ],
    "EXECUTE": [],
    "VERIFY": [
        "{features_dir}/verification.json",
    ],
    "DONE": [
        "{features_dir}/delivery-summary.md",
        "{features_dir}/release-notes.md",
        "{features_dir}/councils/verdict-release_council.json",
    ],
}

# CLARIFY when config clarify_closure_mode=notes_only (verify-artifacts.sh must stay in sync)
CLARIFY_ARTIFACTS_NOTES_ONLY = [
    "{features_dir}/clarification-notes.md",
]


def _stage_gate_artifacts_spec(stage: str, h: Path) -> list[str] | None:
    harness_cfg = merged_harness_config(h)
    clarify_notes_only = (
        stage == "CLARIFY"
        and str(harness_cfg.get("clarify_closure_mode", "full")).lower() == "notes_only"
    )
    if clarify_notes_only:
        return list(CLARIFY_ARTIFACTS_NOTES_ONLY)
    artifacts_spec = STAGE_GATE_ARTIFACTS.get(stage)
    return list(artifacts_spec) if artifacts_spec is not None else None


def _coupling_closure_gate_mode(harness_cfg: dict) -> str:
    raw = str(harness_cfg.get("coupling_closure_gate_mode", "warn")).strip().lower()
    return raw if raw in {"off", "warn", "strict"} else "warn"


_CRI_FANOUT_MODES = frozenset({"repo_wave", "single_agent"})


def _cross_repo_impact_index_errors(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"]
    repos = data.get("repos")
    if not isinstance(repos, list) or len(repos) == 0:
        errors.append("repos must be a non-empty JSON array")
    elif not any(
        isinstance(item, dict) and str(item.get("repo_id", "")).strip()
        for item in repos
    ):
        errors.append("repos must include at least one object with non-empty `repo_id`")

    fd = data.get("fanout_decision")
    if "fanout_decision" not in data:
        errors.append("missing required top-level key `fanout_decision`")
    elif not isinstance(fd, dict):
        errors.append("fanout_decision must be a JSON object")
    else:
        mode = str(fd.get("mode", "")).strip()
        if not mode:
            errors.append("fanout_decision.mode must be a non-empty string")
        elif mode not in _CRI_FANOUT_MODES:
            errors.append(
                "fanout_decision.mode must be one of: repo_wave, single_agent "
                f"(got {mode!r})"
            )
        reason = str(fd.get("reason", "")).strip()
        if not reason:
            errors.append("fanout_decision.reason must be a non-empty string")
        repo_ids = fd.get("repo_ids")
        if not isinstance(repo_ids, list):
            errors.append("fanout_decision.repo_ids must be a JSON array")
        else:
            non_empty_ids = [x for x in repo_ids if str(x).strip()]
            if mode == "repo_wave" and not non_empty_ids:
                errors.append(
                    "fanout_decision.repo_ids must be non-empty when mode is repo_wave"
                )
            elif mode == "single_agent" and non_empty_ids:
                errors.append(
                    "fanout_decision.repo_ids must be empty when mode is single_agent"
                )
    return errors


def cmd_stage_gate_check(args, h: Path, project_root: Path) -> None:
    stage = args.stage.upper()
    epic_id = args.epic_id
    features_dir = h / "features" / epic_id
    harness_cfg = merged_harness_config(h)
    clarify_notes_only = (
        stage == "CLARIFY"
        and str(harness_cfg.get("clarify_closure_mode", "full")).lower() == "notes_only"
    )
    artifacts_spec = _stage_gate_artifacts_spec(stage, h)

    if artifacts_spec is None:
        if args.json:
            out_json({"stage": stage, "passed": True, "message": f"no gate defined for {stage}"})
        else:
            print(f"⚠️  No stage gate defined for: {stage}")
        return

    missing = []
    present = []
    warnings = []
    profile_data = {}
    profile_path = h / PROFILE_FILE
    if profile_path.exists():
        try:
            profile_data = _parse_simple_yaml(profile_path.read_text(encoding="utf-8"))
        except OSError:
            profile_data = {}
    coupling_role_ids = coupling_role_ids_from_profile(profile_data)
    coupling_gate_mode = _coupling_closure_gate_mode(harness_cfg)

    spec_file = spec_path_for_epic(h, epic_id)
    strict_semantic = bool(harness_cfg.get("spec_semantic_hints_strict", False))

    for tmpl in artifacts_spec:
        path_str = tmpl.format(features_dir=str(features_dir), epic_id=epic_id)
        p = Path(path_str)
        # For non-absolute paths, resolve relative to project_root
        if not p.is_absolute():
            p = project_root / p

        if p.exists():
            # For directories, check they are non-empty
            if p.is_dir():
                if any(p.iterdir()):
                    present.append(path_str)
                else:
                    missing.append(f"{path_str} (empty directory)")
            elif p.stat().st_size == 0:
                missing.append(f"{path_str} (empty file)")
            else:
                present.append(path_str)
        else:
            missing.append(path_str)

    if stage == "SPEC" and spec_file.exists() and not _spec_has_acceptance_criteria(spec_file):
        missing.append(f"{spec_file} (missing Acceptance Criteria section)")

    if stage == "SPEC" and spec_file.exists():
        for hint in _spec_semantic_warnings(spec_file):
            if strict_semantic:
                missing.append(f"{spec_file} (semantic gate: {hint})")
            else:
                print(f"  ⚠️  semantic hint: {hint}")

    if stage == "CLARIFY":
        for msg in _clarify_notes_only_closure_errors(features_dir):
            missing.append(msg)
        for msg in clarify_focus_point_closure_errors(features_dir):
            missing.append(msg)
        if not clarify_notes_only:
            for msg in clarify_state_constraint_signal_scn_focus_errors(features_dir):
                missing.append(msg)
        if bool(harness_cfg.get("clarify_signal_gate_enabled", True)):
            for msg in _clarify_signal_gate_errors(features_dir):
                missing.append(msg)
            if not clarify_notes_only:
                for msg in _clarify_signal_closure_errors(features_dir):
                    missing.append(msg)
        if bool(harness_cfg.get("clarify_deep_dive_enabled", True)):
            if (
                not clarify_notes_only
                and bool(harness_cfg.get("clarify_deep_dive_gate_strict", False))
            ):
                for msg in _clarify_deep_dive_gate_errors(features_dir):
                    missing.append(msg)

    if stage == "CLARIFY" and not clarify_notes_only:
        if coupling_gate_mode != "off":
            for msg in profile_coupling_role_errors(profile_data):
                target = missing if coupling_gate_mode == "strict" else warnings
                target.append(msg)

        df_path = features_dir / "domain-frame.json"
        if df_path.exists():
            try:
                df_data = json.loads(df_path.read_text(encoding="utf-8"))
                for key in domain_frame_missing_required_keys(df_data):
                    missing.append(f"{df_path} (missing key: {key})")
                for opt_key in ("state_transition_scenarios", "constraint_conflicts"):
                    if opt_key in df_data and not isinstance(df_data[opt_key], list):
                        missing.append(
                            f"{df_path} ({opt_key} must be a JSON array when present)"
                        )
            except json.JSONDecodeError:
                missing.append(f"{df_path} (invalid JSON)")
        gen_path = features_dir / "generated-scenarios.json"
        if gen_path.exists():
            try:
                gen_data = json.loads(gen_path.read_text(encoding="utf-8"))
                for msg in generated_scenarios_strict_errors(gen_data):
                    missing.append(f"{gen_path} ({msg})")
            except json.JSONDecodeError:
                missing.append(f"{gen_path} (invalid JSON)")
        coverage_path = features_dir / "scenario-coverage.json"
        if coverage_path.exists():
            try:
                coverage_data = json.loads(coverage_path.read_text(encoding="utf-8"))
                for msg in scenario_coverage_strict_errors(coverage_data):
                    missing.append(f"{coverage_path} ({msg})")
            except json.JSONDecodeError:
                missing.append(f"{coverage_path} (invalid JSON)")
        ch_path = features_dir / "challenge-report.md"
        if ch_path.exists():
            ch_text = ch_path.read_text(encoding="utf-8")
            if not re.search(r"(?im)^##\s+summary\b", ch_text):
                missing.append(f"{ch_path} (missing ## Summary section)")
            if strict_semantic and not re.search(r"(?im)Traceability", ch_text):
                missing.append(f"{ch_path} (semantic gate: missing Domain Frame Traceability)")

        req_path = features_dir / "requirements-draft.md"
        if req_path.exists() and strict_semantic:
            req_text = req_path.read_text(encoding="utf-8")
            if not re.search(r"(?im)Traceability", req_text):
                missing.append(f"{req_path} (semantic gate: missing Domain Frame Traceability)")

        impact_path = features_dir / "impact-scan.md"
        if impact_path.exists():
            impact_text = impact_path.read_text(encoding="utf-8")
            required_headings = (
                "Blast Radius Summary",
                "High Impact Surfaces",
                "Medium Impact Surfaces",
            )
            for heading in required_headings:
                if not re.search(rf"(?im)^##\s+{re.escape(heading)}\b", impact_text):
                    missing.append(f"{impact_path} (missing ## {heading} section)")

        sr_path = features_dir / "surface-routing.json"
        sr_data = {}
        if sr_path.exists():
            try:
                sr_data = json.loads(sr_path.read_text(encoding="utf-8"))
                if not isinstance(sr_data, dict):
                    missing.append(f"{sr_path} (root must be a JSON object)")
                else:
                    surfaces = sr_data.get("surfaces")
                    if not isinstance(surfaces, list) or len(surfaces) < 1:
                        missing.append(
                            f"{sr_path} (surfaces must be a non-empty array)"
                        )
                    else:
                        for idx, surf in enumerate(surfaces):
                            if not isinstance(surf, dict):
                                missing.append(
                                    f"{sr_path} (surfaces[{idx}] must be an object)"
                                )
                                break
                            if "type" not in surf or "path" not in surf:
                                missing.append(
                                    f"{sr_path} (surfaces[{idx}] missing type or path)"
                                )
                                break
                    if coupling_gate_mode != "off" and coupling_role_ids:
                        target = missing if coupling_gate_mode == "strict" else warnings
                        for msg in surface_routing_coupling_errors(sr_data, coupling_role_ids):
                            target.append(msg)
            except json.JSONDecodeError:
                missing.append(f"{sr_path} (invalid JSON)")

        if coupling_gate_mode != "off" and coupling_role_ids:
            closure_path = features_dir / "change-coupling-closure.json"
            if closure_path.exists():
                try:
                    closure_data = json.loads(closure_path.read_text(encoding="utf-8"))
                    target = missing if coupling_gate_mode == "strict" else warnings
                    for msg in change_coupling_closure_errors(closure_data, coupling_role_ids):
                        target.append(msg)
                    if coupling_gate_mode in {"warn", "strict"}:
                        for msg in change_coupling_closure_warnings(closure_data, sr_data, coupling_role_ids):
                            warnings.append(msg)
                except json.JSONDecodeError:
                    target = missing if coupling_gate_mode == "strict" else warnings
                    target.append(f"{closure_path} (invalid JSON)")
            else:
                warnings.append(
                    f"{closure_path} (project-profile declares coupling_role_ids but this epic has no closure review yet)"
                )

        if _workspace_mode(h) == "multi-repo":
            cri_path = features_dir / "cross-repo-impact-index.json"
            if cri_path.exists():
                try:
                    cri = json.loads(cri_path.read_text(encoding="utf-8"))
                    for msg in _cross_repo_impact_index_errors(cri):
                        missing.append(f"{cri_path} ({msg})")
                except json.JSONDecodeError:
                    missing.append(f"{cri_path} (invalid JSON)")
            else:
                missing.append(str(cri_path))

        cn_path = features_dir / "clarification-notes.md"
        if cn_path.exists():
            cn_text = cn_path.read_text(encoding="utf-8")
            if strict_semantic and not re.search(r"(?im)Traceability", cn_text):
                missing.append(f"{cn_path} (semantic gate: missing Traceability Matrix)")

        for hint in _clarify_semantic_warnings(features_dir):
            if strict_semantic:
                missing.append(f"CLARIFY (semantic gate: {hint})")
            else:
                print(f"  ⚠️  CLARIFY semantic hint: {hint}")
        if bool(harness_cfg.get("clarify_deep_dive_enabled", True)):
            for hint in _clarify_deep_dive_hints(features_dir):
                print(f"  ⚠️  CLARIFY deep-dive hint: {hint}")

    if stage == "PLAN":
        task_files = list(iter_task_files(h, epic_id) or [])
        if not task_files:
            missing.append(f".harness/tasks/{epic_id}.*.json (no tasks created)")

        matrix_path = features_dir / "coverage-matrix.json"
        if matrix_path.exists():
            try:
                matrix = load_json(matrix_path)
                coverage_pct = _coverage_pct(matrix)
                if coverage_pct is not None and coverage_pct < 80.0:
                    missing.append(f"{matrix_path} (coverage below 80%: {coverage_pct:.1f}%)")
            except SystemExit:
                missing.append(f"{matrix_path} (invalid JSON)")

        codemap_audit_path = features_dir / "codemap-audit.json"
        codemap_root = h / "memory" / "codemaps"
        if codemap_audit_path.exists():
            try:
                audit = load_json(codemap_audit_path)
                summary = audit.get("summary", {}) if isinstance(audit, dict) else {}
                stale = int(summary.get("stale", 0) or 0)
                invalid = int(summary.get("invalid", 0) or 0)
                if stale > 0 or invalid > 0:
                    warnings.append(
                        f"{codemap_audit_path} (stale={stale}, invalid={invalid}; treat cached codemaps as low-confidence background)"
                    )
            except SystemExit:
                warnings.append(f"{codemap_audit_path} (invalid JSON; ignore cached codemaps until re-audited)")
        elif codemap_root.exists() and any(codemap_root.rglob("*.md")):
            warnings.append(
                f"{codemap_root} (codemaps exist but no {features_dir / 'codemap-audit.json'}; run memory codemap-audit before trusting cache)"
            )

        if coupling_gate_mode != "off" and coupling_role_ids:
            for msg in profile_coupling_role_errors(profile_data):
                target = missing if coupling_gate_mode == "strict" else warnings
                target.append(msg)
            sr_path = features_dir / "surface-routing.json"
            sr_data = {}
            if sr_path.exists():
                try:
                    sr_data = json.loads(sr_path.read_text(encoding="utf-8"))
                    target = missing if coupling_gate_mode == "strict" else warnings
                    for msg in surface_routing_coupling_errors(sr_data, coupling_role_ids):
                        target.append(msg)
                except json.JSONDecodeError:
                    sr_data = {}
            closure_path = features_dir / "change-coupling-closure.json"
            if closure_path.exists():
                try:
                    closure_data = json.loads(closure_path.read_text(encoding="utf-8"))
                    target = missing if coupling_gate_mode == "strict" else warnings
                    for msg in change_coupling_closure_errors(closure_data, coupling_role_ids):
                        target.append(msg)
                    for msg in change_coupling_closure_warnings(closure_data, sr_data, coupling_role_ids):
                        warnings.append(msg)
                except json.JSONDecodeError:
                    if coupling_gate_mode == "strict":
                        missing.append(f"{closure_path} (invalid JSON)")
                    else:
                        warnings.append(f"{closure_path} (invalid JSON)")
            else:
                warnings.append(
                    f"{closure_path} (project-profile declares coupling_role_ids but this epic has no closure review yet)"
                )

    if stage == "VERIFY":
        verification_path = features_dir / "verification.json"
        if verification_path.exists():
            try:
                verification = load_json(verification_path)
                if not _verification_passed(verification):
                    verdict_path = council_verdict_path(h, epic_id, "acceptance_council")
                    verdict_ok = False
                    if verdict_path.exists():
                        verdict = load_json(verdict_path)
                        verdict_ok = verdict.get("verdict") in ("PASS", "CONDITIONAL_PASS")
                    if not verdict_ok:
                        missing.append(f"{verification_path} (acceptance_council not passed)")
                # If individual review dimensions are recorded, FAIL blocks the gate.
                for dim in (
                    "code_review",
                    "logic_review",
                    "test_review",
                    "security",
                    "spec_compliance",
                ):
                    raw = verification.get(dim)
                    if isinstance(raw, str) and raw.strip().upper() == "FAIL":
                        missing.append(f"{verification_path} ({dim}=FAIL)")
                critical_issues = verification.get("critical_issues", [])
                if isinstance(critical_issues, list) and critical_issues:
                    missing.append(f"{verification_path} (unresolved critical issues)")
            except SystemExit:
                missing.append(f"{verification_path} (invalid JSON)")

    if stage == "DONE":
        verdict_path = council_verdict_path(h, epic_id, "release_council")
        # 存在性由 STAGE_GATE_ARTIFACTS 主循环覆盖；此处仅做 verdict 语义校验
        if verdict_path.exists():
            try:
                verdict = load_json(verdict_path)
                if verdict.get("verdict") not in ("RELEASE_READY", "RELEASE_WITH_CONDITIONS"):
                    missing.append(f"{verdict_path} (release_council not ready)")
            except SystemExit:
                missing.append(f"{verdict_path} (invalid JSON)")

    # For EXECUTE stage, also verify all tasks are done and receipts exist in any supported directory.
    if stage == "EXECUTE":
        not_done = []
        for f in iter_task_files(h, epic_id) or []:
            try:
                t = load_json(f)
                status = normalize_task_status(t.get("status", "pending"))
                if status not in ("done", "blocked"):
                    not_done.append(t["id"])
            except SystemExit:
                continue
        if not_done:
            missing.append(f"incomplete tasks: {', '.join(not_done)}")

        if not any(directory.exists() and any(directory.iterdir()) for directory in receipt_dirs_for_epic(h, epic_id)):
            missing.append(f"{features_dir}/receipts (or runtime-receipts/runs) (empty or missing)")

    append_trace_event(h, _make_trace_event(
        epic_id, "stage_gate_checked",
        stage=stage,
        command_name="harnessctl stage-gate check",
        summary=f"Gate {stage} checked",
        payload={"present": present, "missing": missing, "warnings": warnings},
    ))

    passed = len(missing) == 0

    # Emit trace event
    _evt = "stage_gate_passed" if passed else "stage_gate_failed"
    append_trace_event(h, _make_trace_event(
        epic_id, _evt,
        stage=stage,
        status="ok" if passed else "blocked",
        command_name="harnessctl stage-gate check",
        summary=f"Gate {stage}: {'PASSED' if passed else f'BLOCKED ({len(missing)} missing)'}",
        payload={"present": present, "missing": missing, "warnings": warnings, "passed": passed},
    ))

    if args.json:
        out_json({
            "stage": stage,
            "epic_id": epic_id,
            "passed": passed,
            "present": present,
            "missing": missing,
            "warnings": warnings,
        })
    else:
        print(f"=== Stage Gate: {stage} for {epic_id} ===")
        for a in present:
            print(f"  ✅ {a}")
        for a in missing:
            print(f"  ❌ {a}")
        for a in warnings:
            print(f"  ⚠️  {a}")
        if passed:
            print(f"\nGate PASSED: {stage}")
        else:
            print(f"\nGate BLOCKED: {len(missing)} artifact(s) missing")
            sys.exit(1)


def cmd_clarify_selfcheck(args, h: Path, project_root: Path) -> None:
    """Print CLARIFY checklist: clarification-notes structure + full artifact presence."""
    epic_id = args.epic_id
    features_dir = h / "features" / epic_id
    harness_cfg = merged_harness_config(h)
    mode = str(harness_cfg.get("clarify_closure_mode", "full")).lower()
    cn_errors = _clarify_notes_only_closure_errors(features_dir)
    signal_summary = _clarify_signal_gate_summary(features_dir)
    signal_gate_enabled = bool(harness_cfg.get("clarify_signal_gate_enabled", True))
    signal_gate_errors = (
        _clarify_signal_gate_errors(features_dir)
        if signal_gate_enabled
        else []
    )
    signal_closure_errors = (
        _clarify_signal_closure_errors(features_dir)
        if (signal_gate_enabled and mode != "notes_only")
        else []
    )
    deep_dive_enabled = bool(harness_cfg.get("clarify_deep_dive_enabled", True))
    deep_dive_hints = _clarify_deep_dive_hints(features_dir) if deep_dive_enabled else []
    deep_dive_gate_errors = (
        _clarify_deep_dive_gate_errors(features_dir)
        if (deep_dive_enabled and bool(harness_cfg.get("clarify_deep_dive_gate_strict", False)))
        else []
    )
    focus_point_errors = clarify_focus_point_closure_errors(features_dir)
    state_constraint_signal_scn_focus_errors = (
        clarify_state_constraint_signal_scn_focus_errors(features_dir)
        if mode != "notes_only"
        else []
    )
    notes_core_errors = cn_errors + focus_point_errors
    clarify_closure_errors = notes_core_errors + state_constraint_signal_scn_focus_errors

    full_rows: list[dict] = []
    for tmpl in STAGE_GATE_ARTIFACTS["CLARIFY"]:
        path_str = tmpl.format(features_dir=str(features_dir), epic_id=epic_id)
        p = Path(path_str)
        if not p.is_absolute():
            p = project_root / p
        ok = p.exists() and (not p.is_file() or p.stat().st_size > 0)
        full_rows.append({"path": path_str, "present": ok})

    if args.json:
        out_json({
            "epic_id": epic_id,
            "clarify_closure_mode": mode,
            "clarification_notes_structure_errors": cn_errors,
            "clarification_notes_errors": clarify_closure_errors,
            "clarification_notes_ok": len(clarify_closure_errors) == 0,
            "clarify_signal_gate_enabled": bool(harness_cfg.get("clarify_signal_gate_enabled", True)),
            "signal_gate_required_axes": signal_summary.get("required_axes", {}),
            "signal_gate_hits": signal_summary.get("hits", []),
            "signal_gate_errors": signal_gate_errors,
            "signal_closure_errors": signal_closure_errors,
            "clarify_deep_dive_enabled": deep_dive_enabled,
            "clarify_deep_dive_gate_strict": bool(harness_cfg.get("clarify_deep_dive_gate_strict", False)),
            "deep_dive_hints": deep_dive_hints,
            "deep_dive_gate_errors": deep_dive_gate_errors,
            "focus_point_errors": focus_point_errors,
            "focus_points_ok": len(focus_point_errors) == 0,
            "state_constraint_signal_scn_focus_errors": state_constraint_signal_scn_focus_errors,
            "state_constraint_signal_scn_focus_ok": len(state_constraint_signal_scn_focus_errors) == 0,
            # Back-compat: same keys as pre–State+Constraint gate (list was state-flow-only).
            "state_flow_scn_focus_errors": state_constraint_signal_scn_focus_errors,
            "state_flow_scn_focus_ok": len(state_constraint_signal_scn_focus_errors) == 0,
            # Structural notes + explicit user focus only (excludes full-mode SCN signal→Focus gate).
            "notes_only_errors": notes_core_errors,
            "notes_only_ok": len(notes_core_errors) == 0,
            "full_gate_artifacts": full_rows,
        })
        return

    print(f"=== CLARIFY self-check: {epic_id} ===")
    print(f"config clarify_closure_mode: {mode}")
    print("")
    print("-- clarification-notes（六轴 / 极简绕行 / 闭环；与 stage-gate check CLARIFY 一致）--")
    if cn_errors:
        for msg in cn_errors:
            print(f"  ❌ {msg}")
    else:
        print("  ✅ clarification-notes 通过结构校验")
    if signal_summary.get("required_axes"):
        print("")
        print("-- signal-driven gate（命中信号时定向加严）--")
        for axis, reasons in sorted(signal_summary["required_axes"].items()):
            print(f"  • {axis}: {', '.join(reasons)}")
        if signal_gate_errors:
            for msg in signal_gate_errors:
                print(f"  ❌ {msg}")
        else:
            print("  ✅ 命中的强化轴未发现额外 gate 问题")
    if deep_dive_hints:
        print("")
        print("-- deep-dive 提示 --")
        for hint in deep_dive_hints:
            print(f"  ⚠️  {hint}")
    if deep_dive_gate_errors:
        print("")
        print("-- deep-dive 严格门禁 --")
        for msg in deep_dive_gate_errors:
            print(f"  ❌ {msg}")
    cn_path = features_dir / "clarification-notes.md"
    notes_for_focus = (
        cn_path.read_text(encoding="utf-8", errors="replace") if cn_path.exists() else ""
    )
    has_focus_section = bool(
        re.search(
            r"(?im)^#{1,4}\s*(?:focus\s*points|用户关注点|用户点名关注)\b",
            notes_for_focus,
        )
    )
    if focus_point_errors:
        print("")
        print("-- 用户关注点闭环（Focus Points → REQ/CHK/SCN/DEC/UNK）--")
        for msg in focus_point_errors:
            print(f"  ❌ {msg}")
    elif (features_dir / "focus-points.json").exists() or has_focus_section:
        print("")
        print("-- 用户关注点闭环 --")
        print("  ✅ 已声明关注点且映射校验通过")
    if mode != "notes_only" and state_constraint_signal_scn_focus_errors:
        print("")
        print("-- 高风险 State/Constraint 信号 SCN → Focus（full 模式）--")
        for msg in state_constraint_signal_scn_focus_errors:
            print(f"  ❌ {msg}")
    print("")
    if mode == "notes_only":
        print("-- full 清单（notes_only 门禁不强制；仅供对照）--")
    else:
        print("-- full 模式门禁文件（stage-gate check CLARIFY）--")
    for row in full_rows:
        mark = "✅" if row["present"] else "❌"
        print(f"  {mark} {row['path']}")
    print("")
    print(
        "提示: clarify_closure_mode=notes_only 时 stage-gate 仅校验 clarification-notes.md 结构，"
        "不强制 unknowns-ledger / decision-bundle 等 JSON。"
    )


# ---------------------------------------------------------------------------
# receipt commands
# ---------------------------------------------------------------------------

def _find_epic_for_task(h: Path, task_id: str) -> str:
    """Resolve epic_id from task file."""
    task, _ = load_task(h, task_id)
    return task.get("epic_id", "")


def cmd_receipt_write(args, h: Path) -> None:
    task_id = args.task_id
    epic_id = _find_epic_for_task(h, task_id)
    if not epic_id:
        err(f"Could not determine epic_id for task {task_id}")

    receipts_dir = canonical_receipts_dir(h, epic_id)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"{task_id}.json"

    smoke_passed_raw = getattr(args, "smoke_passed", "true")
    smoke_passed = str(smoke_passed_raw).lower() not in ("false", "0", "no")

    receipt = {
        "task_id": task_id,
        "epic_id": epic_id,
        "phase": "EXECUTE",
        "preflight": {"passed": True, "checks": []},
        "implementation": {
            "base_commit": getattr(args, "base_commit", "") or "",
            "head_commit": getattr(args, "head_commit", "") or "",
            "files_changed": 0,
        },
        "smoke": {"passed": smoke_passed, "commands": []},
        "evidence": {},
        "new_risks": [],
        "timestamp": now_iso(),
    }

    atomic_write_json(receipt_path, receipt)

    # Emit trace event
    append_trace_event(h, _make_trace_event(
        epic_id, "receipt_written",
        task_id=task_id,
        status="ok" if smoke_passed else "warn",
        command_name="harnessctl receipt write",
        summary=f"Receipt for {task_id}: smoke={'PASS' if smoke_passed else 'FAIL'}",
        artifact_paths=[str(receipt_path)],
        payload={"smoke_passed": smoke_passed},
    ))

    if args.json:
        out_json(receipt)
    else:
        status = "PASS" if smoke_passed else "FAIL"
        print(f"Receipt written: {receipt_path}")
        print(f"  smoke: {status}")
        print(f"  base_commit: {receipt['implementation']['base_commit'][:8] or 'N/A'}")
        print(f"  head_commit: {receipt['implementation']['head_commit'][:8] or 'N/A'}")


def cmd_receipt_show(args, h: Path) -> None:
    task_id = args.task_id
    epic_id = _find_epic_for_task(h, task_id)
    receipt = None
    for directory in receipt_dirs_for_epic(h, epic_id):
        receipt_path = directory / f"{task_id}.json"
        if receipt_path.exists():
            try:
                receipt = load_json(receipt_path)
                break
            except SystemExit:
                continue
    if receipt is None:
        err(f"Receipt not found for task {task_id}")
    if args.json:
        out_json(receipt)
    else:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))


def cmd_receipt_list(args, h: Path) -> None:
    epic_id = args.epic_id
    receipts = []
    seen_task_ids = set()
    for receipts_dir in receipt_dirs_for_epic(h, epic_id):
        if not receipts_dir.exists():
            continue
        for f in sorted(receipts_dir.glob("*.json")):
            try:
                r = load_json(f)
                task_id = r.get("task_id")
                if task_id and task_id in seen_task_ids:
                    continue
                if task_id:
                    seen_task_ids.add(task_id)
                receipts.append(r)
            except SystemExit:
                continue

    if args.json:
        out_json(receipts)
    else:
        if not receipts:
            print(f"No receipts found for {epic_id}")
            return
        print(f"Receipts for {epic_id}:")
        for r in receipts:
            smoke_ok = "✅" if r.get("smoke", {}).get("passed") else "❌"
            print(f"  {smoke_ok} {r['task_id']}  {r.get('timestamp','')[:19]}")


# ---------------------------------------------------------------------------
# council command
# ---------------------------------------------------------------------------

COUNCIL_AGENTS = {
    "light_council": ["challenger", "requirement-analyst", "impact-analyst"],
    "plan_council": ["code-reviewer", "security-reviewer", "logic-reviewer", "test-reviewer", "plan-reviewer"],
    # 与 skills/council/SKILL.md 一致：runtime-auditor 负责 spec/实现对齐
    "acceptance_council": [
        "code-reviewer",
        "logic-reviewer",
        "security-reviewer",
        "test-reviewer",
        "runtime-auditor",
    ],
    "release_council": ["logic-reviewer", "security-reviewer", "runtime-auditor"],
}

COUNCIL_PASS_VERDICTS = {
    "light_council": ["GO", "REVISE"],
    "plan_council": ["READY", "READY_WITH_CONDITIONS"],
    "acceptance_council": ["PASS"],
    "release_council": ["RELEASE_READY", "RELEASE_WITH_CONDITIONS"],
}

COUNCIL_FAIL_VERDICTS = {
    "light_council": ["HOLD"],
    "plan_council": ["BLOCK"],
    "acceptance_council": ["FAIL"],
    "release_council": ["NOT_READY"],
}


def cmd_council_run(args, h: Path) -> None:
    """Describe the council configuration and show pending status."""
    council_type = args.council_type
    epic_id = args.epic_id

    if council_type not in COUNCIL_AGENTS:
        err(f"Unknown council type: {council_type}. Valid: {list(COUNCIL_AGENTS)}")

    agents = COUNCIL_AGENTS[council_type]
    councils_dir = h / "features" / epic_id / "councils"
    councils_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = councils_dir / f"verdict-{council_type}.json"

    if args.json:
        if verdict_file.exists():
            out_json(load_json(verdict_file))
        else:
            out_json({
                "council_type": council_type,
                "epic_id": epic_id,
                "verdict": "PENDING",
                "agents": agents,
                "votes_dir": str(councils_dir / f"votes-{council_type}"),
            })
    else:
        print(f"=== Council: {council_type} for {epic_id} ===")
        print(f"  Agents: {', '.join(agents)}")
        print(f"  Votes dir: {councils_dir / f'votes-{council_type}'}")
        print(f"  Verdict file: {verdict_file}")
        if verdict_file.exists():
            v = load_json(verdict_file)
            print(f"\n  Verdict: {v.get('verdict', '?')}")
        else:
            print("\n  Status: PENDING — run each reviewer agent and write votes, then aggregate")
            print(f"  Aggregate: harnessctl council aggregate {council_type} --epic-id {epic_id}")


def cmd_council_aggregate(args, h: Path) -> None:
    """Aggregate reviewer votes into final council verdict."""
    council_type = args.council_type
    epic_id = args.epic_id

    councils_dir = h / "features" / epic_id / "councils"
    votes_dir = councils_dir / f"votes-{council_type}"
    verdict_file = councils_dir / f"verdict-{council_type}.json"

    if not votes_dir.exists() or not any(votes_dir.glob("*.json")):
        err(f"No vote files in {votes_dir}")

    pass_verdicts = COUNCIL_PASS_VERDICTS.get(council_type, [])
    fail_verdicts = COUNCIL_FAIL_VERDICTS.get(council_type, [])

    votes = []
    for vf in sorted(votes_dir.glob("*.json")):
        try:
            votes.append(load_json(vf))
        except SystemExit:
            pass

    total = len(votes)
    pass_count = sum(1 for v in votes if v.get("verdict") in pass_verdicts)
    fail_count = sum(1 for v in votes if v.get("verdict") in fail_verdicts)
    other_count = total - pass_count - fail_count

    blocking_issues = []
    warnings = []
    for v in votes:
        blocking_issues.extend(v.get("blocking_issues", []))
        warnings.extend(v.get("warnings", []))

    if fail_count > 0:
        final_verdict = fail_verdicts[0]
    elif pass_count == total:
        final_verdict = pass_verdicts[0]
    elif other_count > 0 and len(pass_verdicts) > 1:
        final_verdict = pass_verdicts[1]
    else:
        final_verdict = pass_verdicts[0]

    result = {
        "epic_id": epic_id,
        "council_type": council_type,
        "verdict": final_verdict,
        "timestamp": now_iso(),
        "vote_summary": {"total": total, "pass": pass_count, "fail": fail_count, "other": other_count},
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }

    councils_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(verdict_file, result)

    if args.json:
        out_json(result)
    else:
        print(f"Council verdict: {final_verdict}")
        print(f"  Votes: {pass_count}/{total} pass, {fail_count} fail")
        if blocking_issues:
            print(f"  Blocking ({len(blocking_issues)}):")
            for i in blocking_issues:
                print(f"    - {i}")
        if final_verdict in fail_verdicts:
            sys.exit(1)


# ---------------------------------------------------------------------------
# memory commands
# ---------------------------------------------------------------------------

def _split_codemap_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter (--- ... ---) from CodeMap markdown body."""
    if not text.startswith("---"):
        return {}, text
    first_nl = text.find("\n", 3)
    if first_nl == -1:
        return {}, text
    end = text.find("\n---\n", first_nl + 1)
    if end != -1:
        fm_raw = text[first_nl + 1 : end]
        body = text[end + len("\n---\n") :]
    else:
        end2 = text.find("\n---", first_nl + 1)
        if end2 == -1:
            return {}, text
        fm_raw = text[first_nl + 1 : end2]
        body = text[end2 + len("\n---") :].lstrip("\n")
    meta = _parse_simple_yaml(fm_raw)
    return meta, body


def _render_codemap_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, float):
            lines.append(f"{k}: {v}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        elif v == "":
            lines.append(f'{k}: ""')
        elif isinstance(v, str):
            if any(c in v for c in "\n\r\""):
                lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def cmd_memory_codemap_init(args, h: Path, project_root: Path) -> None:
    """Create a CodeMap file from the template with standard metadata."""
    del h
    repo_id = args.repo_id.strip()
    module_slug = slugify(args.module_slug.strip())
    if not repo_id:
        err("repo_id cannot be empty")
    if not module_slug:
        err("module_slug cannot be empty")
    source_paths = [p.strip() for p in (args.source_path or []) if p.strip()]
    if not source_paths:
        err("Provide at least one --source-path")

    codemap_dir = project_root / HARNESS_DIR / "memory" / "codemaps" / repo_id
    codemap_path = codemap_dir / f"{module_slug}.md"
    if codemap_path.exists() and not args.force:
        err(f"CodeMap already exists: {codemap_path} (use --force to overwrite)")

    template_path = _codemap_template_path()
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        template = (
            "---\n"
            "source_paths: []\n"
            "verified_commit: \"\"\n"
            "generated_at: \"\"\n"
            "confidence: medium\n"
            "---\n\n"
            "# CodeMap: <repo_id> / <module_slug>\n"
        )

    meta = {
        "source_paths": source_paths,
        "verified_commit": getattr(args, "verified_commit", "") or "",
        "generated_at": now_iso(),
        "confidence": getattr(args, "confidence", "medium") or "medium",
        "stale_note": "Regenerate or downgrade confidence if listed paths changed on main.",
    }
    _old_meta, body = _split_codemap_frontmatter(template)
    if not body:
        body = template
    body = body.replace("<repo_id>", repo_id).replace("<module_slug>", module_slug)
    if getattr(args, "purpose", ""):
        body = body.replace(
            "One-paragraph: what this module does in the product.",
            args.purpose.strip(),
        )
    atomic_write(codemap_path, _render_codemap_frontmatter(meta) + body)

    payload = {
        "status": "ok",
        "codemap_path": str(codemap_path),
        "repo_id": repo_id,
        "module_slug": module_slug,
        "source_paths": source_paths,
    }
    if args.json:
        out_json(payload)
    else:
        print(f"Initialized CodeMap: {codemap_path}")


def _probe_codemap_file(project_root: Path, codemap_path: Path, write: bool = False) -> dict:
    """Probe one CodeMap file for staleness against verified_commit..HEAD."""
    p = codemap_path.resolve()
    result = {
        "codemap_path": str(p),
        "source_paths": [],
        "verified_commit": None,
        "stale": None,
        "reason": None,
        "changed_paths": [],
        "missing_paths": [],
        "git_error": None,
        "suggested_confidence": None,
        "wrote": False,
    }
    if not p.is_file():
        result["reason"] = "file_not_found"
        return result
    text = p.read_text(encoding="utf-8")
    meta, body = _split_codemap_frontmatter(text)
    if not meta:
        result["reason"] = "invalid_frontmatter"
        return result

    sp = meta.get("source_paths", [])
    if isinstance(sp, str):
        sp = [sp] if sp.strip() else []
    if not isinstance(sp, list):
        sp = []
    paths = [str(x).strip() for x in sp if str(x).strip()]
    if not paths:
        result["reason"] = "missing_source_paths"
        result["suggested_confidence"] = "low"
        result["verified_commit"] = str(meta.get("verified_commit") or "").strip() or None
        return result

    vc = str(meta.get("verified_commit") or "").strip()
    root = project_root.resolve()

    result["source_paths"] = paths
    result["verified_commit"] = vc or None
    result["suggested_confidence"] = meta.get("confidence")

    rc_git, _, ge = _git(root, "rev-parse", "--git-dir")
    if rc_git != 0:
        result["reason"] = "not_a_git_repository"
        result["git_error"] = ge
        return result

    if not vc:
        result["reason"] = "no_verified_commit"
        result["suggested_confidence"] = "low"
        if write:
            meta["codemap_probe_at"] = now_iso()
            meta["codemap_stale"] = False
            new_text = _render_codemap_frontmatter(meta) + body
            atomic_write(p, new_text)
            result["wrote"] = True
        return result

    rc_v, _, ve = _git(root, "rev-parse", "-q", "--verify", vc + "^{commit}")
    if rc_v != 0:
        result["reason"] = "invalid_verified_commit"
        result["git_error"] = ve
        return result

    for rel in paths:
        full = (root / rel).resolve()
        try:
            full.relative_to(root)
        except ValueError:
            result["missing_paths"].append(rel)
            continue
        if not full.exists():
            result["missing_paths"].append(rel)
            continue
        rc_d, _, _ = _git(root, "diff", "--quiet", vc, "HEAD", "--", rel)
        if rc_d != 0:
            result["changed_paths"].append(rel)

    stale = bool(result["missing_paths"] or result["changed_paths"])
    result["stale"] = stale
    result["reason"] = "ok" if not stale else "sources_changed_or_missing"
    result["suggested_confidence"] = "medium" if not stale else "low"

    if write:
        meta["codemap_probe_at"] = now_iso()
        meta["codemap_stale"] = bool(stale)
        if stale:
            meta["confidence"] = "low"
        new_text = _render_codemap_frontmatter(meta) + body
        atomic_write(p, new_text)
        result["wrote"] = True
    return result


def cmd_memory_codemap_probe(args, _h: Path, project_root: Path) -> None:
    """Compare CodeMap source_paths between verified_commit and HEAD; optional frontmatter update."""
    raw = args.path
    p = Path(raw)
    if not p.is_absolute():
        p = (project_root / p).resolve()
    result = _probe_codemap_file(project_root, p, write=bool(args.write))

    if args.json:
        out_json(result)
    else:
        print(f"stale={result['stale']} reason={result['reason']}")
        if result["changed_paths"]:
            print(f"  changed: {result['changed_paths']}")
        if result["missing_paths"]:
            print(f"  missing: {result['missing_paths']}")
        if result["git_error"]:
            print(f"  git_error: {result['git_error']}")
        if args.write:
            print(f"  updated frontmatter in {p}")

    if result["reason"] in (
        "file_not_found",
        "invalid_frontmatter",
        "missing_source_paths",
        "not_a_git_repository",
        "invalid_verified_commit",
    ):
        sys.exit(1)
    if result["stale"]:
        sys.exit(1)


def cmd_memory_codemap_audit(args, h: Path, project_root: Path) -> None:
    """Audit one directory tree of CodeMaps and summarize stale / invalid entries."""
    raw = getattr(args, "path", "") or str(h / "memory" / "codemaps")
    base = Path(raw)
    if not base.is_absolute():
        base = (project_root / base).resolve()
    if not base.exists():
        err(f"CodeMap path not found: {base}")

    files = [base] if base.is_file() else sorted(base.rglob("*.md"))
    results = []
    summary = {
        "total": 0,
        "stale": 0,
        "fresh": 0,
        "missing_verified_commit": 0,
        "invalid": 0,
        "written": 0,
    }
    for file_path in files:
        result = _probe_codemap_file(project_root, file_path, write=bool(args.write))
        results.append(result)
        summary["total"] += 1
        if result.get("wrote"):
            summary["written"] += 1
        reason = result.get("reason")
        if reason == "ok":
            summary["fresh"] += 1
        elif reason == "no_verified_commit":
            summary["missing_verified_commit"] += 1
        elif reason in (
            "file_not_found",
            "invalid_frontmatter",
            "missing_source_paths",
            "invalid_verified_commit",
            "not_a_git_repository",
        ):
            summary["invalid"] += 1
        if result.get("stale"):
            summary["stale"] += 1

    payload = {
        "status": "ok",
        "base_path": str(base),
        "summary": summary,
        "results": results,
    }
    epic_id = getattr(args, "epic_id", "") or ""
    if epic_id:
        load_epic(h, epic_id)  # validate
        artifact_path = h / "features" / epic_id / "codemap-audit.json"
        atomic_write_json(artifact_path, payload)
        payload["artifact_path"] = str(artifact_path)
    if args.json:
        out_json(payload)
    else:
        print(f"Audited CodeMaps under {base}")
        print(
            "  total={total} fresh={fresh} stale={stale} missing_verified_commit={missing_verified_commit} invalid={invalid}".format(
                **summary
            )
        )
        if args.write:
            print(f"  frontmatter updated: {summary['written']}")
        if epic_id:
            print(f"  artifact: {payload['artifact_path']}")

    if summary["stale"] > 0 or summary["invalid"] > 0:
        sys.exit(1)


def cmd_memory_append_pitfalls(args, h: Path) -> None:
    """Append high-impact pitfalls from unknowns-ledger to memory/pitfalls.md."""
    epic_id = args.epic_id
    ledger_path = h / "features" / epic_id / "unknowns-ledger.json"
    memory_dir = h / "memory"
    pitfalls_path = memory_dir / "pitfalls.md"

    if not ledger_path.exists():
        if args.json:
            out_json({"status": "skipped", "reason": "no unknowns-ledger.json"})
        else:
            print(f"No unknowns-ledger.json for {epic_id}, skipping.")
        return

    ledger = load_json(ledger_path)
    entries = ledger.get("entries", [])

    patterns = [
        e for e in entries
        if e.get("impact") in ("high", "critical")
        and e.get("discovered_at") == "CLARIFY"
    ]

    if not patterns:
        if args.json:
            out_json({"status": "skipped", "reason": "no high-impact CLARIFY patterns"})
        else:
            print("No high-impact CLARIFY patterns to append.")
        return

    memory_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [f"\n## Epic: {epic_id} ({today})\n"]
    for p in patterns:
        lines.append(f"- **{p['id']}** [{p.get('impact','?').upper()}] {p['description']}")
        if p.get("resolution"):
            lines.append(f"  - Resolution: {p['resolution']}")
        if p.get("classification"):
            lines.append(f"  - Category: {p['classification']}")
        lines.append("")

    content = "\n".join(lines)
    with pitfalls_path.open("a", encoding="utf-8") as f:
        f.write(content)

    if args.json:
        out_json({"status": "ok", "patterns_written": len(patterns), "path": str(pitfalls_path)})
    else:
        print(f"Appended {len(patterns)} pattern(s) to {pitfalls_path}")


# ---------------------------------------------------------------------------
# budget commands
# ---------------------------------------------------------------------------

def cmd_budget_check(args, h: Path) -> None:
    """Check interrupt budget status for an epic."""
    epic_id = args.epic_id
    state = load_state(h, epic_id)
    budget = state.get("interrupt_budget", {})
    total = budget.get("total", 0)
    consumed = budget.get("consumed", 0)
    remaining = budget.get("remaining", total - consumed)

    if args.json:
        out_json({
            "epic_id": epic_id,
            "total": total,
            "consumed": consumed,
            "remaining": remaining,
            "exhausted": remaining <= 0,
        })
    else:
        status = "EXHAUSTED" if remaining <= 0 else "OK"
        print(f"Interrupt Budget for {epic_id}: [{status}]")
        print(f"  total:     {total}")
        print(f"  consumed:  {consumed}")
        print(f"  remaining: {remaining}")
    if remaining <= 0:
        sys.exit(1)


def cmd_budget_consume(args, h: Path) -> None:
    """Consume one interrupt from the budget."""
    epic_id = args.epic_id
    state = load_state(h, epic_id)
    budget = dict(state.get("interrupt_budget", {}))
    remaining = budget.get("remaining", budget.get("total", 0) - budget.get("consumed", 0))
    if remaining <= 0:
        err(f"Interrupt budget exhausted for {epic_id}")
    budget["consumed"] = budget.get("consumed", 0) + 1
    budget["remaining"] = remaining - 1
    updated_state = dict(state)
    updated_state["interrupt_budget"] = budget
    updated_state["updated_at"] = now_iso()
    save_state(h, updated_state)
    if args.json:
        out_json({"consumed": budget["consumed"], "remaining": budget["remaining"]})
    else:
        print(f"Consumed 1 interrupt. Remaining: {budget['remaining']}/{budget['total']}")


# ---------------------------------------------------------------------------
# guard command
# ---------------------------------------------------------------------------

def cmd_guard_check(args, h: Path, project_root: Path) -> None:
    """Check guard conditions before entering a stage in auto mode."""
    epic_id = args.epic_id
    stage = args.stage.upper() if args.stage else None

    issues = []
    state = load_state(h, epic_id)
    budget = state.get("interrupt_budget", {})
    remaining = budget.get("remaining", budget.get("total", 0) - budget.get("consumed", 0))

    # Check budget
    if remaining <= 0:
        issues.append("interrupt budget exhausted")

    # Check runtime_health for critical blockers
    rh = state.get("runtime_health", {})
    if rh.get("consecutive_failures", 0) >= 3:
        issues.append(f"consecutive_failures >= 3 (currently {rh['consecutive_failures']})")

    # Check pending CRITICAL decisions
    pending = _effective_pending_decisions(h, state)
    critical = [d for d in pending if d.get("severity") == "critical"]
    if critical:
        issues.append(f"{len(critical)} unhandled CRITICAL decision(s)")

    # Stage-specific gate check
    if stage:
        # Check the PREVIOUS stage gate (stage before current)
        prev_stage_map = {
            "CLARIFY": None,
            "SPEC": "CLARIFY",
            "PLAN": "SPEC",
            "EXECUTE": "PLAN",
            "VERIFY": "EXECUTE",
            "FIX": "VERIFY",
            "DONE": "VERIFY",
        }
        prev_stage = prev_stage_map.get(stage)
        if prev_stage:
            artifacts_spec = _stage_gate_artifacts_spec(prev_stage, h) or []
            features_dir = h / "features" / epic_id
            for tmpl in artifacts_spec:
                path_str = tmpl.format(features_dir=str(features_dir), epic_id=epic_id)
                p = Path(path_str)
                if not p.is_absolute():
                    p = project_root / p
                if not p.exists():
                    issues.append(f"prev stage gate {prev_stage}: missing {path_str}")
                    break  # Report first missing artifact only

    append_trace_event(h, _make_trace_event(
        epic_id, "guard_checked",
        stage=stage or state.get("current_stage", ""),
        command_name="harnessctl guard check",
        summary="Guard checked",
        payload={"issues": issues, "budget_remaining": remaining},
    ))

    passed = len(issues) == 0
    # Emit trace event
    _gevt = "guard_passed" if passed else "guard_failed"
    _state_cur = state.get("current_stage", "")
    append_trace_event(h, _make_trace_event(
        epic_id, _gevt,
        stage=stage or _state_cur,
        status="ok" if passed else "blocked",
        command_name="harnessctl guard check",
        summary=f"Guard {'PASSED' if passed else 'FAILED'}: {', '.join(issues) if issues else 'all ok'}",
        payload={"issues": issues, "passed": passed, "budget_remaining": remaining},
    ))
    if args.json:
        out_json({
            "epic_id": epic_id,
            "stage": stage,
            "passed": passed,
            "issues": issues,
            "budget_remaining": remaining,
        })
    else:
        if passed:
            print(f"✅ Guard check PASSED for {epic_id} → {stage or '?'}")
        else:
            print(f"❌ Guard check FAILED for {epic_id} → {stage or '?'}")
            for i in issues:
                print(f"  - {i}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# triage command
# ---------------------------------------------------------------------------

def cmd_triage(args, h: Path) -> None:
    """Write a triage report for a blocked/failed task."""
    epic_id = args.epic_id
    task_id = args.task_id
    reason = getattr(args, "reason", "unknown")
    failures = getattr(args, "failures", 1)

    triage_dir = h / "features" / epic_id / "triage"
    triage_dir.mkdir(parents=True, exist_ok=True)
    triage_path = triage_dir / f"{task_id}.json"

    report = {
        "task_id": task_id,
        "epic_id": epic_id,
        "reason": reason,
        "consecutive_failures": int(failures),
        "timestamp": now_iso(),
        "status": "open",
        "resolution": None,
    }
    atomic_write_json(triage_path, report)

    # Mark task as blocked
    try:
        task, task_path = load_task(h, task_id)
        updated = dict(task)
        updated["status"] = "blocked"
        atomic_write_json(task_path, updated)
    except SystemExit:
        pass

    # Update runtime_health in state
    try:
        state = load_state(h, epic_id)
        updated_state = dict(state)
        rh = dict(state.get("runtime_health", {}))
        rh["consecutive_failures"] = int(failures)
        updated_state["runtime_health"] = rh
        updated_state["updated_at"] = now_iso()
        save_state(h, updated_state)
    except SystemExit:
        pass

    if args.json:
        out_json(report)
    else:
        print(f"Triage report written: {triage_path}")
        print(f"  task {task_id} marked blocked")
        print(f"  reason: {reason}  failures: {failures}")

    # Emit trace event
    append_trace_event(h, _make_trace_event(
        epic_id, "task_triaged",
        task_id=task_id,
        status="warn",
        command_name="harnessctl triage",
        summary=f"Task {task_id} triaged: {reason} (failures={failures})",
        payload={"reason": reason, "consecutive_failures": int(failures)},
    ))


# ---------------------------------------------------------------------------
# bundle commands (decision-bundle management from Python)
# ---------------------------------------------------------------------------

def _load_bundle(h: Path, epic_id: str) -> dict:
    bundle_path = h / "features" / epic_id / "decision-bundle.json"
    if not bundle_path.exists():
        err(f"No decision-bundle.json for {epic_id}. Run 'decision-bundle.sh generate {epic_id}' first.")
    return load_json(bundle_path)


def cmd_bundle_summary(args, h: Path) -> None:
    epic_id = args.epic_id
    bundle = _load_bundle(h, epic_id)
    s = bundle.get("summary", {})
    decisions = bundle.get("decisions", [])
    pending = [d for d in decisions if d.get("status") == "pending"]

    if args.json:
        out_json({
            "epic_id": epic_id,
            "stage": bundle.get("stage", "?"),
            "summary": s,
            "pending_count": len(pending),
        })
    else:
        print(f"Decision Bundle: {epic_id} ({bundle.get('stage','?')})")
        print(f"  must_confirm: {s.get('must_confirm', 0)}")
        print(f"  assumable:    {s.get('assumable', 0)}")
        print(f"  deferrable:   {s.get('deferrable', 0)}")
        print(f"  pending:      {len(pending)}")


def cmd_bundle_pending_confirms(args, h: Path) -> None:
    """List pending must_confirm decisions."""
    epic_id = args.epic_id
    bundle = _load_bundle(h, epic_id)
    pending = [
        d for d in bundle.get("decisions", [])
        if d.get("category") == "must_confirm" and d.get("status") == "pending"
    ]
    if args.json:
        out_json(pending)
    else:
        if not pending:
            print("No pending must_confirm decisions.")
            return
        print(f"Pending must_confirm decisions for {epic_id}:")
        for d in pending:
            print(f"  [{d['id']}] {d.get('question','')[:70]}")


def cmd_bundle_check_confirmed(args, h: Path) -> None:
    """Check if all must_confirm decisions have been resolved."""
    epic_id = args.epic_id
    bundle = _load_bundle(h, epic_id)
    pending = [
        d for d in bundle.get("decisions", [])
        if d.get("category") == "must_confirm" and d.get("status") == "pending"
    ]
    all_confirmed = len(pending) == 0
    if args.json:
        out_json({
            "epic_id": epic_id,
            "all_confirmed": all_confirmed,
            "pending_count": len(pending),
            "pending_ids": [d["id"] for d in pending],
        })
    else:
        if all_confirmed:
            print(f"✅ All must_confirm decisions resolved for {epic_id}")
        else:
            print(f"❌ {len(pending)} must_confirm decision(s) still pending:")
            for d in pending:
                print(f"  - {d['id']}: {d.get('question','')[:60]}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# audit commands
# ---------------------------------------------------------------------------

def _audit_text_compact_line(label: str, compact: dict | None) -> None:
    if not compact:
        print(f"  {label}: N/A")
        return
    bits = [str(compact.get("event_type") or "?")]
    ts = str(compact.get("ts") or "").strip()
    if ts:
        bits.append(f"@ {ts}")
    stg = str(compact.get("stage") or "").strip()
    if stg:
        bits.append(f"stage={stg}")
    summ = str(compact.get("summary") or "").strip()
    if summ:
        bits.append(summ[:160])
    print(f"  {label}: {' | '.join(bits)}")


def _audit_text_task_summary(task_summary: dict | None) -> None:
    if not isinstance(task_summary, dict):
        print("  task_summary: N/A")
        return
    bs = task_summary.get("by_status")
    lc = task_summary.get("latest_change")
    if not isinstance(bs, dict):
        bs = {}
    tracked = sum(int(bs.get(s, 0) or 0) for s in TASK_STATUSES)
    if tracked == 0 and not lc:
        print("  task_summary: N/A")
        return
    parts = []
    for s in TASK_STATUSES:
        n = int(bs.get(s, 0) or 0)
        if n:
            parts.append(f"{s}={n}")
    tail = "; ".join(parts) if parts else "(none)"
    if isinstance(lc, dict) and lc:
        tid = str(lc.get("task_id") or "").strip()
        ns = str(lc.get("new_status") or "").strip()
        lts = str(lc.get("ts") or "").strip()
        extra = f" | latest: {tid} -> {ns}" + (f" @ {lts}" if lts else "")
        tail = tail + extra
    print(f"  task_summary: {tail}")


def cmd_audit_show(args, h: Path) -> None:
    """Show derived execution audit summary for an epic."""
    epic_id = args.epic_id
    summary = _write_execution_summary(h, epic_id)
    if args.json:
        out_json(summary)
    else:
        print(f"Execution Audit: {epic_id}")
        print(f"  stage:                    {summary.get('current_stage', '?')}")
        print(f"  latest_run_id:            {summary.get('latest_run_id', '') or 'N/A'}")
        print(f"  steps_completed:          {', '.join(summary.get('steps_completed', [])) or 'N/A'}")
        print(f"  parallel_waves_completed: {summary.get('parallel_waves_completed', 0)}")
        print(f"  repo_fanout_waves_completed: {summary.get('repo_fanout_waves_completed', 0)}")
        print(f"  fanout_used:              {'yes' if summary.get('fanout_used') else 'no'}")
        print(f"  fanout_children_count:    {summary.get('fanout_children_count', 0)}")
        state = "generated" if summary.get("decision_packet_generated") else "not_generated"
        print(f"  decision_packet:          {state}")
        print(f"  pending_synced:           {'yes' if summary.get('pending_decisions_synced') else 'no'}")
        print(f"  pending_decisions_count:  {summary.get('pending_decisions_count', 0)}")
        print(f"  latest_pause_reason:      {summary.get('latest_pause_reason', '') or 'N/A'}")
        _audit_text_compact_line("latest_gate", summary.get("latest_gate"))
        _audit_text_compact_line("latest_guard", summary.get("latest_guard"))
        _audit_text_task_summary(summary.get("task_summary"))


# ---------------------------------------------------------------------------
# coverage commands
# ---------------------------------------------------------------------------

def cmd_coverage_map(args, h: Path) -> None:
    """Generate or update coverage matrix from tasks and unknowns-ledger."""
    epic_id = args.epic_id
    features_dir = h / "features" / epic_id
    matrix_path = features_dir / "coverage-matrix.json"
    ledger_path = features_dir / "unknowns-ledger.json"

    # Load existing matrix or create new
    if matrix_path.exists() and not getattr(args, "reset", False):
        matrix = load_json(matrix_path)
    else:
        matrix = {
            "version": "1.0",
            "epic_id": epic_id,
            "generated_at": now_iso(),
            "mappings": [],
            "unmapped_risks": [],
        }

    # Load unknowns if available
    unknowns = []
    if ledger_path.exists():
        ledger = load_json(ledger_path)
        unknowns = ledger.get("entries", [])

    # Load tasks
    tasks_dir = h / "tasks"
    task_ids = []
    if tasks_dir.exists():
        for f in tasks_dir.glob(f"{epic_id}.*.json"):
            try:
                t = load_json(f)
                task_ids.append(t["id"])
            except SystemExit:
                continue

    # Add unmapped unknowns (those not already in mappings)
    mapped_ids = {m.get("unknown_id") for m in matrix.get("mappings", [])}
    unmapped_ids = {m.get("unknown_id") for m in matrix.get("unmapped_risks", [])}

    newly_unmapped = []
    for u in unknowns:
        uid = u.get("id", "")
        if uid and uid not in mapped_ids and uid not in unmapped_ids:
            newly_unmapped.append({
                "unknown_id": uid,
                "reason": "auto-detected: no task mapping yet",
                "mitigation": "",
                "description": u.get("description", ""),
            })

    matrix["unmapped_risks"] = matrix.get("unmapped_risks", []) + newly_unmapped
    matrix["generated_at"] = now_iso()

    features_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(matrix_path, matrix)

    if args.json:
        out_json(matrix)
    else:
        print(f"Coverage matrix updated: {matrix_path}")
        print(f"  mappings:       {len(matrix.get('mappings', []))}")
        print(f"  unmapped_risks: {len(matrix.get('unmapped_risks', []))}")
        if newly_unmapped:
            print(f"  newly detected: {len(newly_unmapped)} unmapped risk(s)")


def cmd_coverage_show(args, h: Path) -> None:
    epic_id = args.epic_id
    matrix_path = h / "features" / epic_id / "coverage-matrix.json"
    if not matrix_path.exists():
        err(f"No coverage-matrix.json for {epic_id}. Run 'harnessctl coverage map --epic-id {epic_id}' first.")
    matrix = load_json(matrix_path)
    if args.json:
        out_json(matrix)
    else:
        print(json.dumps(matrix, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# epic set-worktree
# ---------------------------------------------------------------------------

def cmd_epic_set_worktree(args, h: Path) -> None:
    """Record worktree path in epic metadata."""
    epic_id = args.epic_id
    worktree_path = args.worktree_path
    epic = load_epic(h, epic_id)
    updated = dict(epic)
    repo_id = getattr(args, "repo_id", "") or ""
    branch = getattr(args, "branch", "") or (
        f"harness/{epic_id}/{slugify(repo_id)}" if repo_id else f"harness/{epic_id}"
    )
    if repo_id:
        repo_worktrees = dict(_repo_worktrees_from_epic(epic))
        repo_worktrees[repo_id] = {
            "path": worktree_path,
            "branch": branch,
            "updated_at": now_iso(),
        }
        updated["repo_worktrees"] = repo_worktrees
    else:
        updated["worktree_path"] = worktree_path
        updated["worktree_branch"] = branch
    save_epic(h, updated)
    if args.json:
        payload = {
            "epic_id": epic_id,
            "worktree_path": worktree_path,
            "branch": branch,
        }
        if repo_id:
            payload["repo_id"] = repo_id
            payload["repo_worktrees"] = updated.get("repo_worktrees", {})
        out_json(payload)
    else:
        if repo_id:
            print(f"Set repo worktree for {epic_id}/{repo_id}: {worktree_path}")
        else:
            print(f"Set worktree for {epic_id}: {worktree_path}")


def cmd_epic_show_worktrees(args, h: Path) -> None:
    """Show epic-level and repo-level worktree coordination metadata."""
    epic = load_epic(h, args.epic_id)
    payload = {
        "epic_id": args.epic_id,
        "default_worktree": {
            "path": epic.get("worktree_path", ""),
            "branch": epic.get("worktree_branch", ""),
        },
        "repo_worktrees": _repo_worktrees_from_epic(epic),
    }
    if args.json:
        out_json(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# gate skip
# ---------------------------------------------------------------------------

def cmd_gate_skip(args, h: Path) -> None:
    """Record a gate skip with justification (emergency override)."""
    epic_id = args.epic_id
    stage = args.stage.upper()
    justification = getattr(args, "justification", "") or ""

    gate_skip_path = h / "features" / epic_id / "gate-skips.json"
    skips = []
    if gate_skip_path.exists():
        existing = load_json(gate_skip_path)
        skips = existing if isinstance(existing, list) else existing.get("skips", [])

    skips.append({
        "stage": stage,
        "justification": justification,
        "timestamp": now_iso(),
        "authorized_by": "harnessctl-cli",
    })

    (h / "features" / epic_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(gate_skip_path, skips)

    # Emit trace event
    append_trace_event(h, _make_trace_event(
        epic_id, "gate_skipped",
        stage=stage,
        status="warn",
        command_name="harnessctl gate skip",
        summary=f"Gate SKIPPED for {stage}: {justification or '(no justification)'}",
        payload={"stage": stage, "justification": justification},
    ))

    if args.json:
        out_json({"epic_id": epic_id, "stage": stage, "skipped": True})
    else:
        print(f"⚠️  Gate SKIPPED for {stage} on {epic_id}")
        print(f"   Justification: {justification or '(none provided)'}")
        print(f"   This skip is recorded at: {gate_skip_path}")


# ---------------------------------------------------------------------------
# skill commands (lifecycle management)
# ---------------------------------------------------------------------------

def _skill_candidates_dir(h: Path) -> Path:
    return h / "memory" / "candidate-skills"


def cmd_skill_list(args, h: Path) -> None:
    candidates_dir = _skill_candidates_dir(h)
    skills = []
    if candidates_dir.exists():
        for f in sorted(candidates_dir.glob("*.json")):
            try:
                skills.append(load_json(f))
            except SystemExit:
                continue
    if args.json:
        out_json(skills)
    else:
        if not skills:
            print("No candidate skills found.")
            return
        header = f"{'ID':<30} {'STATUS':<12} {'CONFIDENCE':<12} NAME"
        print(header)
        print("-" * 70)
        for s in skills:
            print(f"{s.get('id','?'):<30} {s.get('status','?'):<12} {s.get('confidence',0):<12.2f} {s.get('name','?')}")


def cmd_skill_show(args, h: Path) -> None:
    candidates_dir = _skill_candidates_dir(h)
    skill_id = args.skill_id
    for f in candidates_dir.glob("*.json"):
        try:
            s = load_json(f)
            if s.get("id") == skill_id:
                if args.json:
                    out_json(s)
                else:
                    print(json.dumps(s, indent=2, ensure_ascii=False))
                return
        except SystemExit:
            continue
    err(f"Skill not found: {skill_id}")


def cmd_skill_promote(args, h: Path) -> None:
    """Promote a candidate skill to active status."""
    candidates_dir = _skill_candidates_dir(h)
    skill_id = args.skill_id
    for f in candidates_dir.glob("*.json"):
        try:
            s = load_json(f)
            if s.get("id") == skill_id:
                updated = dict(s)
                updated["status"] = "promoted"
                updated["promoted_at"] = now_iso()
                atomic_write_json(f, updated)
                if args.json:
                    out_json(updated)
                else:
                    print(f"Promoted skill: {skill_id}")
                return
        except SystemExit:
            continue
    err(f"Skill not found: {skill_id}")


def cmd_skill_archive(args, h: Path) -> None:
    """Archive a candidate skill (mark as inactive)."""
    candidates_dir = _skill_candidates_dir(h)
    skill_id = args.skill_id
    for f in candidates_dir.glob("*.json"):
        try:
            s = load_json(f)
            if s.get("id") == skill_id:
                updated = dict(s)
                updated["status"] = "archived"
                updated["archived_at"] = now_iso()
                reason = getattr(args, "reason", "") or ""
                if reason:
                    updated["archive_reason"] = reason
                atomic_write_json(f, updated)
                if args.json:
                    out_json(updated)
                else:
                    print(f"Archived skill: {skill_id}")
                return
        except SystemExit:
            continue
    err(f"Skill not found: {skill_id}")


    err(f"Skill not found: {skill_id}")


# ---------------------------------------------------------------------------
# patch commands (JIT Evolution)
# ---------------------------------------------------------------------------

def _patch_meta_path(h: Path, patch_id: str) -> Path:
    return _patch_candidates_dir(h) / patch_id / "meta.json"

def _patch_md_path(h: Path, patch_id: str) -> Path:
    return _patch_candidates_dir(h) / patch_id / "candidate-patch.md"

def _patch_obs_path(h: Path, patch_id: str) -> Path:
    return _patch_candidates_dir(h) / patch_id / "observations.jsonl"

def _load_patch_meta(h: Path, patch_id: str) -> dict:
    p = _patch_meta_path(h, patch_id)
    if not p.exists():
        err(f"Patch not found: {patch_id}")
    return load_json(p)

def _save_patch_meta(h: Path, meta: dict) -> None:
    patch_id = meta["id"]
    p = _patch_meta_path(h, patch_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, meta)

def _append_patch_observation(h: Path, patch_id: str, obs: dict) -> None:
    obs_path = _patch_obs_path(h, patch_id)
    obs_path.parent.mkdir(parents=True, exist_ok=True)
    with obs_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obs, ensure_ascii=False) + "\n")

def _list_all_patches(h: Path) -> list[dict]:
    patches = []
    base = _patch_candidates_dir(h)
    if not base.exists():
        return patches
    for patch_dir in sorted(base.iterdir()):
        meta_file = patch_dir / "meta.json"
        if meta_file.is_file():
            try:
                patches.append(json.loads(meta_file.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
    return patches

def cmd_patch_list(args, h: Path) -> None:
    """List all candidate patches with status."""
    scope_filter = getattr(args, "scope", None)
    patches = _list_all_patches(h)
    if scope_filter and scope_filter != "all":
        patches = [p for p in patches if p.get("scope") == scope_filter]
    if args.json:
        out_json(patches)
        return
    if not patches:
        print("No patches found.")
        return
    print(f"{'ID':<36} {'STATUS':<22} {'SCOPE':<16} {'KIND':<22} EPIC")
    print("-" * 110)
    for p in patches:
        print(f"{p.get('id','?'):<36} {p.get('status','?'):<22} {p.get('scope','?'):<16} {p.get('kind','?'):<22} {p.get('epic_id','')}")


def cmd_patch_show(args, h: Path) -> None:
    """Show patch metadata and content."""
    patch_id = args.patch_id
    meta = _load_patch_meta(h, patch_id)
    if args.json:
        out_json(meta)
        return
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    md = _patch_md_path(h, patch_id)
    if md.exists():
        print("\n--- candidate-patch.md ---")
        print(md.read_text(encoding="utf-8"))


def cmd_patch_apply(args, h: Path) -> None:
    """Apply a candidate patch (materialize to rules directory)."""
    patch_id = args.patch_id
    scope = getattr(args, "scope", None) or "epic"
    meta = _load_patch_meta(h, patch_id)
    epic_id = meta.get("epic_id", "")

    md = _patch_md_path(h, patch_id)
    if not md.exists():
        err(f"candidate-patch.md not found for {patch_id}")

    if scope == "project":
        dest_dir = _project_rules_dir(h)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{patch_id}.md"
        dest.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
        new_status = "project_active"
        new_scope = "project-active"
    else:
        if not epic_id:
            err("epic_id required to apply patch at epic scope")
        dest_dir = _active_epic_rules_dir(h, epic_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{patch_id}.md"
        dest.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
        new_status = "active_epic"
        new_scope = "epic-local"

    updated = dict(meta)
    updated["status"] = new_status
    updated["scope"] = new_scope
    updated["applied_at"] = now_iso()
    _save_patch_meta(h, updated)

    # Update rules index
    _update_rules_index(h)

    append_trace_event(h, _make_trace_event(
        epic_id, "patch_applied",
        status="ok",
        patch_id=patch_id,
        command_name="harnessctl patch apply",
        summary=f"Patch {patch_id} applied at {new_scope}",
        artifact_paths=[str(dest)],
    ))

    if args.json:
        out_json({"patch_id": patch_id, "status": new_status, "path": str(dest)})
    else:
        print(f"✅ Patch applied: {patch_id}")
        print(f"   Scope: {new_scope}")
        print(f"   File: {dest}")
        print(f"\nNext: /harness:auto to resume with new rules loaded.")


def cmd_patch_revert(args, h: Path) -> None:
    """Revert an active patch (remove from rules directory)."""
    patch_id = args.patch_id
    meta = _load_patch_meta(h, patch_id)
    epic_id = meta.get("epic_id", "")
    removed = []

    for candidate_dir in [_active_epic_rules_dir(h, epic_id), _project_rules_dir(h)]:
        p = candidate_dir / f"{patch_id}.md"
        if p.exists():
            p.unlink()
            removed.append(str(p))

    updated = dict(meta)
    updated["status"] = "reverted"
    updated["reverted_at"] = now_iso()
    _save_patch_meta(h, updated)
    _update_rules_index(h)

    append_trace_event(h, _make_trace_event(
        epic_id, "patch_reverted",
        patch_id=patch_id,
        status="warn",
        command_name="harnessctl patch revert",
        summary=f"Patch {patch_id} reverted",
    ))

    if args.json:
        out_json({"patch_id": patch_id, "status": "reverted", "removed": removed})
    else:
        print(f"⏪ Patch reverted: {patch_id}")
        for r in removed:
            print(f"   Removed: {r}")


def cmd_patch_promote(args, h: Path) -> None:
    """Promote an epic-local patch to project scope."""
    patch_id = args.patch_id
    meta = _load_patch_meta(h, patch_id)

    if meta.get("status") not in ("active_epic", "shadow_validating", "ready_for_project"):
        err(f"Patch {patch_id} is not ready to promote (status={meta.get('status')})")

    # Move to project-active
    md = _patch_md_path(h, patch_id)
    if not md.exists():
        err(f"candidate-patch.md not found for {patch_id}")
    dest_dir = _project_rules_dir(h)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{patch_id}.md"
    dest.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")

    updated = dict(meta)
    updated["status"] = "project_active"
    updated["scope"] = "project-active"
    updated["promoted_at"] = now_iso()
    _save_patch_meta(h, updated)
    _update_rules_index(h)

    append_trace_event(h, _make_trace_event(
        meta.get("epic_id", ""), "patch_promoted",
        patch_id=patch_id,
        status="ok",
        command_name="harnessctl patch promote",
        summary=f"Patch {patch_id} promoted to project-active",
    ))

    if args.json:
        out_json({"patch_id": patch_id, "status": "project_active", "path": str(dest)})
    else:
        print(f"🚀 Patch promoted to project scope: {patch_id}")
        print(f"   Will load for all future epics in this project.")


def cmd_patch_archive(args, h: Path) -> None:
    """Archive a patch (mark as inactive, remove from rules)."""
    patch_id = args.patch_id
    meta = _load_patch_meta(h, patch_id)
    epic_id = meta.get("epic_id", "")
    reason = getattr(args, "reason", "") or ""

    for candidate_dir in [_active_epic_rules_dir(h, epic_id), _project_rules_dir(h)]:
        p = candidate_dir / f"{patch_id}.md"
        if p.exists():
            p.unlink()

    updated = dict(meta)
    updated["status"] = "archived"
    updated["archived_at"] = now_iso()
    if reason:
        updated["archive_reason"] = reason
    _save_patch_meta(h, updated)
    _update_rules_index(h)

    if args.json:
        out_json({"patch_id": patch_id, "status": "archived"})
    else:
        print(f"📦 Patch archived: {patch_id}")


def cmd_patch_observe(args, h: Path) -> None:
    """Record a live observation for a patch (shadow validation)."""
    patch_id = args.patch_id
    epic_id = getattr(args, "epic_id", "") or ""
    prevented = str(getattr(args, "prevented_repeat", "false")).lower() in ("true", "1", "yes")
    notes = getattr(args, "notes", "") or ""

    meta = _load_patch_meta(h, patch_id)
    obs = {
        "ts": now_iso(),
        "epic_id": epic_id,
        "patch_id": patch_id,
        "scope": meta.get("scope", ""),
        "applied": True,
        "prevented_repeat": prevented,
        "notes": notes,
    }
    _append_patch_observation(h, patch_id, obs)

    # Auto-advance status if enough positive observations
    cfg = merged_harness_config(h)
    min_obs = int(cfg.get("patch_shadow_min_observations", 2))
    obs_path = _patch_obs_path(h, patch_id)
    if obs_path.exists():
        all_obs = [json.loads(l) for l in obs_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        positive = sum(1 for o in all_obs if o.get("prevented_repeat"))
        if positive >= min_obs and meta.get("status") in ("active_epic", "shadow_validating"):
            updated = dict(meta)
            updated["status"] = "ready_for_project"
            updated["match_rate"] = round(positive / len(all_obs), 2)
            _save_patch_meta(h, updated)
            print(f"  ✨ Patch {patch_id} now ready_for_project ({positive}/{len(all_obs)} positive observations)")

    if args.json:
        out_json(obs)
    else:
        print(f"Observation recorded for {patch_id}: prevented_repeat={prevented}")


def cmd_patch_diagnose(args, h: Path) -> None:
    """Print diagnostic context for an epic — to be consumed by system-observer agent."""
    epic_id = args.epic_id

    state = load_state(h, epic_id)
    trace_path = _trace_dir_for_epic(h, epic_id) / "execution-trace.jsonl"

    # Gather last N trace events
    trace_lines: list[dict] = []
    if trace_path.exists():
        raw = trace_path.read_text(encoding="utf-8").splitlines()
        for line in raw[-50:]:  # last 50 events
            try:
                trace_lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Gather high-value failure events
    failure_events = [e for e in trace_lines if e.get("event_type") in (
        "stage_gate_failed", "guard_failed", "task_triaged",
        "task_completed_hook_blocked", "teammate_idle_blocked", "gate_skipped",
    )]

    # Gather triage reports
    triage_dir = h / "features" / epic_id / "triage"
    triages = []
    if triage_dir.exists():
        for f in sorted(triage_dir.glob("*.json")):
            try:
                triages.append(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue

    # Gather active rules (to avoid duplicates)
    active_rules = _load_active_rules(h, epic_id=epic_id)

    # Gather gate-skips
    gate_skips_path = h / "features" / epic_id / "gate-skips.json"
    gate_skips = []
    if gate_skips_path.exists():
        try:
            gate_skips = json.loads(gate_skips_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Handoff
    handoff_path = h / "features" / epic_id / "handoff.md"
    handoff = handoff_path.read_text(encoding="utf-8") if handoff_path.exists() else ""

    diag = {
        "epic_id": epic_id,
        "current_stage": state.get("current_stage"),
        "risk_level": state.get("risk_level"),
        "runtime_health": state.get("runtime_health", {}),
        "interrupt_budget": state.get("interrupt_budget", {}),
        "failure_events": failure_events,
        "triage_reports": triages,
        "gate_skips": gate_skips,
        "active_rules_count": len(active_rules),
        "active_rules": [r["path"] for r in active_rules],
        "handoff_excerpt": handoff[:800] if handoff else "",
        "trace_event_count": len(trace_lines),
        "latest_trace_events": trace_lines[-10:],
    }

    if args.json:
        out_json(diag)
    else:
        print("=== JIT Diagnostic Package ===")
        print(f"Epic: {epic_id}  Stage: {diag['current_stage']}  Risk: {diag['risk_level']}")
        print(f"Budget: {diag['interrupt_budget']}")
        print(f"Runtime health: {diag['runtime_health']}")
        print(f"\nFailure events ({len(failure_events)}):")
        for e in failure_events[-5:]:
            print(f"  [{e.get('event_type')}] {e.get('summary','')}")
        print(f"\nTriage reports ({len(triages)})")
        print(f"Gate skips ({len(gate_skips)})")
        print(f"Active rules ({len(active_rules)})")
        print(f"\nTrace events: {len(trace_lines)} total")
        print(f"\nTo generate a patch, ask system-observer:")
        print(f"  Invoke agent: system-observer")
        print(f"  Input: harnessctl patch diagnose --epic-id {epic_id} --json")


def cmd_patch_trace(args, h: Path) -> None:
    """Append a raw trace event (for use by hook scripts)."""
    event_json = getattr(args, "event_json", "") or ""
    if not event_json:
        err("--event-json required")
    try:
        event = json.loads(event_json)
    except json.JSONDecodeError as ex:
        err(f"Invalid JSON: {ex}")
    epic_id = event.get("epic_id") or ""
    if not epic_id:
        err("event_json must contain epic_id")
    append_trace_event(h, event)
    if args.json:
        out_json({"status": "ok", "event_type": event.get("event_type")})
    else:
        print(f"Trace appended: {event.get('event_type')} for {epic_id}")


def _update_rules_index(h: Path) -> None:
    """Regenerate rules index from all active rule files."""
    index: dict = {"project_active": [], "epic_local": {}, "updated_at": now_iso()}
    proj_dir = _project_rules_dir(h)
    if proj_dir.exists():
        index["project_active"] = [f.name for f in sorted(proj_dir.glob("*.md"))]
    epic_local_root = h / "rules" / "epic-local"
    if epic_local_root.exists():
        for epic_dir in sorted(epic_local_root.iterdir()):
            if epic_dir.is_dir():
                files = [f.name for f in sorted(epic_dir.glob("*.md"))]
                if files:
                    index["epic_local"][epic_dir.name] = files
    atomic_write_json(_rules_index_path(h), index)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnessctl",
        description="stage-harness CLI — manage epics, tasks, and stage transitions",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    parser.add_argument(
        "--project-root",
        metavar="DIR",
        help="Project root directory (default: auto-detect from cwd)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ---- init ----
    p_init = sub.add_parser("init", help="Initialize .harness/ directory structure")
    p_init.add_argument("--force", action="store_true", help="Reinitialize even if .harness/ exists")
    p_init.add_argument("--json", action="store_true")

    # ---- start ----
    p_start = sub.add_parser("start", help="Bootstrap harness and create an epic from a fuzzy requirement")
    p_start.add_argument("requirements", help="Fuzzy requirement or problem statement")
    p_start.add_argument("--title", default="", help="Optional explicit epic title")
    p_start.add_argument("--risk-level", dest="risk_level", choices=RISK_LEVELS)
    p_start.add_argument("--json", action="store_true")

    # ---- setup / doctor / repair ----
    p_setup = sub.add_parser("setup", help="Prepare plugin checkout and optionally initialize a project harness")
    p_setup.add_argument(
        "--init-project",
        action="store_true",
        help="Also initialize .harness/ under --project-root or cwd when missing",
    )
    p_setup.add_argument("--json", action="store_true")

    p_doctor = sub.add_parser("doctor", help="Run plugin installation and runtime self-checks")
    p_doctor.add_argument("--json", action="store_true")

    p_repair = sub.add_parser("repair", help="Plan or apply low-risk installation/runtime repairs")
    p_repair.add_argument("--apply", action="store_true", help="Apply repairs (default: dry-run only)")
    p_repair.add_argument("--json", action="store_true")

    # ---- config ----
    p_config = sub.add_parser("config", help="Read/write .harness/config.json")
    config_sub = p_config.add_subparsers(dest="config_action", metavar="ACTION")
    config_sub.required = True

    p_cget = config_sub.add_parser("get", help="Get a config value")
    p_cget.add_argument("key")
    p_cget.add_argument("--json", action="store_true")

    p_cset = config_sub.add_parser("set", help="Set a config value")
    p_cset.add_argument("key")
    p_cset.add_argument("value")
    p_cset.add_argument("--json", action="store_true")

    p_clist = config_sub.add_parser("list", help="List all config values")
    p_clist.add_argument("--json", action="store_true")

    # ---- profile ----
    p_profile = sub.add_parser("profile", help="Project profile detection and display")
    profile_sub = p_profile.add_subparsers(dest="profile_action", metavar="ACTION")
    profile_sub.required = True

    p_pdetect = profile_sub.add_parser("detect", help="Auto-detect project type")
    p_pdetect.add_argument("--json", action="store_true")

    p_pshow = profile_sub.add_parser("show", help="Show current project profile")
    p_pshow.add_argument("--json", action="store_true")

    p_paliases = profile_sub.add_parser(
        "discover-repo-aliases",
        help="Heuristically fill package_aliases / import_prefixes in repo-catalog.yaml",
    )
    p_paliases.add_argument(
        "--write",
        action="store_true",
        help="Write merged aliases back to .harness/repo-catalog.yaml (default: dry-run)",
    )
    p_paliases.add_argument("--json", action="store_true")

    # ---- epic ----
    p_epic = sub.add_parser("epic", help="Manage epics")
    epic_sub = p_epic.add_subparsers(dest="epic_action", metavar="ACTION")
    epic_sub.required = True

    p_ecreate = epic_sub.add_parser("create", help="Create a new epic")
    p_ecreate.add_argument("title", nargs="?", default="", help="Epic title")
    p_ecreate.add_argument("--title", dest="title_flag", default="", help="Epic title")
    p_ecreate.add_argument("--description", default="", help="Optional epic description")
    p_ecreate.add_argument("--risk-level", dest="risk_level", choices=RISK_LEVELS)
    p_ecreate.add_argument("--json", action="store_true")

    p_eshow = epic_sub.add_parser("show", help="Show an epic")
    p_eshow.add_argument("id", help="Epic ID (e.g. sh-1-feature-name)")
    p_eshow.add_argument("--json", action="store_true")

    p_elist = epic_sub.add_parser("list", help="List all epics")
    p_elist.add_argument("--json", action="store_true")

    p_esetwt = epic_sub.add_parser("set-worktree", help="Record worktree path for an epic")
    p_esetwt.add_argument("epic_id")
    p_esetwt.add_argument("worktree_path")
    p_esetwt.add_argument("--repo-id", default="", help="Optional repo_id for cross-repo epic coordination")
    p_esetwt.add_argument("--branch", default="")
    p_esetwt.add_argument("--json", action="store_true")

    p_eshowwt = epic_sub.add_parser("show-worktrees", help="Show epic and repo-level worktree mappings")
    p_eshowwt.add_argument("epic_id")
    p_eshowwt.add_argument("--json", action="store_true")

    # ---- task ----
    p_task = sub.add_parser("task", help="Manage tasks")
    task_sub = p_task.add_subparsers(dest="task_action", metavar="ACTION")
    task_sub.required = True

    p_tcreate = task_sub.add_parser("create", help="Create a new task")
    p_tcreate.add_argument("epic_id", help="Epic ID")
    p_tcreate.add_argument("title", help="Task title")
    p_tcreate.add_argument("--surface", default="")
    p_tcreate.add_argument("--json", action="store_true")

    p_tstart = task_sub.add_parser("start", help="Mark task as in_progress")
    p_tstart.add_argument("task_id")
    p_tstart.add_argument("--json", action="store_true")

    p_tdone = task_sub.add_parser("done", help="Mark task as done")
    p_tdone.add_argument("task_id")
    p_tdone.add_argument("--json", action="store_true")

    p_tfail = task_sub.add_parser("fail", help="Mark task as failed")
    p_tfail.add_argument("task_id")
    p_tfail.add_argument("--json", action="store_true")

    p_tblock = task_sub.add_parser("block", help="Mark task as blocked")
    p_tblock.add_argument("task_id")
    p_tblock.add_argument("--json", action="store_true")

    p_tshow = task_sub.add_parser("show", help="Show task details")
    p_tshow.add_argument("task_id")
    p_tshow.add_argument("--json", action="store_true")

    p_tlist = task_sub.add_parser("list", help="List tasks for an epic")
    p_tlist.add_argument("epic_id")
    p_tlist.add_argument("--status", default=None, help="Filter by status")
    p_tlist.add_argument("--json", action="store_true")

    p_tnext = task_sub.add_parser("next", help="Get next ready task for an epic")
    p_tnext.add_argument("--epic-id", dest="epic_id", required=True)
    p_tnext.add_argument("--json", action="store_true")

    # ---- stage-gate ----
    p_sg = sub.add_parser("stage-gate", help="Stage gate checks")
    sg_sub = p_sg.add_subparsers(dest="sg_action", metavar="ACTION")
    sg_sub.required = True

    p_sgcheck = sg_sub.add_parser("check", help="Check artifacts for a stage gate")
    p_sgcheck.add_argument("stage", help="Stage name (CLARIFY, SPEC, PLAN, EXECUTE, VERIFY, DONE)")
    p_sgcheck.add_argument("--epic-id", dest="epic_id", required=True)
    p_sgcheck.add_argument("--json", action="store_true")

    # ---- clarify-selfcheck ----
    p_clar_sc = sub.add_parser(
        "clarify-selfcheck",
        help="CLARIFY clarification-notes structure + full artifact checklist (non-blocking)",
    )
    p_clar_sc.add_argument("--epic-id", dest="epic_id", required=True)
    p_clar_sc.add_argument("--json", action="store_true")

    # ---- receipt ----
    p_receipt = sub.add_parser("receipt", help="Manage runtime receipts")
    receipt_sub = p_receipt.add_subparsers(dest="receipt_action", metavar="ACTION")
    receipt_sub.required = True

    p_rwrite = receipt_sub.add_parser("write", help="Write a runtime receipt for a task")
    p_rwrite.add_argument("task_id")
    p_rwrite.add_argument("--base-commit", dest="base_commit", default="")
    p_rwrite.add_argument("--head-commit", dest="head_commit", default="")
    p_rwrite.add_argument("--smoke-passed", dest="smoke_passed", default="true")
    p_rwrite.add_argument("--json", action="store_true")

    p_rshow = receipt_sub.add_parser("show", help="Show runtime receipt for a task")
    p_rshow.add_argument("task_id")
    p_rshow.add_argument("--json", action="store_true")

    p_rlist = receipt_sub.add_parser("list", help="List all receipts for an epic")
    p_rlist.add_argument("epic_id")
    p_rlist.add_argument("--json", action="store_true")

    # ---- council ----
    p_council = sub.add_parser("council", help="Council management")
    council_sub = p_council.add_subparsers(dest="council_action", metavar="ACTION")
    council_sub.required = True

    p_crun = council_sub.add_parser("run", help="Show/initialize council for an epic")
    p_crun.add_argument("council_type", help="Council type (light_council, plan_council, acceptance_council, release_council)")
    p_crun.add_argument("--epic-id", dest="epic_id", required=True)
    p_crun.add_argument("--json", action="store_true")

    p_cagg = council_sub.add_parser("aggregate", help="Aggregate reviewer votes into final verdict")
    p_cagg.add_argument("council_type")
    p_cagg.add_argument("--epic-id", dest="epic_id", required=True)
    p_cagg.add_argument("--json", action="store_true")

    # ---- metrics ----
    p_metrics = sub.add_parser("metrics", help="Record scan ROI metrics and acceptance checks")
    metrics_sub = p_metrics.add_subparsers(dest="metrics_action", metavar="ACTION")
    metrics_sub.required = True

    p_mrecord = metrics_sub.add_parser("record", help="Record one ROI metric value for an epic")
    p_mrecord.add_argument("--epic-id", dest="epic_id", required=True)
    p_mrecord.add_argument("metric", help="Metric name (e.g. cache_hit_rate)")
    p_mrecord.add_argument("value", help="Metric value; JSON/number/bool/string accepted")
    p_mrecord.add_argument("--stage", default="", help="Optional stage label (CLARIFY/PLAN/etc.)")
    p_mrecord.add_argument("--notes", default="", help="Optional context / evidence note")
    p_mrecord.add_argument("--json", action="store_true")

    p_mcheck = metrics_sub.add_parser("check", help="Record an acceptance check status for an epic")
    p_mcheck.add_argument("--epic-id", dest="epic_id", required=True)
    p_mcheck.add_argument("criterion", help="Criterion key (e.g. mvp_no_blind_scan)")
    p_mcheck.add_argument("status", choices=ACCEPTANCE_STATUSES)
    p_mcheck.add_argument("--notes", default="", help="Optional context / evidence note")
    p_mcheck.add_argument("--json", action="store_true")

    p_mderive = metrics_sub.add_parser("derive", help="Derive acceptance checks from stage artifacts")
    p_mderive.add_argument("--epic-id", dest="epic_id", required=True)
    p_mderive.add_argument("--json", action="store_true")

    p_mshow = metrics_sub.add_parser("show", help="Show metrics for one epic or all epics")
    p_mshow.add_argument("--epic-id", dest="epic_id", default="")
    p_mshow.add_argument("--json", action="store_true")

    # ---- memory ----
    p_memory = sub.add_parser("memory", help="Memory management")
    memory_sub = p_memory.add_subparsers(dest="memory_action", metavar="ACTION")
    memory_sub.required = True

    p_map = memory_sub.add_parser("append-pitfalls", help="Append pitfalls from unknowns-ledger to memory")
    p_map.add_argument("--epic-id", dest="epic_id", required=True)
    p_map.add_argument("--json", action="store_true")

    p_minit = memory_sub.add_parser("codemap-init", help="Create a CodeMap file from the standard template")
    p_minit.add_argument("repo_id")
    p_minit.add_argument("module_slug")
    p_minit.add_argument("--source-path", action="append", required=True, help="Source path covered by the CodeMap; may repeat")
    p_minit.add_argument("--verified-commit", default="", help="Optional verified commit SHA")
    p_minit.add_argument("--confidence", default="medium", choices=["high", "medium", "low"])
    p_minit.add_argument("--purpose", default="", help="Optional one-paragraph purpose to replace template placeholder")
    p_minit.add_argument("--force", action="store_true", help="Overwrite existing CodeMap file")
    p_minit.add_argument("--json", action="store_true")

    p_mprobe = memory_sub.add_parser(
        "codemap-probe",
        help="Check whether CodeMap source_paths changed since verified_commit (git)",
    )
    p_mprobe.add_argument(
        "path",
        help="Path to CodeMap .md (relative to project root or absolute)",
    )
    p_mprobe.add_argument(
        "--write",
        action="store_true",
        help="Set codemap_probe_at / codemap_stale and downgrade confidence when stale",
    )
    p_mprobe.add_argument("--json", action="store_true")

    p_maudit = memory_sub.add_parser(
        "codemap-audit",
        help="Batch-audit CodeMaps under a directory (defaults to .harness/memory/codemaps)",
    )
    p_maudit.add_argument(
        "path",
        nargs="?",
        default="",
        help="Optional CodeMap file or directory to audit",
    )
    p_maudit.add_argument(
        "--write",
        action="store_true",
        help="Write codemap_probe_at / codemap_stale updates back into probed CodeMaps",
    )
    p_maudit.add_argument(
        "--epic-id",
        dest="epic_id",
        default="",
        help="Optional epic_id; when set, also write .harness/features/<epic-id>/codemap-audit.json",
    )
    p_maudit.add_argument("--json", action="store_true")

    # ---- triage ----
    p_triage = sub.add_parser("triage", help="Create triage report for a failed task")
    p_triage.add_argument("epic_id")
    p_triage.add_argument("task_id")
    p_triage.add_argument("--reason", default="unknown")
    p_triage.add_argument("--failures", type=int, default=1)
    p_triage.add_argument("--json", action="store_true")

    # ---- state ----
    p_state = sub.add_parser("state", help="Manage epic state machine")
    state_sub = p_state.add_subparsers(dest="state_action", metavar="ACTION")
    state_sub.required = True

    p_sget = state_sub.add_parser("get", help="Get current state for an epic")
    p_sget.add_argument("epic_id")
    p_sget.add_argument("--field", default=None, help="Return specific dotted-path field only")
    p_sget.add_argument("--json", action="store_true")

    p_strans = state_sub.add_parser("transition", help="Transition epic to new stage")
    p_strans.add_argument("epic_id")
    p_strans.add_argument("new_stage")
    p_strans.add_argument("--json", action="store_true")

    p_spatch = state_sub.add_parser("patch", help="Patch specific state fields with --set key=value")
    p_spatch.add_argument("epic_id")
    p_spatch.add_argument("--set", action="append", metavar="KEY=VALUE", required=True)
    p_spatch.add_argument("--json", action="store_true")

    p_snext = state_sub.add_parser("next", help="Return next auto-mode action for an epic")
    p_snext.add_argument("--epic-id", dest="epic_id", required=True)
    p_snext.add_argument("--json", action="store_true")

    # ---- budget ----
    p_budget = sub.add_parser("budget", help="Interrupt budget management")
    budget_sub = p_budget.add_subparsers(dest="budget_action", metavar="ACTION")
    budget_sub.required = True

    p_bcheck = budget_sub.add_parser("check", help="Check interrupt budget remaining")
    p_bcheck.add_argument("--epic-id", dest="epic_id", required=True)
    p_bcheck.add_argument("--json", action="store_true")

    p_bconsume = budget_sub.add_parser("consume", help="Consume one interrupt from the budget")
    p_bconsume.add_argument("--epic-id", dest="epic_id", required=True)
    p_bconsume.add_argument("--json", action="store_true")

    # ---- guard ----
    p_guard = sub.add_parser("guard", help="Guard checks for auto mode")
    guard_sub = p_guard.add_subparsers(dest="guard_action", metavar="ACTION")
    guard_sub.required = True

    p_gcheck = guard_sub.add_parser("check", help="Run guard checks before entering a stage")
    p_gcheck.add_argument("--epic-id", dest="epic_id", required=True)
    p_gcheck.add_argument("--stage", default=None, help="Target stage to enter")
    p_gcheck.add_argument("--json", action="store_true")

    # ---- bundle ----
    p_bundle = sub.add_parser("bundle", help="Decision bundle management")
    bundle_sub = p_bundle.add_subparsers(dest="bundle_action", metavar="ACTION")
    bundle_sub.required = True

    p_bsumm = bundle_sub.add_parser("summary", help="Show decision bundle summary")
    p_bsumm.add_argument("--epic-id", dest="epic_id", required=True)
    p_bsumm.add_argument("--json", action="store_true")

    p_bpc = bundle_sub.add_parser("pending-confirms", help="List pending must_confirm decisions")
    p_bpc.add_argument("--epic-id", dest="epic_id", required=True)
    p_bpc.add_argument("--json", action="store_true")

    p_bcc = bundle_sub.add_parser("check-confirmed", help="Check all must_confirm decisions are resolved")
    p_bcc.add_argument("--epic-id", dest="epic_id", required=True)
    p_bcc.add_argument("--json", action="store_true")

    # ---- audit ----
    p_audit = sub.add_parser("audit", help="Execution audit views")
    audit_sub = p_audit.add_subparsers(dest="audit_action", metavar="ACTION")
    audit_sub.required = True

    p_ashow = audit_sub.add_parser("show", help="Show CLARIFY execution summary for an epic")
    p_ashow.add_argument("--epic-id", dest="epic_id", required=True)
    p_ashow.add_argument("--json", action="store_true")

    # ---- coverage ----
    p_cov = sub.add_parser("coverage", help="Coverage matrix management")
    cov_sub = p_cov.add_subparsers(dest="cov_action", metavar="ACTION")
    cov_sub.required = True

    p_covmap = cov_sub.add_parser("map", help="Generate/update coverage matrix from tasks + unknowns")
    p_covmap.add_argument("--epic-id", dest="epic_id", required=True)
    p_covmap.add_argument("--reset", action="store_true", help="Reset and regenerate from scratch")
    p_covmap.add_argument("--json", action="store_true")

    p_covshow = cov_sub.add_parser("show", help="Show current coverage matrix")
    p_covshow.add_argument("--epic-id", dest="epic_id", required=True)
    p_covshow.add_argument("--json", action="store_true")

    # ---- gate ----
    p_gate = sub.add_parser("gate", help="Stage gate management")
    gate_sub = p_gate.add_subparsers(dest="gate_action", metavar="ACTION")
    gate_sub.required = True

    p_gskip = gate_sub.add_parser("skip", help="Skip a stage gate (emergency override, recorded)")
    p_gskip.add_argument("stage")
    p_gskip.add_argument("--epic-id", dest="epic_id", required=True)
    p_gskip.add_argument("--justification", default="")
    p_gskip.add_argument("--json", action="store_true")

    # ---- skill ----
    p_skill = sub.add_parser("skill", help="Candidate skill lifecycle management")
    skill_sub = p_skill.add_subparsers(dest="skill_action", metavar="ACTION")
    skill_sub.required = True

    p_sklist = skill_sub.add_parser("list", help="List candidate skills")
    p_sklist.add_argument("--json", action="store_true")

    p_skshow = skill_sub.add_parser("show", help="Show a candidate skill")
    p_skshow.add_argument("skill_id")
    p_skshow.add_argument("--json", action="store_true")

    p_skprom = skill_sub.add_parser("promote", help="Promote a candidate skill to active")
    p_skprom.add_argument("skill_id")
    p_skprom.add_argument("--json", action="store_true")

    p_skarc = skill_sub.add_parser("archive", help="Archive a candidate skill")
    p_skarc.add_argument("skill_id")
    p_skarc.add_argument("--reason", default="")
    p_skarc.add_argument("--json", action="store_true")

    # ---- status ----
    p_status = sub.add_parser("status", help="Show overview of all epics")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--check-init", dest="check_init", action="store_true",
                          help="Exit with code 1 if .harness/ not initialized")

    # ---- patch (JIT Evolution) ----
    p_patch = sub.add_parser("patch", help="JIT patch lifecycle (diagnose, apply, promote…)")
    patch_sub = p_patch.add_subparsers(dest="patch_action", metavar="ACTION")
    patch_sub.required = True

    p_pdiag = patch_sub.add_parser("diagnose", help="Print diagnostic context for system-observer")
    p_pdiag.add_argument("--epic-id", dest="epic_id", required=True)
    p_pdiag.add_argument("--json", action="store_true")

    p_plist = patch_sub.add_parser("list", help="List all candidate patches")
    p_plist.add_argument("--scope", default="all", choices=["epic", "project", "all"])
    p_plist.add_argument("--json", action="store_true")

    p_pshow = patch_sub.add_parser("show", help="Show a patch")
    p_pshow.add_argument("patch_id")
    p_pshow.add_argument("--json", action="store_true")

    p_papply = patch_sub.add_parser("apply", help="Apply a patch to epic-local or project rules")
    p_papply.add_argument("patch_id")
    p_papply.add_argument("--scope", default="epic", choices=["epic", "project"])
    p_papply.add_argument("--json", action="store_true")

    p_prev = patch_sub.add_parser("revert", help="Revert an active patch")
    p_prev.add_argument("patch_id")
    p_prev.add_argument("--json", action="store_true")

    p_pprom = patch_sub.add_parser("promote", help="Promote epic-local patch to project scope")
    p_pprom.add_argument("patch_id")
    p_pprom.add_argument("--json", action="store_true")

    p_parc = patch_sub.add_parser("archive", help="Archive a patch")
    p_parc.add_argument("patch_id")
    p_parc.add_argument("--reason", default="")
    p_parc.add_argument("--json", action="store_true")

    p_pobs = patch_sub.add_parser("observe", help="Record a shadow observation for a patch")
    p_pobs.add_argument("patch_id")
    p_pobs.add_argument("--epic-id", dest="epic_id", default="")
    p_pobs.add_argument("--prevented-repeat", dest="prevented_repeat", default="false")
    p_pobs.add_argument("--notes", default="")
    p_pobs.add_argument("--json", action="store_true")

    p_ptrace = patch_sub.add_parser("trace", help="Append a raw trace event (for hook scripts)")
    p_ptrace.add_argument("--event-json", dest="event_json", required=True)
    p_ptrace.add_argument("--json", action="store_true")

    # ---- validate ----
    p_validate = sub.add_parser("validate", help="Validate .harness/ directory integrity")
    p_validate.add_argument("--json", action="store_true")

    return parser


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve project root
    if args.project_root:
        project_root = Path(args.project_root).resolve()
    else:
        if args.command in {"init", "setup", "doctor", "repair"}:
            project_root = Path.cwd().resolve()
        elif args.command == "start":
            project_root = find_bootstrap_root()
        else:
            project_root = find_harness_root()

    h = project_root / HARNESS_DIR

    # For init we don't require .harness/ to exist yet
    if args.command == "init":
        cmd_init(args, project_root)
        return
    if args.command == "setup":
        cmd_setup(args, project_root)
        return
    if args.command == "doctor":
        cmd_doctor(args, project_root)
        return
    if args.command == "repair":
        cmd_repair(args, project_root)
        return
    if args.command == "start":
        cmd_start(args, project_root)
        return

    # All other commands require .harness/ to exist
    if not h.is_dir():
        err(f".harness/ not found at {h}. Run 'harnessctl init' first.")

    # Dispatch
    if args.command == "config":
        if args.config_action == "get":
            cmd_config_get(args, h)
        elif args.config_action == "set":
            cmd_config_set(args, h)
        elif args.config_action == "list":
            cmd_config_list(args, h)

    elif args.command == "profile":
        if args.profile_action == "detect":
            cmd_profile_detect(args, h, project_root)
        elif args.profile_action == "show":
            cmd_profile_show(args, h)
        elif args.profile_action == "discover-repo-aliases":
            cmd_profile_discover_repo_aliases(args, h, project_root)

    elif args.command == "epic":
        if args.epic_action == "create":
            cmd_epic_create(args, h)
        elif args.epic_action == "show":
            cmd_epic_show(args, h)
        elif args.epic_action == "list":
            cmd_epic_list(args, h)
        elif args.epic_action == "set-worktree":
            cmd_epic_set_worktree(args, h)
        elif args.epic_action == "show-worktrees":
            cmd_epic_show_worktrees(args, h)

    elif args.command == "task":
        if args.task_action == "create":
            cmd_task_create(args, h)
        elif args.task_action == "start":
            cmd_task_start(args, h)
        elif args.task_action == "done":
            cmd_task_done(args, h)
        elif args.task_action == "fail":
            cmd_task_fail(args, h)
        elif args.task_action == "block":
            cmd_task_block(args, h)
        elif args.task_action == "show":
            cmd_task_show(args, h)
        elif args.task_action == "list":
            cmd_task_list(args, h)
        elif args.task_action == "next":
            cmd_task_next(args, h)

    elif args.command == "stage-gate":
        if args.sg_action == "check":
            cmd_stage_gate_check(args, h, project_root)

    elif args.command == "clarify-selfcheck":
        cmd_clarify_selfcheck(args, h, project_root)

    elif args.command == "receipt":
        if args.receipt_action == "write":
            cmd_receipt_write(args, h)
        elif args.receipt_action == "show":
            cmd_receipt_show(args, h)
        elif args.receipt_action == "list":
            cmd_receipt_list(args, h)

    elif args.command == "council":
        if args.council_action == "run":
            cmd_council_run(args, h)
        elif args.council_action == "aggregate":
            cmd_council_aggregate(args, h)

    elif args.command == "metrics":
        if args.metrics_action == "record":
            cmd_metrics_record(args, h)
        elif args.metrics_action == "check":
            cmd_metrics_check(args, h)
        elif args.metrics_action == "derive":
            cmd_metrics_derive(args, h)
        elif args.metrics_action == "show":
            cmd_metrics_show(args, h)

    elif args.command == "memory":
        if args.memory_action == "append-pitfalls":
            cmd_memory_append_pitfalls(args, h)
        elif args.memory_action == "codemap-init":
            cmd_memory_codemap_init(args, h, project_root)
        elif args.memory_action == "codemap-probe":
            cmd_memory_codemap_probe(args, h, project_root)
        elif args.memory_action == "codemap-audit":
            cmd_memory_codemap_audit(args, h, project_root)

    elif args.command == "triage":
        cmd_triage(args, h)

    elif args.command == "state":
        if args.state_action == "get":
            cmd_state_get(args, h)
        elif args.state_action == "transition":
            cmd_state_transition(args, h)
        elif args.state_action == "patch":
            cmd_state_patch(args, h)
        elif args.state_action == "next":
            cmd_state_next(args, h)

    elif args.command == "budget":
        if args.budget_action == "check":
            cmd_budget_check(args, h)
        elif args.budget_action == "consume":
            cmd_budget_consume(args, h)

    elif args.command == "guard":
        if args.guard_action == "check":
            cmd_guard_check(args, h, project_root)

    elif args.command == "bundle":
        if args.bundle_action == "summary":
            cmd_bundle_summary(args, h)
        elif args.bundle_action == "pending-confirms":
            cmd_bundle_pending_confirms(args, h)
        elif args.bundle_action == "check-confirmed":
            cmd_bundle_check_confirmed(args, h)

    elif args.command == "audit":
        if args.audit_action == "show":
            cmd_audit_show(args, h)

    elif args.command == "coverage":
        if args.cov_action == "map":
            cmd_coverage_map(args, h)
        elif args.cov_action == "show":
            cmd_coverage_show(args, h)

    elif args.command == "gate":
        if args.gate_action == "skip":
            cmd_gate_skip(args, h)

    elif args.command == "skill":
        if args.skill_action == "list":
            cmd_skill_list(args, h)
        elif args.skill_action == "show":
            cmd_skill_show(args, h)
        elif args.skill_action == "promote":
            cmd_skill_promote(args, h)
        elif args.skill_action == "archive":
            cmd_skill_archive(args, h)

    elif args.command == "patch":
        if args.patch_action == "diagnose":
            cmd_patch_diagnose(args, h)
        elif args.patch_action == "list":
            cmd_patch_list(args, h)
        elif args.patch_action == "show":
            cmd_patch_show(args, h)
        elif args.patch_action == "apply":
            cmd_patch_apply(args, h)
        elif args.patch_action == "revert":
            cmd_patch_revert(args, h)
        elif args.patch_action == "promote":
            cmd_patch_promote(args, h)
        elif args.patch_action == "archive":
            cmd_patch_archive(args, h)
        elif args.patch_action == "observe":
            cmd_patch_observe(args, h)
        elif args.patch_action == "trace":
            cmd_patch_trace(args, h)

    elif args.command == "status":
        if getattr(args, "check_init", False):
            # Just check that .harness/ exists; h is already valid at this point
            print("Initialized")
        else:
            cmd_status(args, h)

    elif args.command == "validate":
        cmd_validate(args, h)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
