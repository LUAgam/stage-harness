#!/usr/bin/env bash
# smoke-check.sh — 运行时阶段冒烟检查（区别于开发期 smoke_test.sh）
# 用法: smoke-check.sh <epic-id> [task|stage] [task-id]
# 在 EXECUTE 阶段自动调用，验证最小可运行状态
# 退出码: 0=PASS, 1=FAIL(阻断), 2=WARN(可继续)

set -euo pipefail

EPIC_ID="${1:-}"
CHECK_TYPE="${2:-stage}"  # task | stage
TASK_ID="${3:-}"
HARNESS_DIR="${HARNESS_DIR:-.harness}"

if [[ -z "$EPIC_ID" ]]; then
  echo "usage: smoke-check.sh <epic-id> [task|stage] [task-id]" >&2
  exit 1
fi

FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"
RECEIPTS_DIR="$FEATURES_DIR/receipts"
mkdir -p "$RECEIPTS_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SMOKE_RESULT_FILE="$RECEIPTS_DIR/smoke-${CHECK_TYPE}-${TIMESTAMP//:/}.json"

echo "=== Smoke Check: $EPIC_ID [$CHECK_TYPE${TASK_ID:+ / $TASK_ID}] ==="
echo ""

CHECKS_PASS=()
CHECKS_FAIL=()
CHECKS_WARN=()

# ── 通用检查（所有项目类型）──────────────────────────────────────────

# 1. Git 工作区检查
check_git() {
  if git rev-parse --git-dir >/dev/null 2>&1; then
    # 检查是否有未暂存的破坏性变更
    UNTRACKED=$(git status --porcelain 2>/dev/null | grep "^??" | wc -l | tr -d ' ')
    if [[ "$UNTRACKED" -gt 10 ]]; then
      CHECKS_WARN+=("git: $UNTRACKED untracked files (may indicate incomplete task)")
    else
      CHECKS_PASS+=("git: working tree accessible")
    fi
  else
    CHECKS_WARN+=("git: not a git repository (commits disabled)")
  fi
}

# 2. 任务产物检查（task smoke）
check_task_artifacts() {
  [[ -z "$TASK_ID" ]] && return

  TASK_FILE="$HARNESS_DIR/tasks/${EPIC_ID}.${TASK_ID#${EPIC_ID}.}.json"
  TASK_FILE_ALT="$HARNESS_DIR/tasks/${TASK_ID}.json"

  local task_file=""
  [[ -f "$TASK_FILE" ]] && task_file="$TASK_FILE"
  [[ -f "$TASK_FILE_ALT" ]] && task_file="$TASK_FILE_ALT"

  if [[ -z "$task_file" ]]; then
    CHECKS_WARN+=("task: task file not found for $TASK_ID")
    return
  fi

  # 检查任务接受标准
  python3 - <<PYEOF
import json, sys, os

task = json.load(open("$task_file"))
ac = task.get("acceptance_criteria", [])
testing = task.get("testing", [])
evidence = task.get("evidence", [])

if not ac:
    print("WARN: no acceptance_criteria defined for $TASK_ID")
else:
    print(f"PASS: {len(ac)} acceptance criteria defined")

# 检查 evidence 文件是否存在
missing_evidence = []
for e in evidence:
    if not os.path.exists(e):
        missing_evidence.append(e)

if missing_evidence:
    for me in missing_evidence:
        print(f"FAIL: evidence missing: {me}")
    sys.exit(1)
elif evidence:
    print(f"PASS: {len(evidence)} evidence file(s) present")
PYEOF
  local pyexit=$?
  if [[ $pyexit -eq 0 ]]; then
    CHECKS_PASS+=("task-artifacts: $TASK_ID")
  else
    CHECKS_FAIL+=("task-artifacts: evidence missing for $TASK_ID")
  fi
}

# 3. 阶段出口检查（stage smoke）
check_stage_exit() {
  local stage
  stage=$(python3 -c "
import json, glob, sys
files = glob.glob('$HARNESS_DIR/epics/*.json')
for f in files:
    d = json.load(open(f))
    if d.get('id') == '$EPIC_ID':
        print(d.get('current_stage', ''))
        sys.exit(0)
" 2>/dev/null || echo "")

  [[ -z "$stage" ]] && { CHECKS_WARN+=("stage: could not determine current stage"); return; }

  # 根据当前阶段检查最基础的产物
  case "$stage" in
    EXECUTE)
      local receipts
      receipts=$(ls "$RECEIPTS_DIR/"*.json 2>/dev/null | wc -l | tr -d ' ')
      if [[ "$receipts" -gt 0 ]]; then
        CHECKS_PASS+=("stage: $receipts runtime receipt(s) found")
      else
        CHECKS_WARN+=("stage: no runtime receipts yet (first task?)")
      fi
      ;;
    VERIFY)
      if [[ -f "$FEATURES_DIR/verification.json" ]]; then
        CHECKS_PASS+=("stage: verification.json present")
      else
        CHECKS_FAIL+=("stage: verification.json missing (VERIFY not complete)")
      fi
      ;;
    *)
      CHECKS_PASS+=("stage: $stage — no specific smoke check defined")
      ;;
  esac
}

