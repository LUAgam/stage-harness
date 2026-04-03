#!/usr/bin/env bash
# TaskCompleted hook: 验证任务完成前的质量门禁
# 输入：stdin JSON（TaskCompleted 事件 payload）
# 输出：JSON {"continue": true/false, "stopReason": "..."}
# 退出码：0=允许, 2=阻断（要求修正后重试）
#
# 策略：只在 EXECUTE / FIX 阶段的任务完成时执行阻断检查。
# 其他阶段的任务（如 council 子任务）直接放行。

HARNESS_DIR="${HARNESS_DIR:-.harness}"
INPUT=$(cat)

[[ -d "$HARNESS_DIR" ]] && [[ -d "$HARNESS_DIR/epics" ]] || {
  printf '{"continue": true}\n'
  exit 0
}

# 查找活跃 epic（当前非 DONE 且非 IDEA 阶段）
ACTIVE_EPIC_ID=""
ACTIVE_STAGE=""

for epic_file in "$HARNESS_DIR/epics"/*.json; do
  [[ -f "$epic_file" ]] || continue

  epic_id=$(python3 -c "import json; d=json.load(open('$epic_file')); print(d.get('id',''))" 2>/dev/null)
  [[ -n "$epic_id" ]] || continue

  state_file="$HARNESS_DIR/features/$epic_id/state.json"
  [[ -f "$state_file" ]] || continue

  stage=$(python3 -c "
import json
try:
    d = json.load(open('$state_file'))
    print(d.get('current_stage', ''))
except:
    print('')
" 2>/dev/null)

  if [[ "$stage" == "EXECUTE" || "$stage" == "FIX" ]]; then
    ACTIVE_EPIC_ID="$epic_id"
    ACTIVE_STAGE="$stage"
    break
  fi
done

# 没有处于 EXECUTE/FIX 的 epic，直接放行
if [[ -z "$ACTIVE_EPIC_ID" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# 提取当前完成的 task_id（兼容几种常见事件字段）
TASK_ID=$(printf '%s' "$INPUT" | python3 - <<'PYEOF'
import json, sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)

candidates = [
    data.get("task_id"),
    data.get("taskId"),
    data.get("id"),
]

task = data.get("task") if isinstance(data.get("task"), dict) else {}
candidates.extend([
    task.get("id"),
    task.get("task_id"),
    task.get("taskId"),
])

for value in candidates:
    if isinstance(value, str) and value.strip():
        print(value.strip())
        break
else:
    print("")
PYEOF
)

# 在 EXECUTE/FIX 阶段：要求当前任务必须有对应的 receipt 文件
RECEIPTS_DIR="$HARNESS_DIR/features/$ACTIVE_EPIC_ID/receipts"
RUNTIME_RECEIPTS_DIR="$HARNESS_DIR/features/$ACTIVE_EPIC_ID/runtime-receipts"
TASK_RECEIPT_FOUND=0

if [[ -n "$TASK_ID" ]]; then
  [[ -f "$RECEIPTS_DIR/$TASK_ID.json" ]] && TASK_RECEIPT_FOUND=1
  [[ -f "$RUNTIME_RECEIPTS_DIR/$TASK_ID.json" ]] && TASK_RECEIPT_FOUND=1
fi

if [[ -n "$TASK_ID" && "$TASK_RECEIPT_FOUND" -eq 0 ]]; then
  python3 -c "
import json
print(json.dumps({
    'continue': False,
    'stopReason': (
        'TaskCompleted 被阻断：当前 epic 处于 $ACTIVE_STAGE 阶段，'
        '但当前任务 $TASK_ID 没有对应的 receipt 文件。'
        '请确保任务执行完成后写入 receipt：'
        'harnessctl receipt write <task-id> --base-commit <sha> --head-commit <sha> --smoke-passed true'
    )
}))
"

  # Emit trace event
  HARNESSCTL="${CLAUDE_PLUGIN_ROOT}/scripts/harnessctl"
  if [[ -x "$HARNESSCTL" ]]; then
    EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'task-completed',
  'event_type': 'task_completed_hook_blocked',
  'status': 'blocked',
  'task_id': '${TASK_ID}',
  'summary': f'TaskCompleted blocked: no receipt for ${TASK_ID}',
  'payload': {'task_id': '${TASK_ID}'},
  'artifact_paths': [],
}))
" 2>/dev/null)
    [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
  fi

  exit 2
fi

# Emit pass trace
HARNESSCTL="${CLAUDE_PLUGIN_ROOT}/scripts/harnessctl"
if [[ -n "$TASK_ID" && -x "$HARNESSCTL" ]]; then
  EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'task-completed',
  'event_type': 'task_completed_hook_passed',
  'status': 'ok',
  'task_id': '${TASK_ID}',
  'summary': f'TaskCompleted passed for ${TASK_ID}',
  'payload': {'task_id': '${TASK_ID}'},
  'artifact_paths': [],
}))
" 2>/dev/null)
  "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
fi

printf '{"continue": true}\n'
exit 0
