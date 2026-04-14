#!/usr/bin/env bash
# decision-bundle.sh — Decision Bundle 生成与操作
# 用法:
#   decision-bundle.sh generate <epic-id>          # 初始化空 bundle
#   decision-bundle.sh add <epic-id> <json-file>   # 添加决策条目
#   decision-bundle.sh status <epic-id>            # 显示 bundle 摘要
#   decision-bundle.sh resolve <epic-id> <dec-id> <resolution>  # 标记已解决
#   decision-bundle.sh packet <epic-id>            # 生成 must_confirm packet

set -euo pipefail

COMMAND="${1:-status}"
EPIC_ID="${2:-}"
HARNESS_DIR="${HARNESS_DIR:-.harness}"

if [[ -z "$EPIC_ID" ]]; then
  echo "usage: decision-bundle.sh <command> <epic-id> [args]" >&2
  exit 1
fi

FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"
BUNDLE_FILE="$FEATURES_DIR/decision-bundle.json"
PACKET_FILE="$FEATURES_DIR/decision-packet.json"
STATE_FILE="$FEATURES_DIR/state.json"

mkdir -p "$FEATURES_DIR"

# ── Helpers ─────────────────────────────────────────────────────────
bundle_exists() { [[ -f "$BUNDLE_FILE" ]]; }
budget_remaining() {
  # Budget lives in state.json (interrupt_budget.remaining), NOT in a separate file
  [[ -f "$STATE_FILE" ]] || { echo 0; return; }
  python3 -c "import json; d=json.load(open('$STATE_FILE')); print(d.get('interrupt_budget', {}).get('remaining', 0))" 2>/dev/null || echo 0
}

sync_state_from_bundle() {
  [[ -f "$STATE_FILE" && -f "$BUNDLE_FILE" ]] || return 0
  python3 - <<PYEOF
import json
from datetime import datetime, timezone
from pathlib import Path

state_path = Path("$STATE_FILE")
bundle_path = Path("$BUNDLE_FILE")
state = json.load(state_path.open(encoding="utf-8"))
bundle = json.load(bundle_path.open(encoding="utf-8"))

decisions = bundle.get("decisions", []) if isinstance(bundle, dict) else []
pending = []
for idx, decision in enumerate(decisions, start=1):
    if not isinstance(decision, dict):
        continue
    if decision.get("category") != "must_confirm":
        continue
    if decision.get("status", "pending") != "pending":
        continue
    risk_if_wrong = str(decision.get("risk_if_wrong") or decision.get("severity") or "high").lower()
    if risk_if_wrong not in {"critical", "high", "medium", "low"}:
        risk_if_wrong = "high"
    severity = str(decision.get("severity") or risk_if_wrong).lower()
    if severity not in {"critical", "high", "medium", "low"}:
        severity = risk_if_wrong
    pending.append({
        "id": str(decision.get("id") or f"DEC-{idx:03d}"),
        "question": str(decision.get("question", "")).strip(),
        "category": "must_confirm",
        "severity": severity,
        "risk_if_wrong": risk_if_wrong,
        "status": "pending",
        "source_ref": str(decision.get("source_ref", "")).strip(),
        "source_artifact": str(decision.get("source_artifact", "decision-bundle.json")).strip(),
        "why_now": str(decision.get("why_now", "")).strip(),
        "options": decision.get("options", []) if isinstance(decision.get("options", []), list) else [],
        "default_action": str(decision.get("proposed_default", "")).strip(),
    })

state["pending_decisions"] = pending
state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with state_path.open("w", encoding="utf-8") as fh:
    json.dump(state, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PYEOF
}

current_interrupt_number() {
  [[ -f "$STATE_FILE" ]] || { echo 1; return; }
  python3 - <<PYEOF
import json
state = json.load(open("$STATE_FILE", encoding="utf-8"))
budget = state.get("interrupt_budget", {})
consumed = int(budget.get("consumed", 0) or 0)
print(consumed + 1)
PYEOF
}

current_pending_count() {
  [[ -f "$STATE_FILE" ]] || { echo 0; return; }
  python3 - <<PYEOF
import json
state = json.load(open("$STATE_FILE", encoding="utf-8"))
pending = state.get("pending_decisions", [])
print(len(pending) if isinstance(pending, list) else 0)
PYEOF
}

emit_trace_event() {
  local event_type="$1"
  local summary="$2"
  local payload_json="${3:-{}}"
  local harnessctl_path="${CLAUDE_PLUGIN_ROOT:-}/scripts/harnessctl"
  [[ -x "$harnessctl_path" ]] || return 0
  local event
  event=$(python3 - <<PYEOF
import json
from datetime import datetime, timezone

try:
    payload = json.loads("""$payload_json""")
except json.JSONDecodeError:
    payload = {}

print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "epic_id": "$EPIC_ID",
    "stage": "CLARIFY",
    "source": "decision-bundle",
    "actor": "decision-bundle",
    "event_type": "$event_type",
    "status": "ok",
    "summary": "$summary",
    "payload": payload,
    "artifact_paths": ["$BUNDLE_FILE", "$PACKET_FILE", "$STATE_FILE"],
}, ensure_ascii=False))
PYEOF
)
  [[ -n "$event" ]] && "$harnessctl_path" patch trace --event-json "$event" >/dev/null 2>&1 || true
}

