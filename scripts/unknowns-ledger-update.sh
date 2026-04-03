#!/usr/bin/env bash
# unknowns-ledger-update.sh — Unknowns Ledger 更新工具
# 用法:
#   unknowns-ledger-update.sh init <epic-id>
#   unknowns-ledger-update.sh add <epic-id> <json-file>
#   unknowns-ledger-update.sh resolve <epic-id> <unk-id> <resolution>
#   unknowns-ledger-update.sh status <epic-id>
#   unknowns-ledger-update.sh sift <epic-id>   # DONE阶段：沉淀为问题模式

set -euo pipefail

COMMAND="${1:-status}"
EPIC_ID="${2:-}"
HARNESS_DIR="${HARNESS_DIR:-.harness}"

if [[ -z "$EPIC_ID" ]]; then
  echo "usage: unknowns-ledger-update.sh <command> <epic-id> [args]" >&2
  exit 1
fi

FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"
LEDGER_FILE="$FEATURES_DIR/unknowns-ledger.json"
MEMORY_DIR="$HARNESS_DIR/memory"

mkdir -p "$FEATURES_DIR" "$MEMORY_DIR"

# ── Commands ────────────────────────────────────────────────────────
case "$COMMAND" in

init)
  if [[ -f "$LEDGER_FILE" ]]; then
    echo "ℹ️  unknowns-ledger.json already exists for $EPIC_ID"
    exit 0
  fi
  python3 - <<PYEOF
import json, datetime
ledger = {
    "epic_id": "$EPIC_ID",
    "version": "4.3",
    "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    "entries": [],
    "summary": {
        "total": 0,
        "open": 0,
        "resolved_in_spec": 0,
        "resolved_in_plan": 0,
        "resolved_in_verify": 0,
        "deferred": 0
    }
}
with open("$LEDGER_FILE", "w") as f:
    json.dump(ledger, f, indent=2, ensure_ascii=False)
print("Initialized unknowns-ledger.json for $EPIC_ID")
PYEOF
  ;;

add)
  JSON_INPUT="${3:-}"
  [[ -z "$JSON_INPUT" ]] && { echo "usage: add <epic-id> <json-file>" >&2; exit 1; }
  [[ -f "$LEDGER_FILE" ]] || { echo "Run 'init' first" >&2; exit 1; }

  python3 - <<PYEOF
import json, sys, datetime

ledger = json.load(open("$LEDGER_FILE"))
new_entry = json.load(open("$JSON_INPUT"))

# Validate required fields
for field in ["id", "description", "discovered_at"]:
    if field not in new_entry:
        print(f"ERROR: missing field '{field}'", file=sys.stderr)
        sys.exit(1)

# Set defaults
new_entry.setdefault("status", "open")
new_entry.setdefault("impact", "medium")
new_entry.setdefault("classification", "deferrable")
new_entry.setdefault("resolution", None)
new_entry.setdefault("resolved_at", None)
new_entry.setdefault("spec_entry", None)
new_entry.setdefault("task_id", None)
new_entry.setdefault("verification", None)
new_entry.setdefault("evidence_path", None)

# Check for duplicate IDs
existing_ids = {e["id"] for e in ledger["entries"]}
if new_entry["id"] in existing_ids:
    print(f"WARNING: {new_entry['id']} already exists, updating instead")
    ledger["entries"] = [e for e in ledger["entries"] if e["id"] != new_entry["id"]]

ledger["entries"].append(new_entry)

# Recompute summary
entries = ledger["entries"]
ledger["summary"]["total"] = len(entries)
ledger["summary"]["open"] = sum(1 for e in entries if e.get("status") == "open")
ledger["summary"]["resolved_in_spec"] = sum(1 for e in entries if e.get("resolved_at_stage") == "SPEC")
ledger["summary"]["resolved_in_plan"] = sum(1 for e in entries if e.get("resolved_at_stage") == "PLAN")
ledger["summary"]["resolved_in_verify"] = sum(1 for e in entries if e.get("resolved_at_stage") == "VERIFY")
ledger["summary"]["deferred"] = sum(1 for e in entries if e.get("classification") == "deferrable")

with open("$LEDGER_FILE", "w") as f:
    json.dump(ledger, f, indent=2, ensure_ascii=False)
print(f"Added {new_entry['id']} to ledger (status: {new_entry['status']}, impact: {new_entry['impact']})")
PYEOF
  ;;

