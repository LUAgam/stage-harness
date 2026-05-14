#!/usr/bin/env bash
# PreToolUse hook: Block Write/Edit to managed feedback artifacts.
# These files must only be created by harnessctl commands, not by agent tools.
#
# Input: stdin JSON ({"tool_name": "Write"|"Edit", "tool_input": {"file_path": "..."}, ...})
# Output: JSON {"continue": true/false, ...}

set -euo pipefail

INPUT_JSON="$(cat 2>/dev/null || true)"

FILE_PATH="$(
  INPUT_JSON_VALUE="$INPUT_JSON" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    data = json.loads(os.environ.get("INPUT_JSON_VALUE", ""))
    ti = data.get("tool_input", {})
    # Write uses file_path, Edit uses file_path
    print(ti.get("file_path", ""))
except Exception:
    print("")
PY
)"

if [[ -z "$FILE_PATH" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# Check if the file path matches a protected feedback artifact pattern
IS_PROTECTED="$(
  FILE_PATH_VALUE="$FILE_PATH" python3 - <<'PY' 2>/dev/null || true
import os
import re

path = os.environ.get("FILE_PATH_VALUE", "")

# Protected patterns — only harnessctl may create/modify these
protected_patterns = [
    r"/feedback/HFB-[^/]*\.evidence-pack\.json$",
    r"/councils/feedback_triage_council/[^/]+/votes/[^/]+\.json$",
    r"/councils/feedback_triage_council/[^/]+/verdict\.json$",
    r"/councils/feedback_triage_council/[^/]+/metadata\.json$",
    r"/feedback/HFB-[^/]*\.triage\.json$",
]

for pattern in protected_patterns:
    if re.search(pattern, path):
        print("PROTECTED")
        break
else:
    print("OK")
PY
)"

if [[ "$IS_PROTECTED" == "PROTECTED" ]]; then
  STOP_REASON="禁止手工创建或修改 feedback 核心产物（evidence-pack / votes / verdict / triage）。必须使用 harnessctl 标准命令：feedback evidence-pack / feedback write-vote / feedback aggregate-triage。" \
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
        FILE_PATH_VALUE="$FILE_PATH" \
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
    "event_type": "feedback_artifact_write_blocked",
    "status": "blocked",
    "summary": "Blocked manual write to managed feedback artifact",
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
