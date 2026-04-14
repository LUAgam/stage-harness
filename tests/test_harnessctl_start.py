import json
import stat
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


class HarnessctlStartTests(unittest.TestCase):
    def test_init_writes_neutral_profile_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            result = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "init",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            show = run_harnessctl(
                tmp_path,
                "profile",
                "show",
                "--json",
            )
            self.assertEqual(show.returncode, 0, show.stderr)
            profile = json.loads(show.stdout)

            self.assertEqual(profile["type"], "unknown")
            self.assertEqual(profile["primary_language"], "unknown")
            self.assertEqual(profile["build_tool"], "unknown")
            self.assertEqual(profile["test_framework"], "unknown")
            self.assertEqual(profile["workspace_mode"], "unknown")
            self.assertEqual(profile["primary_surfaces"], [])
            self.assertIsNone(profile["has_database"])
            self.assertIsNone(profile["has_auth"])
            self.assertIsNone(profile["has_docker"])
            self.assertIsNone(profile["has_ci"])

    def test_start_bootstraps_harness_and_creates_epic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "package.json").write_text('{"name": "demo-app"}\n', encoding="utf-8")

            result = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "start",
                "Need login support for admin users",
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            self.assertTrue(payload["initialized"])
            self.assertEqual(payload["current_stage"], "CLARIFY")
            self.assertEqual(payload["next_action"], "run_clarify")
            self.assertEqual(payload["next_command"], f"/harness:auto {payload['epic_id']}")
            self.assertEqual(payload["manual_next_command"], f"/harness:clarify {payload['epic_id']}")
            self.assertEqual(payload["profile"]["type"], "frontend")
            self.assertEqual(payload["profile"]["workspace_mode"], "single-repo")

            harness_dir = tmp_path / ".harness"
            self.assertTrue(harness_dir.is_dir())
            self.assertTrue((harness_dir / "project-profile.yaml").exists())
            self.assertTrue((harness_dir / "epics" / f"{payload['epic_id']}.json").exists())
            self.assertTrue((harness_dir / "features" / payload["epic_id"] / "state.json").exists())

    def test_start_bootstraps_local_harness_from_nested_directory_outside_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "package.json").write_text('{"name": "demo-app"}\n', encoding="utf-8")

            first = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "start",
                "Initial bootstrap epic",
                "--json",
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            nested = tmp_path / "src" / "nested"
            nested.mkdir(parents=True)

            second = run_harnessctl(
                nested,
                "start",
                "Nested follow-up epic",
                "--json",
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            payload = json.loads(second.stdout)

            self.assertTrue(payload["initialized"])
            self.assertTrue((tmp_path / ".harness").is_dir())
            self.assertTrue((nested / ".harness").is_dir())
            self.assertTrue((nested / ".harness" / "epics" / f"{payload['epic_id']}.json").exists())

    def test_start_bootstraps_at_git_root_when_run_from_nested_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            subprocess.run(
                ["git", "init"],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                check=True,
            )
            (tmp_path / "package.json").write_text('{"name": "demo-app"}\n', encoding="utf-8")

            nested = tmp_path / "src" / "nested"
            nested.mkdir(parents=True)

            result = run_harnessctl(
                nested,
                "start",
                "Bootstrap from nested git worktree",
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            self.assertTrue(payload["initialized"])
            self.assertTrue((tmp_path / ".harness").is_dir())
            self.assertFalse((nested / ".harness").exists())
            self.assertTrue((tmp_path / ".harness" / "epics" / f"{payload['epic_id']}.json").exists())

    def test_start_ignores_parent_harness_outside_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / ".harness").mkdir()

            repo_path = tmp_path / "child-repo"
            repo_path.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
            (repo_path / "package.json").write_text('{"name": "demo-app"}\n', encoding="utf-8")

            nested = repo_path / "src" / "nested"
            nested.mkdir(parents=True)

            result = run_harnessctl(
                nested,
                "start",
                "Bootstrap from nested repo with parent harness",
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            self.assertTrue(payload["initialized"])
            self.assertTrue((repo_path / ".harness").is_dir())
            self.assertTrue((repo_path / ".harness" / "epics" / f"{payload['epic_id']}.json").exists())

    def test_start_retries_cwd_when_git_root_init_is_unwritable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            subprocess.run(
                ["git", "init"],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                check=True,
            )
            child = tmp_path / "child-project"
            child.mkdir()
            (child / "package.json").write_text('{"name": "demo-app"}\n', encoding="utf-8")

            original_mode = stat.S_IMODE(tmp_path.stat().st_mode)
            try:
                tmp_path.chmod(0o555)
                result = run_harnessctl(
                    child,
                    "start",
                    "Bootstrap locally when detected git root is unwritable",
                    "--json",
                )
            finally:
                tmp_path.chmod(original_mode)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            self.assertTrue(payload["initialized"])
            self.assertEqual(payload["project_root"], str(child.resolve()))
            self.assertEqual(payload["bootstrap_retry"]["from"], str(tmp_path.resolve()))
            self.assertEqual(payload["bootstrap_retry"]["to"], str(child.resolve()))
            self.assertIn("retrying bootstrap in current directory", result.stderr)
            self.assertTrue((child / ".harness").is_dir())
            self.assertFalse((tmp_path / ".harness").exists())

    def test_start_does_not_retry_cwd_when_project_root_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            subprocess.run(
                ["git", "init"],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                check=True,
            )
            child = tmp_path / "child-project"
            child.mkdir()
            (child / "package.json").write_text('{"name": "demo-app"}\n', encoding="utf-8")

            original_mode = stat.S_IMODE(tmp_path.stat().st_mode)
            try:
                tmp_path.chmod(0o555)
                result = run_harnessctl(
                    child,
                    "--project-root",
                    str(tmp_path),
                    "start",
                    "Explicit root should fail instead of retrying in cwd",
                    "--json",
                )
            finally:
                tmp_path.chmod(original_mode)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failed to initialize", result.stderr)
            self.assertNotIn("retrying bootstrap in current directory", result.stderr)
            self.assertFalse((child / ".harness").exists())
            self.assertFalse((tmp_path / ".harness").exists())

    def test_state_next_stays_within_current_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / ".harness").mkdir()

            repo_path = tmp_path / "child-repo"
            repo_path.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )

            nested = repo_path / "src" / "nested"
            nested.mkdir(parents=True)

            result = run_harnessctl(
                nested,
                "state",
                "next",
                "--epic-id",
                "sh-1-demo",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f".harness/ not found at {repo_path / '.harness'}", result.stderr)

    def test_epic_create_ignores_parent_harness_when_outside_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / ".harness").mkdir()

            child = tmp_path / "child"
            child.mkdir()

            result = run_harnessctl(
                child,
                "epic",
                "create",
                "Should stay local",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f".harness/ not found at {child / '.harness'}", result.stderr)

    def test_epic_create_accepts_flag_title_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_harnessctl(tmp_path, "--project-root", str(tmp_path), "init")

            result = run_harnessctl(
                tmp_path,
                "epic",
                "create",
                "--title",
                "Flag title epic",
                "--description",
                "Detailed description",
                "--risk-level",
                "medium",
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["title"], "Flag title epic")
            self.assertEqual(payload["description"], "Detailed description")

    def test_start_persists_requirements_as_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            requirement = "delete 不物理删除，只做逻辑删除，并支持无主键表"

            result = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "start",
                requirement,
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            epic_path = tmp_path / ".harness" / "epics" / f"{payload['epic_id']}.json"
            epic = json.loads(epic_path.read_text(encoding="utf-8"))
            self.assertEqual(epic["description"], requirement)

    def test_profile_detect_replaces_legacy_placeholder_values_for_multi_module_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "ui-app").mkdir()
            (tmp_path / "ui-app" / "package.json").write_text('{"name": "ui-app"}\n', encoding="utf-8")
            (tmp_path / "docs-app").mkdir()
            (tmp_path / "docs-app" / "package.json").write_text('{"name": "docs-app"}\n', encoding="utf-8")
            (tmp_path / "native-lib").mkdir()
            (tmp_path / "native-lib" / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8")

            result = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "init",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            legacy_profile = "\n".join(
                [
                    "type: backend-service",
                    "risk_level: medium",
                    "primary_language: typescript",
                    'framework: ""',
                    "build_tool: npm",
                    "test_framework: jest",
                    "has_database: true",
                    "has_auth: false",
                    "has_docker: true",
                    "has_ci: true",
                    "estimated_size: medium",
                    "intensity:",
                    "  agent_parallelism: 3",
                    "  council_size: 3",
                    "  harness_strength: standard",
                    'notes: ""',
                    "workspace_mode: single-repo",
                    "scan:",
                    "  max_repos_deep_scan: 5",
                    "  max_files_deep_read_per_scout: 20",
                    "  max_subagents_wave: 4",
                    "primary_surfaces:",
                    "  - src/",
                    "check_focus:",
                    "  - api_contract",
                    "  - state_idempotency",
                    "detected_at: \"\"",
                    "confidence: 0.0",
                    "overrides: {}",
                    "",
                ]
            )
            (tmp_path / ".harness" / "project-profile.yaml").write_text(legacy_profile, encoding="utf-8")

            detect = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "profile",
                "detect",
                "--json",
            )
            self.assertEqual(detect.returncode, 0, detect.stderr)

            show = run_harnessctl(
                tmp_path,
                "profile",
                "show",
                "--json",
            )
            self.assertEqual(show.returncode, 0, show.stderr)
            profile = json.loads(show.stdout)

            self.assertEqual(profile["workspace_mode"], "monorepo")
            self.assertNotEqual(profile["primary_surfaces"], ["src/"])
            self.assertIn("ui-app/", profile["primary_surfaces"])
            self.assertIn("docs-app/", profile["primary_surfaces"])
            self.assertIn("native-lib/", profile["primary_surfaces"])
            self.assertEqual(profile["build_tool"], "unknown")
            self.assertEqual(profile["test_framework"], "unknown")

    def test_profile_detect_preserves_manual_workspace_and_surfaces_with_inline_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "ui-app").mkdir()
            (tmp_path / "ui-app" / "package.json").write_text('{"name": "ui-app"}\n', encoding="utf-8")
            (tmp_path / "docs-app").mkdir()
            (tmp_path / "docs-app" / "package.json").write_text('{"name": "docs-app"}\n', encoding="utf-8")

            result = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "init",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            manual_profile = "\n".join(
                [
                    "type: unknown",
                    "risk_level: medium",
                    "primary_language: unknown",
                    'framework: ""',
                    "build_tool: unknown",
                    "test_framework: unknown",
                    "has_database: null",
                    "has_auth: null",
                    "has_docker: null",
                    "has_ci: null",
                    "estimated_size: unknown",
                    "intensity: {}",
                    'notes: ""',
                    "workspace_mode: single-repo",
                    "scan: {}",
                    "primary_surfaces: []",
                    "check_focus: []",
                    'detected_at: "2026-01-01T00:00:00Z"',
                    "confidence: 0.9",
                    "overrides: {workspace_mode: true, primary_surfaces: true}",
                    "",
                ]
            )
            (tmp_path / ".harness" / "project-profile.yaml").write_text(manual_profile, encoding="utf-8")

            detect = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "profile",
                "detect",
                "--json",
            )
            self.assertEqual(detect.returncode, 0, detect.stderr)

            show = run_harnessctl(
                tmp_path,
                "profile",
                "show",
                "--json",
            )
            self.assertEqual(show.returncode, 0, show.stderr)
            profile = json.loads(show.stdout)

            self.assertEqual(profile["workspace_mode"], "single-repo")
            self.assertEqual(profile["primary_surfaces"], [])
            self.assertEqual(profile["overrides"]["workspace_mode"], True)
            self.assertEqual(profile["overrides"]["primary_surfaces"], True)

    def test_profile_detect_preserves_hand_authored_profile_without_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "src").mkdir()
            (tmp_path / "apps").mkdir()
            (tmp_path / "apps" / "package.json").write_text('{"name": "apps"}\n', encoding="utf-8")
            (tmp_path / "packages").mkdir()
            (tmp_path / "packages" / "package.json").write_text('{"name": "packages"}\n', encoding="utf-8")

            result = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "init",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            hand_authored = "\n".join(
                [
                    "type: backend-service",
                    "risk_level: medium",
                    "primary_language: typescript",
                    'framework: "custom framework"',
                    "build_tool: npm",
                    "test_framework: jest",
                    "has_database: true",
                    "has_auth: false",
                    "has_docker: true",
                    "has_ci: true",
                    "estimated_size: medium",
                    "intensity:",
                    "  agent_parallelism: 2",
                    "  council_size: 2",
                    '  harness_strength: "standard"',
                    'notes: "release #1 profile"',
                    "workspace_mode: single-repo",
                    "scan:",
                    "  max_repos_deep_scan: 7",
                    "  max_files_deep_read_per_scout: 11",
                    "  max_subagents_wave: 2",
                    "primary_surfaces:",
                    "  - src/",
                    "check_focus:",
                    "  - api_contract",
                    'detected_at: "2026-01-01T00:00:00Z"',
                    "confidence: 0.0",
                    "overrides: {}",
                    "",
                ]
            )
            (tmp_path / ".harness" / "project-profile.yaml").write_text(hand_authored, encoding="utf-8")

            detect = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "profile",
                "detect",
                "--json",
            )
            self.assertEqual(detect.returncode, 0, detect.stderr)
            detect_payload = json.loads(detect.stdout)

            show = run_harnessctl(tmp_path, "profile", "show", "--json")
            self.assertEqual(show.returncode, 0, show.stderr)
            profile = json.loads(show.stdout)

            self.assertEqual(detect_payload["type"], "backend-service")
            self.assertEqual(profile["type"], "backend-service")
            self.assertEqual(profile["workspace_mode"], "single-repo")
            self.assertEqual(profile["primary_surfaces"], ["src/"])
            self.assertEqual(profile["framework"], "custom framework")
            self.assertEqual(profile["notes"], "release #1 profile")
            self.assertEqual(profile["scan"]["max_repos_deep_scan"], 7)


if __name__ == "__main__":
    unittest.main()
