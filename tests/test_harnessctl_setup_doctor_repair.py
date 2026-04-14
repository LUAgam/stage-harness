import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "harnessctl.py"
WRAPPER = REPO_ROOT / "scripts" / "harnessctl"


def run_harnessctl(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


class HarnessctlSetupDoctorRepairTests(unittest.TestCase):
    def test_setup_can_initialize_project_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "setup",
                "--init-project",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)

            self.assertEqual(payload["plugin_root"], str(REPO_ROOT))
            self.assertTrue(payload["project_initialized"])
            self.assertTrue((tmp_path / ".harness").is_dir())
            self.assertEqual(payload["recommended_harnessctl"], str(REPO_ROOT / "scripts" / "harnessctl"))

    def test_setup_init_project_is_idempotent_when_harness_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "setup",
                "--init-project",
                "--json",
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            second = run_harnessctl(
                tmp_path,
                "--project-root",
                str(tmp_path),
                "setup",
                "--init-project",
                "--json",
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            payload = json.loads(second.stdout)

            self.assertFalse(payload["project_initialized"])
            self.assertTrue(payload["project_init_skipped"])
            self.assertTrue((tmp_path / ".harness").is_dir())

    def test_doctor_gracefully_degrades_without_manifests(self) -> None:
        result = run_harnessctl(
            REPO_ROOT,
            "--project-root",
            str(REPO_ROOT),
            "doctor",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)

        self.assertIn(payload["status"], {"warning", "error"})
        self.assertEqual(payload["checks"]["plugin"]["plugin_root"], str(REPO_ROOT))
        self.assertEqual(payload["checks"]["install_state"]["mode"], "recorded-only")
        self.assertEqual(
            payload["checks"]["install_state"]["report"]["manifestMode"],
            "recorded-only",
        )

    def test_repair_is_dry_run_until_apply(self) -> None:
        original_mode = stat.S_IMODE(WRAPPER.stat().st_mode)
        try:
            WRAPPER.chmod(original_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            self.assertFalse(WRAPPER.stat().st_mode & stat.S_IXUSR)

            dry_run = run_harnessctl(REPO_ROOT, "repair", "--json")
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            dry_payload = json.loads(dry_run.stdout)
            self.assertIn(str(WRAPPER), dry_payload["permission_repairs"]["planned"])
            self.assertEqual(dry_payload["permission_repairs"]["applied"], [])
            self.assertFalse(WRAPPER.stat().st_mode & stat.S_IXUSR)

            apply = run_harnessctl(REPO_ROOT, "repair", "--apply", "--json")
            self.assertEqual(apply.returncode, 0, apply.stderr)
            apply_payload = json.loads(apply.stdout)
            self.assertIn(str(WRAPPER), apply_payload["permission_repairs"]["applied"])
            self.assertTrue(WRAPPER.stat().st_mode & stat.S_IXUSR)
        finally:
            WRAPPER.chmod(original_mode)


if __name__ == "__main__":
    unittest.main()
