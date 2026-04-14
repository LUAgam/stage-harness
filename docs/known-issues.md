# Known Issues

## Deferred Fixes

- CLARIFY 并行子任务若通过 **非 Bash** 路径（例如仅发送 slash 命令文本而不经 `PreToolUse`）仍可能尝试跨阶段命令；`pre-tool-use.sh` 仅覆盖 **Bash 工具** 调用。主会话应通过命令文档约束角色边界。
- Observed in the `/stage-harness:harness-start` slash-command orchestration layer: after epic creation, the run may continue into `clarify` instead of stopping immediately at the CLARIFY entry point.
- In some `claude -p --verbose --output-format stream-json` runs, the redirected local JSONL log file (for example `harness-start-run.jsonl` in the working directory used for the run) appears to stop refreshing after `init` even while `.harness/features/<epic-id>/domain-frame.json`, `requirements-draft.md`, or `generated-scenarios.json` continue to appear on disk.
