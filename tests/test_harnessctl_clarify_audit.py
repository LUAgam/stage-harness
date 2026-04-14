import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESSCTL = ROOT / "scripts" / "harnessctl.py"
DECISION_BUNDLE = ROOT / "scripts" / "decision-bundle.sh"
VERIFY_ARTIFACTS = ROOT / "scripts" / "verify-artifacts.sh"


def run_harnessctl(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HARNESSCTL), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def run_decision_bundle(cwd: Path, epic_id: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HARNESS_DIR": ".harness", "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run(
        ["bash", str(DECISION_BUNDLE), *args[:1], epic_id, *args[1:]],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def run_verify_artifacts(cwd: Path, epic_id: str, stage: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(VERIFY_ARTIFACTS), epic_id, stage],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HARNESS_DIR": ".harness"},
    )


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class HarnessctlClarifyAuditTests(unittest.TestCase):
    def _bootstrap_epic(self, tmp_path: Path, requirement: str = "Need audit-ready clarify flow") -> str:
        result = run_harnessctl(
            tmp_path,
            "--project-root",
            str(tmp_path),
            "start",
            requirement,
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["epic_id"]

    def test_stage_gate_multi_repo_requires_cross_repo_impact_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need multi-repo clarify artifacts")
            features_dir = tmp_path / ".harness" / "features" / epic_id
            profile_path = tmp_path / ".harness" / "project-profile.yaml"
            profile_path.write_text(
                "\n".join(
                    [
                        "type: unknown",
                        "risk_level: medium",
                        "primary_language: unknown",
                        "build_tool: unknown",
                        "test_framework: unknown",
                        "has_database: null",
                        "has_auth: null",
                        "has_docker: null",
                        "has_ci: null",
                        "estimated_size: unknown",
                        "workspace_mode: multi-repo",
                        "primary_surfaces: []",
                        "check_focus: []",
                        "intensity: {}",
                        "scan: {}",
                        'notes: ""',
                        'framework: ""',
                        "confidence: 0.9",
                        "overrides: {}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["Keep artifacts canonical"],
                    "domain_constraints": ["No repo-specific shortcuts"],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                            "pattern": "downstream-contract-shift",
                            "source_signals": ["semantic_signals[0]"],
                            "confidence": "medium",
                            "scenario": "Shared contract changes across repos",
                            "why_it_matters": "Multiple repos may need aligned updates",
                            "expected_followup": "REQ",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                            "status": "covered",
                            "mapped_to": ["REQ-001"],
                            "notes": "",
                        }
                    ],
                },
            )
            (features_dir / "requirements-draft.md").write_text("### REQ-001\n\nDefined.\n", encoding="utf-8")
            (features_dir / "challenge-report.md").write_text("## Summary\n\nok\n", encoding="utf-8")
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Ctx.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "## Blast Radius Summary\n\nx\n\n## High Impact Surfaces\n\n- repo-a/\n\n## Medium Impact Surfaces\n\n- repo-b/\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {
                    "epic": epic_id,
                    "created_at": "",
                    "surfaces": [{"type": "code_repository", "path": "repo-a/"}],
                },
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {"total": 0, "open": 0, "resolved_in_spec": 0, "resolved_in_plan": 0, "resolved_in_verify": 0, "deferred": 0},
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {"version": "1.0", "epic_id": epic_id, "stage": "CLARIFY", "decisions": []},
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-001",
                    "created_at": "",
                    "questions": [],
                    "auto_release_if_all_answered": True,
                },
            )

            fail = run_harnessctl(tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id)
            self.assertNotEqual(fail.returncode, 0)
            self.assertIn("cross-repo-impact-index.json", fail.stdout)

            write_json(
                features_dir / "cross-repo-impact-index.json",
                {
                    "epic": epic_id,
                    "repos": [],
                    "interfaces": [],
                    "shared_artifacts": [],
                    "excluded_repos": [],
                },
            )
            still_fail = run_harnessctl(tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id)
            self.assertNotEqual(still_fail.returncode, 0)
            self.assertIn("repos must be a non-empty JSON array", still_fail.stdout)

            write_json(
                features_dir / "cross-repo-impact-index.json",
                {
                    "epic": epic_id,
                    "repos": [{"repo_id": "repo-a", "path": "repo-a/"}],
                    "interfaces": [],
                    "shared_artifacts": [],
                    "excluded_repos": [],
                },
            )
            ok = run_harnessctl(tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

    def test_audit_show_summarizes_clarify_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)

            events = [
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "clarify_run_started",
                    "payload": {"run_id": "clr-000"},
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "step_completed",
                    "payload": {
                        "run_id": "clr-000",
                        "step": "old-run-step",
                        "agent_role": "legacy-role",
                        "execution_mode": "single_agent",
                    },
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "clarify_run_started",
                    "payload": {"run_id": "clr-001"},
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "step_completed",
                    "payload": {
                        "run_id": "clr-001",
                        "step": "domain-scout",
                        "agent_role": "domain-scout",
                        "execution_mode": "single_agent",
                    },
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "parallel_wave_completed",
                    "payload": {
                        "run_id": "clr-001",
                        "wave_id": "wave-1",
                        "roles": [
                            "requirement-analyst",
                            "impact-analyst",
                            "challenger",
                            "scenario-expander",
                        ],
                    },
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "impact-analyst",
                    "event_type": "step_completed",
                    "payload": {
                        "run_id": "clr-001",
                        "step": "impact-analysis",
                        "agent_role": "impact-analyst",
                        "execution_mode": "fan_out_team",
                        "fanout_used": True,
                        "fanout_children_count": 3,
                    },
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "decision-bundle",
                    "event_type": "decision_packet_generated",
                    "payload": {"run_id": "clr-001", "questions_count": 1},
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "decision-bundle",
                    "event_type": "pending_decisions_synced",
                    "payload": {"run_id": "clr-001", "pending_count": 1},
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "clarify_run_completed",
                    "payload": {"run_id": "clr-001"},
                },
            ]

            for event in events:
                result = run_harnessctl(
                    tmp_path,
                    "patch",
                    "trace",
                    "--event-json",
                    json.dumps(event, ensure_ascii=False),
                    "--json",
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            result = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            self.assertEqual(payload["latest_run_id"], "clr-001")
            self.assertIn("domain-scout", payload["steps_completed"])
            self.assertNotIn("old-run-step", payload["steps_completed"])
            self.assertEqual(payload["parallel_waves_completed"], 1)
            self.assertTrue(payload["fanout_used"])
            self.assertEqual(payload["fanout_children_count"], 3)
            self.assertTrue(payload["decision_packet_generated"])
            self.assertTrue(payload["pending_decisions_synced"])

    def test_decision_packet_syncs_state_and_guard_uses_bundle_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            features_dir = tmp_path / ".harness" / "features" / epic_id

            result = run_decision_bundle(tmp_path, epic_id, "generate")
            self.assertEqual(result.returncode, 0, result.stderr)

            decision_path = tmp_path / "decision.json"
            write_json(
                decision_path,
                {
                    "question": "Need user confirmation before SPEC",
                    "category": "must_confirm",
                    "risk_if_wrong": "critical",
                    "severity": "critical",
                    "why_now": "Blocks SPEC",
                    "source_ref": "challenge-report:CHK-001",
                },
            )
            result = run_decision_bundle(tmp_path, epic_id, "add", str(decision_path))
            self.assertEqual(result.returncode, 0, result.stderr)

            result = run_decision_bundle(tmp_path, epic_id, "packet")
            self.assertEqual(result.returncode, 0, result.stderr)
            first_packet = json.loads((features_dir / "decision-packet.json").read_text(encoding="utf-8"))

            state_path = features_dir / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["pending_decisions"]), 1)
            self.assertEqual(state["pending_decisions"][0]["source_ref"], "challenge-report:CHK-001")
            self.assertEqual(state["pending_decisions"][0]["risk_if_wrong"], "critical")

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            audit_payload = json.loads(audit.stdout)
            self.assertTrue(audit_payload["decision_packet_generated"])
            self.assertTrue(audit_payload["pending_decisions_synced"])
            self.assertEqual(audit_payload["pending_decisions_count"], 1)

            result = run_decision_bundle(tmp_path, epic_id, "packet")
            self.assertEqual(result.returncode, 0, result.stderr)
            second_packet = json.loads((features_dir / "decision-packet.json").read_text(encoding="utf-8"))
            self.assertEqual(first_packet["packet_id"], second_packet["packet_id"])
            self.assertEqual(second_packet["interrupt_number"], first_packet["interrupt_number"])

            state["pending_decisions"] = []
            write_json(state_path, state)

            guard = run_harnessctl(
                tmp_path,
                "guard",
                "check",
                "--epic-id",
                epic_id,
                "--stage",
                "SPEC",
            )
            self.assertNotEqual(guard.returncode, 0)
            self.assertIn("unhandled CRITICAL decision", guard.stdout)

            next_action = run_harnessctl(
                tmp_path,
                "state",
                "next",
                "--epic-id",
                epic_id,
            )
            self.assertEqual(next_action.returncode, 0, next_action.stderr)
            self.assertEqual(next_action.stdout.strip(), "wait_user")

    def test_audit_show_uses_real_bundle_trace_with_latest_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)

            for event in (
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "clarify_run_started",
                    "payload": {"run_id": "clr-real"},
                },
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "source": "command",
                    "actor": "lead-orchestrator",
                    "event_type": "step_completed",
                    "payload": {
                        "run_id": "clr-real",
                        "step": "domain-scout",
                        "agent_role": "domain-scout",
                        "execution_mode": "single_agent",
                    },
                },
            ):
                result = run_harnessctl(
                    tmp_path,
                    "patch",
                    "trace",
                    "--event-json",
                    json.dumps(event, ensure_ascii=False),
                    "--json",
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            result = run_decision_bundle(tmp_path, epic_id, "generate")
            self.assertEqual(result.returncode, 0, result.stderr)
            decision_path = tmp_path / "decision.json"
            write_json(
                decision_path,
                {
                    "question": "Need confirmation",
                    "category": "must_confirm",
                    "source_ref": "challenge-report:CHK-001",
                },
            )
            result = run_decision_bundle(tmp_path, epic_id, "add", str(decision_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_decision_bundle(tmp_path, epic_id, "packet")
            self.assertEqual(result.returncode, 0, result.stderr)

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)
            self.assertEqual(payload["latest_run_id"], "clr-real")
            self.assertTrue(payload["decision_packet_generated"])
            self.assertTrue(payload["pending_decisions_synced"])
            self.assertEqual(payload["pending_decisions_count"], 1)

    def test_audit_show_uses_decision_artifacts_even_when_latest_run_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)

            result = run_harnessctl(
                tmp_path,
                "patch",
                "trace",
                "--event-json",
                json.dumps(
                    {
                        "epic_id": epic_id,
                        "stage": "CLARIFY",
                        "source": "command",
                        "actor": "lead-orchestrator",
                        "event_type": "clarify_run_started",
                        "payload": {"run_id": "clr-artifact-only"},
                    },
                    ensure_ascii=False,
                ),
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            result = run_decision_bundle(tmp_path, epic_id, "generate")
            self.assertEqual(result.returncode, 0, result.stderr)
            decision_path = tmp_path / "decision.json"
            write_json(
                decision_path,
                {
                    "question": "Need confirmation",
                    "category": "must_confirm",
                    "source_ref": "challenge-report:CHK-001",
                },
            )
            result = run_decision_bundle(tmp_path, epic_id, "add", str(decision_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_decision_bundle(tmp_path, epic_id, "packet")
            self.assertEqual(result.returncode, 0, result.stderr)

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)
            self.assertEqual(payload["latest_run_id"], "clr-artifact-only")
            self.assertTrue(payload["decision_packet_generated"])
            self.assertTrue(payload["pending_decisions_synced"])
            self.assertEqual(payload["pending_decisions_count"], 1)

    def test_audit_show_does_not_assign_old_artifacts_to_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need run-aware artifact inference")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["legacy artifact exists"],
                    "domain_constraints": [],
                    "invariants": [],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                    "state_transition_scenarios": [],
                    "constraint_conflicts": [],
                    "anti_patterns": [],
                },
            )

            result = run_harnessctl(
                tmp_path,
                "patch",
                "trace",
                "--event-json",
                json.dumps(
                    {
                        "epic_id": epic_id,
                        "stage": "CLARIFY",
                        "source": "command",
                        "actor": "lead-orchestrator",
                        "event_type": "clarify_run_started",
                        "payload": {"run_id": "clr-new"},
                    },
                    ensure_ascii=False,
                ),
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)
            self.assertEqual(payload["latest_run_id"], "clr-new")
            self.assertNotIn("domain-scout", payload["steps_completed"])

    def test_audit_show_infers_completed_steps_from_artifacts_without_trace_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need artifact-based clarify observability")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["Keep CLARIFY observable"],
                    "domain_constraints": ["No project-specific assumptions"],
                    "invariants": ["Artifacts imply step progress"],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                    "state_transition_scenarios": [],
                    "constraint_conflicts": [],
                    "anti_patterns": [],
                },
            )
            (features_dir / "requirements-draft.md").write_text(
                "### REQ-001\n\nClarify step produced requirements.\n",
                encoding="utf-8",
            )

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)

            self.assertIn("domain-scout", payload["steps_completed"])
            self.assertIn("requirement-analyst", payload["steps_completed"])
            self.assertEqual(payload["latest_run_id"], "")

    def test_audit_show_ignores_invalid_artifact_when_inferring_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need invalid artifact guard")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            (features_dir / "surface-routing.json").write_text("{not-json}\n", encoding="utf-8")

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)

            self.assertNotIn("surface-routing", payload["steps_completed"])

    def test_audit_show_ignores_structurally_empty_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need schema-aware artifact inference")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(features_dir / "surface-routing.json", {})

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)

            self.assertNotIn("surface-routing", payload["steps_completed"])

    def test_audit_show_ignores_surface_routing_without_type_or_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need observable surface-routing artifact")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "surface-routing.json",
                {
                    "epic": epic_id,
                    "created_at": "",
                    "surfaces": [{"type": "code_repository"}],
                },
            )

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)

            self.assertNotIn("surface-routing", payload["steps_completed"])

    def test_audit_show_ignores_empty_scenario_coverage_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need non-empty scenario coverage inference")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [],
                },
            )

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)

            self.assertNotIn("semantic-reconciliation", payload["steps_completed"])

    def test_audit_show_ignores_placeholder_generated_scenarios_without_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need generated scenario placeholder guard")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                            "confidence": "high",
                        }
                    ],
                },
            )

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)

            self.assertNotIn("scenario-expander", payload["steps_completed"])

    def test_audit_show_ignores_placeholder_scenario_coverage_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need scenario coverage placeholder guard")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                        }
                    ],
                },
            )

            audit = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            payload = json.loads(audit.stdout)

            self.assertNotIn("semantic-reconciliation", payload["steps_completed"])

    def test_stage_gate_requires_signal_closure_for_high_risk_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need robust clarify signal closure")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["Keep CLARIFY generic"],
                    "domain_constraints": ["Avoid silent drops"],
                    "invariants": ["High-risk semantics must close"],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                    "state_transition_scenarios": [
                        {
                            "transition": "delete then insert same logical key",
                            "confidence": "high",
                            "rationale": "State replay may violate expected semantics",
                        }
                    ],
                    "constraint_conflicts": [
                        {
                            "conflict": "insert conflict may amplify write cost",
                            "confidence": "high",
                            "rationale": "Conflict path can create capacity risk",
                        }
                    ],
                    "anti_patterns": [],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                            "pattern": "reinsert_after_delete",
                            "source_signals": ["state_transition_scenarios[0]"],
                            "confidence": "high",
                            "scenario": "Delete is rewritten, then same key is inserted again",
                            "why_it_matters": "May resurrect logically deleted rows incorrectly",
                            "expected_followup": "REQ",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                            "status": "covered",
                            "mapped_to": ["REQ-001"],
                            "notes": "",
                        }
                    ],
                },
            )
            (features_dir / "requirements-draft.md").write_text(
                "### REQ-001\n\nDelete rewrite and reinsert flow is explicitly defined.\n",
                encoding="utf-8",
            )
            (features_dir / "challenge-report.md").write_text(
                "## Summary\n\n- Constraint conflict remains.\n",
                encoding="utf-8",
            )
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Context.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Focus Points",
                        "- SCN-001 delete/insert semantics → REQ-001",
                        "",
                        "## Unknowns 与待确认决策",
                        "- DEC-001 pending",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "\n".join(
                    [
                        "## Blast Radius Summary",
                        "Broad but manageable.",
                        "",
                        "## High Impact Surfaces",
                        "- src/",
                        "",
                        "## Medium Impact Surfaces",
                        "- docs/",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {
                    "epic": epic_id,
                    "created_at": "",
                    "surfaces": [{"type": "code_repository", "path": "src/"}],
                },
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {"total": 0, "open": 0, "resolved_in_spec": 0, "resolved_in_plan": 0, "resolved_in_verify": 0, "deferred": 0},
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "decisions": [{"id": "DEC-001", "question": "Confirm", "category": "must_confirm"}],
                },
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-001",
                    "created_at": "",
                    "questions": [{"id": "DEC-001", "question": "Confirm"}],
                    "auto_release_if_all_answered": True,
                },
            )

            result = run_harnessctl(
                tmp_path,
                "stage-gate",
                "check",
                "CLARIFY",
                "--epic-id",
                epic_id,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("constraint_conflicts[0]", result.stdout)

            coverage = json.loads((features_dir / "scenario-coverage.json").read_text(encoding="utf-8"))
            coverage["signals"] = [
                {
                    "signal_ref": "constraint_conflicts[0]",
                    "status": "needs_decision",
                    "mapped_to": ["DEC-001"],
                    "notes": "Escalated to decision bundle",
                }
            ]
            write_json(features_dir / "scenario-coverage.json", coverage)

            result = run_harnessctl(
                tmp_path,
                "stage-gate",
                "check",
                "CLARIFY",
                "--epic-id",
                epic_id,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stage_gate_signal_closure_matches_scenario_ids_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need mixed-case scenario ids to close signals")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["Keep closure generic"],
                    "domain_constraints": ["Do not depend on SCN letter case"],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                    "state_transition_scenarios": [
                        {
                            "transition": "retry replay after state change",
                            "confidence": "high",
                            "rationale": "State closure must stay stable",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "scn-001",
                            "pattern": "replay",
                            "source_signals": ["state_transition_scenarios[0]"],
                            "confidence": "high",
                            "scenario": "Replay occurs after a state transition",
                            "why_it_matters": "Need explicit closure",
                            "expected_followup": "REQ",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-001",
                            "status": "covered",
                            "mapped_to": ["REQ-001"],
                        }
                    ],
                },
            )
            (features_dir / "requirements-draft.md").write_text("### REQ-001\n\nDefined.\n", encoding="utf-8")
            (features_dir / "challenge-report.md").write_text("## Summary\n\nok\n", encoding="utf-8")
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Ctx.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Focus Points",
                        "- SCN-001 -> REQ-001",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "## Blast Radius Summary\n\nx\n\n## High Impact Surfaces\n\n- src/\n\n## Medium Impact Surfaces\n\n- docs/\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {
                    "epic": epic_id,
                    "created_at": "",
                    "surfaces": [{"type": "code_repository", "path": "src/"}],
                },
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {"total": 0, "open": 0, "resolved_in_spec": 0, "resolved_in_plan": 0, "resolved_in_verify": 0, "deferred": 0},
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {"version": "1.0", "epic_id": epic_id, "stage": "CLARIFY", "decisions": []},
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-001",
                    "created_at": "",
                    "questions": [],
                    "auto_release_if_all_answered": True,
                },
            )

            result = run_harnessctl(
                tmp_path,
                "stage-gate",
                "check",
                "CLARIFY",
                "--epic-id",
                epic_id,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stage_gate_fails_when_high_confidence_generated_scenario_misses_strict_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need strict generated scenario contract")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["Keep artifacts canonical"],
                    "domain_constraints": ["Avoid placeholder scenarios"],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-101",
                            "confidence": "high",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [],
                },
            )
            (features_dir / "requirements-draft.md").write_text("### REQ-001\n\nDefined.\n", encoding="utf-8")
            (features_dir / "challenge-report.md").write_text("## Summary\n\nok\n", encoding="utf-8")
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Ctx.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "## Blast Radius Summary\n\nx\n\n## High Impact Surfaces\n\n- src/\n\n## Medium Impact Surfaces\n\n- docs/\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {
                    "epic": epic_id,
                    "created_at": "",
                    "surfaces": [{"type": "code_repository", "path": "src/"}],
                },
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {"total": 0, "open": 0, "resolved_in_spec": 0, "resolved_in_plan": 0, "resolved_in_verify": 0, "deferred": 0},
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {"version": "1.0", "epic_id": epic_id, "stage": "CLARIFY", "decisions": []},
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-001",
                    "created_at": "",
                    "questions": [],
                    "auto_release_if_all_answered": True,
                },
            )

            result = run_harnessctl(
                tmp_path,
                "stage-gate",
                "check",
                "CLARIFY",
                "--epic-id",
                epic_id,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("generated-scenarios.json", result.stdout)
            self.assertIn("missing non-empty `pattern`", result.stdout)

    def test_stage_gate_allows_low_confidence_generated_scenario_without_strict_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Low confidence scenario should stay compatible")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["Keep artifacts canonical"],
                    "domain_constraints": ["Avoid over-rejecting legacy data"],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "confidence": "low",
                            "scenario": "Placeholder legacy scenario",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [],
                },
            )
            (features_dir / "requirements-draft.md").write_text("### REQ-001\n\nDefined.\n", encoding="utf-8")
            (features_dir / "challenge-report.md").write_text("## Summary\n\nok\n", encoding="utf-8")
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Ctx.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "## Blast Radius Summary\n\nx\n\n## High Impact Surfaces\n\n- src/\n\n## Medium Impact Surfaces\n\n- docs/\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {
                    "epic": epic_id,
                    "created_at": "",
                    "surfaces": [{"type": "code_repository", "path": "src/"}],
                },
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {"total": 0, "open": 0, "resolved_in_spec": 0, "resolved_in_plan": 0, "resolved_in_verify": 0, "deferred": 0},
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {"version": "1.0", "epic_id": epic_id, "stage": "CLARIFY", "decisions": []},
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-001",
                    "created_at": "",
                    "questions": [],
                    "auto_release_if_all_answered": True,
                },
            )

            result = run_harnessctl(
                tmp_path,
                "stage-gate",
                "check",
                "CLARIFY",
                "--epic-id",
                epic_id,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_full_mode_state_flow_scn_requires_explicit_focus(self) -> None:
        """High-confidence state-flow SCN in generated + coverage must appear in Focus (full mode only)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "State-flow SCN focus gate")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["x"],
                    "domain_constraints": [],
                    "invariants": [],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                    "state_transition_scenarios": [],
                    "constraint_conflicts": [],
                    "anti_patterns": [],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-007",
                            "pattern": "replay",
                            "source_signals": ["state_transition_scenarios[0]"],
                            "confidence": "high",
                            "scenario": "User deletes a row then re-inserts the same primary key",
                            "why_it_matters": "Order of operations affects outcome",
                            "expected_followup": "REQ",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-007",
                            "status": "covered",
                            "mapped_to": ["REQ-010"],
                            "notes": "",
                        }
                    ],
                },
            )
            (features_dir / "requirements-draft.md").write_text(
                "### REQ-010\n\nDefined.\n",
                encoding="utf-8",
            )
            (features_dir / "challenge-report.md").write_text("## Summary\n\nok\n", encoding="utf-8")
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Ctx.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "## Blast Radius Summary\n\nx\n\n## High Impact Surfaces\n\n- a/\n\n## Medium Impact Surfaces\n\n- b/\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {"epic": epic_id, "created_at": "", "surfaces": [{"type": "code_repository", "path": "a/"}]},
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {
                        "total": 0,
                        "open": 0,
                        "resolved_in_spec": 0,
                        "resolved_in_plan": 0,
                        "resolved_in_verify": 0,
                        "deferred": 0,
                    },
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {"version": "1.0", "epic_id": epic_id, "stage": "CLARIFY", "decisions": []},
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-z",
                    "created_at": "",
                    "questions": [],
                    "auto_release_if_all_answered": True,
                },
            )

            fail = run_harnessctl(
                tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id
            )
            self.assertNotEqual(fail.returncode, 0)
            self.assertIn("SCN-007", fail.stdout)
            self.assertIn("focus closure (full)", fail.stdout.lower())

            cn = features_dir / "clarification-notes.md"
            cn.write_text(
                cn.read_text(encoding="utf-8")
                + "\n## Focus Points\n- SCN-007 → REQ-010\n",
                encoding="utf-8",
            )
            ok = run_harnessctl(
                tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id
            )
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

    def test_full_mode_constraint_signal_scn011_requires_explicit_focus(self) -> None:
        """High-confidence SCN hitting constraints-identity must appear in Focus (full mode)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Constraint-signal SCN focus gate")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["x"],
                    "domain_constraints": [],
                    "invariants": [],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                    "state_transition_scenarios": [],
                    "constraint_conflicts": [],
                    "anti_patterns": [],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-011",
                            "pattern": "ambiguous_locator",
                            "source_signals": ["constraint_conflicts[0]"],
                            "confidence": "high",
                            "scenario": "Ambiguous locator yields multi-match rows",
                            "why_it_matters": "Must resolve constraint conflict",
                            "expected_followup": "REQ",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-011",
                            "status": "covered",
                            "mapped_to": ["REQ-010"],
                            "notes": "",
                        }
                    ],
                },
            )
            (features_dir / "requirements-draft.md").write_text(
                "### REQ-010\n\nDefined.\n",
                encoding="utf-8",
            )
            (features_dir / "challenge-report.md").write_text("## Summary\n\nok\n", encoding="utf-8")
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Ctx.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "## Blast Radius Summary\n\nx\n\n## High Impact Surfaces\n\n- a/\n\n## Medium Impact Surfaces\n\n- b/\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {"epic": epic_id, "created_at": "", "surfaces": [{"type": "code_repository", "path": "a/"}]},
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {
                        "total": 0,
                        "open": 0,
                        "resolved_in_spec": 0,
                        "resolved_in_plan": 0,
                        "resolved_in_verify": 0,
                        "deferred": 0,
                    },
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {"version": "1.0", "epic_id": epic_id, "stage": "CLARIFY", "decisions": []},
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-z",
                    "created_at": "",
                    "questions": [],
                    "auto_release_if_all_answered": True,
                },
            )

            fail = run_harnessctl(
                tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id
            )
            self.assertNotEqual(fail.returncode, 0)
            self.assertIn("SCN-011", fail.stdout)

            cn = features_dir / "clarification-notes.md"
            cn.write_text(
                cn.read_text(encoding="utf-8")
                + "\n## Focus Points\n- SCN-011 → REQ-010\n",
                encoding="utf-8",
            )
            ok = run_harnessctl(
                tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id
            )
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

    def test_full_mode_selfcheck_scn_focus_gate_does_not_set_notes_only_ok_false(self) -> None:
        """When only the State/Constraint SCN→Focus gate fails, notes_only_ok stays true (core notes+focus clean)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "SCN gate vs notes_only_ok")
            features_dir = tmp_path / ".harness" / "features" / epic_id

            write_json(
                features_dir / "domain-frame.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "business_goals": ["x"],
                    "domain_constraints": [],
                    "invariants": [],
                    "semantic_signals": [],
                    "candidate_edge_cases": [],
                    "candidate_open_questions": [],
                    "state_transition_scenarios": [],
                    "constraint_conflicts": [],
                    "anti_patterns": [],
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-011",
                            "confidence": "high",
                            "scenario": "Retry replay after partial failure",
                            "why_it_matters": "Order matters",
                            "expected_followup": "REQ",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-011",
                            "status": "covered",
                            "mapped_to": ["REQ-010"],
                            "notes": "",
                        }
                    ],
                },
            )
            (features_dir / "requirements-draft.md").write_text(
                "### REQ-010\n\nDefined.\n",
                encoding="utf-8",
            )
            (features_dir / "challenge-report.md").write_text("## Summary\n\nok\n", encoding="utf-8")
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Ctx.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (features_dir / "impact-scan.md").write_text(
                "## Blast Radius Summary\n\nx\n\n## High Impact Surfaces\n\n- a/\n\n## Medium Impact Surfaces\n\n- b/\n",
                encoding="utf-8",
            )
            write_json(
                features_dir / "surface-routing.json",
                {"epic": epic_id, "created_at": "", "surfaces": [{"type": "code_repository", "path": "a/"}]},
            )
            write_json(
                features_dir / "unknowns-ledger.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "entries": [],
                    "summary": {
                        "total": 0,
                        "open": 0,
                        "resolved_in_spec": 0,
                        "resolved_in_plan": 0,
                        "resolved_in_verify": 0,
                        "deferred": 0,
                    },
                },
            )
            write_json(
                features_dir / "decision-bundle.json",
                {"version": "1.0", "epic_id": epic_id, "stage": "CLARIFY", "decisions": []},
            )
            write_json(
                features_dir / "decision-packet.json",
                {
                    "version": "1.0",
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "packet_id": "DP-z",
                    "created_at": "",
                    "questions": [],
                    "auto_release_if_all_answered": True,
                },
            )

            sc = run_harnessctl(
                tmp_path, "clarify-selfcheck", "--epic-id", epic_id, "--json"
            )
            self.assertEqual(sc.returncode, 0, sc.stderr)
            payload = json.loads(sc.stdout)
            self.assertTrue(payload["notes_only_ok"])
            self.assertFalse(payload["clarification_notes_ok"])
            self.assertEqual(len(payload["state_constraint_signal_scn_focus_errors"]), 1)

    def test_notes_only_skips_state_flow_scn_focus_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "notes_only no SCN in focus")
            harness_dir = tmp_path / ".harness"
            features_dir = harness_dir / "features" / epic_id
            write_json(
                harness_dir / "config.json",
                {
                    "clarify_closure_mode": "notes_only",
                    "clarify_signal_gate_enabled": True,
                    "clarify_deep_dive_enabled": True,
                    "clarify_deep_dive_gate_strict": False,
                },
            )
            write_json(
                features_dir / "generated-scenarios.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {
                            "scenario_id": "SCN-099",
                            "confidence": "high",
                            "scenario": "delete then insert same key workflow",
                            "why_it_matters": "state",
                        }
                    ],
                },
            )
            write_json(
                features_dir / "scenario-coverage.json",
                {
                    "epic_id": epic_id,
                    "version": "1.0",
                    "scenarios": [
                        {"scenario_id": "SCN-099", "status": "covered", "mapped_to": ["REQ-1"]}
                    ],
                },
            )
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "x",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            gate = run_harnessctl(
                tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id
            )
            self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
            self.assertNotIn("SCN-099", gate.stdout)

            sc = run_harnessctl(
                tmp_path, "clarify-selfcheck", "--epic-id", epic_id, "--json"
            )
            self.assertEqual(sc.returncode, 0, sc.stderr)
            payload = json.loads(sc.stdout)
            self.assertEqual(payload["state_constraint_signal_scn_focus_errors"], [])
            self.assertTrue(payload["notes_only_ok"])

    def test_notes_only_focus_closure_matches_stage_gate_verify_and_selfcheck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path, "Need notes-only focus closure")
            harness_dir = tmp_path / ".harness"
            features_dir = harness_dir / "features" / epic_id

            write_json(
                harness_dir / "config.json",
                {
                    "clarify_closure_mode": "notes_only",
                    "clarify_signal_gate_enabled": True,
                    "clarify_deep_dive_enabled": True,
                    "clarify_deep_dive_gate_strict": True,
                },
            )
            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Context.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Focus Points",
                        "- delete then insert same key",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            gate_fail = run_harnessctl(
                tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id
            )
            self.assertNotEqual(gate_fail.returncode, 0)
            self.assertIn("Focus Points bullet", gate_fail.stdout)

            verify_fail = run_verify_artifacts(tmp_path, epic_id, "CLARIFY")
            self.assertNotEqual(verify_fail.returncode, 0)
            self.assertIn("Focus Points bullet", verify_fail.stdout)

            selfcheck_fail = run_harnessctl(
                tmp_path, "clarify-selfcheck", "--epic-id", epic_id, "--json"
            )
            self.assertEqual(selfcheck_fail.returncode, 0, selfcheck_fail.stderr)
            payload_fail = json.loads(selfcheck_fail.stdout)
            self.assertFalse(payload_fail["clarification_notes_ok"])
            self.assertFalse(payload_fail["notes_only_ok"])
            self.assertEqual(len(payload_fail["focus_point_errors"]), 1)

            (features_dir / "clarification-notes.md").write_text(
                "\n".join(
                    [
                        "## Domain Frame",
                        "",
                        "Context.",
                        "",
                        "## 六轴澄清覆盖",
                        "- StateAndTime / 行为与流程: covered",
                        "- ConstraintsAndConflict / 规则与边界: covered",
                        "- CostAndCapacity / 规模与代价: covered",
                        "- CrossSurfaceConsistency / 多入口: covered",
                        "- OperationsAndRecovery / 运行与维护: covered",
                        "- SecurityAndIsolation / 权限与隔离: covered",
                        "",
                        "## Focus Points",
                        "- delete then insert same key -> REQ-001, SCN-001",
                        "",
                        "## Unknowns 与待确认决策",
                        "- 本轮无待确认",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            gate_pass = run_harnessctl(
                tmp_path, "stage-gate", "check", "CLARIFY", "--epic-id", epic_id
            )
            self.assertEqual(gate_pass.returncode, 0, gate_pass.stdout + gate_pass.stderr)

            verify_pass = run_verify_artifacts(tmp_path, epic_id, "CLARIFY")
            self.assertEqual(verify_pass.returncode, 0, verify_pass.stdout + verify_pass.stderr)

            selfcheck_pass = run_harnessctl(
                tmp_path, "clarify-selfcheck", "--epic-id", epic_id, "--json"
            )
            self.assertEqual(selfcheck_pass.returncode, 0, selfcheck_pass.stderr)
            payload_pass = json.loads(selfcheck_pass.stdout)
            self.assertTrue(payload_pass["clarification_notes_ok"])
            self.assertTrue(payload_pass["notes_only_ok"])
            self.assertEqual(payload_pass["focus_point_errors"], [])

            guard_pass = run_harnessctl(
                tmp_path, "guard", "check", "--epic-id", epic_id, "--stage", "SPEC"
            )
            self.assertEqual(guard_pass.returncode, 0, guard_pass.stdout + guard_pass.stderr)


if __name__ == "__main__":
    unittest.main()
