#!/usr/bin/env bash
# SessionStart hook: 检测并恢复 harness 上下文，注入激活规则
# 输入：stdin JSON（{"session_id": "...", ...}）
# 输出：JSON {"continue": true, "additionalContext": "..."}

HARNESS_DIR=".harness"
HARNESSCTL="${CLAUDE_PLUGIN_ROOT}/scripts/harnessctl"

if [[ ! -d "$HARNESS_DIR" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# 读取 session_id
SESSION_ID=$(cat 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('session_id',''))
except:
    print('')
" 2>/dev/null || true)

# 找到最近活跃的 epic
EPICS_DIR="$HARNESS_DIR/epics"
if [[ ! -d "$EPICS_DIR" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# 读取所有非 DONE 的 epic，构建上下文摘要
CONTEXT=""
ACTIVE_EPIC_ID=""
ACTIVE_STAGE=""

for epic_file in "$EPICS_DIR"/*.json; do
  [[ -f "$epic_file" ]] || continue

  epic_id=$(python3 -c "import json,sys; d=json.load(open('$epic_file')); print(d.get('id',''))" 2>/dev/null)
  [[ -n "$epic_id" ]] || continue

  state_file="$HARNESS_DIR/features/$epic_id/state.json"
  [[ -f "$state_file" ]] || continue

  info=$(python3 -c "
import json, sys
try:
    d = json.load(open('$state_file'))
    stage = d.get('current_stage','?')
    budget = d.get('interrupt_budget', {})
    remaining = budget.get('remaining', '?')
    health = d.get('runtime_health', {})
    drift = 'DRIFT DETECTED' if health.get('drift_detected') else 'OK'
    print(f'Epic: $epic_id | Stage: {stage} | Budget remaining: {remaining} | Health: {drift}')
    # capture for trace
    import os
    if stage not in ('DONE', 'CANCELLED'):
        print(f'__ACTIVE__:{stage}:{epic_id}', file=sys.stderr)
except Exception as e:
    print(f'Error reading state for $epic_id: {e}')
" 2>/tmp/sh_session_start_info.tmp)

  [[ -n "$info" ]] || continue
  CONTEXT="${CONTEXT}${info}\n"

  # Capture first active epic for trace
  if [[ -z "$ACTIVE_EPIC_ID" ]]; then
    _active=$(cat /tmp/sh_session_start_info.tmp 2>/dev/null | grep '^__ACTIVE__:' | head -1)
    if [[ -n "$_active" ]]; then
      ACTIVE_STAGE=$(echo "$_active" | cut -d: -f2)
      ACTIVE_EPIC_ID=$(echo "$_active" | cut -d: -f3)
    fi
  fi
done

if [[ -z "$CONTEXT" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# Build active rules summary for this session
RULES_SUMMARY=""
if [[ -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" ]]; then
  RULES_SUMMARY=$("$HARNESSCTL" patch list --scope all --json 2>/dev/null | python3 -c "
import json,sys
patches = json.load(sys.stdin)
active = [p for p in patches if p.get('status') in ('active_epic','project_active')]
if not active:
    sys.exit(0)
lines = ['[Stage-Harness 激活规则]']
for p in active:
    lines.append(f'  [{p.get(\"scope\",\"?\")}] {p.get(\"id\",\"?\")} — {p.get(\"kind\",\"rule\")}')
print('\n'.join(lines))
" 2>/dev/null || true)
fi

# Emit session_started trace event (for first active epic)
if [[ -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" ]]; then
  SNAP_EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'session_id': '${SESSION_ID}',
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'session-start',
  'event_type': 'active_epics_snapshot',
  'status': 'ok',
  'summary': 'Active epics snapshot captured',
  'payload': {'active_epics_count': ${#ACTIVE_EPICS[@]}},
  'artifact_paths': [],
}))
" 2>/dev/null)
  [[ -n "$SNAP_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$SNAP_EVENT" 2>/dev/null || true

  if [[ -n "$RULES_SUMMARY" ]]; then
    RULES_EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'session_id': '${SESSION_ID}',
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'session-start',
  'event_type': 'active_rules_loaded',
  'status': 'ok',
  'summary': 'Active rules loaded into session context',
  'payload': {'has_active_rules': True},
  'artifact_paths': [],
}))
" 2>/dev/null)
    [[ -n "$RULES_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$RULES_EVENT" 2>/dev/null || true
  fi

  EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'session_id': '${SESSION_ID}',
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'session-start',
  'event_type': 'session_started',
  'status': 'ok',
  'summary': 'Session started, harness context loaded',
  'payload': {'active_rules_loaded': bool('${RULES_SUMMARY}')},
  'artifact_paths': [],
}))
" 2>/dev/null)
  [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
fi

# 输出恢复上下文
python3 -c "
import json, sys

context_lines = '''$CONTEXT'''
rules = '''$RULES_SUMMARY'''
context = 'Stage-Harness 会话恢复:\n' + context_lines

if rules.strip():
    context += '\n' + rules + '\n'

context += '\n使用 /harness:status 查看详细进度。'
if '$ACTIVE_EPIC_ID':
    context += '\n如遇流程问题，可运行 /harness:patch $ACTIVE_EPIC_ID 进行即时诊断。'

print(json.dumps({'continue': True, 'additionalContext': context}))
"
exit 0