# ── Commands ────────────────────────────────────────────────────────
case "$COMMAND" in

generate)
  if bundle_exists; then
    echo "⚠️  decision-bundle.json already exists for $EPIC_ID (skipping)"
    exit 0
  fi
  python3 - <<PYEOF
import json, datetime
bundle = {
    "epic": "$EPIC_ID",
    "stage": "CLARIFY",
    "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "summary": {"must_confirm": 0, "assumable": 0, "deferrable": 0, "interrupts_consumed": 0},
    "decisions": []
}
with open("$BUNDLE_FILE", "w") as f:
    json.dump(bundle, f, indent=2, ensure_ascii=False)
print("Generated decision-bundle.json for $EPIC_ID")
PYEOF
  sync_state_from_bundle
  emit_trace_event "pending_decisions_synced" "Synced pending decisions after bundle generate" "{\"pending_count\": $(current_pending_count)}"
  ;;

add)
  JSON_INPUT="${3:-}"
  if [[ -z "$JSON_INPUT" ]]; then
    echo "usage: decision-bundle.sh add <epic-id> <json-file>" >&2
    exit 1
  fi
  bundle_exists || { echo "Run 'generate' first" >&2; exit 1; }
  python3 - <<PYEOF
import json, re, sys
bundle = json.load(open("$BUNDLE_FILE"))
new_decision = json.load(open("$JSON_INPUT"))
# Ensure required fields
for field in ["question", "category"]:
    if field not in new_decision:
        print(f"ERROR: missing field '{field}' in decision JSON", file=sys.stderr)
        sys.exit(1)
existing_ids = {
    str(d.get("id", "")).strip()
    for d in bundle.get("decisions", [])
    if isinstance(d, dict) and str(d.get("id", "")).strip()
}
if not str(new_decision.get("id", "")).strip():
    next_num = 1
    for existing_id in existing_ids:
        match = re.match(r"DEC-(\d+)$", existing_id)
        if match:
            next_num = max(next_num, int(match.group(1)) + 1)
    new_decision["id"] = f"DEC-{next_num:03d}"
elif str(new_decision["id"]).strip() in existing_ids:
    print(f"ERROR: duplicate decision id '{new_decision['id']}'", file=sys.stderr)
    sys.exit(1)
new_decision.setdefault("status", "pending")
new_decision.setdefault("source_artifact", "decision-bundle.json")
bundle["decisions"].append(new_decision)
# Recount summary
cats = [d.get("category") for d in bundle["decisions"]]
bundle["summary"]["must_confirm"] = cats.count("must_confirm")
bundle["summary"]["assumable"] = cats.count("assumable")
bundle["summary"]["deferrable"] = cats.count("deferrable")
with open("$BUNDLE_FILE", "w") as f:
    json.dump(bundle, f, indent=2, ensure_ascii=False)
print(f"Added {new_decision['id']} ({new_decision['category']}) to bundle")
PYEOF
  sync_state_from_bundle
  emit_trace_event "pending_decisions_synced" "Synced pending decisions after bundle add" "{\"pending_count\": $(current_pending_count)}"
  ;;

status)
  bundle_exists || { echo "No decision-bundle.json for $EPIC_ID"; exit 0; }
  python3 - <<PYEOF
import json
bundle = json.load(open("$BUNDLE_FILE"))
s = bundle.get("summary", {})
state = {}
try:
    state = json.load(open("$STATE_FILE"))
except Exception:
    state = {}
