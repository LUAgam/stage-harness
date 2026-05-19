"""Tests for Feedback Subsystem v2 features."""
import json
import hashlib
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

            state_path = tmp_path / ".harness" / "features" / epic_id / "state.json"
            state = json.loads(state_path.read_text())
            state["pending_re_completion"] = {
                "feedback_id": "HFB-001",
                "stages": ["PLAN"],
                "completed_stages": [],
                "created_at": "2026-05-13T10:00:00Z",
            }
            state_path.write_text(json.dumps(state))

            task_graph = tmp_path / ".harness" / "features" / epic_id / "task-graph.json"
            task_graph.write_text(json.dumps({"tasks": [{"id": "T-1", "source_feedback": "HFB-001"}]}))
            digest = "sha256:" + hashlib.sha256(task_graph.read_bytes()).hexdigest()[:16]
            manifest = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.revision-manifest.json"
            manifest.write_text(json.dumps({
                "feedback_id": "HFB-001",
                "stage": "PLAN",
                "changed_artifacts": [{
                    "path": "task-graph.json",
                    "before_hash": "sha256:old",
                    "after_hash": digest,
                    "evidence": "test",
                }],
            }))

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
            self.assertTrue(mc["validated"])
            state = json.loads(state_path.read_text())
            self.assertNotIn("pending_re_completion", state)

    def test_re_complete_requires_pending_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id, "--text", "Missing feature")
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                      "feedback" / "HFB-001.json")
            fb = json.loads(fb_path.read_text())
            fb["status"] = "reopened"
            fb["decision"] = "REOPEN_PLAN"
            fb_path.write_text(json.dumps(fb))

            result = run_harnessctl(tmp_path, "feedback", "re-complete",
                                   "--epic-id", epic_id, "--feedback-id", "HFB-001",
                                   "--stage", "PLAN", "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pending_re_completion", result.stderr)

    def test_re_complete_outputs_recovery_commands_on_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)

            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id, "--text", "Missing feature")
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                      "feedback" / "HFB-001.json")
            fb = json.loads(fb_path.read_text())
            fb["status"] = "reopened"
            fb["decision"] = "REOPEN_PLAN"
            fb_path.write_text(json.dumps(fb))

            state_path = tmp_path / ".harness" / "features" / epic_id / "state.json"
            state = json.loads(state_path.read_text())
            state["pending_re_completion"] = {
                "feedback_id": "HFB-001",
                "stages": ["PLAN"],
                "completed_stages": [],
                "created_at": "2026-05-13T10:00:00Z",
            }
            state_path.write_text(json.dumps(state))

            # Missing task-graph and other artifacts, but manifest exists
            manifest = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.revision-manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({
                "feedback_id": "HFB-001",
                "stage": "PLAN",
                "changed_artifacts": [{
                    "path": "task-graph.json",
                    "before_hash": "sha256:old",
                    "after_hash": "sha256:new",
                    "evidence": "test",
                }],
            }))

            result = run_harnessctl(tmp_path, "feedback", "re-complete",
                                   "--epic-id", epic_id, "--feedback-id", "HFB-001",
                                   "--stage", "PLAN", "--json")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")
            self.assertFalse(data["validated"])
            self.assertTrue(len(data["validation_warnings"]) > 0)
            self.assertIn("recovery_commands", data)
            self.assertTrue(len(data["recovery_commands"]) > 0)
            self.assertIn("harnessctl feedback gate-check", data["recovery_commands"][0])

    def test_re_plan_creates_backing_task_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id, "--text", "Missing feature")
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                      "feedback" / "HFB-001.json")
            fb = json.loads(fb_path.read_text())
            fb["status"] = "reopened"
            fb["decision"] = "REOPEN_PLAN"
            fb_path.write_text(json.dumps(fb))
            amendment = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.amendment-plan.json"
            amendment.write_text(json.dumps({
                "source_verdict": "REOPEN_PLAN",
                "target_stage": "PLAN",
                "tasks_to_add": [{
                    "title": "Implement missing behavior",
                    "surface": "backend",
                    "acceptance_criteria": ["works"],
                }],
                "coverage_updates": [],
            }))

            result = run_harnessctl(tmp_path, "feedback", "re-plan",
                                   "--epic-id", epic_id,
                                   "--feedback-id", "HFB-001",
                                   "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            task_files = list((tmp_path / ".harness" / "tasks").glob(f"{epic_id}.*.json"))
            self.assertEqual(len(task_files), 1)
            task = json.loads(task_files[0].read_text())
            self.assertEqual(task["source_feedback"], "HFB-001")
            task_graph = json.loads((tmp_path / ".harness" / "features" / epic_id /
                                     "task-graph.json").read_text())
            self.assertEqual(task_graph["tasks"][0]["id"], task["id"])

    def test_re_plan_preserves_in_batch_temp_dependencies_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id, "--text", "Missing feature")
            fb_path = (tmp_path / ".harness" / "features" / epic_id /
                      "feedback" / "HFB-001.json")
            fb = json.loads(fb_path.read_text())
            fb["status"] = "reopened"
            fb["decision"] = "REOPEN_PLAN"
            fb_path.write_text(json.dumps(fb))
            amendment = tmp_path / ".harness" / "features" / epic_id / "feedback" / "HFB-001.amendment-plan.json"
            amendment.write_text(json.dumps({
                "source_verdict": "REOPEN_PLAN",
                "target_stage": "PLAN",
                "tasks_to_add": [
                    {"id": "tmp-a", "title": "Create schema", "surface": "backend"},
                    {"id": "tmp-b", "title": "Use schema", "surface": "backend", "depends_on": ["tmp-a"]},
                ],
                "coverage_updates": [{"requirement": "tmp-a", "task": "tmp-a"}],
            }))

            for _ in range(2):
                result = run_harnessctl(tmp_path, "feedback", "re-plan",
                                       "--epic-id", epic_id,
                                       "--feedback-id", "HFB-001",
                                       "--json")
                self.assertEqual(result.returncode, 0, result.stderr)

            task_files = sorted((tmp_path / ".harness" / "tasks").glob(f"{epic_id}.*.json"))
            self.assertEqual(len(task_files), 2)
            tasks = [json.loads(path.read_text()) for path in task_files]
            by_title = {task["title"]: task for task in tasks}
            self.assertEqual(by_title["Use schema"]["dependencies"], [by_title["Create schema"]["id"]])
            task_graph = json.loads((tmp_path / ".harness" / "features" / epic_id /
                                     "task-graph.json").read_text())
            self.assertEqual(len(task_graph["tasks"]), 2)
            graph_by_title = {task["title"]: task for task in task_graph["tasks"]}
            self.assertEqual(graph_by_title["Use schema"]["dependencies"], [by_title["Create schema"]["id"]])
            coverage = json.loads((tmp_path / ".harness" / "features" / epic_id /
                                   "coverage-matrix.json").read_text())
            self.assertEqual(len(coverage["coverage"]), 1)
            self.assertEqual(coverage["coverage"][0]["task"], by_title["Create schema"]["id"])
            self.assertEqual(coverage["coverage"][0]["requirement"], "tmp-a")
            tasks_md = (tmp_path / ".harness" / "features" / epic_id / "TASKS.md").read_text()
            self.assertEqual(tasks_md.count("Create schema"), 1)
            self.assertEqual(tasks_md.count("Use schema"), 1)

    def test_re_plan_repairs_existing_task_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            fb_dir = tmp_path / ".harness" / "features" / epic_id / "feedback"
            fb_dir.mkdir(parents=True, exist_ok=True)
            (fb_dir / "HFB-001.json").write_text(json.dumps({
                "feedback_id": "HFB-001",
                "epic_id": epic_id,
                "status": "reopened",
                "decision": "REOPEN_PLAN",
                "text": "x",
            }))
            created_a = run_harnessctl(tmp_path, "task", "create", epic_id,
                                       "Create schema", "--json")
            task_a = json.loads(created_a.stdout)["id"]
            created_b = run_harnessctl(tmp_path, "task", "create", epic_id,
                                       "Use schema", "--json")
            task_b = json.loads(created_b.stdout)["id"]
            graph_path = tmp_path / ".harness" / "features" / epic_id / "task-graph.json"
            graph_path.write_text(json.dumps({
                "tasks": [
                    {"id": task_a, "source_feedback": "HFB-001", "source_task_id": "tmp-a", "title": "Create schema", "surface": "backend", "dependencies": []},
                    {"id": task_b, "source_feedback": "HFB-001", "source_task_id": "tmp-b", "title": "Use schema", "surface": "backend", "dependencies": []},
                ]
            }))
            amendment = fb_dir / "HFB-001.amendment-plan.json"
            amendment.write_text(json.dumps({
                "source_verdict": "REOPEN_PLAN",
                "target_stage": "PLAN",
                "tasks_to_add": [
                    {"id": "tmp-a", "title": "Create schema", "surface": "backend"},
                    {"id": "tmp-b", "title": "Use schema", "surface": "backend", "depends_on": ["tmp-a"]},
                ],
                "coverage_updates": [],
            }))

            result = run_harnessctl(tmp_path, "feedback", "re-plan",
                                   "--epic-id", epic_id,
                                   "--feedback-id", "HFB-001",
                                   "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            task_b_file = next(
                path for path in (tmp_path / ".harness" / "tasks").glob(f"{epic_id}.*.json")
                if json.loads(path.read_text())["id"] == task_b
            )
            self.assertEqual(json.loads(task_b_file.read_text())["dependencies"], [task_a])


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
                "validated": True,
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


