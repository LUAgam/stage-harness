"""Tests for Feedback-driven Reopen & Amendment Loop commands."""
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
    result = run_harnessctl(
        tmp_path, "start", "Test feedback feature", "--json"
    )
    data = json.loads(result.stdout)
    epic_id = data["epic_id"]

    # Advance to EXECUTE so we can test reopen
    state_path = tmp_path / ".harness" / "features" / epic_id / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "version": "4.6",
        "current_stage": "EXECUTE",
        "epic_id": epic_id,
        "risk_level": "medium",
        "interrupt_budget": {"total": 3, "consumed": 0, "remaining": 3},
        "stage_history": [],
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return epic_id


class TestFeedbackSubmit(unittest.TestCase):
    def test_submit_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            result = run_harnessctl(
                tmp_path, "feedback", "submit",
                "--epic-id", epic_id,
                "--stage", "EXECUTE",
                "--text", "前端不需要调整吗？",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["feedback_id"], "HFB-001")

            # Verify file exists
            fb_path = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.json"
            self.assertTrue(fb_path.exists())
            fb = json.loads(fb_path.read_text())
            self.assertEqual(fb["status"], "submitted")
            self.assertEqual(fb["text"], "前端不需要调整吗？")

    def test_submit_increments_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "first", "--json")
            result = run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "second", "--json")
            data = json.loads(result.stdout)
            self.assertEqual(data["feedback_id"], "HFB-002")


class TestFeedbackTriage(unittest.TestCase):
    def test_triage_writes_file_and_updates_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "test", "--json")
            result = run_harnessctl(
                tmp_path, "feedback", "triage",
                "--epic-id", epic_id,
                "--feedback-id", "HFB-001",
                "--classification", "requirement_gap",
                "--target-stage", "CLARIFY",
                "--requires-reopen",
                "--confidence", "0.9",
                "--reason", "missing frontend",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            # Check triage file
            triage_path = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.triage.json"
            self.assertTrue(triage_path.exists())
            triage = json.loads(triage_path.read_text())
            self.assertEqual(triage["classification"], "requirement_gap")
            self.assertTrue(triage["requires_reopen"])

            # Check main file status updated
            fb_path = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.json"
            fb = json.loads(fb_path.read_text())
            self.assertEqual(fb["status"], "triaged")

    def test_triage_rejects_invalid_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "x", "--json")
            result = run_harnessctl(
                tmp_path, "feedback", "triage",
                "--epic-id", epic_id,
                "--feedback-id", "HFB-001",
                "--classification", "invalid_type",
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)


