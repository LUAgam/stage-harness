#!/usr/bin/env bash
# PreToolUse hook: 拦截危险的 Bash 命令
# 输入：stdin JSON（{"tool_name": "Bash", "tool_input": {"command": "..."}, ...}）
# 输出：JSON {"continue": true/false, ...}

set -euo pipefail
shopt -s nullglob

is_safe_epic_id() {
  local epic_id="$1"
  [[ -n "$epic_id" ]] || return 1
  [[ "$epic_id" != *"/"* ]] || return 1
  [[ "$epic_id" != *"\\"* ]] || return 1
  [[ "$epic_id" != *".."* ]] || return 1
  return 0
}

INPUT_JSON="$(cat 2>/dev/null || true)"

TOOL_NAME="$(
  INPUT_JSON_VALUE="$INPUT_JSON" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    data = json.loads(os.environ.get("INPUT_JSON_VALUE", ""))
    print(data.get("tool_name", ""))
except Exception:
    print("")
PY
)"
if [[ "$TOOL_NAME" != "Bash" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

COMMAND="$(
  INPUT_JSON_VALUE="$INPUT_JSON" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    data = json.loads(os.environ.get("INPUT_JSON_VALUE", ""))
    print(data.get("tool_input", {}).get("command", ""))
except Exception:
    print("")
PY
)"

if [[ -z "$COMMAND" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

NORMALIZED_COMMAND="$(
  COMMAND_VALUE="$COMMAND" python3 - <<'PY' 2>/dev/null || true
import sys
import os

text = os.environ.get("COMMAND_VALUE", "")
text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
print(" ".join(text.split()))
PY
)"

# While an epic is in CLARIFY, block Bash that invokes later-stage harness commands
# only when the command explicitly targets that epic (or there is exactly one active epic).
declare -A ACTIVE_EPIC_STAGE_BY_ID=()
ACTIVE_EPIC_IDS=()
HARNESS_DIR_LOCAL=".harness"
if [[ -d "$HARNESS_DIR_LOCAL/epics" ]]; then
  for epic_file in "$HARNESS_DIR_LOCAL/epics/"*.json; do
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
    is_safe_epic_id "$epic_id" || continue

    current_stage="$(
      STATE_FILE=".harness/features/$epic_id/state.json" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    with open(os.environ["STATE_FILE"], encoding="utf-8") as fh:
        data = json.load(fh)
    print(data.get("current_stage", ""))
except Exception:
    print("")
PY
    )"
    if [[ "$current_stage" != "DONE" && "$current_stage" != "CANCELLED" && -n "$current_stage" ]]; then
      ACTIVE_EPIC_STAGE_BY_ID["$epic_id"]="$current_stage"
      ACTIVE_EPIC_IDS+=("$epic_id")
    fi
  done
fi

DRIFT_MATCH="$(
  COMMAND_VALUE="$COMMAND" python3 - <<'PY' 2>/dev/null || true
import os
import re
import shlex

blocked = {"spec", "plan", "work", "review", "done", "patch", "auto", "bridge", "fix"}
text = os.environ.get("COMMAND_VALUE", "")

for segment in re.split(r"(?:&&|\|\||;)", text):
    segment = segment.strip()
    if not segment:
        continue
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        continue
    if not tokens:
        continue

    idx = 0
    while idx < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", tokens[idx]):
        idx += 1
    if idx >= len(tokens):
        continue

    cmd = tokens[idx]
    rest = tokens[idx + 1 :]
    action = ""
    epic_tokens = rest

    if cmd in ("/harness:", "harness:"):
        if not rest:
            continue
        action = rest[0]
        epic_tokens = rest[1:]
    elif cmd.startswith("/harness:") or cmd.startswith("harness:"):
        action = cmd.split(":", 1)[1]
    elif cmd.startswith("/stage-harness:harness-"):
        action = cmd.split("harness-", 1)[1]
    elif cmd.startswith("stage-harness:harness-"):
        action = cmd.split("harness-", 1)[1]
    else:
        continue

    action = action.strip().lower()
    if action not in blocked:
        continue

    epic_id = ""
    for token in epic_tokens:
        stripped = token.strip()
        if not stripped or stripped.startswith("-"):
            continue
        epic_id = stripped
        break

    print(f"{action}\t{epic_id}")
    break
PY
)"

if [[ -n "$DRIFT_MATCH" ]]; then
  IFS=$'\t' read -r BLOCKED_ACTION TARGET_EPIC_ID <<< "$DRIFT_MATCH"
  BLOCK_EPIC_ID=""
  if [[ -n "$TARGET_EPIC_ID" ]]; then
    if [[ "${ACTIVE_EPIC_STAGE_BY_ID[$TARGET_EPIC_ID]:-}" == "CLARIFY" ]]; then
      BLOCK_EPIC_ID="$TARGET_EPIC_ID"
    fi
  elif [[ "${#ACTIVE_EPIC_IDS[@]}" -eq 1 ]]; then
    sole_epic_id="${ACTIVE_EPIC_IDS[0]}"
    if [[ "${ACTIVE_EPIC_STAGE_BY_ID[$sole_epic_id]:-}" == "CLARIFY" ]]; then
      BLOCK_EPIC_ID="$sole_epic_id"
    fi
  fi

  if [[ -n "$BLOCK_EPIC_ID" ]]; then
    STOP_REASON="目标 Epic（$BLOCK_EPIC_ID）当前处于 CLARIFY 阶段：禁止通过 Bash 调用后续阶段 harness 命令（spec / plan / work / review / done / patch / auto / bridge / fix）。请先完成澄清与 stage-gate check CLARIFY，再由主流程推进。" \
      python3 - <<'PY'
