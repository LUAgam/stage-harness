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


if __name__ == "__main__":
    unittest.main()
