#!/usr/bin/env bash
# SessionStart hook: 检测并恢复 harness 上下文，注入激活规则
# 输入：stdin JSON（{"session_id": "...", ...}）
# 输出：JSON {"continue": true, "additionalContext": "..."}

set -euo pipefail
shopt -s nullglob

HARNESS_DIR=".harness"
HARNESSCTL="${CLAUDE_PLUGIN_ROOT:-}/scripts/harnessctl"

is_safe_epic_id() {
  local epic_id="$1"
  [[ -n "$epic_id" ]] || return 1
  [[ "$epic_id" != *"/"* ]] || return 1
  [[ "$epic_id" != *"\\"* ]] || return 1
  [[ "$epic_id" != *".."* ]] || return 1
  return 0
}

if [[ ! -d "$HARNESS_DIR" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

INPUT_JSON="$(cat 2>/dev/null || true)"
SESSION_ID="$(
  INPUT_JSON_VALUE="$INPUT_JSON" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    data = json.loads(os.environ.get("INPUT_JSON_VALUE", ""))
    print(data.get("session_id", ""))
except Exception:
    print("")
PY
)"

EPICS_DIR="$HARNESS_DIR/epics"
if [[ ! -d "$EPICS_DIR" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

CONTEXT=""
ACTIVE_EPIC_ID=""
ACTIVE_STAGE=""
ACTIVE_EPICS_COUNT=0
TMP_INFO_FILE="$(mktemp "${TMPDIR:-/tmp}/stage-harness-session-start.XXXXXX")"
trap 'rm -f "$TMP_INFO_FILE"' EXIT

for epic_file in "$EPICS_DIR"/*.json; do
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

  state_file="$HARNESS_DIR/features/$epic_id/state.json"
  [[ -f "$state_file" ]] || continue

  info="$(
    STATE_FILE="$state_file" EPIC_ID_VALUE="$epic_id" python3 - <<'PY' 2>"$TMP_INFO_FILE"
import json
import os
import sys

try:
    with open(os.environ["STATE_FILE"], encoding="utf-8") as fh:
        data = json.load(fh)
    epic_id = os.environ["EPIC_ID_VALUE"]
    stage = data.get("current_stage", "?")
    budget = data.get("interrupt_budget", {})
    remaining = budget.get("remaining", "?")
    health = data.get("runtime_health", {})
    drift = "DRIFT DETECTED" if health.get("drift_detected") else "OK"
    print(f"Epic: {epic_id} | Stage: {stage} | Budget remaining: {remaining} | Health: {drift}")
    if stage not in ("DONE", "CANCELLED"):
        print(f"__ACTIVE__:{stage}:{epic_id}", file=sys.stderr)
except Exception as exc:
    print(f"Error reading state for {os.environ.get('EPIC_ID_VALUE', '?')}: {exc}")
PY
  )"

  [[ -n "$info" ]] || continue
  CONTEXT+="${info}"$'\n'

  active_marker="$(grep '^__ACTIVE__:' "$TMP_INFO_FILE" 2>/dev/null | head -1 || true)"
  if [[ -n "$active_marker" ]]; then
    ACTIVE_EPICS_COUNT=$((ACTIVE_EPICS_COUNT + 1))
    if [[ -z "$ACTIVE_EPIC_ID" ]]; then
      ACTIVE_STAGE="$(printf '%s' "$active_marker" | cut -d: -f2)"
      ACTIVE_EPIC_ID="$(printf '%s' "$active_marker" | cut -d: -f3)"
    fi
  fi
done

if [[ -z "$CONTEXT" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

RULES_SUMMARY=""
if [[ -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" ]]; then
  PATCH_LIST_JSON="$("$HARNESSCTL" patch list --scope all --json 2>/dev/null || printf '[]')"
  RULES_SUMMARY="$(
    PATCH_LIST_JSON_VALUE="$PATCH_LIST_JSON" python3 - <<'PY' 2>/dev/null || true
import json
import os

try:
    patches = json.loads(os.environ.get("PATCH_LIST_JSON_VALUE", "[]"))
except Exception:
    patches = []
active = [p for p in patches if p.get("status") in ("active_epic", "project_active")]
if not active:
    raise SystemExit(0)
lines = ["[Stage-Harness 激活规则]"]
for patch in active:
    lines.append(
        f"  [{patch.get('scope', '?')}] {patch.get('id', '?')} — {patch.get('kind', 'rule')}"
    )
print("\n".join(lines))
PY
  )"
fi

if [[ -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" ]]; then
  SNAP_EVENT="$(
    SESSION_ID_VALUE="$SESSION_ID" \
    ACTIVE_EPIC_ID_VALUE="$ACTIVE_EPIC_ID" \
    ACTIVE_STAGE_VALUE="$ACTIVE_STAGE" \
    ACTIVE_EPICS_COUNT_VALUE="$ACTIVE_EPICS_COUNT" \
    python3 - <<'PY' 2>/dev/null
import json
import os
from datetime import datetime, timezone

print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "session_id": os.environ.get("SESSION_ID_VALUE", ""),
    "epic_id": os.environ["ACTIVE_EPIC_ID_VALUE"],
    "stage": os.environ["ACTIVE_STAGE_VALUE"],
    "source": "hook",
    "actor": "session-start",
    "event_type": "active_epics_snapshot",
    "status": "ok",
    "summary": "Active epics snapshot captured",
    "payload": {"active_epics_count": int(os.environ["ACTIVE_EPICS_COUNT_VALUE"])},
    "artifact_paths": [],
}, ensure_ascii=False))
PY
  )"
  [[ -n "$SNAP_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$SNAP_EVENT" 2>/dev/null || true

  if [[ -n "$RULES_SUMMARY" ]]; then
    RULES_EVENT="$(
      SESSION_ID_VALUE="$SESSION_ID" \
      ACTIVE_EPIC_ID_VALUE="$ACTIVE_EPIC_ID" \
      ACTIVE_STAGE_VALUE="$ACTIVE_STAGE" \
      python3 - <<'PY' 2>/dev/null
import json
import os
from datetime import datetime, timezone

print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "session_id": os.environ.get("SESSION_ID_VALUE", ""),
    "epic_id": os.environ["ACTIVE_EPIC_ID_VALUE"],
    "stage": os.environ["ACTIVE_STAGE_VALUE"],
    "source": "hook",
    "actor": "session-start",
    "event_type": "active_rules_loaded",
    "status": "ok",
    "summary": "Active rules loaded into session context",
    "payload": {"has_active_rules": True},
    "artifact_paths": [],
}, ensure_ascii=False))
PY
    )"
    [[ -n "$RULES_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$RULES_EVENT" 2>/dev/null || true
  fi

  EVENT="$(
    SESSION_ID_VALUE="$SESSION_ID" \
    ACTIVE_EPIC_ID_VALUE="$ACTIVE_EPIC_ID" \
    ACTIVE_STAGE_VALUE="$ACTIVE_STAGE" \
    RULES_SUMMARY_VALUE="$RULES_SUMMARY" \
    python3 - <<'PY' 2>/dev/null
import json
import os
from datetime import datetime, timezone

print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "session_id": os.environ.get("SESSION_ID_VALUE", ""),
    "epic_id": os.environ["ACTIVE_EPIC_ID_VALUE"],
    "stage": os.environ["ACTIVE_STAGE_VALUE"],
    "source": "hook",
    "actor": "session-start",
    "event_type": "session_started",
    "status": "ok",
    "summary": "Session started, harness context loaded",
    "payload": {"active_rules_loaded": bool(os.environ.get("RULES_SUMMARY_VALUE", ""))},
    "artifact_paths": [],
}, ensure_ascii=False))
PY
  )"
  [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
fi

CONTEXT_LINES_VALUE="$CONTEXT" \
RULES_SUMMARY_VALUE="$RULES_SUMMARY" \
ACTIVE_EPIC_ID_VALUE="$ACTIVE_EPIC_ID" \
python3 - <<'PY'
import json
import os

context_lines = os.environ.get("CONTEXT_LINES_VALUE", "")
rules = os.environ.get("RULES_SUMMARY_VALUE", "")
active_epic_id = os.environ.get("ACTIVE_EPIC_ID_VALUE", "")

context = "Stage-Harness 会话恢复:\n" + context_lines
if rules.strip():
    context += "\n" + rules + "\n"
context += "\n使用 /harness:status 查看详细进度。"
if active_epic_id:
    context += f"\n如遇流程问题，可运行 /harness:patch {active_epic_id} 进行即时诊断。"

print(json.dumps({"continue": True, "additionalContext": context}, ensure_ascii=False))
PY
