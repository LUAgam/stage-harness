#!/usr/bin/env bash
# eval-patch.sh — JIT Evolution Patch Evaluator
# 对 candidate patch 做第一段验证：结构校验 + counterfactual 可行性检查
#
# 用法：
#   eval-patch.sh --patch-id <id> [--epic-id <epic-id>]
#
# 退出码：
#   0 — 通过基础校验
#   1 — 校验失败或补丁有问题
#   2 — 错误（缺参数、文件不存在）

set -euo pipefail

HARNESS_DIR=".harness"
HARNESSCTL="${CLAUDE_PLUGIN_ROOT:-../stage-harness}/scripts/harnessctl"

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
PATCH_ID=""
EPIC_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --patch-id) PATCH_ID="$2"; shift 2 ;;
    --epic-id)  EPIC_ID="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$PATCH_ID" ]] && { echo "error: --patch-id required" >&2; exit 2; }

# ---------------------------------------------------------------------------
# 定位文件
# ---------------------------------------------------------------------------
PATCH_DIR="$HARNESS_DIR/memory/candidate-patches/$PATCH_ID"
PATCH_MD="$PATCH_DIR/candidate-patch.md"
PATCH_META="$PATCH_DIR/meta.json"

[[ -f "$PATCH_MD" ]]   || { echo "error: candidate-patch.md not found: $PATCH_MD" >&2; exit 2; }
[[ -f "$PATCH_META" ]] || { echo "error: meta.json not found: $PATCH_META" >&2; exit 2; }

echo "=== eval-patch: $PATCH_ID ==="
echo ""

# ---------------------------------------------------------------------------
# Check 1: 结构校验 — frontmatter 完整性
# ---------------------------------------------------------------------------
echo "[1/4] Frontmatter structure check..."

python3 - <<PYEOF
import sys, re

text = open("$PATCH_MD", encoding="utf-8").read()

# Check frontmatter exists
if not text.startswith("---"):
    print("  ❌ Missing frontmatter (no leading ---)")
    sys.exit(1)

end = text.find("---", 3)
if end == -1:
    print("  ❌ Frontmatter not closed")
    sys.exit(1)

fm = text[3:end]

required_keys = ["id", "status", "scope", "kind", "epic_id"]
missing = [k for k in required_keys if not re.search(rf"^{k}:", fm, re.MULTILINE)]
if missing:
    print(f"  ❌ Missing frontmatter keys: {missing}")
    sys.exit(1)

required_sections = [
    "## Incident",
    "## Expected Behavior",
    "## Observed Behavior",
    "## Proposed Rule",
    "## Apply When",
]
missing_secs = [s for s in required_sections if s not in text]
if missing_secs:
    print(f"  ❌ Missing required sections: {missing_secs}")
    sys.exit(1)

# Check proposed rule is non-empty
m = re.search(r"## Proposed Rule\s+(.*?)(?=\n##|\Z)", text, re.DOTALL)
if not m or not m.group(1).strip():
    print("  ❌ Proposed Rule section is empty")
    sys.exit(1)

print("  ✅ Frontmatter and sections OK")
PYEOF

echo ""

# ---------------------------------------------------------------------------
# Check 2: 作用域与 stage 一致性
# ---------------------------------------------------------------------------
echo "[2/4] Scope and stage compatibility check..."

python3 - <<PYEOF
import json, sys

meta = json.load(open("$PATCH_META", encoding="utf-8"))
scope = meta.get("scope", "")
status = meta.get("status", "")
kind = meta.get("kind", "")

valid_scopes = {"epic-local", "project-active"}
valid_kinds = {
    "prompt_rule", "assumption_rule", "orchestration_rule",
    "guard_tuning", "project_pattern", "source_change_proposal"
}
valid_statuses = {"candidate", "active_epic", "shadow_validating", "ready_for_project",
                  "project_active", "plugin_proposal", "archived", "reverted"}

issues = []
if scope not in valid_scopes:
    issues.append(f"Unknown scope '{scope}' (expected: {valid_scopes})")
if kind not in valid_kinds:
    issues.append(f"Unknown kind '{kind}' (expected: {valid_kinds})")
if status not in valid_statuses:
    issues.append(f"Unknown status '{status}'")
