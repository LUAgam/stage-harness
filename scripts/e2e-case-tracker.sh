#!/usr/bin/env bash
# e2e-case-tracker.sh — E2E 测试 case 状态追踪器（产物写入的唯一合法通道）
# 用法: e2e-case-tracker.sh <command> <epic-id> [args...]
# 退出码: 0=成功, 1=失败/不完整, 2=参数错误

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_DIR="${HARNESS_DIR:-.harness}"

CMD="${1:-}"
EPIC_ID="${2:-}"

if [[ -z "$CMD" ]]; then
  cat >&2 <<'EOF'
usage: e2e-case-tracker.sh <command> <epic-id> [args...]

commands:
  init <epic-id>                        初始化 tracker
  register <epic-id> <case-id> <title> <priority> <dimension>  注册单个 case
  register-all <epic-id>                从 test-cases.md 批量注册
  status <epic-id>                      查看进度
  pending <epic-id>                     列出待执行 case
  start <epic-id> <case-id>             标记 case 开始执行
  pass <epic-id> <case-id>              标记 case 通过
  fail <epic-id> <case-id> <reason>     标记 case 失败
  skip <epic-id> <case-id> <reason>     标记 case 跳过（需合法理由）
  attempt <epic-id> <case-id>           记录一次修复尝试
  summary <epic-id>                     生成 verify-receipt.json + verify-summary.md
  check-complete <epic-id>              检查是否所有 case 都已处理
  gate init <epic-id>                   初始化门禁状态文件
  gate validate-step1 <epic-id>         验证 Step 1 产物合规性
  gate set <epic-id> <step> <status> [--field k=v ...]  写入步骤状态
  gate check <epic-id> <step>           检查该步骤的前置是否满足
  gate dump <epic-id>                   输出完整门禁状态
EOF
  exit 2
fi

# gate 命令自行解析 epic-id，其他命令需要全局 EPIC_ID
if [[ "$CMD" != "gate" && -z "$EPIC_ID" ]]; then
  echo "ERROR: 缺少 epic-id 参数" >&2
  echo "usage: e2e-case-tracker.sh <command> <epic-id> [args...]" >&2
  exit 2
fi

if [[ "$CMD" != "gate" ]]; then
  FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"
  VERIFY_DIR="$FEATURES_DIR/verify-cases"
  TRACKER_FILE="$VERIFY_DIR/case-tracker.json"
  GATE_FILE="$VERIFY_DIR/e2e-gate-status.json"
fi

# ── 工具函数 ──────────────────────────────────────────────────────────

_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

_atomic_write() {
  local target="$1"
  local tmp="${target}.tmp.$$"
  cat > "$tmp"
  mv -f "$tmp" "$target"
}

_read_tracker() {
  if [[ ! -f "$TRACKER_FILE" ]]; then
    echo "ERROR: tracker not initialized. Run: e2e-case-tracker.sh init $EPIC_ID" >&2
    exit 1
  fi
  cat "$TRACKER_FILE"
}

