"""Tests for Feedback Subsystem v2 features."""
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
    result = run_harnessctl(tmp_path, "start", "Test v2 feedback", "--json")
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


class TestVoteNormalization(unittest.TestCase):
    """Test that aggregate-triage normalizes legacy vote formats."""

    def test_lowercase_reopen_with_target_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit and setup council
            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id, "--text", "Test issue")
            run_harnessctl(tmp_path, "feedback", "council-triage",
                          "--epic-id", epic_id, "--feedback-id", "HFB-001")

            # Write votes with legacy lowercase format
            votes_dir = (tmp_path / ".harness" / "features" / epic_id /
                        "councils" / "feedback_triage_council" / "HFB-001" / "votes")
            votes_dir.mkdir(parents=True, exist_ok=True)

            for agent in ["requirement-analyst", "impact-analyst", "challenger",
                         "plan-reviewer", "test-reviewer", "code-reviewer"]:
                vote = {
                    "agent": agent,
                    "decision": "reopen",
                    "target_stage": "PLAN",
                    "confidence": 0.9,
                    "evidence": ["test evidence"],
                }
                (votes_dir / f"{agent}.json").write_text(json.dumps(vote))

            result = run_harnessctl(tmp_path, "feedback", "aggregate-triage",
                                   "--epic-id", epic_id, "--feedback-id", "HFB-001",
                                   "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["decision"], "REOPEN_PLAN")


class TestReCompletionMarker(unittest.TestCase):
    """Test re-completion marker creation and validation."""

    def test_re_complete_creates_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit feedback and set to reopened
            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id, "--text", "Missing feature")
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                      "feedback" / "HFB-001.json")
            fb = json.loads(fb_path.read_text())
            fb["status"] = "reopened"
            fb["decision"] = "REOPEN_PLAN"
            fb_path.write_text(json.dumps(fb))

            # Write revision-diff at the expected location (features/<epic>/revision-diff-HFB-001.md)
            rd_path = (tmp_path / ".harness" / "features" / epic_id /
                      "revision-diff-HFB-001.md")
            rd_path.write_text("# Revision Diff\n\nChanges made.")

            result = run_harnessctl(tmp_path, "feedback", "re-complete",
                                   "--epic-id", epic_id, "--feedback-id", "HFB-001",
                                   "--stage", "PLAN",
                                   "--artifacts", "tasks/,coverage-matrix.json",
                                   "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")

            # Verify marker file exists
            marker = (tmp_path / ".harness" / "features" / epic_id /
                     "feedback" / "HFB-001.re-completion.json")
            self.assertTrue(marker.exists())
            mc = json.loads(marker.read_text())
            self.assertEqual(mc["stage"], "PLAN")


class TestReopenGuard(unittest.TestCase):
    """Test that guard blocks EXECUTE when reopened feedback lacks re-completion."""

    def test_guard_blocks_without_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Create reopened feedback without re-completion
            fb_dir = (tmp_path / ".harness" / "features" / epic_id / "feedback")
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb = {
                "feedback_id": "HFB-001",
                "status": "reopened",
                "decision": "REOPEN_PLAN",
                "text": "Missing task",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb))

            result = run_harnessctl(tmp_path, "guard", "check",
                                   "--epic-id", epic_id, "--stage", "EXECUTE",
                                   "--json")
            data = json.loads(result.stdout)
            self.assertFalse(data["passed"])
            self.assertTrue(any("re-" in i for i in data["issues"]))

    def test_guard_passes_with_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            fb_dir = (tmp_path / ".harness" / "features" / epic_id / "feedback")
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb = {
                "feedback_id": "HFB-001",
                "status": "reopened",
                "decision": "REOPEN_PLAN",
                "text": "Missing task",
            }
            (fb_dir / "HFB-001.json").write_text(json.dumps(fb))

            # Add re-completion marker
            marker = {
                "feedback_id": "HFB-001",
                "stage": "PLAN",
                "completed_at": "2026-05-13T10:00:00Z",
            }
            (fb_dir / "HFB-001.re-completion.json").write_text(json.dumps(marker))

            result = run_harnessctl(tmp_path, "guard", "check",
                                   "--epic-id", epic_id, "--stage", "EXECUTE",
                                   "--json")
            data = json.loads(result.stdout)
            # Should not have reopen-related issues
            reopen_issues = [i for i in data["issues"] if "re-" in i and "REOPEN" in i]
            self.assertEqual(len(reopen_issues), 0)


class TestDecisionsLedger(unittest.TestCase):
    """Test decisions ledger CRUD and authority checks."""

    def test_add_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            result = run_harnessctl(tmp_path, "decisions", "add",
                                   "--epic-id", epic_id,
                                   "--stage", "CLARIFY",
                                   "--topic", "scope",
                                   "--decision", "No stored procedures",
                                   "--authority", "user_confirmed",
                                   "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["id"], "D-001")

            result = run_harnessctl(tmp_path, "decisions", "list",
                                   "--epic-id", epic_id, "--json")
            data = json.loads(result.stdout)
            self.assertEqual(len(data["decisions"]), 1)
            self.assertEqual(data["decisions"][0]["authority"], "user_confirmed")

    def test_check_override_user_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "decisions", "add",
                          "--epic-id", epic_id,
                          "--stage", "CLARIFY",
                          "--topic", "scope",
                          "--decision", "No stored procedures",
                          "--authority", "user_confirmed",
                          "--json")

            result = run_harnessctl(tmp_path, "decisions", "check-override",
                                   "--epic-id", epic_id,
                                   "--decision-id", "D-001",
                                   "--json")
            data = json.loads(result.stdout)
            self.assertFalse(data["is_overridable_by_system"])

    def test_check_override_agent_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "decisions", "add",
                          "--epic-id", epic_id,
                          "--stage", "PLAN",
                          "--topic", "approach",
                          "--decision", "Use batch processing",
                          "--authority", "agent_assumed",
                          "--json")

            result = run_harnessctl(tmp_path, "decisions", "check-override",
                                   "--epic-id", epic_id,
                                   "--decision-id", "D-001",
                                   "--json")
            data = json.loads(result.stdout)
            self.assertTrue(data["is_overridable_by_system"])


class TestFeedbackDedup(unittest.TestCase):
    """Test feedback deduplication logic."""

    def test_duplicate_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            # Submit first feedback (use English for reliable word-split dedup)
            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id,
                          "--text", "frontend page needs adjustment for migration")

            # Submit near-duplicate (high word overlap)
            result = run_harnessctl(tmp_path, "feedback", "submit",
                                   "--epic-id", epic_id,
                                   "--text", "frontend page needs adjustment for migration path",
                                   "--json")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "merged")
            self.assertEqual(data["feedback_id"], "HFB-001")

    def test_different_feedback_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id,
                          "--text", "Frontend page needs changes")

            result = run_harnessctl(tmp_path, "feedback", "submit",
                                   "--epic-id", epic_id,
                                   "--text", "Backend API is missing validation",
                                   "--json")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["feedback_id"], "HFB-002")


class TestRelatedGapScan(unittest.TestCase):
    """Test related-gap-scan command."""

    def test_generates_scan_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id, "--text", "Missing frontend config")

            result = run_harnessctl(tmp_path, "feedback", "related-gap-scan",
                                   "--epic-id", epic_id,
                                   "--feedback-id", "HFB-001",
                                   "--phase", "pre",
                                   "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["feedback_id"], "HFB-001")
            self.assertEqual(data["scan_phase"], "pre")
            self.assertIn("sibling_categories", data)
            self.assertTrue(len(data["sibling_categories"]) >= 5)


if __name__ == "__main__":
    unittest.main()
