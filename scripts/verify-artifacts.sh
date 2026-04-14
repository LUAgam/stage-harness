#!/usr/bin/env bash
# verify-artifacts.sh — 产物完整性检查
# 用法: verify-artifacts.sh <epic-id> <stage>
# 退出码: 0=通过, 1=缺失产物(阻断), 2=警告(可继续)

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

EPIC_ID="${1:-}"
STAGE="${2:-}"
HARNESS_DIR="${HARNESS_DIR:-.harness}"

if [[ -z "$EPIC_ID" || -z "$STAGE" ]]; then
  echo "usage: verify-artifacts.sh <epic-id> <stage>" >&2
  exit 1
fi

STAGE_UPPER="$(printf '%s' "$STAGE" | tr '[:lower:]' '[:upper:]')"

if [[ "$STAGE_UPPER" == "CLARIFY" ]]; then
  exec python3 "$_SCRIPT_DIR/harnessctl.py" --project-root "$PWD" stage-gate check CLARIFY --epic-id "$EPIC_ID"
fi

EPIC_DIR="$HARNESS_DIR/epics"
FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"

# 与 harnessctl STAGE_GATE_ARTIFACTS / clarify_closure_mode 对齐（notes_only 时仅校验 clarification-notes.md）
CLARIFY_MODE="full"
SIGNAL_GATE_ENABLED="true"
DEEP_DIVE_ENABLED="true"
DEEP_DIVE_GATE_STRICT="false"
if [[ -f "$HARNESS_DIR/config.json" ]]; then
  CLARIFY_MODE="$(python3 -c "import json;print(str(json.load(open('$HARNESS_DIR/config.json')).get('clarify_closure_mode','full')).lower())" 2>/dev/null || echo full)"
  SIGNAL_GATE_ENABLED="$(python3 -c "import json;print(str(bool(json.load(open('$HARNESS_DIR/config.json')).get('clarify_signal_gate_enabled', True))).lower())" 2>/dev/null || echo true)"
  DEEP_DIVE_ENABLED="$(python3 -c "import json;print(str(bool(json.load(open('$HARNESS_DIR/config.json')).get('clarify_deep_dive_enabled', True))).lower())" 2>/dev/null || echo true)"
  DEEP_DIVE_GATE_STRICT="$(python3 -c "import json;print(str(bool(json.load(open('$HARNESS_DIR/config.json')).get('clarify_deep_dive_gate_strict', False))).lower())" 2>/dev/null || echo false)"
fi

# ── 各阶段必须产物定义 ──────────────────────────────────────────────
declare -A REQUIRED_ARTIFACTS
# CLARIFY stage artifacts are checked by harnessctl stage-gate check CLARIFY via exec above.
REQUIRED_ARTIFACTS[SPEC]="
  .harness/specs/$EPIC_ID.md
  $FEATURES_DIR/spec-council-notes.md
"
REQUIRED_ARTIFACTS[PLAN]="
  $FEATURES_DIR/bridge-spec.md
  $FEATURES_DIR/coverage-matrix.json
  $FEATURES_DIR/surface-routing.json
"
REQUIRED_ARTIFACTS[EXECUTE]="
  $FEATURES_DIR/receipts
"
REQUIRED_ARTIFACTS[VERIFY]="
  $FEATURES_DIR/verification.json
"
REQUIRED_ARTIFACTS[DONE]="
  $FEATURES_DIR/delivery-summary.md
  $FEATURES_DIR/release-notes.md
  $FEATURES_DIR/councils/verdict-release_council.json
"

# ── 检查 ────────────────────────────────────────────────────────────
ARTIFACTS_LIST="${REQUIRED_ARTIFACTS[$STAGE_UPPER]:-}"
if [[ -z "$ARTIFACTS_LIST" ]]; then
  echo "⚠️  No artifact spec defined for stage: $STAGE_UPPER (skipping check)"
  exit 0
fi

MISSING=()
PRESENT=()

while IFS= read -r artifact; do
  artifact=$(echo "$artifact" | xargs)  # trim whitespace
  [[ -z "$artifact" ]] && continue

  if [[ -e "$artifact" ]]; then
    # 检查是否为空
    if [[ -f "$artifact" ]] && [[ ! -s "$artifact" ]]; then
      MISSING+=("$artifact (empty)")
    else
      PRESENT+=("$artifact")
    fi
  else
    MISSING+=("$artifact")
  fi
done <<< "$ARTIFACTS_LIST"

# ── 输出结果 ────────────────────────────────────────────────────────
echo "=== Artifact Verification: $EPIC_ID @ $STAGE_UPPER ==="
echo ""

if [[ ${#PRESENT[@]} -gt 0 ]]; then
  echo "✅ Present (${#PRESENT[@]}):"
  for a in "${PRESENT[@]}"; do
    echo "   $a"
  done
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo ""
  echo "❌ Missing (${#MISSING[@]}):"
  for a in "${MISSING[@]}"; do
    echo "   $a"
  done
  echo ""
  echo "RESULT: BLOCKED — missing required artifacts for $STAGE_UPPER"
  exit 1
fi

echo ""
echo "RESULT: PASS — all required artifacts present for $STAGE_UPPER"
exit 0
