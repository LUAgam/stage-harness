import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESSCTL = ROOT / "scripts" / "harnessctl.py"


def run_harnessctl(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HARNESSCTL), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


class HarnessctlAuditShowExtendedTests(unittest.TestCase):
    def _bootstrap_epic(self, tmp_path: Path, requirement: str = "Audit extended MVP") -> str:
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

    def _append_trace(self, tmp_path: Path, event: dict) -> None:
        r = run_harnessctl(
            tmp_path,
            "patch",
            "trace",
            "--event-json",
            json.dumps(event, ensure_ascii=False),
            "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_legacy_trace_envelope_gets_normalized_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            raw = {"epic_id": epic_id, "event_type": "custom_legacy", "payload": {"x": 1}}
            self._append_trace(tmp_path, raw)
            trace_path = tmp_path / ".harness" / "logs" / "epics" / epic_id / "execution-trace.jsonl"
            self.assertTrue(trace_path.exists())
            line = trace_path.read_text(encoding="utf-8").strip().splitlines()[-1]
            stored = json.loads(line)
            self.assertIn("ts", stored)
            self.assertTrue(str(stored["ts"]).strip())
            self.assertEqual(stored.get("status"), "ok")
            self.assertIn("event_id", stored)
            self.assertTrue(str(stored["event_id"]).startswith("evt_"))

    def test_audit_json_latest_gate_is_last_gate_event_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "stage_gate_checked",
                    "stage": "SPEC",
                    "summary": "first check",
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "stage_gate_failed",
                    "stage": "PLAN",
                    "summary": "blocked plan",
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "stage_gate_checked",
                    "stage": "DONE",
                    "summary": "later check only",
                },
            )
            r = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            g = payload.get("latest_gate")
            self.assertIsInstance(g, dict)
            self.assertEqual(g.get("event_type"), "stage_gate_checked")
            self.assertEqual(g.get("stage"), "DONE")

    def test_audit_json_latest_guard_is_last_guard_event_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "guard_passed",
                    "stage": "SPEC",
                    "summary": "ok to enter",
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "guard_checked",
                    "stage": "SPEC",
                    "summary": "gchk later",
                },
            )
            r = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            gu = payload.get("latest_guard")
            self.assertIsInstance(gu, dict)
            self.assertEqual(gu.get("event_type"), "guard_checked")

    @staticmethod
    def _strip_updated_at(payload: dict) -> dict:
        out = dict(payload)
        out.pop("updated_at", None)
        return out

    def test_audit_show_json_stable_for_legacy_trace_without_ts_or_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            trace_path = tmp_path / ".harness" / "logs" / "epics" / epic_id / "execution-trace.jsonl"
            legacy = {
                "epic_id": epic_id,
                "event_type": "task_status_changed",
                "payload": {"task_id": f"{epic_id}.9", "new_status": "done"},
                "summary": "legacy",
            }
            with trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(legacy, ensure_ascii=False) + "\n")
            r1 = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            r2 = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r1.returncode, 0, r1.stderr)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertEqual(
                self._strip_updated_at(json.loads(r1.stdout)),
                self._strip_updated_at(json.loads(r2.stdout)),
            )

    def test_read_normalize_fills_json_null_ts_event_id_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            trace_path = tmp_path / ".harness" / "logs" / "epics" / epic_id / "execution-trace.jsonl"
            raw = {
                "epic_id": epic_id,
                "event_type": "stage_gate_checked",
                "stage": "SPEC",
                "summary": "null fields",
                "ts": None,
                "event_id": None,
                "status": None,
            }
            with trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(raw, ensure_ascii=False) + "\n")
            r = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            g = json.loads(r.stdout).get("latest_gate")
            self.assertIsInstance(g, dict)
            self.assertEqual(g.get("event_type"), "stage_gate_checked")
            self.assertTrue(str(g.get("ts") or "").startswith("legacy_ts:"))
            self.assertEqual(g.get("status"), "ok")
            self.assertTrue(str(g.get("event_id") or "").startswith("evt_"))

    def test_late_checked_not_masked_by_earlier_pass_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "stage_gate_passed",
                    "stage": "SPEC",
                    "summary": "old pass",
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "stage_gate_checked",
                    "stage": "VERIFY",
                    "summary": "re-checked later",
                },
            )
            r = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            g = json.loads(r.stdout).get("latest_gate")
            self.assertIsInstance(g, dict)
            self.assertEqual(g.get("event_type"), "stage_gate_checked")
            self.assertEqual(g.get("stage"), "VERIFY")
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "guard_failed",
                    "stage": "PLAN",
                    "summary": "old fail",
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "guard_checked",
                    "stage": "DONE",
                    "summary": "guard re-check",
                },
            )
            r2 = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            gu = json.loads(r2.stdout).get("latest_guard")
            self.assertIsInstance(gu, dict)
            self.assertEqual(gu.get("event_type"), "guard_checked")
            self.assertEqual(gu.get("stage"), "DONE")

    def test_audit_json_task_summary_counts_latest_per_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            tid = f"{epic_id}.1"
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "task_status_changed",
                    "payload": {"task_id": tid, "new_status": "in_progress"},
                    "summary": "start",
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "task_status_changed",
                    "payload": {"task_id": tid, "new_status": "done"},
                    "summary": "finish",
                },
            )
            r = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            ts = payload.get("task_summary")
            self.assertIsInstance(ts, dict)
            self.assertEqual(ts["by_status"].get("done"), 1)
            self.assertEqual(ts["by_status"].get("in_progress"), 0)
            lc = ts.get("latest_change")
            self.assertIsInstance(lc, dict)
            self.assertEqual(lc.get("task_id"), tid)
            self.assertEqual(lc.get("new_status"), "done")

    def test_audit_text_includes_extended_lines_and_na_without_extra_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            r = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = r.stdout
            self.assertIn("latest_gate:", out)
            self.assertIn("latest_guard:", out)
            self.assertIn("task_summary:", out)
            self.assertIn("N/A", out)

    def test_mixed_clarify_and_gate_preserves_clarify_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            epic_id = self._bootstrap_epic(tmp_path)
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "event_type": "clarify_run_started",
                    "payload": {"run_id": "clr-mix"},
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "stage": "CLARIFY",
                    "event_type": "step_completed",
                    "payload": {"run_id": "clr-mix", "step": "domain-scout"},
                },
            )
            self._append_trace(
                tmp_path,
                {
                    "epic_id": epic_id,
                    "event_type": "stage_gate_passed",
                    "stage": "CLARIFY",
                    "summary": "gate ok",
                },
            )
            r = run_harnessctl(tmp_path, "audit", "show", "--epic-id", epic_id, "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload.get("latest_run_id"), "clr-mix")
            self.assertIn("domain-scout", payload.get("steps_completed", []))
            self.assertEqual(payload.get("latest_gate", {}).get("event_type"), "stage_gate_passed")


if __name__ == "__main__":
    unittest.main()
