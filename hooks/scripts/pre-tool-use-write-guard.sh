#!/usr/bin/env bash
# PreToolUse hook: Block Write/Edit/MultiEdit/Delete to managed harness artifacts.
# These files must only be created by harnessctl commands, not by agent tools.
#
# Input: stdin JSON ({"tool_name": "Write"|"Edit"|"MultiEdit"|"Delete", "tool_input": {"file_path": "..."}, ...})
# Output: JSON {"continue": true/false, ...}

set -euo pipefail

INPUT_JSON="$(cat 2>/dev/null || true)"

FILE_PATHS="$(
  INPUT_JSON_VALUE="$INPUT_JSON" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    data = json.loads(os.environ.get("INPUT_JSON_VALUE", ""))
    ti = data.get("tool_input", {})
    paths = []
    if ti.get("file_path"):
        paths.append(str(ti.get("file_path", "")))
    if ti.get("path"):
        paths.append(str(ti.get("path", "")))
    for edit in ti.get("edits", []) or []:
        if isinstance(edit, dict):
            edit_path = edit.get("file_path") or edit.get("path")
            if edit_path:
                paths.append(str(edit_path))
    print("\n".join(dict.fromkeys(p for p in paths if p)))
except Exception:
    print("")
PY
)"

if [[ -z "$FILE_PATHS" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# Check if any file path matches a protected harness artifact pattern.
PROTECTED_PATH="$(
  FILE_PATHS_VALUE="$FILE_PATHS" python3 - <<'PY' 2>/dev/null || true
import os
import re

paths = [p.strip() for p in os.environ.get("FILE_PATHS_VALUE", "").splitlines() if p.strip()]

protected_patterns = [
    r"(?:^|/)\.harness/epics/[^/]+\.json$",
    r"(?:^|/)\.harness/features/[^/]+/state\.json$",
    r"(?:^|/)\.harness/tasks/[^/]+\.json$",
    r"(?:^|/)\.harness/features/[^/]+/feedback/HFB-[^/]+\.json$",
    r"(?:^|/)\.harness/features/[^/]+/artifact-status\.json$",
    r"(?:^|/)\.harness/features/[^/]+/coverage-matrix\.json$",
    r"(?:^|/)\.harness/features/[^/]+/receipts/[^/]+\.json$",
    r"(?:^|/)\.harness/features/[^/]+/runtime-receipts/[^/]+\.json$",
    r"(?:^|/)\.harness/features/[^/]+/runs/[^/]+\.json$",
    r"(?:^|/)\.harness/features/[^/]+/councils/.*/(?:verdict|metadata)\.json$",
    r"(?:^|/)\.harness/features/[^/]+/councils/.*/votes/[^/]+\.json$",
    # Backward-compatible relative snippets seen in older hook tests/commands.
    r"/feedback/HFB-[^/]*\.evidence-pack\.json$",
    r"/councils/feedback_triage_council/[^/]+/votes/[^/]+\.json$",
    r"/councils/feedback_triage_council/[^/]+/verdict\.json$",
    r"/councils/feedback_triage_council/[^/]+/metadata\.json$",
    r"/feedback/HFB-[^/]*\.triage\.json$",
]

for path in paths:
    normalized = os.path.normpath(path).replace("\\", "/")
    for pattern in protected_patterns:
        if re.search(pattern, normalized):
            print(path)
            raise SystemExit(0)
print("")
PY
)"

if [[ -n "$PROTECTED_PATH" ]]; then
  STOP_REASON="禁止手工创建或修改 .harness 受控产物（状态机、task、feedback、结构化证据或 receipt）。必须使用 harnessctl 标准命令或受信 runtime adapter。" \
    python3 - <<'PY'
import json
import os

print(json.dumps({
    "continue": False,
    "stopReason": os.environ["STOP_REASON"],
}, ensure_ascii=False))
PY

  # Trace the blocked event
  HARNESSCTL="${CLAUDE_PLUGIN_ROOT:-}/scripts/harnessctl"
  if [[ -x "$HARNESSCTL" ]]; then
    HARNESS_DIR=".harness"
    ACTIVE_EPIC_ID=""
    if [[ -d "$HARNESS_DIR/epics" ]]; then
      for epic_file in "$HARNESS_DIR/epics/"*.json; do
        [[ -f "$epic_file" ]] || continue
        epic_id="$(
          EPIC_FILE="$epic_file" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    with open(os.environ["EPIC_FILE"], encoding="utf-8") as fh:
        data = json.load(fh)
    print(data.get("id", ""))
except Exception:
    print("")
PY
        )"
        if [[ -n "$epic_id" ]]; then
          ACTIVE_EPIC_ID="$epic_id"
          break
        fi
      done
    fi

    if [[ -n "$ACTIVE_EPIC_ID" ]]; then
      EVENT="$(
        FILE_PATH_VALUE="$PROTECTED_PATH" \
        ACTIVE_EPIC_ID_VALUE="$ACTIVE_EPIC_ID" \
        python3 - <<'PY' 2>/dev/null
import hashlib
import json
import os
from datetime import datetime, timezone

path_hash = hashlib.sha256(os.environ["FILE_PATH_VALUE"].encode("utf-8")).hexdigest()[:12]
print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "epic_id": os.environ["ACTIVE_EPIC_ID_VALUE"],
    "source": "hook",
    "actor": "pre-tool-use-write-guard",
    "event_type": "managed_harness_artifact_write_blocked",
    "status": "blocked",
    "summary": "Blocked manual write to managed harness artifact",
    "payload": {
        "file_path": os.environ["FILE_PATH_VALUE"],
        "path_hash": path_hash,
    },
    "artifact_paths": [],
}, ensure_ascii=False))
PY
      )"
      [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
    fi
  fi
  exit 0
fi

printf '{"continue": true}\n'
