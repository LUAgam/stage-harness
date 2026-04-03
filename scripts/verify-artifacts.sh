#!/usr/bin/env bash
# verify-artifacts.sh — 产物完整性检查
# 用法: verify-artifacts.sh <epic-id> <stage>
# 退出码: 0=通过, 1=缺失产物(阻断), 2=警告(可继续)

set -euo pipefail

EPIC_ID="${1:-}"
STAGE="${2:-}"
HARNESS_DIR="${HARNESS_DIR:-.harness}"

if [[ -z "$EPIC_ID" || -z "$STAGE" ]]; then
  echo "usage: verify-artifacts.sh <epic-id> <stage>" >&2
  exit 1
fi

STAGE_UPPER="$(printf '%s' "$STAGE" | tr '[:lower:]' '[:upper:]')"

EPIC_DIR="$HARNESS_DIR/epics"
FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"

# 与 harnessctl STAGE_GATE_ARTIFACTS / clarify_closure_mode 对齐（notes_only 时仅校验 clarification-notes.md）
CLARIFY_MODE="full"
if [[ -f "$HARNESS_DIR/config.json" ]]; then
  CLARIFY_MODE="$(python3 -c "import json;print(str(json.load(open('$HARNESS_DIR/config.json')).get('clarify_closure_mode','full')).lower())" 2>/dev/null || echo full)"
fi

# ── 各阶段必须产物定义 ──────────────────────────────────────────────
declare -A REQUIRED_ARTIFACTS
if [[ "$STAGE_UPPER" == "CLARIFY" && "$CLARIFY_MODE" == "notes_only" ]]; then
  REQUIRED_ARTIFACTS[CLARIFY]="
  $FEATURES_DIR/clarification-notes.md
"
else
  REQUIRED_ARTIFACTS[CLARIFY]="
  $FEATURES_DIR/domain-frame.json
  $FEATURES_DIR/generated-scenarios.json
  $FEATURES_DIR/scenario-coverage.json
  $FEATURES_DIR/challenge-report.md
  $FEATURES_DIR/clarification-notes.md
  $FEATURES_DIR/impact-scan.md
  $FEATURES_DIR/surface-routing.json
  $FEATURES_DIR/unknowns-ledger.json
  $FEATURES_DIR/decision-bundle.json
  $FEATURES_DIR/decision-packet.json
"
fi
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

if [[ "$STAGE_UPPER" == "CLARIFY" && -f "$FEATURES_DIR/clarification-notes.md" && -s "$FEATURES_DIR/clarification-notes.md" ]]; then
  NOTE_ERRORS="$(
    python3 - "$FEATURES_DIR/clarification-notes.md" <<'PY'
import pathlib
import re
import sys

note_path = pathlib.Path(sys.argv[1])
text = note_path.read_text(encoding="utf-8", errors="replace")
errors = []

if not re.search(r"(?im)^#{1,4}\s*(?:domain\s*frame|领域框架|需求上下文)\b", text):
    errors.append("missing Domain Frame / 领域框架 / 需求上下文 heading")

minimal_heading = re.search(r"(?im)^#{1,4}\s*(?:极简澄清绕行|极简澄清模式|minimal\s*clarify)\b", text)
minimal_signal = re.search(r"(?i)极简澄清绕行|minimal\s*clarify\s*bypass", text) and re.search(
    r"(?i)not_applicable|全局[^\n]{0,40}不适用|不适用[^\n]{0,40}全局", text
)
minimal_ok = bool(minimal_heading or minimal_signal)

axis_section = re.search(r"(?im)^#{1,4}\s*(?:六轴澄清覆盖|six[- ]axis\s*clarification|澄清必答覆盖)\b", text)
if not minimal_ok and not axis_section:
    errors.append("missing 六轴澄清覆盖 section or 极简澄清绕行 declaration")

closure_heading = re.search(r"(?im)^#{1,4}\s*(?:unknowns?\s*与\s*待确认|待确认决策|决策闭环|unknown\s*closure|closures?)\b", text)
closure_inline = re.search(r"(?i)\b(UNK-\d+|DEC-\d+|must_confirm)\b", text)
closure_none = re.search(r"(?i)无待确认|无\s*must_confirm|无\s*unknown\s*项|closure:\s*none|本轮\s*无\s*待确认", text)
if not closure_heading and not closure_inline and not (minimal_ok and closure_none):
    errors.append("missing Unknowns 与待确认决策 closure section (or UNK/DEC/must_confirm references)")

if not minimal_ok and axis_section:
    tri_re = re.compile(r"(?i)\b(covered|not_applicable|not\s+applicable|unknown|已覆盖|不适用|尚不清楚)\b")
    axis_specs = [
        (r"StateAndTime|行为与流程", "StateAndTime / 行为与流程"),
        (r"ConstraintsAndConflict|规则与边界", "ConstraintsAndConflict / 规则与边界"),
        (r"CostAndCapacity|规模与代价", "CostAndCapacity / 规模与代价"),
        (r"CrossSurfaceConsistency|多入口|多阶段一致性", "CrossSurfaceConsistency / 多入口"),
        (r"OperationsAndRecovery|运行与维护", "OperationsAndRecovery / 运行与维护"),
        (r"SecurityAndIsolation|权限与隔离", "SecurityAndIsolation / 权限与隔离"),
    ]
    for pattern, label in axis_specs:
        m = re.search(pattern, text)
        if not m:
            errors.append(f"missing six-axis row for {label}")
            continue
        chunk = text[max(0, m.start() - 120): m.end() + 500]
        if not tri_re.search(chunk):
            errors.append(f"missing covered/not_applicable/unknown state near {label}")

for item in errors:
    print(item)
PY
  )"
  if [[ -n "$NOTE_ERRORS" ]]; then
    while IFS= read -r err_line; do
      [[ -z "$err_line" ]] && continue
      MISSING+=("$FEATURES_DIR/clarification-notes.md ($err_line)")
    done <<< "$NOTE_ERRORS"
  fi
fi

# ── 输出结果 ────────────────────────────────────────────────────────
echo "=== Artifact Verification: $EPIC_ID @ $STAGE_UPPER ==="
if [[ "$STAGE_UPPER" == "CLARIFY" ]]; then
  echo "clarify_closure_mode (from config): $CLARIFY_MODE"
fi
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
