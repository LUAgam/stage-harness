#!/usr/bin/env python3
"""Shared CLARIFY gate helpers for harnessctl and verify-artifacts.sh.

This file is the single implementation source for:
- clarification-notes structural validation
- signal-driven CLARIFY gate
- deep-dive escalation hints / strict gate
- user focus-point closure (maps to REQ/CHK/SCN/DEC/UNK)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CLARIFY_AXES: list[tuple[str, str, str]] = [
    ("StateAndTime", r"StateAndTime|行为与流程", "StateAndTime / 行为与流程"),
    ("ConstraintsAndConflict", r"ConstraintsAndConflict|规则与边界", "ConstraintsAndConflict / 规则与边界"),
    ("CostAndCapacity", r"CostAndCapacity|规模与代价", "CostAndCapacity / 规模与代价"),
    ("CrossSurfaceConsistency", r"CrossSurfaceConsistency|多入口|多阶段一致性", "CrossSurfaceConsistency / 多入口"),
    ("OperationsAndRecovery", r"OperationsAndRecovery|运行与维护", "OperationsAndRecovery / 运行与维护"),
    ("SecurityAndIsolation", r"SecurityAndIsolation|权限与隔离", "SecurityAndIsolation / 权限与隔离"),
]


# Top-level keys required by stage-gate check CLARIFY for domain-frame.json (presence only).
DOMAIN_FRAME_REQUIRED_KEYS: tuple[str, ...] = (
    "business_goals",
    "domain_constraints",
    "semantic_signals",
    "candidate_edge_cases",
    "candidate_open_questions",
)

STRICT_SCENARIO_ID_RE = re.compile(r"^SCN-\d+$", re.IGNORECASE)
SCENARIO_COVERAGE_ALLOWED_STATUSES: frozenset[str] = frozenset(
    {"covered", "needs_decision", "deferred", "dropped_invalid"}
)
COUPLING_ROLE_ID_RE = re.compile(r"^role\.[a-z0-9_.-]+$", re.IGNORECASE)
COUPLING_EXEMPTION_BIND_RE = re.compile(r"^(?:DEC|UNK)-\d+$", re.IGNORECASE)


def domain_frame_missing_required_keys(data: dict) -> list[str]:
    """Return required top-level keys missing from domain-frame data (same order as DOMAIN_FRAME_REQUIRED_KEYS)."""
    return [key for key in DOMAIN_FRAME_REQUIRED_KEYS if key not in data]


def _non_empty_string(value: object) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


def generated_scenarios_strict_errors(data: object) -> list[str]:
    """Validate the canonical generated-scenarios contract used by stage-gate CLARIFY."""
    if not isinstance(data, dict):
        return ["root must be a JSON object"]

    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        return ["field `scenarios` must be a JSON array"]

    errors: list[str] = []
    if any(not isinstance(item, dict) for item in scenarios):
        errors.append("field `scenarios` must contain only JSON objects")
    seen_ids: set[str] = set()
    for idx, item in enumerate(scenarios):
        if not isinstance(item, dict):
            continue
        if not item:
            errors.append(f"scenarios[{idx}] must not be an empty object")
            continue
        confidence = str(item.get("confidence", "")).strip().lower()
        if confidence not in ("high", "medium", "low", ""):
            errors.append(
                f"scenarios[{idx}] has invalid `confidence` {confidence!r}; expected high, medium, low, or empty"
            )
            continue
        if confidence == "":
            if any(
                _non_empty_string(value)
                or (isinstance(value, list) and any(_non_empty_string(x) for x in value))
                for value in item.values()
            ):
                errors.append(
                    f"scenarios[{idx}] must declare `confidence` when scenario content is present"
                )
            continue
        if confidence == "low":
            continue

        scenario_id = str(item.get("scenario_id", "")).strip()
        if not scenario_id:
            errors.append(f"scenarios[{idx}] missing non-empty `scenario_id` for {confidence} confidence")
        elif not STRICT_SCENARIO_ID_RE.fullmatch(scenario_id):
            errors.append(
                f"scenarios[{idx}] has invalid `scenario_id` {scenario_id!r}; expected SCN-<digits>"
            )
        elif scenario_id.upper() in seen_ids:
            errors.append(f"scenarios[{idx}] duplicates `scenario_id` {scenario_id!r}")
        else:
            seen_ids.add(scenario_id.upper())

        if not _non_empty_string(item.get("pattern")):
            errors.append(f"scenarios[{idx}] missing non-empty `pattern` for {confidence} confidence")

        source_signals = item.get("source_signals")
        if not isinstance(source_signals, list) or len(source_signals) == 0:
            errors.append(
                f"scenarios[{idx}] missing non-empty `source_signals` array for {confidence} confidence"
            )

        for field_name in ("scenario", "why_it_matters", "expected_followup"):
            if not _non_empty_string(item.get(field_name)):
                errors.append(
                    f"scenarios[{idx}] missing non-empty `{field_name}` for {confidence} confidence"
                )
    return errors


def scenario_coverage_strict_errors(data: object) -> list[str]:
    """Validate the canonical scenario-coverage contract used by stage-gate CLARIFY."""
    if not isinstance(data, dict):
        return ["root must be a JSON object"]

    if not _non_empty_string(data.get("epic_id")):
        return ["missing non-empty `epic_id`"]
    if not _non_empty_string(data.get("version")):
        return ["missing non-empty `version`"]

    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        return ["field `scenarios` must be a JSON array"]

    signals = data.get("signals")
    if signals is not None and not isinstance(signals, list):
        return ["field `signals` must be a JSON array when present"]

    errors: list[str] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(scenarios):
        if not isinstance(item, dict):
            errors.append(f"scenarios[{idx}] must be a JSON object")
            continue

        scenario_id = str(item.get("scenario_id", "")).strip()
        if not scenario_id:
            errors.append(f"scenarios[{idx}] missing non-empty `scenario_id`")
        elif not STRICT_SCENARIO_ID_RE.fullmatch(scenario_id):
            errors.append(
                f"scenarios[{idx}] has invalid `scenario_id` {scenario_id!r}; expected SCN-<digits>"
            )
        elif scenario_id.upper() in seen_ids:
            errors.append(f"scenarios[{idx}] duplicates `scenario_id` {scenario_id!r}")
        else:
            seen_ids.add(scenario_id.upper())

        status = str(item.get("status", "")).strip()
        if status not in SCENARIO_COVERAGE_ALLOWED_STATUSES:
            errors.append(
                f"scenarios[{idx}] has invalid `status` "
                f"{status!r}; expected one of {', '.join(sorted(SCENARIO_COVERAGE_ALLOWED_STATUSES))}"
            )
            continue

        mapped_to = item.get("mapped_to")
        if status != "dropped_invalid" and (not isinstance(mapped_to, list) or len(mapped_to) == 0):
            errors.append(
                f"scenarios[{idx}] missing non-empty `mapped_to` array when status != dropped_invalid"
            )
    return errors


def _normalized_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def coupling_role_ids_from_profile(data: object) -> list[str]:
    if not isinstance(data, dict):
        return []
    return _normalized_string_list(data.get("coupling_role_ids"))


def profile_coupling_role_errors(data: object) -> list[str]:
    if not isinstance(data, dict):
        return []
    if "coupling_role_ids" not in data:
        return []
    role_ids = data.get("coupling_role_ids")
    if not isinstance(role_ids, list):
        return ["project-profile.yaml (`coupling_role_ids` must be a YAML list when present)"]

    errors: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(role_ids):
        text = str(item).strip()
        if not text:
            errors.append(
                f"project-profile.yaml (`coupling_role_ids[{idx}]` must be a non-empty string)"
            )
            continue
        if not COUPLING_ROLE_ID_RE.fullmatch(text):
            errors.append(
                "project-profile.yaml "
                f"(`coupling_role_ids[{idx}]` has invalid role id {text!r}; expected role.<name>)"
            )
            continue
        key = text.upper()
        if key in seen:
            errors.append(
                f"project-profile.yaml (`coupling_role_ids[{idx}]` duplicates role id {text!r})"
            )
            continue
        seen.add(key)
    return errors


def surface_routing_coupling_errors(data: object, known_role_ids: list[str]) -> list[str]:
    if not isinstance(data, dict):
        return []
    surfaces = data.get("surfaces")
    if not isinstance(surfaces, list):
        return []

    known_roles_upper = {role.upper() for role in known_role_ids}
    errors: list[str] = []
    for idx, surface in enumerate(surfaces):
        if not isinstance(surface, dict) or "serves_roles" not in surface:
            continue
        serves_roles = surface.get("serves_roles")
        if not isinstance(serves_roles, list) or len(serves_roles) == 0:
            errors.append(
                f"surface-routing.json (surfaces[{idx}].serves_roles must be a non-empty array when present)"
            )
            continue
        seen: set[str] = set()
        for role_idx, raw_role in enumerate(serves_roles):
            role_id = str(raw_role).strip()
            if not role_id:
                errors.append(
                    f"surface-routing.json (surfaces[{idx}].serves_roles[{role_idx}] must be a non-empty string)"
                )
                continue
            if not COUPLING_ROLE_ID_RE.fullmatch(role_id):
                errors.append(
                    "surface-routing.json "
                    f"(surfaces[{idx}].serves_roles[{role_idx}] has invalid role id {role_id!r}; expected role.<name>)"
                )
                continue
            role_key = role_id.upper()
            if role_key in seen:
                errors.append(
                    f"surface-routing.json (surfaces[{idx}].serves_roles[{role_idx}] duplicates role id {role_id!r})"
                )
                continue
            seen.add(role_key)
            if known_roles_upper and role_key not in known_roles_upper:
                errors.append(
                    "surface-routing.json "
                    f"(surfaces[{idx}].serves_roles[{role_idx}] references unknown role id {role_id!r})"
                )
    return errors


def change_coupling_closure_errors(data: object, known_role_ids: list[str]) -> list[str]:
    if not isinstance(data, dict):
        return ["change-coupling-closure.json (root must be a JSON object)"]

    errors: list[str] = []
    if not _non_empty_string(data.get("version")):
        errors.append("change-coupling-closure.json (missing non-empty `version`)")

    required_role_ids = data.get("required_role_ids")
    if required_role_ids is not None and not isinstance(required_role_ids, list):
        errors.append("change-coupling-closure.json (`required_role_ids` must be a JSON array when present)")

    exemptions = data.get("exemptions")
    if exemptions is not None and not isinstance(exemptions, list):
        errors.append("change-coupling-closure.json (`exemptions` must be a JSON array when present)")

    known_roles_upper = {role.upper() for role in known_role_ids}
    seen_required: set[str] = set()
    for idx, raw_role in enumerate(required_role_ids or []):
        role_id = str(raw_role).strip()
        if not role_id:
            errors.append(
                f"change-coupling-closure.json (`required_role_ids[{idx}]` must be a non-empty string)"
            )
            continue
        if not COUPLING_ROLE_ID_RE.fullmatch(role_id):
            errors.append(
                "change-coupling-closure.json "
                f"(`required_role_ids[{idx}]` has invalid role id {role_id!r}; expected role.<name>)"
            )
            continue
        role_key = role_id.upper()
        if role_key in seen_required:
            errors.append(
                f"change-coupling-closure.json (`required_role_ids[{idx}]` duplicates role id {role_id!r})"
            )
            continue
        seen_required.add(role_key)
        if known_roles_upper and role_key not in known_roles_upper:
            errors.append(
                f"change-coupling-closure.json (`required_role_ids[{idx}]` references unknown role id {role_id!r})"
            )

    seen_exempt: set[str] = set()
    for idx, item in enumerate(exemptions or []):
        if not isinstance(item, dict):
            errors.append(f"change-coupling-closure.json (`exemptions[{idx}]` must be a JSON object)")
            continue
        role_id = str(item.get("role_id", "")).strip()
        if not role_id:
            errors.append(f"change-coupling-closure.json (`exemptions[{idx}].role_id` is required)")
            continue
        if not COUPLING_ROLE_ID_RE.fullmatch(role_id):
            errors.append(
                "change-coupling-closure.json "
                f"(`exemptions[{idx}].role_id` has invalid role id {role_id!r}; expected role.<name>)"
            )
            continue
        role_key = role_id.upper()
        if role_key in seen_exempt:
            errors.append(
                f"change-coupling-closure.json (`exemptions[{idx}].role_id` duplicates role id {role_id!r})"
            )
        seen_exempt.add(role_key)
        if known_roles_upper and role_key not in known_roles_upper:
            errors.append(
                f"change-coupling-closure.json (`exemptions[{idx}].role_id` references unknown role id {role_id!r})"
            )
        binds_to = str(item.get("binds_to", "")).strip()
        if not COUPLING_EXEMPTION_BIND_RE.fullmatch(binds_to):
            errors.append(
                "change-coupling-closure.json "
                f"(`exemptions[{idx}].binds_to` must reference DEC-* or UNK-*, got {binds_to!r})"
            )
    return errors


def change_coupling_closure_warnings(
    closure_data: object,
    surface_routing_data: object,
    known_role_ids: list[str],
) -> list[str]:
    if not isinstance(closure_data, dict):
        return []

    required_roles = _normalized_string_list(closure_data.get("required_role_ids"))
    if not required_roles:
        return []

    routed_roles: set[str] = set()
    if isinstance(surface_routing_data, dict):
        surfaces = surface_routing_data.get("surfaces")
        if isinstance(surfaces, list):
            for surface in surfaces:
                if not isinstance(surface, dict):
                    continue
                for role_id in _normalized_string_list(surface.get("serves_roles")):
                    routed_roles.add(role_id.upper())

    exempt_roles: set[str] = set()
    exemptions = closure_data.get("exemptions")
    if isinstance(exemptions, list):
        for item in exemptions:
            if not isinstance(item, dict):
                continue
            role_id = str(item.get("role_id", "")).strip()
            if role_id:
                exempt_roles.add(role_id.upper())

    warnings: list[str] = []
    uncovered = [role_id for role_id in required_roles if role_id.upper() not in routed_roles and role_id.upper() not in exempt_roles]
    if uncovered:
        warnings.append(
            "change-coupling-closure.json "
            f"(required_role_ids not covered by surface-routing.json or exemptions: {', '.join(uncovered)})"
        )

    unused_exemptions = []
    known_roles_upper = {role.upper() for role in known_role_ids}
    exemption_role_values = []
    if isinstance(exemptions, list):
        for item in exemptions:
            if isinstance(item, dict):
                exemption_role_values.append(item.get("role_id"))
    required_roles_upper = {r.upper() for r in required_roles}
    for role_id in _normalized_string_list(exemption_role_values):
        role_upper = role_id.upper()
        if role_upper not in required_roles_upper:
            unused_exemptions.append(role_id)
        elif known_roles_upper and role_upper not in known_roles_upper:
            unused_exemptions.append(role_id)
    if unused_exemptions:
        warnings.append(
            "change-coupling-closure.json "
            f"(exemptions reference role_ids outside required_role_ids: {', '.join(unused_exemptions)})"
        )

    return warnings


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


def _safe_load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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


def clarify_notes_only_closure_errors(features_dir: Path) -> list[str]:
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

    minimal_ok, axis_section, _axis_states = _clarify_minimal_mode_and_axis_states(text)
    if not minimal_ok and not axis_section:
        errors.append(
            f"{cn.name}: add «## 六轴澄清覆盖» (per-axis covered|not_applicable|unknown) "
            "OR «## 极简澄清绕行» with global not_applicable + one-line reason"
        )

    tri_re = re.compile(
        r"(?i)\b(covered|not_applicable|not\s+applicable|unknown|已覆盖|不适用|尚不清楚)\b"
    )
    if not minimal_ok and axis_section:
        for _axis_id, pattern, label in CLARIFY_AXES:
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


def _iter_high_medium_signal_texts(features_dir: Path) -> list[dict]:
    rows: list[dict] = []
    data = _safe_load_json(features_dir / "domain-frame.json")
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

    data = _safe_load_json(features_dir / "generated-scenarios.json")
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


def clarify_signal_gate_summary(features_dir: Path) -> dict:
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


def clarify_signal_gate_errors(features_dir: Path) -> list[str]:
    """Signal-driven CLARIFY gate: only strengthen axes when high/medium signals justify it."""
    summary = clarify_signal_gate_summary(features_dir)
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


def _clarify_ambiguous_requirement_ids(req_text: str) -> list[str]:
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


def clarify_deep_dive_summary(features_dir: Path) -> dict:
    """Return deep-dive escalation state derived from signals + ambiguous requirements."""
    summary = clarify_signal_gate_summary(features_dir)
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


def clarify_deep_dive_hints(features_dir: Path) -> list[str]:
    """Suggest deep-dive when high-risk signals coexist with ambiguous requirements."""
    summary = clarify_deep_dive_summary(features_dir)
    if not summary.get("should_escalate"):
        return []
    sample = "; ".join(summary.get("candidates", [])[:3])
    reqs = ", ".join(summary.get("ambiguous_requirements", [])[:4]) or "REQ-?"
    return [
        "CLARIFY deep-dive hint: requirements-draft 中存在 UNCLEAR/AMBIGUOUS，且命中高风险语义信号，"
        f"建议触发 `deep-dive-specialist` 调查这些主题：{sample}（相关需求：{reqs}）"
    ]


_CLOSURE_REF_RE = re.compile(r"\b(REQ|CHK|SCN|DEC|UNK)-\d+\b", re.IGNORECASE)

_SCN_ID_RE = re.compile(r"\bSCN-\d+\b", re.IGNORECASE)

_FOCUS_SECTION_HEADING = re.compile(
    r"(?im)^#{1,4}\s*(?:focus\s*points|用户关注点|用户点名关注)\b"
)

_FOCUS_NONE_LINE = re.compile(
    r"(?i)^\s*[-*•\d.)]+\s*(无|none|n/a|na\b|无可追踪|用户未点名|本轮无关注点)\b"
)


def _state_flow_signal_rule() -> dict | None:
    for rule in CLARIFY_SIGNAL_RULES:
        if rule.get("id") == "state-flow":
            return rule
    return None


def _scn_ids_in_value(val: object) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [m.group(0).upper() for m in _SCN_ID_RE.finditer(val)]
    if isinstance(val, list):
        out: list[str] = []
        for x in val:
            out.extend(_scn_ids_in_value(x))
        return out
    return []


def _scenario_coverage_status_by_scn(features_dir: Path) -> dict[str, str]:
    data = _safe_load_json(features_dir / "scenario-coverage.json")
    scenarios = data.get("scenarios") if isinstance(data, dict) else None
    out: dict[str, str] = {}
    if not isinstance(scenarios, list):
        return out
    for item in scenarios:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("scenario_id", "")).strip()
        if not sid:
            continue
        out[sid.upper()] = str(item.get("status", "")).strip().lower()
    return out


_STATE_CONSTRAINT_SIGNAL_GATE_AXES: frozenset[str] = frozenset(
    {"StateAndTime", "ConstraintsAndConflict"}
)


def _clarify_signal_rules_for_state_constraint_gate() -> list[dict]:
    """Rules whose axes touch StateAndTime or ConstraintsAndConflict (only those axes in CLARIFY_SIGNAL_RULES)."""
    out: list[dict] = []
    for rule in CLARIFY_SIGNAL_RULES:
        axes = set(rule.get("axes", []))
        if axes & _STATE_CONSTRAINT_SIGNAL_GATE_AXES:
            out.append(rule)
    return out


def _high_confidence_scn_focus_errors_for_rule_subset(
    features_dir: Path,
    rules: list[dict],
) -> list[str]:
    """Shared loop: high-confidence generated SCN in coverage must appear in Focus when text hits given rules."""
    errors: list[str] = []
    if not rules:
        return errors
    compiled: list[tuple[str, re.Pattern[str]]] = [
        (str(r["id"]), re.compile(str(r["regex"]))) for r in rules
    ]

    gen = _safe_load_json(features_dir / "generated-scenarios.json")
    scenarios = gen.get("scenarios") if isinstance(gen, dict) else None
    if not isinstance(scenarios, list):
        return errors

    cov = _scenario_coverage_status_by_scn(features_dir)
    explicit = _explicit_scn_ids_in_focus_surfaces(features_dir)

    for item in scenarios:
        if not isinstance(item, dict):
            continue
        if str(item.get("confidence", "")).strip().lower() != "high":
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
        combined = " | ".join(parts)
        source_signals = item.get("source_signals")
        source_signal_refs = (
            {
                str(source).strip()
                for source in source_signals
                if str(source).strip()
            }
            if isinstance(source_signals, list)
            else set()
        )
        structured_match = any(
            source_ref.startswith("state_transition_scenarios[")
            or source_ref.startswith("constraint_conflicts[")
            for source_ref in source_signal_refs
        )
        regex_match = any(rx.search(combined) for _rid, rx in compiled)
        if not structured_match and not regex_match:
            continue
        sid_raw = str(item.get("scenario_id", "")).strip()
        if not re.fullmatch(r"(?i)SCN-\d+", sid_raw):
            continue
        sid = sid_raw.upper()
        status = cov.get(sid)
        if status is None:
            continue
        if status == "dropped_invalid":
            continue
        if sid not in explicit:
            errors.append(
                "CLARIFY focus closure (full): 高置信度且命中 StateAndTime / ConstraintsAndConflict "
                f"风险信号的场景 {sid}（generated-scenarios.json）须在 "
                "«Focus Points»/«用户关注点»/«用户点名关注» 或 focus-points.json "
                "（maps_to|closure_ref|mapped_to|trace）显式出现该 SCN 编号"
            )
    return errors


def clarify_state_constraint_signal_scn_focus_errors(features_dir: Path) -> list[str]:
    """Full-mode gate: high-confidence SCN matching State/Constraint signal rules must appear in Focus closure.

    Caller must only invoke when ``clarify_closure_mode != notes_only``.
    Uses ``CLARIFY_SIGNAL_RULES`` entries whose axes intersect StateAndTime or ConstraintsAndConflict
    (currently ``state-flow`` and ``constraints-identity``); does not use cost/cross-surface/security rules.
    """
    return _high_confidence_scn_focus_errors_for_rule_subset(
        features_dir,
        _clarify_signal_rules_for_state_constraint_gate(),
    )


def _explicit_scn_ids_in_focus_surfaces(features_dir: Path) -> set[str]:
    """SCN ids mentioned in Focus headings section body and/or focus-points.json trace fields."""
    ids: set[str] = set()
    cn = features_dir / "clarification-notes.md"
    if cn.exists() and cn.is_file() and cn.stat().st_size > 0:
        text = cn.read_text(encoding="utf-8", errors="replace")
        m = _FOCUS_SECTION_HEADING.search(text)
        if m:
            rest = text[m.end() :]
            section_lines: list[str] = []
            for line in rest.splitlines():
                if re.match(r"^#{1,4}\s", line):
                    break
                section_lines.append(line)
            chunk = "\n".join(section_lines)
            for match in _SCN_ID_RE.finditer(chunk):
                ids.add(match.group(0).upper())

    fp_path = features_dir / "focus-points.json"
    if fp_path.exists():
        try:
            data = json.loads(fp_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    for key in ("maps_to", "closure_ref", "mapped_to", "trace"):
                        for sid in _scn_ids_in_value(item.get(key)):
                            ids.add(sid.upper())
    return ids


def clarify_state_flow_scn_focus_errors(features_dir: Path) -> list[str]:
    """CLI/back-compat: same as full gate but only the ``state-flow`` signal rule (StateAndTime)."""
    rule = _state_flow_signal_rule()
    if not rule:
        return []
    return _high_confidence_scn_focus_errors_for_rule_subset(features_dir, [rule])


def _focus_refs_in_value(val: object) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return _CLOSURE_REF_RE.findall(val)
    if isinstance(val, list):
        out: list[str] = []
        for x in val:
            out.extend(_focus_refs_in_value(x))
        return out
    return []


def clarify_focus_point_closure_errors(features_dir: Path) -> list[str]:
    """When users declare explicit focus points, require traceable closure refs.

    Sources (any triggers validation when non-empty):
    - ``focus-points.json`` with non-empty ``items`` array
    - ``clarification-notes.md`` section «Focus Points» / «用户关注点» / «用户点名关注»
    """
    errors: list[str] = []
    fp_path = features_dir / "focus-points.json"
    if fp_path.exists():
        raw = fp_path.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(f"{fp_path.name}: invalid JSON")
            return errors
        if not isinstance(data, dict):
            errors.append(f"{fp_path.name}: root must be a JSON object")
            return errors
        items = data.get("items")
        if isinstance(items, list) and len(items) > 0:
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"{fp_path.name}: items[{idx}] must be an object")
                    continue
                refs: list[str] = []
                for key in ("maps_to", "closure_ref", "mapped_to", "trace"):
                    refs.extend(_focus_refs_in_value(item.get(key)))
                if not refs:
                    label = str(item.get("id") or item.get("title") or idx).strip()
                    errors.append(
                        f"{fp_path.name}: focus item «{label}» missing maps_to / closure_ref "
                        "to REQ-/CHK-/SCN-/DEC-/UNK-"
                    )

    cn = features_dir / "clarification-notes.md"
    if not cn.exists() or (cn.is_file() and cn.stat().st_size == 0):
        return errors

    text = cn.read_text(encoding="utf-8", errors="replace")
    m = _FOCUS_SECTION_HEADING.search(text)
    if not m:
        return errors

    rest = text[m.end() :]
    section_lines: list[str] = []
    for line in rest.splitlines():
        if re.match(r"^#{1,4}\s", line):
            break
        section_lines.append(line)

    bullets: list[str] = []
    non_bullet_lines: list[str] = []
    for line in section_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"(?i)^\s*[-*•]\s", line) or re.match(r"^\s*\d+[.)]\s", line):
            bullets.append(stripped)
        else:
            non_bullet_lines.append(stripped)

    if not bullets:
        if non_bullet_lines:
            errors.append(
                f"{cn.name}: Focus Points section must use bullets with REQ-/CHK-/SCN-/DEC-/UNK- refs "
                f"(found paragraph text: {non_bullet_lines[0][:120]}{'…' if len(non_bullet_lines[0]) > 120 else ''})"
            )
        return errors

    if len(bullets) == 1 and _FOCUS_NONE_LINE.match(bullets[0]):
        return errors

    for b in bullets:
        if _FOCUS_NONE_LINE.match(b):
            continue
        if not _CLOSURE_REF_RE.search(b):
            errors.append(
                f"{cn.name}: Focus Points bullet must map to REQ-/CHK-/SCN-/DEC-/UNK- "
                f"(missing in: {b[:120]}{'…' if len(b) > 120 else ''})"
            )

    return errors


def clarify_deep_dive_gate_errors(features_dir: Path) -> list[str]:
    """Blocking deep-dive gate for teams that opt into strict escalation."""
    summary = clarify_deep_dive_summary(features_dir)
    if not summary.get("should_escalate"):
        return []
    reqs = ", ".join(summary.get("ambiguous_requirements", [])[:4]) or "REQ-?"
    sample = "; ".join(summary.get("candidates", [])[:3])
    return [
        "CLARIFY deep-dive gate: 命中高风险语义信号且 requirements-draft 存在 "
        f"UNCLEAR/AMBIGUOUS（{reqs}），但尚无 `deep-dive-*.md` 备忘录；"
        f"请触发 `deep-dive-specialist` 调查：{sample}"
    ]


def _print_lines(lines: list[str]) -> int:
    for line in lines:
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clarify_gate_shared",
        description="Shared CLARIFY gate checks for harnessctl and verify-artifacts.sh",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in (
        "notes-errors",
        "signal-errors",
        "deep-dive-errors",
        "deep-dive-hints",
        "focus-errors",
        "state-flow-scn-focus-errors",
        "state-constraint-scn-focus-errors",
        "summary",
    ):
        p = sub.add_parser(name)
        p.add_argument("features_dir")
        p.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    features_dir = Path(args.features_dir).resolve()

    if args.command == "notes-errors":
        _print_lines(clarify_notes_only_closure_errors(features_dir))
        return
    if args.command == "signal-errors":
        _print_lines(clarify_signal_gate_errors(features_dir))
        return
    if args.command == "deep-dive-errors":
        _print_lines(clarify_deep_dive_gate_errors(features_dir))
        return
    if args.command == "deep-dive-hints":
        _print_lines(clarify_deep_dive_hints(features_dir))
        return
    if args.command == "focus-errors":
        _print_lines(clarify_focus_point_closure_errors(features_dir))
        return
    if args.command == "state-flow-scn-focus-errors":
        _print_lines(clarify_state_flow_scn_focus_errors(features_dir))
        return
    if args.command == "state-constraint-scn-focus-errors":
        _print_lines(clarify_state_constraint_signal_scn_focus_errors(features_dir))
        return
    if args.command == "summary":
        data = {
            "notes_errors": clarify_notes_only_closure_errors(features_dir),
            "signal_summary": clarify_signal_gate_summary(features_dir),
            "signal_errors": clarify_signal_gate_errors(features_dir),
            "deep_dive_summary": clarify_deep_dive_summary(features_dir),
            "deep_dive_hints": clarify_deep_dive_hints(features_dir),
            "deep_dive_errors": clarify_deep_dive_gate_errors(features_dir),
            "focus_errors": clarify_focus_point_closure_errors(features_dir),
            "state_flow_scn_focus_errors": clarify_state_flow_scn_focus_errors(features_dir),
            "state_constraint_signal_scn_focus_errors": clarify_state_constraint_signal_scn_focus_errors(
                features_dir
            ),
        }
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
