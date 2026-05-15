import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION_START_SCRIPT = ROOT / "hooks" / "scripts" / "session-start.sh"
PRE_TOOL_USE_SCRIPT = ROOT / "hooks" / "scripts" / "pre-tool-use.sh"
PRE_TOOL_USE_WRITE_GUARD_SCRIPT = ROOT / "hooks" / "scripts" / "pre-tool-use-write-guard.sh"
STAGE_REMINDER_SCRIPT = ROOT / "hooks" / "scripts" / "stage-reminder.sh"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class HookScriptTests(unittest.TestCase):
    def test_pre_tool_use_write_guard_blocks_multiedit_managed_task(self) -> None:
        payload = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": ".harness/tasks/sh-1-demo.1.json",
                "edits": [{"old_string": "pending", "new_string": "done"}],
            },
        }
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_WRITE_GUARD_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])
        self.assertIn(".harness", response["stopReason"])

    def test_pre_tool_use_write_guard_blocks_multiedit_edit_path(self) -> None:
        payload = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "edits": [
                    {"path": ".harness/features/sh-1-demo/state.json",
                     "old_string": "PLAN", "new_string": "DONE"}
                ],
            },
        }
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_WRITE_GUARD_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_write_guard_normalizes_managed_path(self) -> None:
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "foo/../.harness/./tasks//sh-1-demo.1.json"},
        }
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_WRITE_GUARD_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_write_guard_blocks_state_file(self) -> None:
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": ".harness/features/sh-1-demo/state.json"},
        }
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_WRITE_GUARD_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_write_guard_blocks_delete_tool(self) -> None:
        payload = {
            "tool_name": "Delete",
            "tool_input": {"path": ".harness/features/sh-1-demo/state.json"},
        }
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_WRITE_GUARD_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_untrusted_protected_write(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "python3 -c \"open('.harness/tasks/sh-1-demo.1.json','w').write('{}')\""
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])
        self.assertIn("非受信 Bash", response["stopReason"])

    def test_pre_tool_use_bash_blocks_absolute_protected_write(self) -> None:
        protected_path = ROOT / ".harness" / "tasks" / "sh-1-demo.1.json"
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"python3 -c \"open('{protected_path}','w').write('{{}}')\""
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_no_space_redirect_to_protected_path(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "echo '{}'>.harness/tasks/sh-1-demo.1.json"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_untrusted_segment_with_trusted_segment(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "scripts/harnessctl --version && python3 -c \"open('.harness/tasks/sh-1-demo.1.json','w').write('{}')\""
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_pipe_mixed_trusted_untrusted_write(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "scripts/harnessctl --version | python3 -c \"open('.harness/tasks/sh-1-demo.1.json','w').write('{}')\""
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_cd_into_harness_then_write(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "cd .harness/tasks && echo '{}' > sh-1-demo.1.json"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_tracks_relative_cd_inside_harness(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "cd .harness && cd tasks && echo '{}' > sh-1-demo.1.json"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_trusted_command_redirect_to_protected_path(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "scripts/harnessctl --version > .harness/epics/sh-1-demo.json"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_trusted_no_space_redirect_to_protected_path(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "scripts/harnessctl --version>.harness/epics/sh-1-demo.json"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_allows_trusted_command_redirect_to_safe_path(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "scripts/harnessctl feedback close --epic-id sh-1-demo --feedback-id HFB-001 --evidence .harness/features/sh-1-demo/feedback/HFB-001.json > /tmp/harnessctl.out"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response["continue"])

    def test_pre_tool_use_bash_blocks_trusted_command_substitution_write(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "scripts/harnessctl epic show $(python3 -c \"open('.harness/tasks/sh-1-demo.1.json','w').write('{}')\")"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_blocks_tee_to_protected_path(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "printf '{}' | tee .harness/tasks/sh-1-demo.1.json"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["continue"])

    def test_pre_tool_use_bash_does_not_keep_protected_cd_after_leaving(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "cd .harness && cd .. && echo ok > notes.txt"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response["continue"])

    def test_pre_tool_use_bash_allows_trusted_harnessctl_write(self) -> None:
        result = subprocess.run(
            ["bash", str(PRE_TOOL_USE_SCRIPT)],
            cwd=str(ROOT),
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "scripts/harnessctl feedback close --epic-id sh-1-demo --feedback-id HFB-001 --evidence .harness/features/sh-1-demo/feedback/HFB-001.json"
                    },
                }
            ),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response["continue"])

    def test_stage_reminder_skips_start_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-1").mkdir(parents=True)
            plugin_root = tmp_path / "plugin"
            (plugin_root / "scripts").mkdir(parents=True)
            call_log = tmp_path / "stage-reminder-calls.log"

            (harness_dir / "epics" / "epic-1.json").write_text(
                json.dumps({"id": "epic-1", "title": "Existing Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-1" / "state.json").write_text(
                json.dumps({"current_stage": "CLARIFY"}),
                encoding="utf-8",
            )

            harnessctl_stub = textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import pathlib
                import sys

                log_path = pathlib.Path({str(call_log)!r})
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(" ".join(sys.argv[1:]) + "\\n")
                raise SystemExit(0)
                """
            )
            make_executable(plugin_root / "scripts" / "harnessctl", harnessctl_stub)

            for prompt in (
                "/harness:start 新需求",
                "/stage-harness:harness-start 新需求",
            ):
                result = subprocess.run(
                    ["bash", str(STAGE_REMINDER_SCRIPT)],
                    cwd=str(tmp_path),
                    input=json.dumps({"prompt": prompt}),
                    capture_output=True,
                    text=True,
                    env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
                    check=False,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "")

            self.assertFalse(call_log.exists())

    def test_stage_reminder_reports_active_epics_for_non_start_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-1").mkdir(parents=True)

            (harness_dir / "epics" / "epic-1.json").write_text(
                json.dumps({"id": "epic-1", "title": "Existing Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-1" / "state.json").write_text(
                json.dumps({"current_stage": "CLARIFY"}),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(STAGE_REMINDER_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps({"prompt": "/harness:status epic-1"}),
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("Epic: epic-1 | 阶段: CLARIFY", payload["additionalContext"])

    def test_session_start_ignores_unsafe_epic_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "safe-epic").mkdir(parents=True)
            outside_dir = tmp_path / "escape-target"
            outside_dir.mkdir(parents=True)

            (harness_dir / "epics" / "bad.json").write_text(
                json.dumps({"id": "../../escape-target", "title": "Bad Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "epics" / "safe.json").write_text(
                json.dumps({"id": "safe-epic", "title": "Safe Epic"}),
                encoding="utf-8",
            )
            (outside_dir / "state.json").write_text(
                json.dumps({"current_stage": "EXECUTE"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "safe-epic" / "state.json").write_text(
                json.dumps(
                    {
                        "current_stage": "PLAN",
                        "interrupt_budget": {"remaining": 2},
                        "runtime_health": {"drift_detected": False},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(SESSION_START_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps({"session_id": "sess-safe"}),
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("safe-epic", payload["additionalContext"])
            self.assertNotIn("../../escape-target", payload["additionalContext"])

    def test_session_start_reports_all_active_epics_in_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-a").mkdir(parents=True)
            (harness_dir / "features" / "epic-b").mkdir(parents=True)

            (harness_dir / "epics" / "epic-a.json").write_text(
                json.dumps({"id": "epic-a", "title": "Epic A"}),
                encoding="utf-8",
            )
            (harness_dir / "epics" / "epic-b.json").write_text(
                json.dumps({"id": "epic-b", "title": "Epic B"}),
                encoding="utf-8",
            )

            active_state = {
                "current_stage": "PLAN",
                "interrupt_budget": {"remaining": 1},
                "runtime_health": {"drift_detected": False},
            }
            (harness_dir / "features" / "epic-a" / "state.json").write_text(
                json.dumps(active_state),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-b" / "state.json").write_text(
                json.dumps({**active_state, "current_stage": "VERIFY"}),
                encoding="utf-8",
            )

            plugin_root = tmp_path / "plugin"
            (plugin_root / "scripts").mkdir(parents=True)
            trace_log = tmp_path / "trace-events.jsonl"
            harnessctl_stub = textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import pathlib
                import sys

                trace_log = pathlib.Path({str(trace_log)!r})
                args = sys.argv[1:]
                if args[:2] == ["patch", "list"]:
                    print("[]")
                    raise SystemExit(0)
                if args[:2] == ["patch", "trace"]:
                    event = args[args.index("--event-json") + 1]
                    with trace_log.open("a", encoding="utf-8") as fh:
                        fh.write(event + "\\n")
                    raise SystemExit(0)
                raise SystemExit(1)
                """
            )
            make_executable(plugin_root / "scripts" / "harnessctl", harnessctl_stub)

            result = subprocess.run(
                ["bash", str(SESSION_START_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps({"session_id": "sess-1"}),
                capture_output=True,
                text=True,
                env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["continue"])
            self.assertIn("Epic: epic-a | Stage: PLAN", payload["additionalContext"])
            self.assertIn("Epic: epic-b | Stage: VERIFY", payload["additionalContext"])
            self.assertNotIn("\\n", payload["additionalContext"])

            events = [
                json.loads(line)
                for line in trace_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            snapshot = next(event for event in events if event["event_type"] == "active_epics_snapshot")
            self.assertEqual(snapshot["payload"]["active_epics_count"], 2)

    def test_pre_tool_use_blocks_quoted_dangerous_command_and_records_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-1").mkdir(parents=True)

            (harness_dir / "epics" / "epic-1.json").write_text(
                json.dumps({"id": "epic-1", "title": "Dangerous Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-1" / "state.json").write_text(
                json.dumps({"current_stage": "EXECUTE"}),
                encoding="utf-8",
            )

            plugin_root = tmp_path / "plugin"
            (plugin_root / "scripts").mkdir(parents=True)
            trace_log = tmp_path / "dangerous-events.jsonl"
            harnessctl_stub = textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import pathlib
                import sys

                trace_log = pathlib.Path({str(trace_log)!r})
                args = sys.argv[1:]
                if args[:2] == ["patch", "trace"]:
                    event = args[args.index("--event-json") + 1]
                    with trace_log.open("a", encoding="utf-8") as fh:
                        fh.write(event + "\\n")
                    raise SystemExit(0)
                raise SystemExit(1)
                """
            )
            make_executable(plugin_root / "scripts" / "harnessctl", harnessctl_stub)

            dangerous_command = "git reset --hard 'oops'"
            result = subprocess.run(
                ["bash", str(PRE_TOOL_USE_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": dangerous_command}}
                ),
                capture_output=True,
                text=True,
                env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["continue"])
            self.assertIn("潜在危险操作", payload["stopReason"])

            events = [
                json.loads(line)
                for line in trace_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event["event_type"], "dangerous_bash_blocked")
            self.assertEqual(event["payload"]["pattern"], "git reset --hard")
            self.assertRegex(event["payload"]["command_hash"], r"^[0-9a-f]{12}$")

    def test_pre_tool_use_clarify_blocks_later_harness_slash_in_bash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-1").mkdir(parents=True)

            (harness_dir / "epics" / "epic-1.json").write_text(
                json.dumps({"id": "epic-1", "title": "Clarify Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-1" / "state.json").write_text(
                json.dumps({"current_stage": "CLARIFY"}),
                encoding="utf-8",
            )

            plugin_root = tmp_path / "plugin"
            (plugin_root / "scripts").mkdir(parents=True)
            trace_log = tmp_path / "drift-events.jsonl"
            harnessctl_stub = textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import pathlib
                import sys

                trace_log = pathlib.Path({str(trace_log)!r})
                args = sys.argv[1:]
                if args[:2] == ["patch", "trace"]:
                    event = args[args.index("--event-json") + 1]
                    with trace_log.open("a", encoding="utf-8") as fh:
                        fh.write(event + "\\n")
                    raise SystemExit(0)
                raise SystemExit(1)
                """
            )
            make_executable(plugin_root / "scripts" / "harnessctl", harnessctl_stub)

            for cmd in (
                "/harness:spec epic-1",
                "/harness: done epic-1",
                "stage-harness:harness-patch epic-1",
            ):
                result = subprocess.run(
                    ["bash", str(PRE_TOOL_USE_SCRIPT)],
                    cwd=str(tmp_path),
                    input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                    capture_output=True,
                    text=True,
                    env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertFalse(payload["continue"], cmd)
                self.assertIn("CLARIFY", payload["stopReason"])

            events = [
                json.loads(line)
                for line in trace_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(events), 3)
            self.assertTrue(all(e["event_type"] == "clarify_stage_drift_blocked" for e in events))

    def test_pre_tool_use_clarify_does_not_block_plain_text_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-1").mkdir(parents=True)

            (harness_dir / "epics" / "epic-1.json").write_text(
                json.dumps({"id": "epic-1", "title": "Clarify Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-1" / "state.json").write_text(
                json.dumps({"current_stage": "CLARIFY"}),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(PRE_TOOL_USE_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "echo /stage-harness:harness-patch epic-1"},
                    }
                ),
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["continue"])

    def test_pre_tool_use_scopes_block_to_target_epic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-a").mkdir(parents=True)
            (harness_dir / "features" / "epic-b").mkdir(parents=True)

            (harness_dir / "epics" / "epic-a.json").write_text(
                json.dumps({"id": "epic-a", "title": "Clarify Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "epics" / "epic-b.json").write_text(
                json.dumps({"id": "epic-b", "title": "Plan Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-a" / "state.json").write_text(
                json.dumps({"current_stage": "CLARIFY"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-b" / "state.json").write_text(
                json.dumps({"current_stage": "PLAN"}),
                encoding="utf-8",
            )

            blocked = subprocess.run(
                ["bash", str(PRE_TOOL_USE_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": "/harness:spec epic-a"}}
                ),
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )
            self.assertEqual(blocked.returncode, 0, blocked.stderr)
            blocked_payload = json.loads(blocked.stdout)
            self.assertFalse(blocked_payload["continue"])
            self.assertIn("epic-a", blocked_payload["stopReason"])

            allowed = subprocess.run(
                ["bash", str(PRE_TOOL_USE_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": "/harness:review epic-b"}}
                ),
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            allowed_payload = json.loads(allowed.stdout)
            self.assertTrue(allowed_payload["continue"])

    def test_pre_tool_use_allows_later_harness_when_stage_not_clarify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            harness_dir = tmp_path / ".harness"
            (harness_dir / "epics").mkdir(parents=True)
            (harness_dir / "features" / "epic-1").mkdir(parents=True)

            (harness_dir / "epics" / "epic-1.json").write_text(
                json.dumps({"id": "epic-1", "title": "Spec Epic"}),
                encoding="utf-8",
            )
            (harness_dir / "features" / "epic-1" / "state.json").write_text(
                json.dumps({"current_stage": "SPEC"}),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(PRE_TOOL_USE_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": "/harness:plan epic-1"}}
                ),
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["continue"])

    def test_pre_tool_use_blocks_whitespace_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = subprocess.run(
                ["bash", str(PRE_TOOL_USE_SCRIPT)],
                cwd=str(tmp_path),
                input=json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": "git\treset\t--hard"}}
                ),
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["continue"])
            self.assertIn("git reset --hard", payload["stopReason"])


if __name__ == "__main__":
    unittest.main()