# 4. 测试运行检查（如果有 test runner 配置）
check_tests() {
  local test_cmd=""

  # 检测测试命令
  if [[ -f "package.json" ]]; then
    test_cmd=$(python3 -c "import json; d=json.load(open('package.json')); print(d.get('scripts',{}).get('test',''))" 2>/dev/null || true)
  elif [[ -f "pyproject.toml" ]] || [[ -f "pytest.ini" ]]; then
    test_cmd="pytest --tb=no -q"
  elif [[ -f "go.mod" ]]; then
    test_cmd="go test ./... -count=1 -timeout 30s"
  fi

  if [[ -z "$test_cmd" ]]; then
    CHECKS_WARN+=("tests: no test runner detected (skipping)")
    return
  fi

  # 仅在 task smoke 时运行相关测试（不全量）
  if [[ "$CHECK_TYPE" == "task" && -n "$TASK_ID" ]]; then
    CHECKS_WARN+=("tests: skipping full test run for task smoke (run manually if needed)")
  else
    CHECKS_PASS+=("tests: test runner detected ($test_cmd)")
  fi
}

# ── 运行检查 ─────────────────────────────────────────────────────────
check_git
check_tests

if [[ "$CHECK_TYPE" == "task" ]]; then
  check_task_artifacts
else
  check_stage_exit
fi

# ── 结果汇总 ─────────────────────────────────────────────────────────
TOTAL_FAIL=${#CHECKS_FAIL[@]}
TOTAL_WARN=${#CHECKS_WARN[@]}
TOTAL_PASS=${#CHECKS_PASS[@]}

echo "Results:"
for c in "${CHECKS_PASS[@]}"; do echo "  ✅ $c"; done
for c in "${CHECKS_WARN[@]}"; do echo "  ⚠️  $c"; done
for c in "${CHECKS_FAIL[@]}"; do echo "  ❌ $c"; done
echo ""
echo "Summary: ${TOTAL_PASS} pass, ${TOTAL_WARN} warn, ${TOTAL_FAIL} fail"

# 写入 receipt
python3 - <<PYEOF
import json, datetime
result = {
    "epic": "$EPIC_ID",
    "check_type": "$CHECK_TYPE",
    "task_id": "$TASK_ID" or None,
    "timestamp": "$TIMESTAMP",
    "pass": $TOTAL_PASS,
    "warn": $TOTAL_WARN,
    "fail": $TOTAL_FAIL,
    "checks_pass": $(python3 -c "import json; print(json.dumps(${CHECKS_PASS[@]+${CHECKS_PASS[@]}}))" 2>/dev/null || echo "[]"),
    "checks_warn": $(python3 -c "import json; print(json.dumps(${CHECKS_WARN[@]+${CHECKS_WARN[@]}}))" 2>/dev/null || echo "[]"),
    "checks_fail": $(python3 -c "import json; print(json.dumps(${CHECKS_FAIL[@]+${CHECKS_FAIL[@]}}))" 2>/dev/null || echo "[]"),
    "overall": "FAIL" if $TOTAL_FAIL > 0 else ("WARN" if $TOTAL_WARN > 0 else "PASS")
}
with open("$SMOKE_RESULT_FILE", "w") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
PYEOF

# 退出码
if [[ $TOTAL_FAIL -gt 0 ]]; then
  echo "❌ Smoke check FAILED — blocking"
  exit 1
elif [[ $TOTAL_WARN -gt 0 ]]; then
  echo "⚠️  Smoke check passed with warnings"
  exit 2
else
  echo "✅ Smoke check PASSED"
  exit 0
fi
