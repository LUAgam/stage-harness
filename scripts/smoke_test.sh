#!/usr/bin/env bash
# smoke_test.sh: stage-harness 端到端冒烟测试
# 测试：harnessctl init → epic create → task create → state transition

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESSCTL="$PLUGIN_ROOT/scripts/harnessctl"
TEST_DIR=$(mktemp -d)
trap "rm -rf $TEST_DIR" EXIT

cd "$TEST_DIR"

echo "=== Stage-Harness Smoke Test ==="
echo "Test dir: $TEST_DIR"
echo "Plugin root: $PLUGIN_ROOT"
echo ""

# 初始化
echo "[1/6] Testing harnessctl init..."
"$HARNESSCTL" init
[[ -d ".harness" ]] || { echo "FAIL: .harness not created"; exit 1; }
echo "  OK"

# 项目画像
echo "[2/6] Testing profile detect..."
"$HARNESSCTL" profile detect
[[ -f ".harness/project-profile.yaml" ]] || { echo "FAIL: project-profile.yaml not created"; exit 1; }
echo "  OK"

# 创建 epic
echo "[3/6] Testing epic create..."
"$HARNESSCTL" epic create "Test Feature"
EPIC_ID=$("$HARNESSCTL" epic list --json | python3 -c "
import json, sys
epics = json.load(sys.stdin)
if not epics:
    print('')
else:
    print(epics[0].get('id', ''))
" 2>/dev/null)
[[ -n "$EPIC_ID" ]] || { echo "FAIL: no epic created or could not retrieve epic ID"; exit 1; }
echo "  OK: $EPIC_ID"

# 创建 task
echo "[4/6] Testing task create..."
"$HARNESSCTL" task create "$EPIC_ID" "Test Task"
echo "  OK"

# 状态转换
echo "[5/6] Testing state transition..."
"$HARNESSCTL" state transition "$EPIC_ID" SPEC
STATE=$("$HARNESSCTL" state get "$EPIC_ID" --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('current_stage', ''))
" 2>/dev/null)
[[ "$STATE" == "SPEC" ]] || { echo "FAIL: expected SPEC, got '$STATE'"; exit 1; }
echo "  OK"

# Status
echo "[6/6] Testing status..."
"$HARNESSCTL" status
echo "  OK"

echo ""
echo "=== All smoke tests passed! ==="