if kind == "source_change_proposal" and status != "candidate":
    issues.append("source_change_proposal should stay as candidate until plugin review")

if issues:
    for i in issues:
        print(f"  ❌ {i}")
    sys.exit(1)

print(f"  ✅ scope={scope}  kind={kind}  status={status}")
PYEOF

echo ""

# ---------------------------------------------------------------------------
# Check 3: 不与现有激活规则重复
# ---------------------------------------------------------------------------
echo "[3/4] Duplicate rule check..."

if [[ -x "$HARNESSCTL" ]] && [[ -n "$EPIC_ID" ]]; then
  python3 - <<PYEOF
import json, sys, os, re

patch_text = open("$PATCH_MD", encoding="utf-8").read()
m = re.search(r"## Proposed Rule\s+(.*?)(?=\n##|\Z)", patch_text, re.DOTALL)
proposed = m.group(1).strip().lower() if m else ""

harnessctl = "$HARNESSCTL"
import subprocess
result = subprocess.run(
    [harnessctl, "patch", "list", "--scope", "all", "--json"],
    capture_output=True, text=True, cwd="."
)
if result.returncode != 0:
    print("  ⚠️  Could not check existing patches (harnessctl unavailable)")
    sys.exit(0)

patches = json.loads(result.stdout or "[]")
active = [p for p in patches if p.get("status") in ("active_epic", "project_active")
          and p.get("id") != "$PATCH_ID"]

duplicates = []
for p in active:
    pid = p.get("id", "")
    # Simple keyword overlap check
    md_path = f".harness/memory/candidate-patches/{pid}/candidate-patch.md"
    if not os.path.exists(md_path):
        continue
    other_text = open(md_path, encoding="utf-8").read().lower()
    om = re.search(r"## proposed rule\s+(.*?)(?=\n##|\Z)", other_text, re.DOTALL)
    other_proposed = om.group(1).strip().lower() if om else ""
    # Rough overlap: if > 50% of words in new rule appear in existing rule
    words = set(proposed.split())
    other_words = set(other_proposed.split())
    if words and len(words & other_words) / len(words) > 0.6:
        duplicates.append(pid)

if duplicates:
    print(f"  ⚠️  Potential overlap with active patches: {duplicates}")
    print(f"     Review before applying to avoid context bloat.")
else:
    print(f"  ✅ No significant overlap with {len(active)} active patches")
PYEOF
else
  echo "  ⚠️  Skipped (harnessctl unavailable or no epic_id)"
fi

echo ""

# ---------------------------------------------------------------------------
# Check 4: Counterfactual summary output
# ---------------------------------------------------------------------------
echo "[4/4] Counterfactual assessment summary..."

python3 - <<PYEOF
import json, re, sys

meta = json.load(open("$PATCH_META", encoding="utf-8"))
patch_text = open("$PATCH_MD", encoding="utf-8").read()

m_rule = re.search(r"## Proposed Rule\s+(.*?)(?=\n##|\Z)", patch_text, re.DOTALL)
m_when = re.search(r"## Apply When\s+(.*?)(?=\n##|\Z)", patch_text, re.DOTALL)
m_notes = re.search(r"## Validation Notes\s+(.*?)(?=\n##|\Z)", patch_text, re.DOTALL)

rule = m_rule.group(1).strip() if m_rule else "(empty)"
when = m_when.group(1).strip() if m_when else "(empty)"
notes = m_notes.group(1).strip() if m_notes else "(not specified)"

print(f"  Proposed Rule:")
for line in rule.splitlines()[:5]:
    print(f"    {line}")
print(f"")
print(f"  Apply When: {when[:120]}")
print(f"  Shadow Validation Target: {notes[:120]}")
print(f"")
print(f"  ✅ Counterfactual check requires live shadow observation.")
print(f"     To start: harnessctl patch apply $PATCH_ID --scope epic")
print(f"     Then run the epic and observe via: harnessctl patch observe $PATCH_ID --epic-id <id> --prevented-repeat true/false")
PYEOF

echo ""
echo "=== eval-patch complete: $PATCH_ID ==="
echo ""
echo "If all checks passed:"
echo "  harnessctl patch apply $PATCH_ID [--scope epic|project]"