budget = state.get("interrupt_budget", {}) if isinstance(state, dict) else {}
print(f"Decision Bundle: $EPIC_ID ({bundle.get('stage','?')})")
print(f"  must_confirm: {s.get('must_confirm', 0)}")
print(f"  assumable:    {s.get('assumable', 0)}")
print(f"  deferrable:   {s.get('deferrable', 0)}")
print(f"  interrupts consumed: {budget.get('consumed', 0)}")
print("")
pending = [d for d in bundle.get("decisions", []) if d.get("status") == "pending"]
if pending:
    print(f"  Pending decisions ({len(pending)}):")
    for d in pending:
        print(f"    [{d['category'].upper()[:1]}] {d['id']}: {d['question'][:60]}...")
PYEOF
  ;;

resolve)
  DEC_ID="${3:-}"
  RESOLUTION="${4:-resolved}"
  [[ -z "$DEC_ID" ]] && { echo "usage: resolve <epic-id> <dec-id> [resolution]" >&2; exit 1; }
  bundle_exists || { echo "No bundle file" >&2; exit 1; }
  python3 - <<PYEOF
import json, datetime
bundle = json.load(open("$BUNDLE_FILE"))
found = False
for d in bundle["decisions"]:
    if d["id"] == "$DEC_ID":
        d["status"] = "resolved"
        d["resolution"] = "$RESOLUTION"
        d["resolved_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        found = True
        break
if not found:
    print(f"ERROR: decision $DEC_ID not found", file=sys.stderr)
    exit(1)
with open("$BUNDLE_FILE", "w") as f:
    json.dump(bundle, f, indent=2, ensure_ascii=False)
print(f"Resolved $DEC_ID: $RESOLUTION")
PYEOF
  sync_state_from_bundle
  emit_trace_event "pending_decisions_synced" "Synced pending decisions after bundle resolve" "{\"pending_count\": $(current_pending_count)}"
  ;;

packet)
  bundle_exists || { echo "No bundle file" >&2; exit 1; }
  REMAINING=$(budget_remaining)
INTERRUPT_NUMBER=$(current_interrupt_number)
  python3 - <<PYEOF
import json, datetime, sys
bundle = json.load(open("$BUNDLE_FILE"))
must_confirm = [d for d in bundle["decisions"] if d.get("category") == "must_confirm" and d.get("status") == "pending"]
if not must_confirm:
    print("No must_confirm decisions — no packet needed")
    sys.exit(0)

remaining = int("$REMAINING")
if remaining <= 0:
    print("⚠️  INTERRUPT BUDGET EXHAUSTED — applying safe defaults for all must_confirm items")
    for d in must_confirm:
        d["status"] = "assumed"
        d["resolution"] = d.get("proposed_default", "safe default applied — budget exhausted")
    with open("$BUNDLE_FILE", "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
    sys.exit(0)

packet = {
    "version": "1.0",
    "epic_id": "$EPIC_ID",
    "stage": "CLARIFY",
    "packet_id": f"DP-CLARIFY-{int('$INTERRUPT_NUMBER'):03d}",
    "interrupt_number": int("$INTERRUPT_NUMBER"),
    "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "total_interrupts_in_budget": remaining,
    "questions": []
}
for d in must_confirm:
    packet["questions"].append({
        "id": d["id"],
        "question": d["question"],
        "why_now": d.get("why_now", ""),
        "options": d.get("options", []),
        "default_action": d.get("proposed_default", ""),
        "deadline": d.get("deadline", "before next stage"),
        "source_ref": d.get("source_ref", ""),
        "risk_if_wrong": d.get("risk_if_wrong", d.get("severity", "")),
    })
packet["auto_release_if_all_answered"] = True

with open("$PACKET_FILE", "w") as f:
    json.dump(packet, f, indent=2, ensure_ascii=False)
with open("$BUNDLE_FILE", "w") as f:
    json.dump(bundle, f, indent=2, ensure_ascii=False)
print(f"Generated decision-packet.json with {len(packet['questions'])} question(s)")
print(f"Interrupt budget remaining after this packet: {remaining - 1}")
PYEOF
  sync_state_from_bundle
  emit_trace_event "decision_packet_generated" "Generated decision packet" "{\"questions_count\": $(python3 - <<PYEOF
import json
packet = json.load(open("$PACKET_FILE", encoding="utf-8"))
print(len(packet.get("questions", [])))
PYEOF
), \"interrupt_number\": $INTERRUPT_NUMBER}"
  emit_trace_event "pending_decisions_synced" "Synced pending decisions after packet generation" "{\"pending_count\": $(current_pending_count)}"
  ;;

*)
  echo "Unknown command: $COMMAND" >&2
  echo "Commands: generate | add | status | resolve | packet" >&2
  exit 1
  ;;
esac
