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

# 记录 feedback_candidate — 范围质疑类
IS_SCOPE_GAP=false
if echo "$PROMPT_TEXT" | grep -qiE "(模块|页面|接口|前端|后端|测试|文档|权限|配置|组件|仓库).*(不需要|不考虑|是否也要|是不是漏)"; then
  IS_SCOPE_GAP=true
elif echo "$PROMPT_TEXT" | grep -qiE "不需要(改|调整|处理|适配|支持)吗"; then
  IS_SCOPE_GAP=true
elif echo "$PROMPT_TEXT" | grep -qiE "是不是漏了.*(模块|页面|接口|组件|仓库)"; then
  IS_SCOPE_GAP=true
elif echo "$PROMPT_TEXT" | grep -qiE "是否需要调整|需不需要改|有没有遗漏"; then
  IS_SCOPE_GAP=true
elif echo "$PROMPT_TEXT" | grep -qiE "是否也要适配|不用处理吗|是不是还差"; then
  IS_SCOPE_GAP=true
elif echo "$PROMPT_TEXT" | grep -qiE "还有.*没覆盖|是否.*也要(改|调整|适配|处理)"; then
  IS_SCOPE_GAP=true
fi

# 提取 mentioned_surface（scope_gap_question 时从文本中提取命名对象）
MENTIONED_SURFACE=""
if [[ "$IS_SCOPE_GAP" == "true" ]]; then
  MENTIONED_SURFACE=$(echo "$PROMPT_TEXT" | python3 -c "
import sys, re
text = sys.stdin.read().strip()
# Extract named objects: look for identifiers before question patterns
patterns = [
    r'([\w\-]+)\s*(?:是否需要|需不需要|不需要|不用|有没有)',
    r'(?:是否也要|是不是漏了?)\s*([\w\-]+)',
    r'([\w\-]+)\s*(?:也要适配|不用处理|还差)',
]
for p in patterns:
    m = re.search(p, text)
    if m:
        surface = m.group(1)
        # Filter out common non-surface words
        if surface not in ('这个', '那个', '这些', '那些', '什么', '哪些', '是否', '是不是'):
            print(surface)
            break
" 2>/dev/null || true)
fi

# 记录 feedback_candidate — 需求变更类
IS_SCOPE_CHANGE=false
if echo "$PROMPT_TEXT" | grep -qiE "还要加|新增.*需求|追加.*功能|范围.*变|改需求"; then
  IS_SCOPE_CHANGE=true
fi

# 确定 feedback candidate 类型
FEEDBACK_CANDIDATE_TYPE=""
if [[ "$IS_CORRECTION" == "true" ]]; then
  FEEDBACK_CANDIDATE_TYPE="correction"
elif [[ "$IS_SCOPE_GAP" == "true" ]]; then
  FEEDBACK_CANDIDATE_TYPE="scope_gap_question"
elif [[ "$IS_SCOPE_CHANGE" == "true" ]]; then
  FEEDBACK_CANDIDATE_TYPE="scope_change"
fi

if [[ -n "$FEEDBACK_CANDIDATE_TYPE" && -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" ]]; then
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
  'event_type': 'feedback_candidate',
  'status': 'warn',
  'summary': 'User prompt suggests feedback (unverified)',
  'payload': {'candidate_type': '${FEEDBACK_CANDIDATE_TYPE}', 'prompt_excerpt': '''$EXCERPT'''},
  'artifact_paths': [],
}))
" 2>/dev/null)
  [[ -n "$EVENT" ]] && "$HARNESSCTL" patch trace --event-json "$EVENT" 2>/dev/null || true

  # 自动提交 feedback（系统动作，不依赖 AI 自觉）
  AUTO_FB_RESULT=$("$HARNESSCTL" feedback submit \
    --epic-id "$ACTIVE_EPIC_ID" \
    --stage "$ACTIVE_STAGE" \
    --text "$EXCERPT" \
    --source hook \
    --candidate-type "$FEEDBACK_CANDIDATE_TYPE" \
    --json 2>/dev/null)
  AUTO_FB_ID=$(echo "$AUTO_FB_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('feedback_id',''))" 2>/dev/null)

  # 写入 mentioned_surface metadata（scope_gap_question 时，通过 harnessctl 管理）
  if [[ -n "$AUTO_FB_ID" && -n "$MENTIONED_SURFACE" ]]; then
    "$HARNESSCTL" feedback update-metadata \
      --epic-id "$ACTIVE_EPIC_ID" \
      --feedback-id "$AUTO_FB_ID" \
      --metadata-json "{\"mentioned_surface\":\"${MENTIONED_SURFACE}\"}" \
      --json 2>/dev/null || true
  fi