def setup_git_repo_with_files(tmp_path: Path, epic_id: str) -> None:
    """Create a git repo with sample source files for probe testing."""
    # Init git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=str(tmp_path), capture_output=True, check=True)

    # Create source files
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    (src_dir / "mapping.ts").write_text(
        "export const ENDPOINT_INFOS = {\n"
        "  SQLSERVER: {\n"
        "    enableMigrationDest: [{ name: 'OB_MYSQL' }],\n"
        "    enableSyncDest: [{ name: 'OB_MYSQL' }],\n"
        "  },\n"
        "  POSTGRESQL: {\n"
        "    enableMigrationDest: [{ name: 'OB_MYSQL' }],\n"
        "  },\n"
        "};\n"
    )

    (src_dir / "config.ts").write_text(
        "export const DB_PASSWORD = 'super_secret_123';\n"
        "export const API_KEY = 'sk-1234567890abcdef';\n"
        "export const SQLSERVER_HOST = 'localhost';\n"
    )

    # Create ignored dir
    nm_dir = tmp_path / "node_modules" / "pkg"
    nm_dir.mkdir(parents=True)
    (nm_dir / "index.js").write_text("const SQLSERVER = 'ignore me';\n")

    # Commit all
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"],
                   cwd=str(tmp_path), capture_output=True, check=True)