_update_counters() {
  python3 -c "
import json, sys
data = json.load(sys.stdin)
counters = {'pending': 0, 'in_progress': 0, 'passed': 0, 'failed': 0, 'skipped': 0}
for c in data['cases']:
    s = c['status']
    if s in counters:
        counters[s] += 1
data['counters'] = counters
data['last_updated'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
"
}

# ── 命令实现 ──────────────────────────────────────────────────────────

cmd_init() {
  mkdir -p "$VERIFY_DIR"
  local now; now=$(_now)
  cat <<EOF | _atomic_write "$TRACKER_FILE"
{
  "epic_id": "$EPIC_ID",
  "initialized_at": "$now",
  "total_cases": 0,
  "cases": [],
  "counters": {"pending": 0, "in_progress": 0, "passed": 0, "failed": 0, "skipped": 0},
  "last_updated": "$now"
}
EOF
  echo "✅ Tracker initialized: $TRACKER_FILE"
}

cmd_register() {
  local case_id="${3:-}"
  local title="${4:-}"
  local priority="${5:-P1}"
  local dimension="${6:-API}"

  if [[ -z "$case_id" || -z "$title" ]]; then
    echo "ERROR: register requires <case-id> <title> [priority] [dimension]" >&2
    exit 2
  fi

  _read_tracker | python3 -c "
import json, sys
data = json.load(sys.stdin)
# 检查重复
for c in data['cases']:
    if c['case_id'] == '$case_id':
        print(f'WARN: case $case_id already registered, skipping', file=sys.stderr)
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.exit(0)
new_case = {
    'case_id': '$case_id',
    'title': '''$title''',
    'priority': '$priority',
    'dimension': '$dimension',
    'status': 'pending',
    'attempts': 0,
    'max_attempts': 3,
    'started_at': None,
    'finished_at': None,
    'reason': None
}
data['cases'].append(new_case)
data['total_cases'] = len(data['cases'])
data['counters']['pending'] = sum(1 for c in data['cases'] if c['status'] == 'pending')
data['last_updated'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
" | _atomic_write "$TRACKER_FILE"
  echo "  registered: $case_id ($priority, $dimension)"
}

cmd_register_all() {
  local test_cases_file="$FEATURES_DIR/test-cases.md"
  if [[ ! -f "$test_cases_file" ]]; then
    echo "ERROR: $test_cases_file not found" >&2
    exit 1
  fi

  # 从 Case 注册表解析（在 E2E_CASE_REGISTRY_START 和 E2E_CASE_REGISTRY_END 之间）
  local count=0
  local in_registry=false

  while IFS= read -r line; do
    if [[ "$line" == *"E2E_CASE_REGISTRY_START"* ]]; then
      in_registry=true
      continue
    fi
    if [[ "$line" == *"E2E_CASE_REGISTRY_END"* ]]; then
      in_registry=false
      continue
    fi
    if [[ "$in_registry" == true ]] && [[ "$line" == "| TC-"* || "$line" == "| tc-"* ]]; then
      # 解析: | Case ID | 维度 | 优先级 | 标题 |
      local case_id dimension priority title
      case_id=$(echo "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2}')
      dimension=$(echo "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $3); print $3}')
      priority=$(echo "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $4); print $4}')
      title=$(echo "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $5); print $5}')

      if [[ -n "$case_id" ]]; then
        cmd_register "register" "$EPIC_ID" "$case_id" "$title" "$priority" "$dimension"
        count=$((count + 1))
      fi
    fi
  done < "$test_cases_file"

  if [[ $count -eq 0 ]]; then
    echo "ERROR: No cases found in registry section of $test_cases_file" >&2
    echo "  Expected <!-- E2E_CASE_REGISTRY_START --> ... <!-- E2E_CASE_REGISTRY_END -->" >&2
    exit 1
  fi

  echo ""
  echo "✅ Registered $count cases from test-cases.md"
}

cmd_status() {
  local data; data=$(_read_tracker)
  local total passed failed skipped pending in_progress
  total=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_cases'])")
  passed=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counters'].get('passed',0))")
  failed=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counters'].get('failed',0))")
  skipped=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counters'].get('skipped',0))")
  pending=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counters'].get('pending',0))")
  in_progress=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counters'].get('in_progress',0))")

  echo "📊 E2E Case Tracker: $EPIC_ID"
  echo "   Total: $total | Passed: $passed | Failed: $failed | Skipped: $skipped"
  echo "   Pending: $pending | In Progress: $in_progress"
  echo ""

  if [[ "$pending" -gt 0 || "$in_progress" -gt 0 ]]; then
    echo "   Status: INCOMPLETE"
    return 1
  else
    echo "   Status: COMPLETE"
    return 0
  fi
}

cmd_pending() {
  _read_tracker | python3 -c "
import json, sys
data = json.load(sys.stdin)
pending = [c for c in data['cases'] if c['status'] in ('pending', 'in_progress')]
for c in pending:
    print(f\"{c['case_id']}|{c['priority']}|{c['dimension']}|{c['title']}|{c['status']}\")
if not pending:
    print('(none)')
"
}

cmd_start() {
  local case_id="${3:-}"
  if [[ -z "$case_id" ]]; then
    echo "ERROR: start requires <case-id>" >&2
    exit 2
  fi

  _read_tracker | python3 -c "
import json, sys
data = json.load(sys.stdin)
found = False
for c in data['cases']:
    if c['case_id'] == '$case_id':
        found = True
        if c['status'] not in ('pending', 'in_progress'):
            print(f\"WARN: case $case_id is already {c['status']}, cannot start\", file=sys.stderr)
            json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
            sys.exit(0)
        c['status'] = 'in_progress'
        c['started_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
        break
if not found:
    print(f'ERROR: case $case_id not found in tracker', file=sys.stderr)
    sys.exit(1)
data['counters']['pending'] = sum(1 for c in data['cases'] if c['status'] == 'pending')
data['counters']['in_progress'] = sum(1 for c in data['cases'] if c['status'] == 'in_progress')
data['last_updated'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
" | _atomic_write "$TRACKER_FILE"
  echo "  ▶ started: $case_id"
}

cmd_pass() {
  local case_id="${3:-}"
  if [[ -z "$case_id" ]]; then
    echo "ERROR: pass requires <case-id>" >&2
    exit 2
  fi

  _read_tracker | python3 -c "
import json, sys
data = json.load(sys.stdin)
found = False
for c in data['cases']:
    if c['case_id'] == '$case_id':
        found = True
        c['status'] = 'passed'
        c['finished_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
        break
if not found:
    print(f'ERROR: case $case_id not found in tracker', file=sys.stderr)
    sys.exit(1)
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
" | _update_counters | _atomic_write "$TRACKER_FILE"
  echo "  ✅ passed: $case_id"
}

cmd_fail() {
  local case_id="${3:-}"
  local reason="${4:-no reason provided}"
  if [[ -z "$case_id" ]]; then
    echo "ERROR: fail requires <case-id> <reason>" >&2
    exit 2
  fi

  _read_tracker | python3 -c "
import json, sys
data = json.load(sys.stdin)
found = False
for c in data['cases']:
    if c['case_id'] == '$case_id':
        found = True
        c['status'] = 'failed'
        c['finished_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
        c['reason'] = '''$reason'''
        break
if not found:
    print(f'ERROR: case $case_id not found in tracker', file=sys.stderr)
    sys.exit(1)
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
" | _update_counters | _atomic_write "$TRACKER_FILE"
  echo "  ❌ failed: $case_id — $reason"
}

cmd_skip() {
  local case_id="${3:-}"
  local reason="${4:-no reason provided}"
  if [[ -z "$case_id" ]]; then
    echo "ERROR: skip requires <case-id> <reason>" >&2
    exit 2
  fi

  _read_tracker | python3 -c "
import json, sys
data = json.load(sys.stdin)
found = False
for c in data['cases']:
    if c['case_id'] == '$case_id':
        found = True
        c['status'] = 'skipped'
        c['finished_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
        c['reason'] = '''$reason'''
        break
if not found:
    print(f'ERROR: case $case_id not found in tracker', file=sys.stderr)
    sys.exit(1)
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
" | _update_counters | _atomic_write "$TRACKER_FILE"
  echo "  ⏭ skipped: $case_id — $reason"
}

cmd_attempt() {
  local case_id="${3:-}"
  if [[ -z "$case_id" ]]; then
    echo "ERROR: attempt requires <case-id>" >&2
    exit 2
  fi

  _read_tracker | python3 -c "
import json, sys
data = json.load(sys.stdin)
found = False
for c in data['cases']:
    if c['case_id'] == '$case_id':
        found = True
        c['attempts'] = c.get('attempts', 0) + 1
        if c['attempts'] >= c.get('max_attempts', 3):
            print(f\"WARN: case $case_id reached max attempts ({c['attempts']}/{c['max_attempts']})\", file=sys.stderr)
        break
if not found:
    print(f'ERROR: case $case_id not found in tracker', file=sys.stderr)
    sys.exit(1)
data['last_updated'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
" | _atomic_write "$TRACKER_FILE"
  echo "  🔄 attempt recorded: $case_id"
}

cmd_summary() {
  local data; data=$(_read_tracker)

  # Generate verify-receipt.json
  echo "$data" | python3 -c "
import json, sys
data = json.load(sys.stdin)
counters = data['counters']
total = data['total_cases']
passed = counters.get('passed', 0)
failed = counters.get('failed', 0)
skipped = counters.get('skipped', 0)
pending = counters.get('pending', 0)
in_progress = counters.get('in_progress', 0)

# Determine overall status
failed_cases = [c['case_id'] for c in data['cases'] if c['status'] == 'failed']
p0_failed = [c['case_id'] for c in data['cases'] if c['status'] == 'failed' and c.get('priority') == 'P0']

if pending > 0 or in_progress > 0:
    status = 'INCOMPLETE'
elif failed == 0:
    status = 'PASS'
elif len(p0_failed) > 0:
    status = 'FAIL'
else:
    status = 'PARTIAL'

receipt = {
    'epic_id': data['epic_id'],
    'status': status,
    'total': total,
    'passed': passed,
    'failed': failed,
    'skipped': skipped,
    'pending': pending,
    'in_progress': in_progress,
    'max_attempts_reached': failed_cases,
    'p0_failures': p0_failed,
    'summary_path': 'verify-cases/verify-summary.md',
    'tracker_path': 'verify-cases/case-tracker.json',
    'finished_at': '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
}
json.dump(receipt, sys.stdout, ensure_ascii=False, indent=2)
" | _atomic_write "$VERIFY_DIR/verify-receipt.json"

  # Generate verify-summary.md
  echo "$data" | python3 -c "
import json, sys
data = json.load(sys.stdin)
counters = data['counters']
total = data['total_cases']

lines = []
lines.append('# E2E 验证总结')
lines.append('')
lines.append(f\"**Epic ID**: {data['epic_id']}\")
lines.append(f\"**完成时间**: $(date -u +%Y-%m-%dT%H:%M:%SZ)\")
lines.append('')
lines.append('## 统计')
lines.append('')
lines.append(f\"| 状态 | 数量 |\")
lines.append(f\"|------|------|\")
lines.append(f\"| 总计 | {total} |\")
lines.append(f\"| 通过 | {counters.get('passed',0)} |\")
lines.append(f\"| 失败 | {counters.get('failed',0)} |\")
lines.append(f\"| 跳过 | {counters.get('skipped',0)} |\")
lines.append(f\"| 待执行 | {counters.get('pending',0)} |\")
lines.append(f\"| 执行中 | {counters.get('in_progress',0)} |\")
lines.append('')
lines.append('## Case 明细')
lines.append('')
lines.append('| Case ID | 维度 | 优先级 | 状态 | 尝试次数 | 原因 |')
lines.append('|---------|------|--------|------|----------|------|')
for c in data['cases']:
    reason = c.get('reason') or '-'
    lines.append(f\"| {c['case_id']} | {c.get('dimension','-')} | {c.get('priority','-')} | {c['status']} | {c.get('attempts',0)} | {reason} |\")
lines.append('')

print('\n'.join(lines))
" | _atomic_write "$VERIFY_DIR/verify-summary.md"

  echo "✅ Summary generated:"
  echo "   - $VERIFY_DIR/verify-receipt.json"
  echo "   - $VERIFY_DIR/verify-summary.md"
}

cmd_check_complete() {
  local data; data=$(_read_tracker)
  local incomplete
  incomplete=$(echo "$data" | python3 -c "
import json, sys
data = json.load(sys.stdin)
incomplete = [c for c in data['cases'] if c['status'] in ('pending', 'in_progress')]
if incomplete:
    for c in incomplete:
        print(f\"  ⚠ {c['case_id']} ({c['priority']}, {c['dimension']}): {c['status']}\", file=sys.stderr)
    sys.exit(1)
else:
    sys.exit(0)
" 2>&1)

  if [[ $? -ne 0 ]]; then
    echo "❌ NOT COMPLETE — unprocessed cases remain:" >&2
    echo "$incomplete" >&2
    return 1
  else
    echo "✅ All cases processed."
    return 0
  fi
}

# ── 门禁（Gate）命令 ─────────────────────────────────────────────────

cmd_gate() {
  local subcmd="${2:-}"
  # gate 命令格式: gate <subcmd> <epic-id> [args...]
  # 全局 EPIC_ID=$2 此时实际是 subcmd，需要从 $3 重新取 epic-id
  EPIC_ID="${3:-}"
  if [[ -z "$EPIC_ID" ]]; then
    echo "ERROR: gate 命令缺少 epic-id 参数" >&2
    echo "usage: e2e-case-tracker.sh gate <init|validate-step1|set|check|dump> <epic-id> [args...]" >&2
    exit 2
  fi
  FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"
  VERIFY_DIR="$FEATURES_DIR/verify-cases"
  TRACKER_FILE="$VERIFY_DIR/case-tracker.json"
  GATE_FILE="$VERIFY_DIR/e2e-gate-status.json"
  case "$subcmd" in
    init)           _gate_init ;;
    validate-step1) _gate_validate_step1 ;;
    set)            shift 3; _gate_set "$@" ;;
    check)          shift 3; _gate_check "$@" ;;
    dump)           _gate_dump ;;
    *)
      echo "ERROR: unknown gate subcommand '$subcmd'" >&2
      echo "usage: e2e-case-tracker.sh gate <init|validate-step1|set|check|dump> <epic-id> [args...]" >&2
      exit 2
      ;;
  esac
}

_gate_init() {
  mkdir -p "$VERIFY_DIR"
  if [[ -f "$GATE_FILE" ]]; then
    echo "⚠ Gate status already exists, reusing: $GATE_FILE"
    return 0
  fi
  local now; now=$(_now)
  cat <<EOF | _atomic_write "$GATE_FILE"
{
  "epic_id": "$EPIC_ID",
  "initialized_at": "$now",
  "steps": {}
}
EOF
  echo "✅ Gate status initialized: $GATE_FILE"
}

_gate_validate_step1() {
  local test_cases_file="$FEATURES_DIR/test-cases.md"
  local errors=""
  local file_exists="false"
  local registry_exists="false"
  local case_count=0

  if [[ -s "$test_cases_file" ]]; then
    file_exists="true"
  else
    errors="${errors}test-cases.md missing or empty;"
  fi

  if [[ "$file_exists" == "true" ]] && grep -q "E2E_CASE_REGISTRY_START" "$test_cases_file" 2>/dev/null; then
    registry_exists="true"
  elif [[ "$file_exists" == "true" ]]; then
    errors="${errors}E2E_CASE_REGISTRY_START marker not found;"
  fi

  if [[ "$registry_exists" == "true" ]]; then
    case_count=$(sed -n '/E2E_CASE_REGISTRY_START/,/E2E_CASE_REGISTRY_END/p' "$test_cases_file" \
      | grep -c "^| TC-" || true)
  fi
  if [[ $case_count -lt 1 ]]; then
    errors="${errors}registry contains 0 cases;"
  fi

  mkdir -p "$VERIFY_DIR"
  local now; now=$(_now)
  local prev_attempts=0
  if [[ -f "$GATE_FILE" ]]; then
    prev_attempts=$(python3 -c "
import json
try:
    with open('$GATE_FILE') as f:
        d = json.load(f)
    print(d.get('steps',{}).get('step_1_generate',{}).get('attempts',0))
except:
    print(0)
" 2>/dev/null)
  fi
  local attempts=$((prev_attempts + 1))

  python3 << PYEOF
import json, os, sys

gate_file = "$GATE_FILE"
if os.path.exists(gate_file):
    with open(gate_file) as f:
        data = json.load(f)
else:
    data = {"epic_id": "$EPIC_ID", "initialized_at": "$now", "steps": {}}

errors_str = """$errors"""
error_list = [e.strip() for e in errors_str.split(";") if e.strip()]

step_data = {
    "completed_at": "$now",
    "attempts": $attempts,
    "validation": {
        "file_exists": $([[ "$file_exists" == "true" ]] && echo "True" || echo "False"),
        "registry_exists": $([[ "$registry_exists" == "true" ]] && echo "True" || echo "False"),
        "case_count": $case_count
    }
}

if error_list:
    step_data["status"] = "FAIL"
    step_data["errors"] = error_list
else:
    step_data["status"] = "PASS"
    step_data["test_cases_count"] = $case_count

data.setdefault("steps", {})["step_1_generate"] = step_data
with open(gate_file, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

if error_list:
    print(f"❌ Step 1 validation FAILED (attempt {$attempts}):", file=sys.stderr)
    for e in error_list:
        print(f"   - {e}", file=sys.stderr)
    sys.exit(1)
else:
    print(f"✅ Step 1 validation PASSED (attempt {$attempts}, {$case_count} cases)")
    sys.exit(0)
PYEOF
}

_gate_set() {
  local step="${1:-}"
  local status="${2:-}"
  shift 2 || true

  if [[ -z "$step" || -z "$status" ]]; then
    echo "ERROR: gate set requires <step> <status> [--field k=v ...]" >&2
    exit 2
  fi

  if [[ ! -f "$GATE_FILE" ]]; then
    echo "ERROR: gate not initialized. Run: gate init" >&2
    exit 1
  fi

  local fields_json="{}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --field)
        local key="${2%%=*}"
        local val="${2#*=}"
        fields_json=$(python3 -c "
import json
d = json.loads('$fields_json')
v = '$val'
if v in ('true','false'): v = (v == 'true')
elif v.isdigit(): v = int(v)
d['$key'] = v
print(json.dumps(d))
")
        shift 2
        ;;
      *) shift ;;
    esac
  done

  local now; now=$(_now)
  python3 << PYEOF
import json

with open("$GATE_FILE") as f:
    data = json.load(f)

step_data = {"status": "$status", "completed_at": "$now"}
extra = json.loads('$fields_json')
step_data.update(extra)
data.setdefault("steps", {})["$step"] = step_data

with open("$GATE_FILE", "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"✅ Gate: $step = $status")
PYEOF
}

_gate_check() {
  local step="${1:-}"
  if [[ -z "$step" ]]; then
    echo "ERROR: gate check requires <step>" >&2
    exit 2
  fi

  if [[ ! -f "$GATE_FILE" ]]; then
    echo "❌ Gate status file not found. Run: gate init" >&2
    return 1
  fi

  python3 << PYEOF
import json, sys

with open("$GATE_FILE") as f:
    data = json.load(f)

steps = data.get("steps", {})
errors = []

prerequisites = {
    "step_1_5_register": [
        ("step_1_generate", "status", "PASS", "Step 1 (generate) must PASS first")
    ],
    "step_2_verify": [
        ("step_1_5_register", "status", "PASS", "Step 1.5 (register) must PASS first")
    ],
    "step_2_5_complete": [
        ("step_2_verify", "status", "PASS", "Step 2 (verify) must PASS first"),
        ("step_2_verify", "dispatched_via", "skill:", "Step 2 must be dispatched via skill (prefix match)"),
        ("step_2_verify", "dispatch_tool", "Skill", "Step 2 must use Skill tool (not Agent)")
    ],
    "step_3_artifacts": [
        ("step_2_5_complete", "status", "PASS", "Step 2.5 (complete) must PASS first")
    ],
    "credential_gate": []
}

target = "$step"
if target not in prerequisites:
    print(f"⚠ No prerequisite rules for '{target}', allowing")
    sys.exit(0)

for (dep_step, field, expected, msg) in prerequisites[target]:
    dep = steps.get(dep_step, {})
    if not dep:
        errors.append(f"{msg} (step '{dep_step}' not found in gate status)")
        continue
    actual = str(dep.get(field, ""))
    if expected.endswith(":"):
        if not actual.startswith(expected):
            errors.append(f"{msg} (got: '{actual}')")
    else:
        if actual != expected:
            errors.append(f"{msg} (got: '{actual}')")

if target == "credential_gate":
    cg = steps.get("credential_gate", {})
    groups_total = cg.get("total_groups", 0)
    groups_resolved = cg.get("groups_resolved", 0)
    groups_skipped = cg.get("groups_skipped", 0)
    if groups_total > 0 and (groups_resolved + groups_skipped) < groups_total:
        errors.append(f"Credential groups unresolved: {groups_total} total, "
                      f"{groups_resolved} resolved, {groups_skipped} skipped")

if errors:
    print(f"❌ Gate check FAILED for '{target}':", file=sys.stderr)
    for e in errors:
        print(f"   - {e}", file=sys.stderr)
    sys.exit(1)
else:
    print(f"✅ Gate check PASSED for '{target}'")
    if target == "step_2_verify":
        print("─── DISPATCH INSTRUCTION ───")
        print("DISPATCH_METHOD: Skill (NOT Agent)")
        print("REQUIRED_SKILL: stage-harness:verify-and-fix-cases")
        print("DISPATCH_VIA: Skill tool — shared context with main session")
        print("REASON: verify-and-fix-cases needs AskUserQuestion for credentials")
        print("────────────────────────────")
    sys.exit(0)
PYEOF
}

_gate_dump() {
  if [[ ! -f "$GATE_FILE" ]]; then
    echo "Gate status file not found." >&2
    return 1
  fi
  python3 -c "
import json
with open('$GATE_FILE') as f:
    print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
"
}

# ── 主调度 ──────────────────────────────────────────────────────────────

case "$CMD" in
  init)           cmd_init ;;
  register)       cmd_register "$@" ;;
  register-all)   cmd_register_all ;;
  status)         cmd_status ;;
  pending)        cmd_pending ;;
  start)          cmd_start "$@" ;;
  pass)           cmd_pass "$@" ;;
  fail)           cmd_fail "$@" ;;
  skip)           cmd_skip "$@" ;;
  attempt)        cmd_attempt "$@" ;;
  summary)        cmd_summary ;;
  check-complete) cmd_check_complete ;;
  gate)           cmd_gate "$@" ;;
  *)
    echo "ERROR: unknown command '$CMD'" >&2
    exit 2
    ;;
esac
