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
  # Bash 工具被调用但 command 字段缺失或为空字符串。这通常是模型在长上下文下
  # 生成了空参数 tool_use payload。直接放行会让 runtime 抛 InputValidationError
  # 浪费 turn；这里返回 stopReason 让模型立刻自检并重发带 command 的调用。
  STOP_REASON="Bash 工具调用缺少必填参数 command。请重新发起 Bash 工具调用，并在 input 对象中显式提供 {\"command\": \"<要执行的 shell 命令>\", \"description\": \"<简述>\"}。如本次只是想思考下一步而不需要执行命令，请不要发起工具调用，直接输出文本。" \
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
    ACTIVE_EPIC_ID_FOR_EVENT=""
    HARNESS_DIR_FOR_EVENT=".harness"
    if [[ -d "$HARNESS_DIR_FOR_EVENT/epics" ]]; then
      for epic_file in "$HARNESS_DIR_FOR_EVENT/epics/"*.json; do
        [[ -f "$epic_file" ]] || continue
        candidate_id="$(
          EPIC_FILE="$epic_file" python3 - <<'PY' 2>/dev/null || true
import json
import os
try:
    with open(os.environ["EPIC_FILE"], encoding="utf-8") as fh:
        print(json.load(fh).get("id", ""))
except Exception:
    print("")
PY
        )"
        [[ -n "$candidate_id" ]] || continue
        is_safe_epic_id "$candidate_id" || continue
        candidate_stage="$(
          STATE_FILE=".harness/features/$candidate_id/state.json" python3 - <<'PY' 2>/dev/null || true
import json
import os
try:
    with open(os.environ["STATE_FILE"], encoding="utf-8") as fh:
        print(json.load(fh).get("current_stage", ""))
except Exception:
    print("")
PY
        )"
        if [[ "$candidate_stage" != "DONE" && "$candidate_stage" != "CANCELLED" && -n "$candidate_stage" ]]; then
          ACTIVE_EPIC_ID_FOR_EVENT="$candidate_id"
          break
        fi
      done
    fi

    EVENT="$(ACTIVE_EPIC_ID_VALUE="$ACTIVE_EPIC_ID_FOR_EVENT" python3 - <<'PY' 2>/dev/null
import json
import os
from datetime import datetime, timezone

