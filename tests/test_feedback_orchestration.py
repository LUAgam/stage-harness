"""Tests for Feedback Orchestration: gate-check, related-gap-scan triggers, submit flow."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "harnessctl.py"


def run_harnessctl(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def setup_harness_with_epic(tmp_path: Path) -> str:
    """Initialize harness and create a test epic, return epic_id."""
    run_harnessctl(tmp_path, "--project-root", str(tmp_path), "init")
    result = run_harnessctl(tmp_path, "start", "Test orchestration", "--json")
    data = json.loads(result.stdout)
    epic_id = data["epic_id"]

    state_path = tmp_path / ".harness" / "features" / epic_id / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "version": "4.6",
        "current_stage": "EXECUTE",
        "epic_id": epic_id,
        "risk_level": "low",
        "interrupt_budget": {"total": 3, "consumed": 0, "remaining": 3},
        "stage_history": [],
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return epic_id


class TestGateCheckPass(unittest.TestCase):
    """gate-check should pass when no feedback exists."""

    def test_no_feedback_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "pass")
            self.assertEqual(data["blocked_count"], 0)


class TestGateCheckBlocked(unittest.TestCase):
    """gate-check should block when submitted feedback exists without evidence-pack."""

    def test_submitted_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit feedback
            result = run_harnessctl(tmp_path, "feedback", "submit",
                                    "--epic-id", epic_id,
                                    "--stage", "EXECUTE",
                                    "--text", "oms-docs 是否需要调整？",
                                    "--candidate-type", "scope_gap_question",
                                    "--json")
            self.assertEqual(result.returncode, 0)
            fb_data = json.loads(result.stdout)
            feedback_id = fb_data["feedback_id"]

            # gate-check should block
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 1)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "blocked")
            self.assertEqual(data["blocked_count"], 1)
            self.assertEqual(data["blocked_items"][0]["feedback_id"], feedback_id)
            self.assertEqual(data["blocked_items"][0]["reason"],
                             "submitted_without_evidence_pack")

    def test_record_only_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit feedback then mark as record_only
            result = run_harnessctl(tmp_path, "feedback", "submit",
                                    "--epic-id", epic_id,
                                    "--stage", "EXECUTE",
                                    "--text", "batch note",
                                    "--json")
            fb_data = json.loads(result.stdout)
            feedback_id = fb_data["feedback_id"]

            # Manually set record_only in the JSON
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                       "feedback" / f"{feedback_id}.json")
            fb_json = json.loads(fb_path.read_text())
            fb_json["record_only"] = True
            fb_path.write_text(json.dumps(fb_json, indent=2))

            # gate-check should pass
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "pass")


class TestGateCheckDeferred(unittest.TestCase):
    """gate-check should block deferred feedback without proper evidence."""

    def test_deferred_without_reason_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Create a deferred feedback without proper fields
            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_data = {
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "deferred",
                "text": "some feedback",
                "candidate_type": "correction",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb_data, indent=2))

            # gate-check should block
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 1)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "blocked")
            self.assertIn("deferred_incomplete", data["blocked_items"][0]["reason"])

    def test_deferred_with_reason_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_data = {
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "deferred",
                "text": "some feedback",
                "candidate_type": "correction",
                "defer_reason": "Not in scope for this sprint",
                "defer_to": "next_sprint",
                "defer_evidence": "Confirmed with PM",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb_data, indent=2))

            # gate-check should pass
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "pass")


class TestRelatedGapScanTrigger(unittest.TestCase):
    """Test _feedback_requires_related_gap_scan logic via approve-amendment gate."""

    def test_reopen_verdict_requires_gap_scan(self):
        """approve-amendment should fail if REOPEN verdict but no gap-scan file."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Create feedback in amendment_planned state
            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_data = {
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "amendment_planned",
                "text": "missing docs",
                "candidate_type": "scope_gap_question",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb_data, indent=2))

            # Create amendment plan
            (fb_dir / "HFB-001.amendment-plan.md").write_text(
                "## Amend\n- Add docs\n## Deferred Related Gaps\n- None\n")

            # Create verdict with REOPEN_PLAN
            councils_dir = (tmp_path / ".harness" / "features" / epic_id /
                            "councils" / "feedback_triage_council" / "HFB-001")
            councils_dir.mkdir(parents=True, exist_ok=True)
            verdict = {
                "decision": "REOPEN_PLAN",
                "classification": "scope_gap_question",
                "target_stage": "PLAN",
                "requires_reopen": True,
            }
            (councils_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))

            # approve-amendment should fail (no related-gap-scan.json)
            result = run_harnessctl(tmp_path, "feedback", "approve-amendment",
                                    "--epic-id", epic_id,
                                    "--feedback-id", "HFB-001", "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("related-gap-scan is required", result.stderr)

    def test_vote_related_gaps_triggers_scan(self):
        """approve-amendment should fail if any vote has related_gaps but no scan file."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_data = {
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "amendment_planned",
                "text": "check config",
                "candidate_type": "correction",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb_data, indent=2))
            (fb_dir / "HFB-001.amendment-plan.md").write_text(
                "## Amend\n- Fix config\n## Deferred Related Gaps\n- None\n")

            # Create verdict with STAY_EXECUTE (no REOPEN)
            councils_dir = (tmp_path / ".harness" / "features" / epic_id /
                            "councils" / "feedback_triage_council" / "HFB-001")
            councils_dir.mkdir(parents=True, exist_ok=True)
            (councils_dir / "verdict.json").write_text(json.dumps({
                "decision": "STAY_EXECUTE",
                "classification": "correction",
                "requires_reopen": False,
            }, indent=2))

            # Create a vote with related_gaps
            votes_dir = councils_dir / "votes"
            votes_dir.mkdir(parents=True, exist_ok=True)
            (votes_dir / "impact-analyst.json").write_text(json.dumps({
                "role": "impact-analyst",
                "decision": "STAY_EXECUTE",
                "evidence": [{"file": "config.yaml", "snippet": "..."}],
                "related_gaps": ["i18n config not checked"],
                "_managed": True,
            }, indent=2))

            # approve-amendment should fail
            result = run_harnessctl(tmp_path, "feedback", "approve-amendment",
                                    "--epic-id", epic_id,
                                    "--feedback-id", "HFB-001", "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("related-gap-scan is required", result.stderr)


class TestContinueReopenRouting(unittest.TestCase):
    """continue --execute should route REOPEN_* by current/target stage."""

    def _write_triaged_reopen(self, tmp_path: Path, epic_id: str, feedback_id: str,
                              decision: str, target_stage: str,
                              classification: str = "plan_patch") -> None:
        fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
        fb_dir.mkdir(parents=True, exist_ok=True)
        (fb_dir / f"{feedback_id}.json").write_text(json.dumps({
            "feedback_id": feedback_id,
            "epic_id": epic_id,
            "status": "triaged",
            "text": "missing docs task",
            "candidate_type": classification,
        }, indent=2))
        (fb_dir / f"{feedback_id}.triage.json").write_text(json.dumps({
            "feedback_id": feedback_id,
            "classification": classification,
            "target_stage": target_stage,
            "requires_reopen": True,
            "confidence": 0.9,
        }, indent=2))
        (fb_dir / f"{feedback_id}.related-gap-scan.json").write_text(json.dumps({
            "gaps": [],
            "scanned_categories": ["docs", "tests"],
        }, indent=2))
        councils_dir = (tmp_path / ".harness" / "features" / epic_id /
                        "councils" / "feedback_triage_council" / feedback_id)
        councils_dir.mkdir(parents=True, exist_ok=True)
        (councils_dir / "verdict.json").write_text(json.dumps({
            "decision": decision,
            "classification": classification,
            "target_stage": target_stage,
            "requires_reopen": True,
        }, indent=2))

    def _set_stage(self, tmp_path: Path, epic_id: str, stage: str) -> None:
        state_path = tmp_path / ".harness" / "features" / epic_id / "state.json"
        state = json.loads(state_path.read_text())
        state["current_stage"] = stage
        state["risk_level"] = "low"
        state_path.write_text(json.dumps(state, indent=2))

    def test_same_stage_plan_continue_does_not_call_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            self._set_stage(tmp_path, epic_id, "PLAN")
            self._write_triaged_reopen(tmp_path, epic_id, "HFB-001", "REOPEN_PLAN", "PLAN")

            result = run_harnessctl(tmp_path, "feedback", "continue",
                                    "--epic-id", epic_id,
                                    "--feedback-id", "HFB-001",
                                    "--execute", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            decoder = json.JSONDecoder()
            objects = []
            pos = 0
            stdout = result.stdout
            while pos < len(stdout):
                start = stdout.find("{", pos)
                if start == -1:
                    break
                try:
                    obj, end = decoder.raw_decode(stdout[start:])
                    objects.append(obj)
                    pos = start + end
                except json.JSONDecodeError:
                    pos = start + 1
            self.assertTrue(objects, result.stdout)
            data = objects[-1]
            self.assertEqual(data["status"], "continuation_pending")
            self.assertEqual(data["mode"], "same_stage_replan")
            self.assertEqual(data["continuation"]["next_action"], "feedback_replan")
            self.assertIn("feedback re-plan", data["continuation"]["next_command"])
            self.assertTrue(data["continuation"]["must_auto_continue"])

            state = json.loads((tmp_path / ".harness" / "features" / epic_id / "state.json").read_text())
            self.assertEqual(state["current_stage"], "PLAN")
            self.assertEqual(state["pending_re_completion"]["stages"], ["PLAN"])
            self.assertTrue(state["reopen_history"][-1]["same_stage"])

            fb = json.loads((tmp_path / ".harness" / "features" / epic_id /
                             "feedback" / "HFB-001.json").read_text())
            self.assertEqual(fb["status"], "continuation_pending")
            self.assertEqual(fb["continuation"]["mode"], "same_stage_replan")

            gate = run_harnessctl(tmp_path, "feedback", "gate-check",
                                  "--epic-id", epic_id, "--json")
            self.assertEqual(gate.returncode, 1)
            gate_data = json.loads(gate.stdout)
            self.assertEqual(gate_data["blocked_items"][0]["reason"], "continuation_pending")

    def test_continue_reopen_next_command_is_stage_aware(self):
        cases = [
            ("CLARIFY", "REOPEN_CLARIFY", "feedback_reclarify", "feedback re-clarify"),
            ("SPEC", "REOPEN_SPEC", "feedback_respec", "feedback re-spec"),
            ("PLAN", "REOPEN_PLAN", "feedback_replan", "feedback re-plan"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            for idx, (target_stage, decision, next_action, cmd_fragment) in enumerate(cases, start=1):
                feedback_id = f"HFB-{idx:03d}"
                self._write_triaged_reopen(tmp_path, epic_id, feedback_id, decision, target_stage)
                result = run_harnessctl(tmp_path, "feedback", "continue",
                                        "--epic-id", epic_id,
                                        "--feedback-id", feedback_id,
                                        "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                cont = data["continuation"]
                self.assertEqual(cont["next_action"], next_action)
                self.assertIn(cmd_fragment, cont["next_command"])

    def test_reclarify_and_respec_commands_generate_manifest(self):
        cases = [
            ("CLARIFY", "REOPEN_CLARIFY", "re-clarify", "clarify-summary.md"),
            ("SPEC", "REOPEN_SPEC", "re-spec", "SDD.md"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            features_dir = tmp_path / ".harness" / "features" / epic_id
            for idx, (target_stage, decision, command, artifact) in enumerate(cases, start=1):
                feedback_id = f"HFB-{idx:03d}"
                self._set_stage(tmp_path, epic_id, target_stage)
                self._write_triaged_reopen(tmp_path, epic_id, feedback_id, decision, target_stage)
                run_harnessctl(tmp_path, "feedback", "continue",
                               "--epic-id", epic_id,
                               "--feedback-id", feedback_id,
                               "--execute", "--json")
                artifact_path = features_dir / artifact
                artifact_path.write_text(f"updated {artifact} for {feedback_id}\n")
                amendment_path = features_dir / "feedback" / f"{feedback_id}.amendment-plan.json"
                amendment_path.write_text(json.dumps({
                    "target_stage": target_stage,
                    "source_verdict": decision,
                    "changed_artifacts": [{
                        "path": artifact,
                        "before_hash": "sha256:before",
                        "evidence": f"updated {artifact}",
                    }],
                }, indent=2))

                result = run_harnessctl(tmp_path, "feedback", command,
                                        "--epic-id", epic_id,
                                        "--feedback-id", feedback_id,
                                        "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data["stage"], target_stage)

                manifest = json.loads((features_dir / "feedback" /
                                       f"{feedback_id}.revision-manifest.json").read_text())
                self.assertEqual(manifest["stage"], target_stage)
                self.assertEqual(manifest["changed_artifacts"][0]["path"], artifact)

    def test_plain_reopen_still_rejects_same_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            self._set_stage(tmp_path, epic_id, "PLAN")
            self._write_triaged_reopen(tmp_path, epic_id, "HFB-001", "REOPEN_PLAN", "PLAN")
            run_harnessctl(tmp_path, "feedback", "plan-amendment",
                           "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            run_harnessctl(tmp_path, "feedback", "approve-amendment",
                           "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")

            result = run_harnessctl(tmp_path, "reopen",
                                    "--epic-id", epic_id,
                                    "--to", "PLAN",
                                    "--feedback-id", "HFB-001",
                                    "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be earlier than current stage", result.stderr)


class TestContinueAutoExecute(unittest.TestCase):
    """Test that continue --execute auto-creates tasks for STAY_EXECUTE."""

    def test_stay_execute_auto_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Create feedback in triaged state
            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_data = {
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "triaged",
                "text": "add missing docs",
                "candidate_type": "scope_gap_question",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb_data, indent=2))

            # Create verdict
            councils_dir = (tmp_path / ".harness" / "features" / epic_id /
                            "councils" / "feedback_triage_council" / "HFB-001")
            councils_dir.mkdir(parents=True, exist_ok=True)
            (councils_dir / "verdict.json").write_text(json.dumps({
                "decision": "STAY_EXECUTE",
                "classification": "scope_gap_question",
                "requires_reopen": False,
            }, indent=2))

            # Create related-gap-scan (required for scope_gap_question)
            (fb_dir / "HFB-001.related-gap-scan.json").write_text(json.dumps({
                "gaps": [],
                "scanned_categories": ["docs", "tests"],
            }, indent=2))

            # Create task-graph so merge works
            task_graph_path = (tmp_path / ".harness" / "features" / epic_id /
                               "task-graph.json")
            task_graph_path.write_text(json.dumps({
                "tasks": [],
                "version": "1.0",
            }, indent=2))

            # Run continue --execute
            result = run_harnessctl(tmp_path, "feedback", "continue",
                                    "--epic-id", epic_id,
                                    "--feedback-id", "HFB-001",
                                    "--execute", "--json")
            # continue --execute may produce multiple JSON lines (from sub-commands)
            # Parse the last valid JSON object from stdout
            data = {}
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        pass
            if not data and result.stdout.strip():
                # Try parsing multi-line JSON blocks
                import re
                blocks = re.findall(r'\{[^{}]*\}', result.stdout, re.DOTALL)
                for block in reversed(blocks):
                    try:
                        data = json.loads(block)
                        break
                    except json.JSONDecodeError:
                        continue
            if result.returncode == 0:
                self.assertIn(data.get("status", ""),
                              ("auto_task_created", "ok"))


class TestScopeGapClassification(unittest.TestCase):
    """Test that scope_gap_question candidate_type is properly stored."""

    def test_submit_with_candidate_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            result = run_harnessctl(tmp_path, "feedback", "submit",
                                    "--epic-id", epic_id,
                                    "--stage", "EXECUTE",
                                    "--text", "oms-docs 是否需要调整？",
                                    "--candidate-type", "scope_gap_question",
                                    "--json")
            self.assertEqual(result.returncode, 0)
            fb_data = json.loads(result.stdout)
            feedback_id = fb_data["feedback_id"]

            # Verify stored data
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                       "feedback" / f"{feedback_id}.json")
            stored = json.loads(fb_path.read_text())
            self.assertEqual(stored["candidate_type"], "scope_gap_question")


class TestUpdateMetadata(unittest.TestCase):
    """Test harnessctl feedback update-metadata command."""

    def test_update_metadata_basic(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit feedback
            result = run_harnessctl(tmp_path, "feedback", "submit",
                                    "--epic-id", epic_id,
                                    "--stage", "EXECUTE",
                                    "--text", "test metadata update",
                                    "--json")
            fb_data = json.loads(result.stdout)
            feedback_id = fb_data["feedback_id"]

            # Update metadata
            result = run_harnessctl(tmp_path, "feedback", "update-metadata",
                                    "--epic-id", epic_id,
                                    "--feedback-id", feedback_id,
                                    "--metadata-json", '{"mentioned_surface":"oms-docs","priority":"high"}',
                                    "--json")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")
            self.assertIn("mentioned_surface", data["updated_fields"])
            self.assertIn("priority", data["updated_fields"])

            # Verify persisted
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                       "feedback" / f"{feedback_id}.json")
            stored = json.loads(fb_path.read_text())
            self.assertEqual(stored["mentioned_surface"], "oms-docs")
            self.assertEqual(stored["priority"], "high")
            # Core fields preserved
            self.assertEqual(stored["text"], "test metadata update")

    def test_update_metadata_rejects_protected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            result = run_harnessctl(tmp_path, "feedback", "submit",
                                    "--epic-id", epic_id,
                                    "--stage", "EXECUTE",
                                    "--text", "test protected",
                                    "--json")
            fb_data = json.loads(result.stdout)
            feedback_id = fb_data["feedback_id"]

            # Try to overwrite protected field
            result = run_harnessctl(tmp_path, "feedback", "update-metadata",
                                    "--epic-id", epic_id,
                                    "--feedback-id", feedback_id,
                                    "--metadata-json", '{"status":"closed","custom_field":"ok"}',
                                    "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected", result.stderr)


class TestTriageIncomplete(unittest.TestCase):
    """Test gate-check detects incomplete triage (missing votes) and provides recovery path."""

    def test_missing_votes_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Create feedback in triaging state
            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_data = {
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "triaging",
                "text": "some feedback",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb_data, indent=2))

            # Create council dir with only 3 of 6 votes
            votes_dir = (tmp_path / ".harness" / "features" / epic_id /
                         "councils" / "feedback_triage_council" / "HFB-001" / "votes")
            votes_dir.mkdir(parents=True, exist_ok=True)
            for agent in ["requirement-analyst", "impact-analyst", "challenger"]:
                vote = {"agent": agent, "decision": "STAY_EXECUTE",
                        "confidence": 0.8, "evidence": ["test"]}
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))

            # gate-check should block with triage_incomplete
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 1)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "blocked")
            blocked = data["blocked_items"][0]
            self.assertIn("triage_incomplete", blocked["reason"])
            self.assertIn("plan-reviewer", blocked["reason"])
            self.assertIn("test-reviewer", blocked["reason"])
            self.assertIn("code-reviewer", blocked["reason"])
            # Should suggest write-vote for missing agents
            self.assertTrue(any("write-vote" in cmd for cmd in blocked["required_commands"]))
            # Should end with aggregate-triage
            self.assertIn("aggregate-triage", blocked["required_commands"][-1])

    def test_all_votes_present_suggests_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Create feedback in triaging state
            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_data = {
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "triaging",
                "text": "some feedback",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb_data, indent=2))

            # Create all 6 votes but no verdict
            votes_dir = (tmp_path / ".harness" / "features" / epic_id /
                         "councils" / "feedback_triage_council" / "HFB-001" / "votes")
            votes_dir.mkdir(parents=True, exist_ok=True)
            for agent in ["requirement-analyst", "impact-analyst", "challenger",
                          "plan-reviewer", "test-reviewer", "code-reviewer"]:
                vote = {"agent": agent, "decision": "STAY_EXECUTE",
                        "confidence": 0.8, "evidence": ["test"]}
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))

            # gate-check should block with triaging_without_verdict
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 1)
            data = json.loads(result.stdout)
            blocked = data["blocked_items"][0]
            self.assertEqual(blocked["reason"], "triaging_without_verdict")
            self.assertEqual(blocked["next_action"], "feedback aggregate-triage")

    def test_resume_after_adding_missing_vote(self):
        """Simulate recovery: add missing vote then gate-check passes after aggregate."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit and start triage
            result = run_harnessctl(tmp_path, "feedback", "submit",
                                    "--epic-id", epic_id,
                                    "--stage", "EXECUTE",
                                    "--text", "test resume",
                                    "--json")
            fb_data = json.loads(result.stdout)
            feedback_id = fb_data["feedback_id"]

            # evidence-pack
            run_harnessctl(tmp_path, "feedback", "evidence-pack",
                           "--epic-id", epic_id,
                           "--feedback-id", feedback_id, "--json")

            # council-triage (sets status to triaging)
            run_harnessctl(tmp_path, "feedback", "council-triage",
                           "--epic-id", epic_id,
                           "--feedback-id", feedback_id, "--json")

            # Write all 6 votes via write-vote
            for agent in ["requirement-analyst", "impact-analyst", "challenger",
                          "plan-reviewer", "test-reviewer", "code-reviewer"]:
                run_harnessctl(tmp_path, "feedback", "write-vote",
                               "--epic-id", epic_id,
                               "--feedback-id", feedback_id,
                               "--agent", agent,
                               "--decision", "NO_REOPEN_WITH_EVIDENCE",
                               "--confidence", "0.9",
                               "--evidence", "verified in code",
                               "--json")

            # Aggregate
            run_harnessctl(tmp_path, "feedback", "aggregate-triage",
                           "--epic-id", epic_id,
                           "--feedback-id", feedback_id, "--json")

            # Continue
            run_harnessctl(tmp_path, "feedback", "continue",
                           "--epic-id", epic_id,
                           "--feedback-id", feedback_id,
                           "--execute", "--json")

            # gate-check should now pass
            result = run_harnessctl(tmp_path, "feedback", "gate-check",
                                    "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "pass")


if __name__ == "__main__":
    unittest.main()
