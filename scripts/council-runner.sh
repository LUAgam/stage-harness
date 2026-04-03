#!/usr/bin/env bash
# council-runner.sh — 议会启动与结果汇总
# 用法: council-runner.sh <council-type> <epic-id>
# council-type: light | plan | acceptance | release
# 退出码: 0=PASS/GO/READY/RELEASE_READY, 1=BLOCK/FAIL/NOT_READY, 2=REVISE/HOLD/CONDITIONS

set -euo pipefail

COUNCIL_TYPE="${1:-}"
EPIC_ID="${2:-}"
HARNESS_DIR="${HARNESS_DIR:-.harness}"

if [[ -z "$COUNCIL_TYPE" || -z "$EPIC_ID" ]]; then
  echo "usage: council-runner.sh <light|plan|acceptance|release> <epic-id>" >&2
  exit 1
fi

FEATURES_DIR="$HARNESS_DIR/features/$EPIC_ID"
COUNCILS_DIR="$FEATURES_DIR/councils"
mkdir -p "$COUNCILS_DIR"

VERDICT_FILE="$COUNCILS_DIR/verdict-${COUNCIL_TYPE}.json"

# ── Council 配置 ─────────────────────────────────────────────────────
declare -A COUNCIL_PASS_VERDICTS
COUNCIL_PASS_VERDICTS[light]="GO"
COUNCIL_PASS_VERDICTS[plan]="READY READY_WITH_CONDITIONS"
COUNCIL_PASS_VERDICTS[acceptance]="PASS"
COUNCIL_PASS_VERDICTS[release]="RELEASE_READY RELEASE_WITH_CONDITIONS"

declare -A COUNCIL_FAIL_VERDICTS
COUNCIL_FAIL_VERDICTS[light]="HOLD"
COUNCIL_FAIL_VERDICTS[plan]="BLOCK"
COUNCIL_FAIL_VERDICTS[acceptance]="FAIL"
COUNCIL_FAIL_VERDICTS[release]="NOT_READY"

declare -A COUNCIL_AGENTS
COUNCIL_AGENTS[light]="plan-reviewer logic-reviewer challenger"
COUNCIL_AGENTS[plan]="plan-reviewer logic-reviewer security-reviewer test-reviewer challenger"
COUNCIL_AGENTS[acceptance]="code-reviewer logic-reviewer security-reviewer test-reviewer"
COUNCIL_AGENTS[release]="release-reviewer security-reviewer quality-auditor"

AGENTS="${COUNCIL_AGENTS[$COUNCIL_TYPE]:-}"
if [[ -z "$AGENTS" ]]; then
  echo "ERROR: Unknown council type: $COUNCIL_TYPE" >&2
  exit 1
fi

echo "=== Council: $COUNCIL_TYPE for $EPIC_ID ==="
echo ""
echo "Agents: $AGENTS"
echo "Verdict file: $VERDICT_FILE"
echo ""

# ── 检查已有裁决 ─────────────────────────────────────────────────────
if [[ -f "$VERDICT_FILE" ]]; then
  echo "ℹ️  Existing verdict found:"
  python3 - <<PYEOF
import json
v = json.load(open("$VERDICT_FILE"))
print(f"  Verdict: {v.get('verdict', '?')}")
print(f"  Timestamp: {v.get('timestamp', '?')}")
issues = v.get('blocking_issues', [])
if issues:
    print(f"  Blocking issues ({len(issues)}):")
    for i in issues:
        print(f"    - {i}")
PYEOF
  VERDICT=$(python3 -c "import json; print(json.load(open('$VERDICT_FILE')).get('verdict','UNKNOWN'))" 2>/dev/null)
else
  echo "No verdict yet — agents must run and write to: $VERDICT_FILE"
  echo ""
  echo "Expected agent workflow:"
  echo "  Each reviewer agent reads the artifacts and writes its vote."
  echo "  Then call: council-runner.sh $COUNCIL_TYPE $EPIC_ID --aggregate"
  VERDICT="PENDING"
fi

# ── 聚合子命令 ───────────────────────────────────────────────────────
SUBCOMMAND="${3:-}"

if [[ "$SUBCOMMAND" == "--aggregate" ]]; then
  # 聚合各 reviewer 的 vote 文件
  VOTES_DIR="$COUNCILS_DIR/votes-${COUNCIL_TYPE}"
  if [[ ! -d "$VOTES_DIR" ]]; then
    echo "ERROR: No votes directory at $VOTES_DIR" >&2
    exit 1
  fi

  python3 - <<PYEOF
import json, os, datetime, glob

votes_dir = "$VOTES_DIR"
vote_files = glob.glob(f"{votes_dir}/*.json")

if not vote_files:
    print("ERROR: No vote files found", flush=True)
    exit(1)

votes = []
for vf in vote_files:
    try:
        v = json.load(open(vf))
        votes.append(v)
    except Exception as e:
        print(f"Warning: could not parse {vf}: {e}")

# Count verdicts
pass_verdicts = "${COUNCIL_PASS_VERDICTS[$COUNCIL_TYPE]}".split()
fail_verdicts = "${COUNCIL_FAIL_VERDICTS[$COUNCIL_TYPE]}".split()

total = len(votes)
pass_count = sum(1 for v in votes if v.get("verdict") in pass_verdicts)
fail_count = sum(1 for v in votes if v.get("verdict") in fail_verdicts)
other_count = total - pass_count - fail_count

blocking_issues = []
warnings = []
for v in votes:
    blocking_issues.extend(v.get("blocking_issues", []))
    warnings.extend(v.get("warnings", []))

# Determine final verdict
if fail_count > 0:
    final_verdict = fail_verdicts[0]
elif pass_count == total:
    final_verdict = pass_verdicts[0]
elif other_count > 0 and len(pass_verdicts) > 1:
    final_verdict = pass_verdicts[1]  # e.g. READY_WITH_CONDITIONS
else:
    final_verdict = pass_verdicts[0]

result = {
    "epic": "$EPIC_ID",
    "council": "$COUNCIL_TYPE",
    "verdict": final_verdict,
    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    "vote_summary": {"total": total, "pass": pass_count, "fail": fail_count, "other": other_count},
    "blocking_issues": blocking_issues,
    "warnings": warnings
}

with open("$VERDICT_FILE", "w") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"Council verdict: {final_verdict}")
print(f"  Votes: {pass_count}/{total} pass, {fail_count} fail")
if blocking_issues:
    print(f"  Blocking issues ({len(blocking_issues)}):")
    for i in blocking_issues:
        print(f"    - {i}")
if warnings:
    print(f"  Warnings ({len(warnings)}):")
    for w in warnings:
        print(f"    - {w}")
PYEOF

  # 返回退出码
  VERDICT=$(python3 -c "import json; print(json.load(open('$VERDICT_FILE')).get('verdict','UNKNOWN'))" 2>/dev/null)
fi

# ── 退出码 ───────────────────────────────────────────────────────────
FAIL_V="${COUNCIL_FAIL_VERDICTS[$COUNCIL_TYPE]}"

if echo "$FAIL_V" | grep -qw "$VERDICT"; then
  echo ""
  echo "❌ Council BLOCKED: $VERDICT"
  exit 1
elif [[ "$VERDICT" == "PENDING" ]]; then
  echo ""
  echo "⏳ Verdict pending — run agents first, then: $0 $COUNCIL_TYPE $EPIC_ID --aggregate"
  exit 2
else
  echo ""
  echo "✅ Council PASSED: $VERDICT"
  exit 0
fi