import json
import os

print(json.dumps({
    "continue": False,
    "stopReason": os.environ["STOP_REASON"],
}, ensure_ascii=False))
PY

    HARNESSCTL="${CLAUDE_PLUGIN_ROOT:-}/scripts/harnessctl"
    if [[ -x "$HARNESSCTL" ]]; then
      EVENT="$(
        COMMAND_VALUE="$COMMAND" \
        ACTIVE_EPIC_ID_VALUE="$BLOCK_EPIC_ID" \
        BLOCKED_ACTION_VALUE="$BLOCKED_ACTION" \
        python3 - <<'PY' 2>/dev/null
import hashlib
import json
import os
from datetime import datetime, timezone

cmd_hash = hashlib.sha256(os.environ["COMMAND_VALUE"].encode("utf-8")).hexdigest()[:12]
print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "epic_id": os.environ["ACTIVE_EPIC_ID_VALUE"],
    "source": "hook",
    "actor": "pre-tool-use",
    "event_type": "clarify_stage_drift_blocked",
    "status": "blocked",
    "tool_name": "Bash",
    "summary": "CLARIFY stage: blocked later-stage harness command in Bash",
    "payload": {
        "blocked_action": os.environ["BLOCKED_ACTION_VALUE"],
        "command_hash": cmd_hash,
    },
    "artifact_paths": [],
}, ensure_ascii=False))
PY
      )"
      [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
    fi
    exit 0
  fi
fi

while IFS=$'\t' read -r pattern trace_label description; do
  [[ -n "$pattern" ]] || continue
  if printf '%s\n%s\n' "$COMMAND" "$NORMALIZED_COMMAND" | grep -Eqi "$pattern" 2>/dev/null; then
    STOP_REASON="检测到潜在危险操作：$description。如确认需要执行，请直接在终端运行，或在消息中明确说明意图后重试。" \
      python3 - <<'PY'
import json
import os

print(json.dumps({
    "continue": False,
    "stopReason": os.environ["STOP_REASON"],
}, ensure_ascii=False))
PY

    HARNESSCTL="${CLAUDE_PLUGIN_ROOT:-}/scripts/harnessctl"
    if [[ -x "$HARNESSCTL" ]]; then
      ACTIVE_EPIC_ID=""
      HARNESS_DIR=".harness"
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
          is_safe_epic_id "$epic_id" || continue

          current_stage="$(
            STATE_FILE=".harness/features/$epic_id/state.json" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    with open(os.environ["STATE_FILE"], encoding="utf-8") as fh:
        data = json.load(fh)
    print(data.get("current_stage", ""))
except Exception:
    print("")
PY
          )"
          if [[ "$current_stage" != "DONE" && "$current_stage" != "CANCELLED" && -n "$current_stage" ]]; then
            ACTIVE_EPIC_ID="$epic_id"
            break
          fi
        done
      fi

      if [[ -n "$ACTIVE_EPIC_ID" ]]; then
        EVENT="$(
          COMMAND_VALUE="$COMMAND" \
          ACTIVE_EPIC_ID_VALUE="$ACTIVE_EPIC_ID" \
          DESCRIPTION_VALUE="$description" \
          PATTERN_VALUE="$trace_label" \
          python3 - <<'PY' 2>/dev/null
import hashlib
import json
import os
from datetime import datetime, timezone

cmd_hash = hashlib.sha256(os.environ["COMMAND_VALUE"].encode("utf-8")).hexdigest()[:12]
print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "epic_id": os.environ["ACTIVE_EPIC_ID_VALUE"],
    "source": "hook",
    "actor": "pre-tool-use",
    "event_type": "dangerous_bash_blocked",
    "status": "blocked",
    "tool_name": "Bash",
    "summary": f"Dangerous bash blocked: {os.environ['DESCRIPTION_VALUE']}",
    "payload": {
        "pattern": os.environ["PATTERN_VALUE"],
        "command_hash": cmd_hash,
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
done <<'EOF'
(^|[[:space:]])git[[:space:]]+reset[[:space:]]+--hard([[:space:]]|$)	git reset --hard	git reset --hard 会丢失未提交的更改
(^|[[:space:]])rm([[:space:]]|\$\{?IFS\}?)+-rf([[:space:]]|\$\{?IFS\}?)+/([[:space:]]|$)	rm -rf /	rm -rf / 会删除根目录所有文件
(^|[[:space:]])git[[:space:]]+push[[:space:]]+--force([[:space:]]|$)	git push --force	git push --force 会强制覆盖远程历史
(^|[[:space:]])git[[:space:]]+push[[:space:]]+-f([[:space:]]|$)	git push -f	git push -f 会强制覆盖远程历史
(^|[[:space:]])drop[[:space:]]+table([[:space:]]|$)	DROP TABLE	DROP TABLE 会永久删除数据库表
(^|[[:space:]])truncate[[:space:]]+table([[:space:]]|$)	TRUNCATE TABLE	TRUNCATE TABLE 会清空数据库表所有数据
(^|[[:space:]])rm[[:space:]]+-rf[[:space:]]+\.harness([[:space:]]|$)	rm -rf .harness	rm -rf .harness 会删除 stage-harness 所有状态数据
EOF

printf '{"continue": true}\n'