resolve)
  UNK_ID="${3:-}"
  RESOLUTION="${4:-resolved}"
  STAGE="${5:-}"
  [[ -z "$UNK_ID" ]] && { echo "usage: resolve <epic-id> <unk-id> <resolution> [stage]" >&2; exit 1; }
  [[ -f "$LEDGER_FILE" ]] || { echo "No ledger file" >&2; exit 1; }

  python3 - <<PYEOF
import json, datetime

ledger = json.load(open("$LEDGER_FILE"))
found = False
for entry in ledger["entries"]:
    if entry["id"] == "$UNK_ID":
        entry["status"] = "resolved"
        entry["resolution"] = "$RESOLUTION"
        entry["resolved_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        if "$STAGE":
            entry["resolved_at_stage"] = "$STAGE"
        found = True
        break

if not found:
    print(f"ERROR: unknown $UNK_ID not found in ledger")
    exit(1)

# Recompute summary
entries = ledger["entries"]
ledger["summary"]["open"] = sum(1 for e in entries if e.get("status") == "open")
ledger["summary"]["resolved_in_spec"] = sum(1 for e in entries if e.get("resolved_at_stage") == "SPEC")
ledger["summary"]["resolved_in_plan"] = sum(1 for e in entries if e.get("resolved_at_stage") == "PLAN")
ledger["summary"]["resolved_in_verify"] = sum(1 for e in entries if e.get("resolved_at_stage") == "VERIFY")

with open("$LEDGER_FILE", "w") as f:
    json.dump(ledger, f, indent=2, ensure_ascii=False)
print(f"Resolved $UNK_ID: $RESOLUTION")
print(f"Open unknowns remaining: {ledger['summary']['open']}")
PYEOF
  ;;

status)
  if [[ ! -f "$LEDGER_FILE" ]]; then
    echo "No unknowns-ledger.json for $EPIC_ID"
    exit 0
  fi
  python3 - <<PYEOF
import json

ledger = json.load(open("$LEDGER_FILE"))
s = ledger.get("summary", {})
entries = ledger.get("entries", [])

print(f"Unknowns Ledger: $EPIC_ID")
print(f"  Total:    {s.get('total', 0)}")
print(f"  Open:     {s.get('open', 0)}")
print(f"  Deferred: {s.get('deferred', 0)}")
print(f"  Resolved in SPEC:   {s.get('resolved_in_spec', 0)}")
print(f"  Resolved in PLAN:   {s.get('resolved_in_plan', 0)}")
print(f"  Resolved in VERIFY: {s.get('resolved_in_verify', 0)}")

open_entries = [e for e in entries if e.get("status") == "open"]
if open_entries:
    print(f"\n  Open items:")
    for e in open_entries:
        impact = e.get("impact", "?")
        print(f"    [{impact.upper()[:1]}] {e['id']}: {e['description'][:60]}...")
PYEOF
  ;;

sift)
  # DONE阶段：将本 epic 的问题模式沉淀到 .harness/memory/
  [[ -f "$LEDGER_FILE" ]] || { echo "No ledger file" >&2; exit 0; }
  PITFALLS_FILE="$MEMORY_DIR/pitfalls.md"

  python3 - <<PYEOF
import json, datetime

ledger = json.load(open("$LEDGER_FILE"))
entries = ledger.get("entries", [])

# 提取高价值模式：impact=high 且已在 CLARIFY 发现的条目
patterns = [
    e for e in entries
    if e.get("impact") in ["high", "critical"]
    and e.get("discovered_at") == "CLARIFY"
]

if not patterns:
    print("No high-impact CLARIFY patterns to sift")
    exit(0)

# 追加到 pitfalls.md
today = datetime.date.today().isoformat()
lines = [f"\n## Epic: $EPIC_ID ({today})\n"]
for p in patterns:
    lines.append(f"- **{p['id']}** [{p.get('impact','?').upper()}] {p['description']}")
    if p.get("resolution"):
        lines.append(f"  - Resolution: {p['resolution']}")
    if p.get("classification"):
        lines.append(f"  - Category: {p['classification']}")
    lines.append("")

with open("$PITFALLS_FILE", "a") as f:
    f.write("\n".join(lines))

print(f"Sifted {len(patterns)} pattern(s) into memory/pitfalls.md")
PYEOF
  ;;

*)
  echo "Unknown command: $COMMAND" >&2
  echo "Commands: init | add | resolve | status | sift" >&2
  exit 1
  ;;
esac