fi

# 注入 feedback_candidate 提示到 REMINDER
if [[ -n "$FEEDBACK_CANDIDATE_TYPE" ]]; then
  if [[ -n "$AUTO_FB_ID" ]]; then
    REMINDER+="\n  [Feedback - AUTO SUBMITTED] 系统已自动提交 ${AUTO_FB_ID} (type: ${FEEDBACK_CANDIDATE_TYPE})。"
    REMINDER+="\n     该 feedback 未完成 triage 前，禁止直接回答用户问题。"
    REMINDER+="\n     必须执行："
    REMINDER+="\n     1. harnessctl feedback run-triage --epic-id ${ACTIVE_EPIC_ID} --feedback-id ${AUTO_FB_ID} --json"
    REMINDER+="\n        （此命令自动完成：evidence-pack → council-triage → 6 agent 并行评审 → aggregate-triage）"
    REMINDER+="\n     2. 并行调度 feedback_triage_council 6 agent 评审（使用 Agent 工具）"
    REMINDER+="\n     3. harnessctl feedback aggregate-triage --epic-id ${ACTIVE_EPIC_ID} --feedback-id ${AUTO_FB_ID}"
    REMINDER+="\n     4. harnessctl feedback continue --epic-id ${ACTIVE_EPIC_ID} --feedback-id ${AUTO_FB_ID}"
    REMINDER+="\n        （根据 verdict 自动执行后续：reopen/close/create-task，无需人工确认）"
    REMINDER+="\n"
    REMINDER+="\n     ⛔ 硬性规则："
    REMINDER+="\n     - 禁止手工创建 evidence-pack.json / votes/*.json / verdict.json 文件"
    REMINDER+="\n     - 禁止用 Bash/Write 工具模拟 triage 流程，必须使用 harnessctl 标准命令"
    REMINDER+="\n     - 禁止使用旧版 vote schema（agree_reopen/conditional 等已废弃值）"
    REMINDER+="\n     - 有效 decision 值仅限：REOPEN_CLARIFY/REOPEN_SPEC/REOPEN_PLAN/STAY_EXECUTE/"
    REMINDER+="\n       NO_REOPEN_WITH_EVIDENCE/INSUFFICIENT_EVIDENCE/REJECT/DEFER"
    REMINDER+="\n     完成以上流程后，再基于 verdict 结论回答用户。"
  else
    REMINDER+="\n  [Feedback Candidate] 检测到用户反馈候选 (type: ${FEEDBACK_CANDIDATE_TYPE})，自动提交失败。"
    REMINDER+="\n     请手动执行: harnessctl feedback submit --epic-id ${ACTIVE_EPIC_ID} --stage ${ACTIVE_STAGE} --text \"...\""
  fi
fi

# Guard: Use gate-check for structured blocking detection
if [[ -n "$ACTIVE_EPIC_ID" && -x "$HARNESSCTL" && -z "$FEEDBACK_CANDIDATE_TYPE" ]]; then
  GATE_RESULT=$("$HARNESSCTL" feedback gate-check --epic-id "$ACTIVE_EPIC_ID" --json 2>/dev/null || true)
  GATE_STATUS=$(echo "$GATE_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)

  if [[ "$GATE_STATUS" == "blocked" ]]; then
    GATE_INFO=$(echo "$GATE_RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
parts = []
for item in data.get('blocked_items', []):
    fid = item.get('feedback_id', '?')
    reason = item.get('reason', '?')
    next_act = item.get('next_action', '?')
    cmds = item.get('required_commands', [])
    parts.append(f'{fid} ({reason}) → next: {next_act}')
    for c in cmds:
        parts.append(f'    harnessctl {c}')
print('\n'.join(parts))
" 2>/dev/null || true)
    if [[ -n "$GATE_INFO" ]]; then
      REMINDER+="\n  ⚠️  [Feedback Gate-Check BLOCKED] 存在未处理的 feedback，禁止进行其他开发工作。"
      REMINDER+="\n     阻断详情："
      while IFS= read -r line; do
        REMINDER+="\n     ${line}"
      done <<< "$GATE_INFO"
      REMINDER+="\n"
      REMINDER+="\n     允许的操作：feedback evidence-pack/council-triage/write-vote/aggregate-triage/related-gap-scan/continue/close"
      REMINDER+="\n     阻断的操作：普通开发、阶段推进、与 HFB 无关的调查"
    fi
  fi
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
