#!/usr/bin/env bash
# PreToolUse hook: 拦截危险的 Bash 命令
# 输入：stdin JSON（{"tool_name": "Bash", "tool_input": {"command": "..."}, ...}）
# 输出：JSON {"continue": true/false, ...}

INPUT=$(cat)

# 只处理 Bash 工具调用
TOOL_NAME=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)
if [[ "$TOOL_NAME" != "Bash" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# 提取命令内容
COMMAND=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

if [[ -z "$COMMAND" ]]; then
  printf '{"continue": true}\n'
  exit 0
fi

# 检查危险操作模式
# 使用关联数组存储模式和说明
declare -A DANGEROUS_PATTERNS
DANGEROUS_PATTERNS["git reset --hard"]="git reset --hard 会丢失未提交的更改"
DANGEROUS_PATTERNS["rm -rf /"]="rm -rf / 会删除根目录所有文件"
DANGEROUS_PATTERNS["git push --force"]="git push --force 会强制覆盖远程历史"
DANGEROUS_PATTERNS["git push -f "]="git push -f 会强制覆盖远程历史"
DANGEROUS_PATTERNS["drop table"]="DROP TABLE 会永久删除数据库表"
DANGEROUS_PATTERNS["DROP TABLE"]="DROP TABLE 会永久删除数据库表"
DANGEROUS_PATTERNS["truncate table"]="TRUNCATE TABLE 会清空数据库表所有数据"
DANGEROUS_PATTERNS["TRUNCATE TABLE"]="TRUNCATE TABLE 会清空数据库表所有数据"
DANGEROUS_PATTERNS["rm -rf .harness"]="rm -rf .harness 会删除 stage-harness 所有状态数据"

for pattern in "${!DANGEROUS_PATTERNS[@]}"; do
  description="${DANGEROUS_PATTERNS[$pattern]}"
  if echo "$COMMAND" | grep -qi "$pattern" 2>/dev/null; then
    python3 -c "
import json
print(json.dumps({
    'continue': False,
    'stopReason': '检测到潜在危险操作：$description。如确认需要执行，请直接在终端运行，或在消息中明确说明意图后重试。'
}))
"
    # Emit trace event (best-effort)
    HARNESSCTL="${CLAUDE_PLUGIN_ROOT}/scripts/harnessctl"
    if [[ -x "$HARNESSCTL" ]]; then
      ACTIVE_EPIC_ID=""
      HARNESS_DIR=".harness"
      if [[ -d "$HARNESS_DIR/epics" ]]; then
        for ef in "$HARNESS_DIR/epics/"*.json; do
          [[ -f "$ef" ]] || continue
          _eid=$(python3 -c "import json; d=json.load(open('$ef')); print(d.get('id',''))" 2>/dev/null)
          [[ -z "$_eid" ]] && continue
          _st=$(python3 -c "import json; d=json.load(open('.harness/features/$_eid/state.json')); print(d.get('current_stage',''))" 2>/dev/null)
          if [[ "$_st" != "DONE" && "$_st" != "CANCELLED" && -n "$_st" ]]; then
            ACTIVE_EPIC_ID="$_eid"
            break
          fi
        done
      fi
      if [[ -n "$ACTIVE_EPIC_ID" ]]; then
        EVENT=$(python3 -c "
import json, hashlib
cmd_hash = hashlib.sha256('$COMMAND'.encode()).hexdigest()[:12]
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'epic_id': '${ACTIVE_EPIC_ID}',
  'source': 'hook',
  'actor': 'pre-tool-use',
  'event_type': 'dangerous_bash_blocked',
  'status': 'blocked',
  'tool_name': 'Bash',
  'summary': 'Dangerous bash blocked: $description',
  'payload': {'pattern': '$pattern', 'command_hash': cmd_hash},
  'artifact_paths': [],
}))
" 2>/dev/null)
        [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
      fi
    fi
    exit 0
  fi
done

printf '{"continue": true}\n'
exit 0
