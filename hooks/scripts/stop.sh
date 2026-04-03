#!/usr/bin/env bash
# Stop hook: 保存 handoff 文件，归档 transcript，写入 session_stopped trace
# 输入：stdin JSON（{"transcript_path": "...", "session_id": "...", ...}）
# 输出：JSON {"continue": true}

HARNESS_DIR=".harness"
HARNESSCTL="${CLAUDE_PLUGIN_ROOT}/scripts/harnessctl"

stage_to_command() {
  case "$1" in
    CLARIFY) echo "clarify" ;;
    SPEC) echo "spec" ;;
    PLAN) echo "plan" ;;
    EXECUTE) echo "work" ;;
    VERIFY) echo "review" ;;
    FIX) echo "fix" ;;
    DONE) echo "done" ;;
    *) echo "status" ;;
  esac
}

[[ -d "$HARNESS_DIR" ]] || { printf '{"continue": true}\n'; exit 0; }

EPICS_DIR="$HARNESS_DIR/epics"
[[ -d "$EPICS_DIR" ]] || { printf '{"continue": true}\n'; exit 0; }

# 读取 hook payload
PAYLOAD=$(cat)
TRANSCRIPT_PATH=$(echo "$PAYLOAD" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('transcript_path',''))
except:
    print('')
" 2>/dev/null || true)
SESSION_ID=$(echo "$PAYLOAD" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('session_id',''))
except:
    print('')
" 2>/dev/null || true)

# 为每个活跃 epic 写 handoff + trace
for epic_file in "$EPICS_DIR"/*.json; do
  [[ -f "$epic_file" ]] || continue

  epic_id=$(python3 -c "import json; d=json.load(open('$epic_file')); print(d.get('id',''))" 2>/dev/null)
  [[ -n "$epic_id" ]] || continue

  state_file="$HARNESS_DIR/features/$epic_id/state.json"
  [[ -f "$state_file" ]] || continue

  current_stage=$(python3 -c "
import json
try:
    d = json.load(open('$state_file'))
    print(d.get('current_stage', ''))
except:
    print('')
" 2>/dev/null)
  [[ "$current_stage" == "DONE" ]] && continue

  # 生成 handoff.md
  next_command=$(stage_to_command "$current_stage")
  python3 -c "
import json
from datetime import datetime, timezone

try:
    state = json.load(open('$state_file'))
    epic = json.load(open('$epic_file'))

    stage = state.get('current_stage', '?')
    budget = state.get('interrupt_budget', {})
    health = state.get('runtime_health', {})
    risk = state.get('risk_level', '?')
    title = epic.get('title', '$epic_id')
    cf = health.get('consecutive_failures', 0)

    hint = ''
    if cf >= 2:
        hint = f'\n⚠️  {cf} 次连续失败 — 考虑运行 /harness:patch $epic_id 诊断原因。'

    handoff = f'''# Handoff: {title}

**Saved**: {datetime.now(timezone.utc).isoformat()}
**Epic ID**: $epic_id
**Current Stage**: {stage}
**Risk Level**: {risk}

## Interrupt Budget
- Total: {budget.get('total', '?')}
- Consumed: {budget.get('consumed', '?')}
- Remaining: {budget.get('remaining', '?')}

## Runtime Health
- Consecutive Failures: {cf}
- Drift Detected: {health.get('drift_detected', False)}
{hint}
## Next Step
Resume with: /harness:auto $epic_id
Or check status: /harness:status
Or continue specific stage: /harness:$next_command $epic_id

## JIT Patch
If the run was interrupted due to issues, diagnose with:
  /harness:patch $epic_id
'''

    feature_dir = '.harness/features/$epic_id'
    import os
    os.makedirs(feature_dir, exist_ok=True)

    with open(f'{feature_dir}/handoff.md', 'w') as f:
        f.write(handoff)
except Exception as e:
    import sys
    print(f'Warning: Could not write handoff for $epic_id: {e}', file=sys.stderr)
" 2>/dev/null

  # Transcript archive (best-effort)
  ARCHIVE_STATUS="archive_skipped"
  ARCHIVE_REASON="no_transcript_path"
  TRANSCRIPT_DEST=""
  if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
    SESSION_LOG_DIR="$HARNESS_DIR/logs/sessions"
    mkdir -p "$SESSION_LOG_DIR"
    DEST_FILE="$SESSION_LOG_DIR/${SESSION_ID:-$(date +%s)}.transcript"
    if cp "$TRANSCRIPT_PATH" "$DEST_FILE" 2>/dev/null; then
      ARCHIVE_STATUS="transcript_archived"
      ARCHIVE_REASON=""
      TRANSCRIPT_DEST="$DEST_FILE"
    else
      ARCHIVE_STATUS="archive_skipped"
      ARCHIVE_REASON="copy_failed"
    fi
  elif [[ -n "$TRANSCRIPT_PATH" ]]; then
    ARCHIVE_STATUS="archive_skipped"
    ARCHIVE_REASON="transcript_path_not_readable"
  fi

  # Emit trace events
  if [[ -x "$HARNESSCTL" ]]; then
    # session_stopped
    EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'session_id': '${SESSION_ID}',
  'epic_id': '${epic_id}',
  'stage': '${current_stage}',
  'source': 'hook',
  'actor': 'stop',
  'event_type': 'session_stopped',
  'status': 'ok',
  'summary': 'Session stopped, handoff written',
  'payload': {'consecutive_failures': $(python3 -c "import json; d=json.load(open('$state_file')); print(d.get('runtime_health',{}).get('consecutive_failures',0))" 2>/dev/null || echo 0)},
  'artifact_paths': ['.harness/features/${epic_id}/handoff.md'],
}))
" 2>/dev/null)
    [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true

    HANDOFF_EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'session_id': '${SESSION_ID}',
  'epic_id': '${epic_id}',
  'stage': '${current_stage}',
  'source': 'hook',
  'actor': 'stop',
  'event_type': 'handoff_written',
  'status': 'ok',
  'summary': 'handoff.md written',
  'payload': {},
  'artifact_paths': ['.harness/features/${epic_id}/handoff.md'],
}))
" 2>/dev/null)
    [[ -n "$HANDOFF_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$HANDOFF_EVENT" 2>/dev/null || true

    # transcript archive event
    ARCH_EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'session_id': '${SESSION_ID}',
  'epic_id': '${epic_id}',
  'stage': '${current_stage}',
  'source': 'hook',
  'actor': 'stop',
  'event_type': '${ARCHIVE_STATUS}',
  'status': 'ok' if '${ARCHIVE_STATUS}' == 'transcript_archived' else 'warn',
  'summary': '${ARCHIVE_STATUS}' + (': ${ARCHIVE_REASON}' if '${ARCHIVE_REASON}' else ''),
  'payload': {'reason': '${ARCHIVE_REASON}', 'dest': '${TRANSCRIPT_DEST}'},
  'artifact_paths': ['${TRANSCRIPT_DEST}'] if '${TRANSCRIPT_DEST}' else [],
}))
" 2>/dev/null)
    [[ -n "$ARCH_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$ARCH_EVENT" 2>/dev/null || true
  fi
done

printf '{"continue": true}\n'
exit 0
