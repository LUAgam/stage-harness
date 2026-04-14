#!/usr/bin/env bash
# stage-reminder.sh — UserPromptSubmit hook
# 在每次用户提交 prompt 时注入当前阶段信息、激活规则，并记录 correction_candidate 线索
# 输出到 stdout 的内容会被 Claude Code 作为系统注入上下文使用

set -euo pipefail
shopt -s nullglob

HARNESSCTL="${CLAUDE_PLUGIN_ROOT:-}/scripts/harnessctl"

# 读取输入
INPUT=$(cat 2>/dev/null || true)

# 查找 .harness/ 目录
find_harness_dir() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.harness" ]]; then
      echo "$dir/.harness"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

HARNESS_DIR=$(find_harness_dir 2>/dev/null || true)
[[ -z "$HARNESS_DIR" ]] && exit 0

ACTIVE_EPICS=()
STAGES=()
TASKS_INFO=()

if [[ -d "$HARNESS_DIR/epics" ]]; then
  for epic_file in "$HARNESS_DIR/epics/"*.json; do
    [[ -f "$epic_file" ]] || continue

    epic_id=$(python3 -c "
import json
d = json.load(open('$epic_file'))
print(d.get('id', ''))
" 2>/dev/null || true)

    [[ -z "$epic_id" ]] && continue

    state_file="$HARNESS_DIR/features/$epic_id/state.json"
    [[ -f "$state_file" ]] || continue

    stage=$(python3 -c "
import json, sys
try:
    d = json.load(open('$state_file'))
    s = d.get('current_stage', '')
    if s not in ['DONE', 'CANCELLED']:
        print(s)
except:
    pass
" 2>/dev/null || true)

    [[ -z "$stage" ]] && continue

    title=$(python3 -c "
import json
d = json.load(open('$epic_file'))
print(d.get('title', 'unknown'))
" 2>/dev/null || true)

    tasks_total=0
    tasks_done=0
    if [[ -d "$HARNESS_DIR/tasks" ]]; then
      tasks_total=$(ls "$HARNESS_DIR/tasks/${epic_id}".*.json 2>/dev/null | wc -l | tr -d ' ')
      tasks_done=$(python3 - <<PYEOF
import glob, json
count = 0
for task_file in glob.glob("$HARNESS_DIR/tasks/${epic_id}.*.json"):
    try:
        task = json.load(open(task_file))
        if task.get("status", "") in ("done", "completed"):
            count += 1
    except Exception:
        pass
print(count)
PYEOF
      )
    fi

    ACTIVE_EPICS+=("$epic_id")
    STAGES+=("$stage")
    TASKS_INFO+=("${tasks_done}/${tasks_total}")
  done
fi

[[ ${#ACTIVE_EPICS[@]} -eq 0 ]] && exit 0

# 提取 prompt 文本
PROMPT_TEXT=""
if [[ -n "$INPUT" ]]; then
  PROMPT_TEXT=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', ''))
except:
    print(sys.stdin.read())
" 2>/dev/null || echo "$INPUT")
fi

# `/harness:start` / `/stage-harness:harness-start` 需要独立完成 bootstrap，
# 避免把现有 active epic 的阶段提醒注入进去，导致模型误判为应继续推进。
if [[ "$PROMPT_TEXT" =~ ^[[:space:]]*/(harness:start|stage-harness:harness-start)([[:space:]]|$) ]]; then
  exit 0
fi

REMINDER="[Stage-Harness 阶段提醒]\n"

for i in "${!ACTIVE_EPICS[@]}"; do
  epic_id="${ACTIVE_EPICS[$i]}"
  stage="${STAGES[$i]}"
  tasks="${TASKS_INFO[$i]}"
  REMINDER+="  Epic: $epic_id | 阶段: $stage | 任务: $tasks\n"
done

# 跨阶段操作警告
IS_CROSS_STAGE=false
if echo "$PROMPT_TEXT" | grep -qiE "直接实现|跳过(规格|计划|澄清)|skip (spec|plan|clarify)|implement without|just code it"; then
  IS_CROSS_STAGE=true
  REMINDER+="\n  ⚠️  检测到跨阶段操作请求。当前流程要求按阶段推进："
  REMINDER+="\n     CLARIFY → SPEC → PLAN → EXECUTE → VERIFY → FIX → DONE"
  REMINDER+="\n     如需跳过阶段，请使用 /harness:auto（仅低/中风险）。"
fi

# 注入 stage-scoped 激活规则（如有）
ACTIVE_EPIC_ID="${ACTIVE_EPICS[0]}"
ACTIVE_STAGE="${STAGES[0]}"
RULES_TEXT=""
if [[ -x "$HARNESSCTL" ]]; then
  RULES_TEXT=$("$HARNESSCTL" patch list --scope all --json 2>/dev/null | python3 -c "
import json,sys
stage = '${ACTIVE_STAGE}'
patches = json.load(sys.stdin)
active = [p for p in patches if p.get('status') in ('active_epic','project_active')
          and (not p.get('stages') or stage in p.get('stages',[]))]
if not active:
    sys.exit(0)
lines = []
for p in active:
    patch_path = '.harness/rules/epic-local/${ACTIVE_EPIC_ID}/' + p['id'] + '.md'
    import os
    if not os.path.exists(patch_path):
        patch_path = '.harness/rules/project-active/' + p['id'] + '.md'
    try:
        content = open(patch_path).read().strip()
        # Extract first heading/content after frontmatter
        file_lines = content.splitlines()
        in_fm = False
        first = ''
        for i, line in enumerate(file_lines):
            stripped = line.strip()
            if i == 0 and stripped == '---':
                in_fm = True
                continue
            if in_fm and stripped == '---':
                in_fm = False
                continue
            if in_fm:
                continue
            if stripped.startswith('#'):
                first = stripped.lstrip('#').strip()
                break
            if stripped:
                first = stripped
                break
        lines.append(f'  [{p[\"scope\"]}] {first}')
    except:
        lines.append(f'  [{p.get(\"scope\",\"?\")}] {p.get(\"id\",\"?\")}')
if lines:
    print('[激活规则约束]')
    print('\n'.join(lines))
" 2>/dev/null || true)
fi

if [[ -n "$RULES_TEXT" ]]; then
  REMINDER+="\n${RULES_TEXT}\n"
fi

# 记录 prompt_submitted / cross_stage_request_suspected
if [[ -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" ]]; then
  PROMPT_EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'stage-reminder',
  'event_type': 'prompt_submitted',
  'status': 'ok',
  'summary': 'User prompt submitted',
  'payload': {'prompt_excerpt_present': bool('''$PROMPT_TEXT'''.strip())},
  'artifact_paths': [],
}))
" 2>/dev/null)
  [[ -n "$PROMPT_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$PROMPT_EVENT" 2>/dev/null || true

  if [[ "$IS_CROSS_STAGE" == "true" ]]; then
    XSTAGE_EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'stage-reminder',
  'event_type': 'cross_stage_request_suspected',
  'status': 'warn',
  'summary': 'User prompt may be attempting to bypass stage flow',
  'payload': {},
  'artifact_paths': [],
}))
" 2>/dev/null)
    [[ -n "$XSTAGE_EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$XSTAGE_EVENT" 2>/dev/null || true
  fi
fi

# 记录 correction_candidate（疑似人工纠偏）
IS_CORRECTION=false
if echo "$PROMPT_TEXT" | grep -qiE "不对|不行|重来|重新|修正|错了|你漏了|你忘了|再来一次|redo|wrong|incorrect|fix this|you missed|retry"; then
  IS_CORRECTION=true
fi

if [[ "$IS_CORRECTION" == "true" && -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" ]]; then
  EXCERPT=""
  if [[ -n "$PROMPT_TEXT" ]]; then
    EXCERPT=$(echo "$PROMPT_TEXT" | head -c 200)
  fi
  EVENT=$(python3 -c "
import json
print(json.dumps({
  'ts': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
  'epic_id': '${ACTIVE_EPIC_ID}',
  'stage': '${ACTIVE_STAGE}',
  'source': 'hook',
  'actor': 'stage-reminder',
  'event_type': 'correction_candidate',
  'status': 'warn',
  'summary': 'User prompt suggests manual correction (unverified)',
  'payload': {'prompt_excerpt': '''$EXCERPT'''},
  'artifact_paths': [],
}))
" 2>/dev/null)
  [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true
fi

python3 -c "
import json, sys
reminder = '''$REMINDER'''
output = {
    'additionalContext': reminder.replace('\\\\n', '\n')
}
print(json.dumps(output))
"

exit 0
