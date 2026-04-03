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

mkdir -p "$FEATURES_DIR"

# ── Helpers ─────────────────────────────────────────────────────────
bundle_exists() { [[ -f "$BUNDLE_FILE" ]]; }
budget_remaining() {
  # Budget lives in state.json (interrupt_budget.remaining), NOT in a separate file
  STATE_FILE="$FEATURES_DIR/state.json"
  [[ -f "$STATE_FILE" ]] || { echo 0; return; }
  python3 -c "import json; d=json.load(open('$STATE_FILE')); print(d.get('interrupt_budget', {}).get('remaining', 0))" 2>/dev/null || echo 0
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
    "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    "summary": {"must_confirm": 0, "assumable": 0, "deferrable": 0, "interrupts_consumed": 0},
    "decisions": []
}
with open("$BUNDLE_FILE", "w") as f:
    json.dump(bundle, f, indent=2, ensure_ascii=False)
print("Generated decision-bundle.json for $EPIC_ID")
PYEOF
  ;;

add)
  JSON_INPUT="${3:-}"
  if [[ -z "$JSON_INPUT" ]]; then
    echo "usage: decision-bundle.sh add <epic-id> <json-file>" >&2
    exit 1
  fi
  bundle_exists || { echo "Run 'generate' first" >&2; exit 1; }
  python3 - <<PYEOF
import json, sys
bundle = json.load(open("$BUNDLE_FILE"))
new_decision = json.load(open("$JSON_INPUT"))
# Ensure required fields
for field in ["id", "question", "category"]:
    if field not in new_decision:
        print(f"ERROR: missing field '{field}' in decision JSON", file=sys.stderr)
        sys.exit(1)
new_decision.setdefault("status", "pending")
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
  ;;

status)
  bundle_exists || { echo "No decision-bundle.json for $EPIC_ID"; exit 0; }
  python3 - <<PYEOF
import json
bundle = json.load(open("$BUNDLE_FILE"))
s = bundle.get("summary", {})
print(f"Decision Bundle: $EPIC_ID ({bundle.get('stage','?')})")
print(f"  must_confirm: {s.get('must_confirm', 0)}")
print(f"  assumable:    {s.get('assumable', 0)}")
print(f"  deferrable:   {s.get('deferrable', 0)}")
print(f"  interrupts consumed: {s.get('interrupts_consumed', 0)}")
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
        d["resolved_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        found = True
        break
if not found:
    print(f"ERROR: decision $DEC_ID not found", file=sys.stderr)
    exit(1)
with open("$BUNDLE_FILE", "w") as f:
    json.dump(bundle, f, indent=2, ensure_ascii=False)
print(f"Resolved $DEC_ID: $RESOLUTION")
PYEOF
  ;;

packet)
  bundle_exists || { echo "No bundle file" >&2; exit 1; }
  REMAINING=$(budget_remaining)
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
    "epic": "$EPIC_ID",
    "interrupt_number": bundle.get("summary", {}).get("interrupts_consumed", 0) + 1,
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
        "deadline": d.get("deadline", "before next stage")
    })

with open("$PACKET_FILE", "w") as f:
    json.dump(packet, f, indent=2, ensure_ascii=False)
print(f"Generated decision-packet.json with {len(packet['questions'])} question(s)")
print(f"Interrupt budget remaining after this packet: {remaining - 1}")
PYEOF
  ;;

*)
  echo "Unknown command: $COMMAND" >&2
  echo "Commands: generate | add | status | resolve | packet" >&2
  exit 1
  ;;
esac
