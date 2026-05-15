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

  # E2E 阶段异常停机判定：current_stage=E2E 但缺少 e2e-receipt.json
  abnormal_stop="false"
  abnormal_reason=""
  if [[ "$current_stage" == "E2E" ]]; then
    receipt_file="$HARNESS_DIR/features/$epic_id/e2e-receipt.json"
    if [[ ! -f "$receipt_file" ]]; then
      abnormal_stop="true"
      abnormal_reason="E2E stage stopped without e2e-receipt.json"
      python3 -c "
import json
p = '$state_file'
try:
    d = json.load(open(p))
    rh = d.setdefault('runtime_health', {})
    rh['consecutive_failures'] = int(rh.get('consecutive_failures', 0)) + 1
    json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
except Exception as e:
    import sys; print(f'warn: bump consecutive_failures failed: {e}', file=sys.stderr)
" 2>/dev/null
    fi
  fi

  # 空参工具调用循环检测：本 session 中 empty_param_tool_call_blocked 事件 ≥ 3 次
  # 视为模型陷入空参循环。即便阶段产物存在也标记异常，提示用户介入。
  if [[ "$abnormal_stop" != "true" && -n "$SESSION_ID" ]]; then
    trace_file="$HARNESS_DIR/logs/epics/$epic_id/execution-trace.jsonl"
    if [[ -f "$trace_file" ]]; then
      empty_param_count=$(SESSION_ID="$SESSION_ID" TRACE_FILE="$trace_file" python3 -c "
import json
import os
count = 0
sid = os.environ['SESSION_ID']
try:
    with open(os.environ['TRACE_FILE']) as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get('session_id') == sid and ev.get('event_type') == 'empty_param_tool_call_blocked':
                count += 1
except Exception:
    pass
print(count)
" 2>/dev/null || echo 0)
      if [[ "$empty_param_count" -ge 3 ]]; then
        abnormal_stop="true"
        abnormal_reason="Session looped on empty-parameter tool calls (count=$empty_param_count)"
        python3 -c "
import json
p = '$state_file'
try:
    d = json.load(open(p))
    rh = d.setdefault('runtime_health', {})
    rh['consecutive_failures'] = int(rh.get('consecutive_failures', 0)) + 1
    json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
except Exception as e:
    import sys; print(f'warn: bump consecutive_failures failed: {e}', file=sys.stderr)
" 2>/dev/null
      fi
    fi
  fi

  # 生成 handoff.md
  next_command=$(stage_to_command "$current_stage")
  ABNORMAL_STOP="$abnormal_stop" ABNORMAL_REASON="$abnormal_reason" python3 -c "
import json
import os
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

    abnormal = os.environ.get('ABNORMAL_STOP') == 'true'
    abnormal_reason = os.environ.get('ABNORMAL_REASON', '')

    abnormal_block = ''
    if abnormal:
        abnormal_block = f'''> ⚠️ **异常停机**：{abnormal_reason}
> 推荐立即执行：/stage-harness:harness-patch $epic_id

'''

    hint = ''
    if cf >= 2:
        hint = f'\n⚠️  {cf} 次连续失败 — 考虑运行 /harness:patch $epic_id 诊断原因。'

    handoff = f'''# Handoff: {title}

{abnormal_block}**Saved**: {datetime.now(timezone.utc).isoformat()}
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
    # session_stopped (or stage_abnormal_stop)
    EVENT=$(ABNORMAL_STOP="$abnormal_stop" ABNORMAL_REASON="$abnormal_reason" python3 -c "
import json
import os
abnormal = os.environ.get('ABNORMAL_STOP') == 'true'
abnormal_reason = os.environ.get('ABNORMAL_REASON', '')
cf = 0
try:
    cf = json.load(open('$state_file')).get('runtime_health', {}).get('consecutive_failures', 0)
except:
    pass
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'session_id': '${SESSION_ID}',
  'epic_id': '${epic_id}',
  'stage': '${current_stage}',
  'source': 'hook',
  'actor': 'stop',
  'event_type': 'stage_abnormal_stop' if abnormal else 'session_stopped',
  'status': 'warn' if abnormal else 'ok',
  'summary': abnormal_reason if abnormal else 'Session stopped, handoff written',
  'payload': {'consecutive_failures': cf, 'abnormal': abnormal, 'reason': abnormal_reason} if abnormal else {'consecutive_failures': cf},
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
