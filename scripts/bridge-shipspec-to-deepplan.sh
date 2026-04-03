#!/usr/bin/env bash
# bridge-shipspec-to-deepplan.sh
#
# Usage: bridge-shipspec-to-deepplan.sh <feature-name> <epic-id>
# Reads: .shipspec/planning/{feature}/PRD.md, SDD.md, TASKS.json
# Reads: .harness/features/{epic-id}/unknowns-ledger.json
# Writes: .harness/features/{epic-id}/bridge-spec.md

set -euo pipefail

FEATURE="${1:-}"
EPIC_ID="${2:-}"

if [[ -z "$FEATURE" || -z "$EPIC_ID" ]]; then
  echo "Usage: bridge-shipspec-to-deepplan.sh <feature-name> <epic-id>" >&2
  exit 1
fi

PLANNING_DIR=".shipspec/planning/${FEATURE}"
HARNESS_DIR=".harness/features/${EPIC_ID}"
OUTPUT="${HARNESS_DIR}/bridge-spec.md"

# 检查必须的源文件
for f in "${PLANNING_DIR}/PRD.md" "${PLANNING_DIR}/SDD.md"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing: $f" >&2
    exit 1
  fi
done

mkdir -p "$HARNESS_DIR"

# 生成 bridge-spec.md
cat > "$OUTPUT" << 'BRIDGE_EOF'
# Bridge Spec: Implementation Plan Input

Generated from ShipSpec artifacts for deep-plan consumption.

BRIDGE_EOF

echo "## Requirements (from PRD)" >> "$OUTPUT"
echo "" >> "$OUTPUT"
cat "${PLANNING_DIR}/PRD.md" >> "$OUTPUT"
echo "" >> "$OUTPUT"

echo "## Technical Design (from SDD)" >> "$OUTPUT"
echo "" >> "$OUTPUT"
cat "${PLANNING_DIR}/SDD.md" >> "$OUTPUT"
echo "" >> "$OUTPUT"

if [[ -f "${PLANNING_DIR}/TASKS.json" ]]; then
  echo "## Task Breakdown (from TASKS.json)" >> "$OUTPUT"
  echo '```json' >> "$OUTPUT"
  cat "${PLANNING_DIR}/TASKS.json" >> "$OUTPUT"
  echo '```' >> "$OUTPUT"
  echo "" >> "$OUTPUT"
fi

if [[ -f "${HARNESS_DIR}/unknowns-ledger.json" ]]; then
  echo "## Open Unknowns (must be addressed in plan)" >> "$OUTPUT"
  echo '```json' >> "$OUTPUT"
  cat "${HARNESS_DIR}/unknowns-ledger.json" >> "$OUTPUT"
  echo '```' >> "$OUTPUT"
fi

echo "Bridge spec written to: $OUTPUT"