class TestReopen(unittest.TestCase):
    def _setup_approved_feedback(self, tmp_path: Path, epic_id: str):
        """Submit, triage, plan-amendment, approve."""
        run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "gap", "--json")
        run_harnessctl(tmp_path, "feedback", "triage", "--epic-id", epic_id,
                       "--feedback-id", "HFB-001", "--classification", "requirement_gap",
                       "--target-stage", "CLARIFY", "--requires-reopen", "--json")
        run_harnessctl(tmp_path, "feedback", "plan-amendment", "--epic-id", epic_id,
                       "--feedback-id", "HFB-001", "--json")
        run_harnessctl(tmp_path, "feedback", "approve-amendment", "--epic-id", epic_id,
                       "--feedback-id", "HFB-001", "--json")

    def test_reopen_changes_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            self._setup_approved_feedback(tmp_path, epic_id)

            result = run_harnessctl(
                tmp_path, "reopen",
                "--epic-id", epic_id,
                "--to", "CLARIFY",
                "--feedback-id", "HFB-001",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["reopened_to"], "CLARIFY")

            # Verify state
            state_path = tmp_path / ".harness" / "features" / epic_id / "state.json"
            state = json.loads(state_path.read_text())
            self.assertEqual(state["current_stage"], "CLARIFY")
            self.assertEqual(len(state["reopen_history"]), 1)

    def test_reopen_rejects_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "x", "--json")
            run_harnessctl(tmp_path, "feedback", "triage", "--epic-id", epic_id,
                           "--feedback-id", "HFB-001", "--classification", "requirement_gap",
                           "--target-stage", "CLARIFY", "--requires-reopen", "--json")
            # Skip plan-amendment and approve
            result = run_harnessctl(
                tmp_path, "reopen", "--epic-id", epic_id,
                "--to", "CLARIFY", "--feedback-id", "HFB-001", "--json",
            )
            self.assertNotEqual(result.returncode, 0)

    def test_reopen_rejects_mismatched_target(self):
        """Reopen must match triage target_stage."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            self._setup_approved_feedback(tmp_path, epic_id)

            # Triage says CLARIFY, but we try SPEC
            result = run_harnessctl(
                tmp_path, "reopen", "--epic-id", epic_id,
                "--to", "SPEC", "--feedback-id", "HFB-001", "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match triage recommendation", result.stderr)

    def test_reopen_invalidates_downstream_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            self._setup_approved_feedback(tmp_path, epic_id)

            run_harnessctl(tmp_path, "reopen", "--epic-id", epic_id,
                           "--to", "CLARIFY", "--feedback-id", "HFB-001", "--json")

            # Check artifact-status
            result = run_harnessctl(tmp_path, "artifact-status", "show", "--epic-id", epic_id, "--json")
            data = json.loads(result.stdout)
            stale = [a for a in data["artifacts"] if a["status"] == "stale"]
            self.assertGreater(len(stale), 0)


class TestGuardCheck(unittest.TestCase):
    def test_guard_blocks_with_stale_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Manually write artifact-status with stage field set
            art_status_path = tmp_path / ".harness" / "features" / epic_id / "artifact-status.json"
            art_status_path.parent.mkdir(parents=True, exist_ok=True)
            art_data = {
                "artifacts": [{
                    "path": f"features/{epic_id}/specs/",
                    "stage": "SPEC",
                    "status": "stale",
                    "invalidated_by": "HFB-001",
                    "invalidated_at": "2026-01-01T00:00:00Z",
                    "reason": "test",
                    "last_valid_at": "",
                }],
                "updated_at": "2026-01-01T00:00:00Z",
            }
            art_status_path.write_text(json.dumps(art_data), encoding="utf-8")

            result = run_harnessctl(tmp_path, "guard", "check",
                                    "--epic-id", epic_id, "--stage", "EXECUTE", "--json")
            data = json.loads(result.stdout)
            self.assertFalse(data["passed"])
            self.assertTrue(any("stale" in i for i in data["issues"]))

    def test_guard_passes_with_revision_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Create stale artifact with stage
            art_status_path = tmp_path / ".harness" / "features" / epic_id / "artifact-status.json"
            art_status_path.parent.mkdir(parents=True, exist_ok=True)
            art_data = {
                "artifacts": [{
                    "path": f"features/{epic_id}/specs/",
                    "stage": "SPEC",
                    "status": "stale",
                    "invalidated_by": "HFB-001",
                    "invalidated_at": "2026-01-01T00:00:00Z",
                    "reason": "test",
                    "last_valid_at": "",
                }],
                "updated_at": "2026-01-01T00:00:00Z",
            }
            art_status_path.write_text(json.dumps(art_data), encoding="utf-8")

            # Write revision-diff
            rdiff = tmp_path / ".harness" / "features" / epic_id / "revision-diff-HFB-001.md"
            rdiff.write_text("# Revision Diff\nNo impact.", encoding="utf-8")

            result = run_harnessctl(tmp_path, "guard", "check",
                                    "--epic-id", epic_id, "--stage", "EXECUTE", "--json")
            data = json.loads(result.stdout)
            # Revision-diff should resolve the stale artifact issue specifically
            # (other guard issues like missing PLAN artifacts may still exist in test env)
            stale_issues = [i for i in data["issues"] if "stale" in i]
            self.assertEqual(stale_issues, [])


class TestFeedbackClose(unittest.TestCase):
    def test_close_rejects_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "x", "--json")
            run_harnessctl(tmp_path, "feedback", "triage", "--epic-id", epic_id,
                           "--feedback-id", "HFB-001", "--classification", "question", "--json")

            result = run_harnessctl(tmp_path, "feedback", "close",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertNotEqual(result.returncode, 0)

    def test_close_with_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit", "--epic-id", epic_id, "--text", "x", "--json")
            run_harnessctl(tmp_path, "feedback", "triage", "--epic-id", epic_id,
                           "--feedback-id", "HFB-001", "--classification", "question", "--json")

            result = run_harnessctl(tmp_path, "feedback", "close",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001",
                                    "--reject", "--json")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["final_status"], "rejected")


class TestArtifactStatusWaiver(unittest.TestCase):
    def test_waiver_sets_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "artifact-status", "set",
                           "--epic-id", epic_id, "--path", "features/test/specs/",
                           "--status", "stale", "--json")

            result = run_harnessctl(tmp_path, "artifact-status", "waiver",
                                    "--epic-id", epic_id, "--path", "features/test/specs/",
                                    "--reason", "Not affected", "--json")
            self.assertEqual(result.returncode, 0)

            show = run_harnessctl(tmp_path, "artifact-status", "show", "--epic-id", epic_id, "--json")
            data = json.loads(show.stdout)
            art = [a for a in data["artifacts"] if "specs" in a["path"]][0]
            self.assertEqual(art["status"], "current")


class TestFeedbackCoverage(unittest.TestCase):
    def test_coverage_passes_with_no_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            result = run_harnessctl(tmp_path, "feedback-coverage", "--epic-id", epic_id, "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["feedback_count"], 0)


class TestTaskGraphMerge(unittest.TestCase):
    def _setup_with_task(self, tmp_path: Path):
        """Setup harness with one existing task."""
        epic_id = setup_harness_with_epic(tmp_path)
        # Create an existing task (positional args: epic_id title)
        run_harnessctl(tmp_path, "task", "create", epic_id, "Existing task", "--json")
        return epic_id

    def test_merge_creates_new_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = self._setup_with_task(tmp_path)

            new_tasks = json.dumps([
                {"title": "New task A"},
                {"title": "New task B", "acceptance_criteria": ["AC-1"]},
            ])
            result = run_harnessctl(
                tmp_path, "task-graph", "merge",
                "--epic-id", epic_id,
                "--new-tasks", new_tasks,
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["merged"], 2)
            self.assertEqual(len(data["created_task_ids"]), 2)
            self.assertEqual(data["total_tasks"], 3)

    def test_merge_resolves_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = self._setup_with_task(tmp_path)

            # Get existing task id
            tasks_dir = tmp_path / ".harness" / "tasks"
            existing = list(tasks_dir.glob(f"{epic_id}.*.json"))
            existing_id = json.loads(existing[0].read_text())["id"]

            new_tasks = json.dumps([
                {"title": "Depends on existing", "depends_on": [existing_id]},
                {"title": "Invalid dep", "depends_on": ["nonexistent-task"]},
            ])
            result = run_harnessctl(
                tmp_path, "task-graph", "merge",
                "--epic-id", epic_id,
                "--new-tasks", new_tasks,
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["merged"], 2)

            # Verify first task has valid dep, second has empty deps
            task_files = sorted(tasks_dir.glob(f"{epic_id}.*.json"))
            t2 = json.loads(task_files[1].read_text())
            t3 = json.loads(task_files[2].read_text())
            self.assertEqual(t2["dependencies"], [existing_id])
            self.assertEqual(t3["dependencies"], [])

    def test_merge_tags_feedback_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = self._setup_with_task(tmp_path)

            new_tasks = json.dumps([{"title": "From feedback"}])
            result = run_harnessctl(
                tmp_path, "task-graph", "merge",
                "--epic-id", epic_id,
                "--feedback-id", "HFB-001",
                "--new-tasks", new_tasks,
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            tasks_dir = tmp_path / ".harness" / "tasks"
            task_files = sorted(tasks_dir.glob(f"{epic_id}.*.json"))
            new_task = json.loads(task_files[-1].read_text())
            self.assertEqual(new_task["added_by_feedback"], "HFB-001")


class TestFeedbackEvidencePack(unittest.TestCase):
    def test_evidence_pack_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit",
                           "--epic-id", epic_id, "--text", "OMS前端页面不需要调整吗", "--json")

            result = run_harnessctl(tmp_path, "feedback", "evidence-pack",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["feedback_id"], "HFB-001")
            self.assertIn("artifacts", data)
            self.assertIn("source_evidence_hints", data)
            self.assertIn("keywords", data["source_evidence_hints"])
            # Should extract Chinese keywords from feedback text
            self.assertTrue(len(data["source_evidence_hints"]["keywords"]) > 0)

    def test_evidence_pack_missing_feedback_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            result = run_harnessctl(tmp_path, "feedback", "evidence-pack",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-999", "--json")
            self.assertNotEqual(result.returncode, 0)


class TestFeedbackCouncilTriage(unittest.TestCase):
    def test_council_triage_requires_evidence_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit",
                           "--epic-id", epic_id, "--text", "test", "--json")
            # No evidence-pack collected
            result = run_harnessctl(tmp_path, "feedback", "council-triage",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertNotEqual(result.returncode, 0)

    def test_council_triage_creates_votes_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit",
                           "--epic-id", epic_id, "--text", "test", "--json")
            run_harnessctl(tmp_path, "feedback", "evidence-pack",
                           "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")

            result = run_harnessctl(tmp_path, "feedback", "council-triage",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["council_type"], "feedback_triage_council")
            self.assertEqual(len(data["agents"]), 6)
            # Verify votes dir exists
            votes_dir = Path(data["votes_dir"])
            self.assertTrue(votes_dir.exists())


class TestFeedbackAggregateTriage(unittest.TestCase):
    def _setup_council(self, tmp_path: Path):
        epic_id = setup_harness_with_epic(tmp_path)
        run_harnessctl(tmp_path, "feedback", "submit",
                       "--epic-id", epic_id, "--text", "test gap", "--json")
        run_harnessctl(tmp_path, "feedback", "evidence-pack",
                       "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
        r = run_harnessctl(tmp_path, "feedback", "council-triage",
                           "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
        config = json.loads(r.stdout)
        return epic_id, Path(config["votes_dir"])

    def test_aggregate_reopen_clarify(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id, votes_dir = self._setup_council(tmp_path)

            # Write votes: majority says REOPEN_CLARIFY
            for agent in ["requirement-analyst", "impact-analyst", "challenger"]:
                vote = {
                    "agent": agent, "feedback_id": "HFB-001",
                    "decision": "REOPEN_CLARIFY",
                    "classification": "requirement_gap",
                    "confidence": 0.85, "evidence": ["missing impact"]
                }
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))
            for agent in ["plan-reviewer", "test-reviewer", "code-reviewer"]:
                vote = {
                    "agent": agent, "feedback_id": "HFB-001",
                    "decision": "REOPEN_PLAN",
                    "classification": "plan_defect",
                    "confidence": 0.7, "evidence": ["tasks missing"]
                }
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))

            result = run_harnessctl(tmp_path, "feedback", "aggregate-triage",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["decision"], "REOPEN_CLARIFY")
            self.assertTrue(data["requires_reopen"])
            self.assertEqual(data["target_stage"], "CLARIFY")

    def test_aggregate_no_reopen_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id, votes_dir = self._setup_council(tmp_path)

            # All agents say NO_REOPEN with evidence
            for agent in ["requirement-analyst", "impact-analyst", "challenger",
                          "plan-reviewer", "test-reviewer", "code-reviewer"]:
                vote = {
                    "agent": agent, "feedback_id": "HFB-001",
                    "decision": "NO_REOPEN_WITH_EVIDENCE",
                    "classification": "",
                    "confidence": 0.9, "evidence": ["checked, no gap"]
                }
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))

            result = run_harnessctl(tmp_path, "feedback", "aggregate-triage",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["decision"], "NO_REOPEN_WITH_EVIDENCE")
            self.assertFalse(data["requires_reopen"])

    def test_aggregate_insufficient_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id, votes_dir = self._setup_council(tmp_path)

            # All say NO_REOPEN but without evidence
            for agent in ["requirement-analyst", "impact-analyst", "challenger",
                          "plan-reviewer", "test-reviewer", "code-reviewer"]:
                vote = {
                    "agent": agent, "feedback_id": "HFB-001",
                    "decision": "NO_REOPEN_WITH_EVIDENCE",
                    "classification": "",
                    "confidence": 0.5, "evidence": []  # empty!
                }
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))

            result = run_harnessctl(tmp_path, "feedback", "aggregate-triage",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["decision"], "INSUFFICIENT_EVIDENCE")

    def test_aggregate_writes_triage_json_always(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id, votes_dir = self._setup_council(tmp_path)

            # NO_REOPEN with evidence
            for agent in ["requirement-analyst", "impact-analyst", "challenger",
                          "plan-reviewer", "test-reviewer", "code-reviewer"]:
                vote = {
                    "agent": agent, "feedback_id": "HFB-001",
                    "decision": "NO_REOPEN_WITH_EVIDENCE",
                    "classification": "",
                    "confidence": 0.9, "evidence": ["verified ok"]
                }
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))

            run_harnessctl(tmp_path, "feedback", "aggregate-triage",
                           "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")

            # Verify triage.json was written even for NO_REOPEN
            triage_path = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.triage.json"
            self.assertTrue(triage_path.exists())
            triage = json.loads(triage_path.read_text())
            self.assertEqual(triage["decision"], "NO_REOPEN_WITH_EVIDENCE")
            self.assertEqual(triage["triaged_by"], "feedback_triage_council")

    def test_aggregate_picks_earliest_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id, votes_dir = self._setup_council(tmp_path)

            # Mix of REOPEN_SPEC and REOPEN_PLAN
            vote1 = {"agent": "impact-analyst", "feedback_id": "HFB-001",
                     "decision": "REOPEN_SPEC", "classification": "spec_gap",
                     "confidence": 0.8, "evidence": ["spec missing"]}
            vote2 = {"agent": "plan-reviewer", "feedback_id": "HFB-001",
                     "decision": "REOPEN_PLAN", "classification": "plan_defect",
                     "confidence": 0.9, "evidence": ["tasks missing"]}
            vote3 = {"agent": "code-reviewer", "feedback_id": "HFB-001",
                     "decision": "STAY_EXECUTE", "classification": "implementation_bug",
                     "confidence": 0.7, "evidence": ["code gap"]}
            (votes_dir / "impact-analyst.json").write_text(json.dumps(vote1))
            (votes_dir / "plan-reviewer.json").write_text(json.dumps(vote2))
            (votes_dir / "code-reviewer.json").write_text(json.dumps(vote3))

            result = run_harnessctl(tmp_path, "feedback", "aggregate-triage",
                                    "--epic-id", epic_id, "--feedback-id", "HFB-001", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            # SPEC is earlier than PLAN, so should pick SPEC
            self.assertEqual(data["decision"], "REOPEN_SPEC")
            self.assertEqual(data["target_stage"], "SPEC")

    def test_votes_dir_is_feedback_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit two feedbacks
            run_harnessctl(tmp_path, "feedback", "submit",
                           "--epic-id", epic_id, "--text", "fb1", "--json")
            run_harnessctl(tmp_path, "feedback", "submit",
                           "--epic-id", epic_id, "--text", "fb2", "--json")

            # Evidence-pack + council-triage for both
            for fb_id in ["HFB-001", "HFB-002"]:
                run_harnessctl(tmp_path, "feedback", "evidence-pack",
                               "--epic-id", epic_id, "--feedback-id", fb_id, "--json")
                r = run_harnessctl(tmp_path, "feedback", "council-triage",
                                   "--epic-id", epic_id, "--feedback-id", fb_id, "--json")
                config = json.loads(r.stdout)
                # Verify paths are different
                self.assertIn(fb_id, config["votes_dir"])

            # Verify directories are separate
            base = tmp_path / ".harness" / "features" / epic_id / "councils" / "feedback_triage_council"
            self.assertTrue((base / "HFB-001" / "votes").exists())
            self.assertTrue((base / "HFB-002" / "votes").exists())


class TestGuardBlocksSubmittedFeedback(unittest.TestCase):
    def test_guard_blocks_submitted_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit feedback (status=submitted, not yet triaged)
            run_harnessctl(tmp_path, "feedback", "submit",
                           "--epic-id", epic_id, "--stage", "EXECUTE",
                           "--text", "test question", "--json")

            # Guard check should block
            result = run_harnessctl(tmp_path, "guard", "check",
                                    "--epic-id", epic_id, "--stage", "EXECUTE", "--json")
            data = json.loads(result.stdout)
            feedback_issues = [i for i in data["issues"] if "unresolved feedback" in i]
            self.assertGreater(len(feedback_issues), 0)


if __name__ == "__main__":
    unittest.main()