class TestSourceProbe(unittest.TestCase):
    """Test source evidence probe (P2)."""

    def test_probe_finds_matching_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            setup_git_repo_with_files(tmp_path, epic_id)

            # Submit feedback mentioning SQLSERVER
            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id,
                          "--text", "SQLSERVER enableMigrationDest missing POSTGRESQL")

            result = run_harnessctl(tmp_path, "feedback", "source-probe",
                                   "--epic-id", epic_id,
                                   "--feedback-id", "HFB-001",
                                   "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")
            self.assertTrue(len(data["candidates"]) > 0)

            # mapping.ts should be in candidates
            paths = [c["path"] for c in data["candidates"]]
            self.assertTrue(any("mapping.ts" in p for p in paths))

    def test_probe_skips_ignored_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            setup_git_repo_with_files(tmp_path, epic_id)

            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id,
                          "--text", "SQLSERVER configuration issue")

            result = run_harnessctl(tmp_path, "feedback", "source-probe",
                                   "--epic-id", epic_id,
                                   "--feedback-id", "HFB-001",
                                   "--json")
            data = json.loads(result.stdout)

            # node_modules files should NOT appear
            paths = [c["path"] for c in data["candidates"]]
            self.assertFalse(any("node_modules" in p for p in paths))

    def test_probe_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            setup_git_repo_with_files(tmp_path, epic_id)

            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id,
                          "--text", "SQLSERVER config password issue")

            result = run_harnessctl(tmp_path, "feedback", "source-probe",
                                   "--epic-id", epic_id,
                                   "--feedback-id", "HFB-001",
                                   "--json")
            data = json.loads(result.stdout)

            # Check that secret lines are redacted in snippets
            for candidate in data["candidates"]:
                if "config.ts" in candidate["path"]:
                    for snippet in candidate["snippets"]:
                        content = snippet["content"]
                        self.assertNotIn("super_secret_123", content)
                        # Should contain REDACTED
                        if "PASSWORD" in content.upper() or "API_KEY" in content.upper():
                            self.assertIn("[REDACTED]", content)

    def test_probe_respects_resource_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            epic_id = setup_harness_with_epic(tmp_path)
            setup_git_repo_with_files(tmp_path, epic_id)

            run_harnessctl(tmp_path, "feedback", "submit",
                          "--epic-id", epic_id,
                          "--text", "SQLSERVER enableMigrationDest")

            result = run_harnessctl(tmp_path, "feedback", "source-probe",
                                   "--epic-id", epic_id,
                                   "--feedback-id", "HFB-001",
                                   "--json")
            data = json.loads(result.stdout)

            # Verify resource limits are reported
            self.assertIn("resource_limits", data)
            self.assertEqual(data["resource_limits"]["max_files"], 30)
            self.assertEqual(data["resource_limits"]["max_total_snippet_lines"], 200)

            # Verify total snippet lines don't exceed limit
            total_lines = sum(
                s["end_line"] - s["start_line"] + 1
                for c in data["candidates"]
                for s in c["snippets"]
            )
            self.assertLessEqual(total_lines, 200)


if __name__ == "__main__":
    unittest.main()