print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "epic_id": os.environ.get("ACTIVE_EPIC_ID_VALUE", ""),
    "source": "hook",
    "actor": "pre-tool-use",
    "event_type": "empty_param_tool_call_blocked",
    "status": "blocked",
    "tool_name": "Bash",
    "summary": "Bash invoked with empty/missing command parameter; instructed model to retry",
    "payload": {"missing_param": "command"},
    "artifact_paths": [],
}, ensure_ascii=False))
PY
    )"
    [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
  fi
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

# Guard: block Bash commands that write to managed harness artifacts.
# Policy: protected path hit + non-trusted command source => blocked.
BASH_WRITES_PROTECTED="$(
  COMMAND_VALUE="$COMMAND" python3 - <<'PY' 2>/dev/null || true
import os
import posixpath
import re
import shlex

cmd = os.environ.get("COMMAND_VALUE", "")
cwd = os.getcwd().replace("\\", "/")

protected = [
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/epics/[^\"'\s;|&]+\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/features/[^/]+/state\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/tasks/[^\"'\s;|&]+\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/features/[^/]+/feedback/HFB-[^\"'\s;|&]+\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/features/[^/]+/artifact-status\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/features/[^/]+/coverage-matrix\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/features/[^/]+/(?:receipts|runtime-receipts|runs)/[^\"'\s;|&]+\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/features/[^/]+/councils/.*/(?:verdict|metadata)\.json",
    r"(?:^|[\"'\s/>])(?:\./)?\.harness/features/[^/]+/councils/.*/votes/[^\"'\s;|&]+\.json",
    r"feedback/HFB-[^\"'\s;|&]*\.evidence-pack\.json",
    r"councils/feedback_triage_council/[^/]+/votes/[^\"'\s;|&]+\.json",
    r"councils/feedback_triage_council/[^/]+/verdict\.json",
    r"councils/feedback_triage_council/[^/]+/metadata\.json",
    r"feedback/HFB-[^\"'\s;|&]*\.triage\.json",
]

write_ops = [
    r"(?<![12])>\s*\S", r">>\s*\S", r"\btee\s+\S", r"\bcp\s+\S", r"\bmv\s+\S",
    r"\brm\s+(?:-[A-Za-z]+\s+)*\S",
    r"\bsed\s+[^;&|]*\s-i(?:\s|$)", r"\bperl\s+[^;&|]*\s-i(?:\s|$)",
    r"open\s*\([^)]*['\"]w['\"]", r"write_text\s*\(", r"json\.dump\s*\(",
    r"atomic_write", r"atomic_write_json", r"\becho\b.*>", r"\bprintf\b.*>", r"\bcat\b.*>",
]

trusted_basenames = {"harnessctl", "harnessctl.py"}
logical_cwd = posixpath.normpath(cwd)
protected_cwd = bool(re.search(r"(?:^|/)\.harness(?:/|$)", cwd))

protected_shell_write = re.compile(
    r"(?:>>?|tee(?:\s+-[A-Za-z]+\b)*|cp|mv|rm)\s*[^;&|]*['\"]?(?:[^'\"\s;&|]*/)?\.harness(?:/|$)"
)

for segment in re.split(r"(?:&&|\|\||;|(?<!\|)\|(?!\|))", cmd):
    segment = segment.strip()
    if not segment:
        continue
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    if tokens:
        idx = 0
        while idx < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", tokens[idx]):
            idx += 1
        if idx < len(tokens) and tokens[idx] == "cd" and idx + 1 < len(tokens):
            target = tokens[idx + 1].replace("\\", "/")
            if target == "-":
                protected_cwd = False
                logical_cwd = cwd
            elif target.startswith("/"):
                logical_cwd = posixpath.normpath(target)
            else:
                logical_cwd = posixpath.normpath(posixpath.join(logical_cwd, target))
            protected_cwd = bool(re.search(r"(?:^|/)\.harness(?:/|$)", logical_cwd))
            continue
    has_protected = any(re.search(p, segment) for p in protected)
    has_write = any(re.search(w, segment) for w in write_ops)
    if protected_cwd and has_write:
        print("BLOCKED")
        raise SystemExit(0)
    if not (has_protected and has_write):
        continue
    if not tokens:
        print("BLOCKED")
        raise SystemExit(0)
    idx = 0
    while idx < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", tokens[idx]):
        idx += 1
    if idx >= len(tokens):
        print("BLOCKED")
        raise SystemExit(0)
    executable = tokens[idx].split("/")[-1]
    trusted = False
    if executable in trusted_basenames:
        trusted = True
    elif executable in {"python", "python3"} and idx + 1 < len(tokens):
        script_name = tokens[idx + 1].split("/")[-1]
        if script_name == "harnessctl.py":
            trusted = True

    if trusted and ("$(" in segment or "`" in segment):
        print("BLOCKED")
        raise SystemExit(0)
    if trusted and protected_shell_write.search(segment):
        print("BLOCKED")
        raise SystemExit(0)
    if not trusted:
        print("BLOCKED")
        raise SystemExit(0)

print("OK")
PY
)"

if [[ "$BASH_WRITES_PROTECTED" == "BLOCKED" ]]; then
  STOP_REASON="禁止通过非受信 Bash 写入 .harness 受控产物（状态机、task、feedback、结构化证据或 receipt）。必须使用 harnessctl 标准命令或受信 runtime adapter。" \
    python3 - <<'PY'
import json
import os

print(json.dumps({
    "continue": False,
    "stopReason": os.environ["STOP_REASON"],
}, ensure_ascii=False))
PY
  exit 0
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

# ---------------------------------------------------------------------------
# Feedback Gate Guard (P1): block investigation commands when HFB is unresolved
# Only blocks: grep -R / rg / find / ack / ag
# Does NOT block: ls, harnessctl feedback commands, evidence-pack/source-probe internals
# ---------------------------------------------------------------------------

# Check if command looks like a search/investigation command
IS_INVESTIGATION_CMD=false
if echo "$NORMALIZED_COMMAND" | grep -qiE '(^|[[:space:]])(grep[[:space:]]+-[rR]|grep[[:space:]]+--recursive|rg[[:space:]]|find[[:space:]]|ack[[:space:]]|ag[[:space:]])'; then
  IS_INVESTIGATION_CMD=true
fi

if [[ "$IS_INVESTIGATION_CMD" == "true" ]]; then
  # Check if this is a feedback-allowlisted internal call
  # (evidence-pack, source-probe, related-gap-scan invoke grep/find internally)
  IS_FEEDBACK_INTERNAL=false
  if echo "$NORMALIZED_COMMAND" | grep -qiE 'harnessctl[[:space:]]+feedback|evidence.pack|source.probe|related.gap.scan|council.triage'; then
    IS_FEEDBACK_INTERNAL=true
  fi

  if [[ "$IS_FEEDBACK_INTERNAL" == "false" ]]; then
    # Determine active epic and check gate
    GATE_EPIC_ID=""
    if [[ "${#ACTIVE_EPIC_IDS[@]}" -eq 1 ]]; then
      GATE_EPIC_ID="${ACTIVE_EPIC_IDS[0]}"
    fi

    if [[ -n "$GATE_EPIC_ID" && -x "${HARNESSCTL:-}" ]]; then
      GATE_RESULT=$("$HARNESSCTL" feedback gate-check --epic-id "$GATE_EPIC_ID" --json 2>/dev/null || true)
      GATE_STATUS=$(echo "$GATE_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)

      if [[ "$GATE_STATUS" == "blocked" ]]; then
        BLOCKED_INFO=$(echo "$GATE_RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data.get('blocked_items', [])
if items:
    item = items[0]
    print(f\"{item.get('feedback_id','?')}: {item.get('reason','?')} → next: {item.get('next_action','?')}\")
" 2>/dev/null || true)

        # Trace the block event
        if [[ -n "$GATE_EPIC_ID" ]]; then
          EVENT="$(
            ACTIVE_EPIC_ID_VALUE="$GATE_EPIC_ID" COMMAND_VALUE="$COMMAND" BLOCKED_INFO_VALUE="${BLOCKED_INFO:-unknown}" python3 - <<'PY' 2>/dev/null || true
import hashlib
import json
import os
from datetime import datetime, timezone

cmd_hash = hashlib.sha256(os.environ["COMMAND_VALUE"].encode("utf-8")).hexdigest()[:12]
print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "epic_id": os.environ["ACTIVE_EPIC_ID_VALUE"],
    "source": "hook",
    "actor": "pre-tool-use-feedback-guard",
    "event_type": "investigation_blocked_by_feedback_gate",
    "status": "blocked",
    "tool_name": "Bash",
    "summary": f"Investigation command blocked: unresolved feedback ({os.environ['BLOCKED_INFO_VALUE']})",
    "payload": {
        "command_hash": cmd_hash,
        "blocked_info": os.environ["BLOCKED_INFO_VALUE"],
    },
    "artifact_paths": [],
}, ensure_ascii=False))
PY
          )"
          [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
        fi

        printf '{"continue": false, "reason": "⚠️ [Feedback Gate Guard] 存在未处理的 feedback (%s)，禁止执行调查命令。请先完成 feedback triage 流程。"}\n' "$BLOCKED_INFO"
        exit 0
      fi
    fi
  fi
fi

printf '{"continue": true}\n'
