---
description: "交付沉淀（发布议会 + 交付包 + 问题模式沉淀 + 候选 Skill 挖掘）"
argument-hint: "<epic-id>"
---

# harness-done

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，先解析本地 CLI 路径：

```bash
if [ -z "${HARNESSCTL:-}" ]; then
  candidates=(
    "./stage-harness/scripts/harnessctl"
    "../stage-harness/scripts/harnessctl"
    "$(git rev-parse --show-toplevel 2>/dev/null)/stage-harness/scripts/harnessctl"
  )

  for candidate in "${candidates[@]}"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      HARNESSCTL="$candidate"
      break
    fi
  done
fi

test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "harnessctl not found. Set HARNESSCTL=/abs/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}
```


执行交付沉淀阶段。通过发布议会裁决，生成交付包，沉淀问题模式，挖掘候选 Skill，最终标记 epic 为 DONE。

## 角色定义

DONE 阶段 orchestrator。负责验证 VERIFY 通过、编排发布议会、触发交付包生成、执行知识沉淀。是 epic 生命周期的最后阶段，须确保所有沉淀操作完成后再标记 DONE。

## 前置检查

验证 VERIFY 阶段通过：

```bash
$HARNESSCTL stage-gate check VERIFY --epic-id <epic-id>
```

必须满足（与 `$HARNESSCTL stage-gate check VERIFY` 一致）：
- `verification.json` 存在且其中 `acceptance_council` 或 `council_verdict` 为 `PASS` 或 `CONDITIONAL_PASS`，**或** `councils/verdict-acceptance_council.json` 中 `verdict` 为 `PASS` 或 `CONDITIONAL_PASS`（兜底）
- 无未解决的 `critical_issues`，且各 review 维度字段若存在则不得为 `FAIL`

若检查失败，提示先完成 `/harness:review <epic-id>`，终止。

## 执行步骤

### Step 1：发布议会

召集 3-4 个 reviewer 并行审查交付完整性：

**REQUIRED SKILL:** Use `council/SKILL.md release_council`

调用参数：
- `epic-id`
- `verification_path`: `.harness/features/<epic-id>/verification.json`

并行 reviewer 构成（与 `skills/council/SKILL.md` 的 `release_council` 一致；3 人核心，高风险可追加 1 人）：

| Reviewer | 审查维度 |
|---------|---------|
| logic-reviewer | 业务逻辑与场景闭合、残留逻辑风险 |
| security-reviewer | 无遗留安全问题、敏感面收口 |
| runtime-auditor | 运行时行为、spec/实现一致性、回执与证据链 |
| code-reviewer（高风险追加） | 变更面与代码质量复核 |

议会裁决：
- `RELEASE_READY`：所有维度通过，可标记 DONE
- `RELEASE_WITH_CONDITIONS`：有低/中优先级待处理，记录在案，可继续
- `NOT_READY`：有阻断性问题，必须修复

若裁决为 `NOT_READY`，展示阻断问题并终止。

### Step 2：生成交付包

生成两份交付文档：

**delivery-summary.md**（写入 `.harness/features/<epic-id>/delivery-summary.md`）：
- Epic 标题和目标
- 最终实现的功能列表
- 技术决策摘要
- 偏差记录（与原始规格的差异）
- 运行时指标汇总（覆盖率、smoke 通过率、总耗时）

**release-notes.md**（写入 `.harness/features/<epic-id>/release-notes.md`）：
- 版本信息
- 新增功能（用户视角）
- 变更影响（Breaking changes 或迁移步骤）
- 已知限制

### Step 3：问题模式沉淀

读取 `unknowns-ledger.json`，将本次 epic 遭遇的问题类型写入全局记忆：

```bash
$HARNESSCTL memory append-pitfalls --epic-id <epic-id>
```

写入路径：`.harness/memory/pitfalls.md`

沉淀格式（追加，不覆盖）：
```markdown
## [日期] <epic-id>: <epic 标题>

**问题类型**: [分类]
**描述**: [问题描述]
**实际解法**: [采用的解决方案]
**预防建议**: [下次如何提前发现]
```

### Step 3b：JIT Patch 效果汇总

检查本次 epic 期间的候选补丁状态：

```bash
$HARNESSCTL patch list --json
```

筛选与本 epic 关联的 patch（`epic_id` 匹配）：

- 若有 `status=active_epic` 且多次运行未出现相同失败事件，提示：
  > 💡 "Patch <id> 本次 epic 表现良好。运行 `harnessctl patch promote <id>` 晋升为项目规则。"
- 若有 `status=candidate` 但始终未 apply，提示：
  > "Patch <id> 未被应用。可运行 `harnessctl patch archive <id>` 归档。"
- 若有 `status=ready_for_project`，明确提示晋升建议。

### Step 4：候选 Skill 挖掘

调用 `skill-miner` agent 分析本次运行记录：

分析目标：
- `.harness/features/<epic-id>/receipts/` 中的 receipt 文件
- `unknowns-ledger.json` 中的问题类型分布
- 本次 epic 中重复出现 3 次以上的操作模式

输出候选 Skill 到：`.harness/memory/candidate-skills/<epic-id>-candidates.json`

置信度 < 0.6 的模式只写为 observation，不提升为候选 Skill。

### Step 4c（可选）：CodeMap 异步补全

若本轮 CLARIFY/PLAN 曾对热点模块做深读且尚未写入长文摘要，可在交付后（不阻塞 DONE）由 Lead 或 `skill-miner` 协同将 **短摘要** 合并为 `.harness/memory/codemaps/<repo_id>/<module_slug>.md`（模板见 `stage-harness/templates/codemap-module.md`）。主链路以同步短记为主；本步为 **可选补全**，用于后续 Epic 复用。若元数据显示与当前分支不一致，应降低 `confidence` 或触发回源核对后再写。

### Step 5：标记 Epic 为 DONE

```bash
$HARNESSCTL state transition <epic-id> DONE
```

## 产物要求

| 产物 | 路径 |
|------|------|
| 交付摘要 | `.harness/features/<epic-id>/delivery-summary.md` |
| 发布说明 | `.harness/features/<epic-id>/release-notes.md` |
| 问题模式 | `.harness/memory/pitfalls.md`（追加） |
| 候选 Skill | `.harness/memory/candidate-skills/<epic-id>-candidates.json` |
| 发布议会裁决 | `.harness/features/<epic-id>/councils/verdict-release_council.json` |

## 出口条件（门禁规则）

- 发布议会裁决为 `RELEASE_READY` 或 `RELEASE_WITH_CONDITIONS`
- 两份交付文档均已生成
- `pitfalls.md` 已更新（追加了本次 epic 的条目）
- Epic 状态已转换为 `DONE`

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| VERIFY 门禁未通过 | 终止，提示先完成审查阶段 |
| 发布议会 NOT_READY | 展示阻断问题，终止，等待修复后重试 |
| skill-miner 失败 | 记录警告，跳过候选 Skill 挖掘，继续执行 |
| pitfalls.md 写入失败 | 记录警告，输出到 stdout，继续执行 |
| state transition 失败 | 展示错误，所有产物已生成，提示手动运行 `$HARNESSCTL state transition <epic-id> DONE` |
