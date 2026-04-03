#!/usr/bin/env bash
# TeammateIdle hook: 阻止 teammate 在有待办任务时进入空闲
# 输入：stdin JSON（TeammateIdle 事件 payload）
# 输出：JSON {"continue": true/false, "stopReason": "..."}
# 退出码：0=允许空闲, 2=阻断空闲（还有任务未完成）
#
# 策略：读取活跃 epic 的任务列表，若有 pending/in_progress 任务则阻断空闲。
# 只在 EXECUTE / FIX 阶段触发。其他阶段直接放行。

HARNESS_DIR="${HARNESS_DIR:-.harness}"

[[ -d "$HARNESS_DIR" ]] && [[ -d "$HARNESS_DIR/epics" ]] || {
  printf '{"continue": true}\n'
  exit 0
}

# 查找处于 EXECUTE 或 FIX 阶段的活跃 epic
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

# 检查是否还有 pending 或 in_progress 的任务
TASKS_DIR="$HARNESS_DIR/tasks"
PENDING_TASKS=0
PENDING_LIST=""

if [[ -d "$TASKS_DIR" ]]; then
  PENDING_TASKS=$(python3 - <<PYEOF
import json, glob, os

tasks_dir = "$TASKS_DIR"
epic_id = "$ACTIVE_EPIC_ID"

pending = []
for task_file in glob.glob(f"{tasks_dir}/{epic_id}.*.json") + glob.glob(f"{tasks_dir}/{epic_id}/*.json"):
    try:
        t = json.load(open(task_file))
        status = t.get("status", "")
        if status in ("pending", "ready", "in_progress"):
            pending.append(f"  - [{status}] {t.get('id','?')}: {t.get('title', t.get('description',''))[:60]}")
    except Exception:
        pass

print(len(pending))
for line in pending[:5]:
    import sys
    print(line, file=sys.stderr)
PYEOF
  )
fi

if [[ "$PENDING_TASKS" -gt 0 ]]; then
  python3 -c "
import json
print(json.dumps({
    'continue': False,
    'stopReason': (
        f'TeammateIdle 被阻断：epic $ACTIVE_EPIC_ID 处于 $ACTIVE_STAGE 阶段，'
        f'仍有 $PENDING_TASKS 个任务未完成（pending/in_progress）。'
        '请继续执行待办任务，或运行：'
        'harnessctl task list $ACTIVE_EPIC_ID --status pending'
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
  'actor': 'teammate-idle',
  'event_type': 'teammate_idle_blocked',
  'status': 'blocked',
  'summary': f'TeammateIdle blocked: ${PENDING_TASKS} pending tasks',
  'payload': {'pending_count': int('${PENDING_TASKS}')},
  'artifact_paths': [],
}))
" 2>/dev/null)
    [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
  fi

  exit 2
fi

HARNESSCTL="${CLAUDE_PLUGIN_ROOT}/scripts/harnessctl"
if [[ -x "$HARNESSCTL" ]]; then
  EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'teammate-idle',
  'event_type': 'teammate_idle_passed',
  'status': 'ok',
  'summary': 'TeammateIdle passed: no pending tasks',
  'payload': {'pending_count': 0},
  'artifact_paths': [],
}))
" 2>/dev/null)
  [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
fi

printf '{"continue": true}\n'
exit 0
