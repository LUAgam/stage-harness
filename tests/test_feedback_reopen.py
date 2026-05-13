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


if __name__ == "__main__":
    unittest.main()
