# Stage-Harness 插件

> 阶段化 AI 开发 Harness — 从模糊需求到交付的端到端 Claude Code 插件

## 概述

Stage-Harness 是一个 Claude Code 插件，为 AI 辅助软件开发提供**结构化的阶段流水线**。它将一个模糊的需求（"我想加个权限系统"）转化为完整的交付产物，全程通过状态机、产物门禁、中断预算和议会审查来保证质量。

## 设计理念

### 三层架构

```
┌─────────────────────────────────────────┐
│           编排层 (Orchestration)          │
│  commands/*.md — 阶段 slash（`/stage-harness:harness-*`），驱动流水线 │
│  agents/*.md   — 22 个专业 Agent 角色      │
├─────────────────────────────────────────┤
│         集成插件层 (Integration)           │
│  skills/*/SKILL.md — 18 个可复用技能       │
│  hooks/hooks.json  — 6 个钩子点           │
│  templates/        — 产物模板             │
├─────────────────────────────────────────┤
│           控制层 (Control)               │
│  harnessctl.py     — 核心 CLI 状态机      │
│  decision-bundle.sh — 决策包 CRUD         │
│  unknowns-ledger-update.sh — 未知台账     │
│  verify-artifacts.sh — 产物验证           │
└─────────────────────────────────────────┘
```

- **编排层**：定义"做什么"——每个阶段执行哪些步骤、调用哪些 Agent
- **集成插件层**：定义"怎么做"——具体的技能指导、钩子触发、模板格式
- **控制层**：定义"能不能做"——状态转移合法性、产物完整性检查、预算消耗

### 核心原则

1. **阶段门禁 (Stage Gate)**：每个阶段必须产出指定产物才能推进到下一阶段
2. **中断预算 (Interrupt Budget)**：限制向用户提问次数，按风险等级自动分配
3. **决策包 (Decision Bundle)**：所有假设和决策集中管理，必须确认的打包为 Decision Packet
4. **议会审查 (Council)**：关键节点由多 Agent 投票审查，避免单一视角偏差

## 7 阶段流水线

```
IDEA → CLARIFY → SPEC → PLAN → EXECUTE → VERIFY → DONE
                                  ↑          ↓
                                  ←── FIX ←──┘
```

| 阶段 | 目标 | 核心命令 | 关键产物 |
|------|------|---------|---------|
| **IDEA** | 接收原始需求 | `/stage-harness:harness-start` | — |
| **CLARIFY** | 需求澄清与风险评估 | `/stage-harness:harness-clarify` | clarification-notes.md, impact-scan.md, unknowns-ledger.json, decision-bundle.json, decision-packet.json |
| **SPEC** | 生成规格说明 | `/stage-harness:harness-spec` | specs/{epic-id}.md, spec-council-notes.md |
| **PLAN** | 任务分解与覆盖矩阵 | `/stage-harness:harness-plan` | bridge-spec.md, coverage-matrix.json |
| **EXECUTE** | TDD 实现 | `/stage-harness:harness-work` | receipts/ |
| **VERIFY** | 多维度审查 | `/stage-harness:harness-review` | verification.json |
| **FIX** | 修复问题 | `/stage-harness:harness-fix` | — (回到 VERIFY) |
| **DONE** | 交付与知识沉淀 | `/stage-harness:harness-done` | delivery-summary.md, release-notes.md |
| **PATCH** | 即时纠偏(任意阶段) | `/stage-harness:harness-patch` | incident-summary.json, candidate-patch.md |

## 核心概念

### Decision Bundle（决策包）

在 CLARIFY 阶段，所有决策按类型归类：

| 类型 | 含义 | 处理方式 |
|------|------|---------|
| `must_confirm` | 必须用户确认 | 打包进 Decision Packet，消耗中断预算 |
| `assumable` | 可安全假设 | 记录假设，不打扰用户 |
| `deferrable` | 可延后决定 | 标记为 pending，后续阶段按需处理 |

### Interrupt Budget（中断预算）

按 `risk_level` 自动分配向用户提问的次数上限：

| 风险等级 | 预算 |
|---------|------|
| low | 1 次 |
| medium | 2 次 |
| high | 3 次 |

用尽后只能假设，不再打扰用户。

### Council（议会）

4 种议会类型，在不同阶段进行多 Agent 投票：

| 议会 | 阶段 | 参与 Agent |
|------|------|-----------|
| light_council | SPEC | challenger, requirement-analyst, impact-analyst |
| plan_council | PLAN | code-reviewer, security-reviewer, logic-reviewer, test-reviewer, plan-reviewer |
| acceptance_council | VERIFY | code-reviewer, logic-reviewer, security-reviewer, test-reviewer, runtime-auditor |
| release_council | DONE | logic-reviewer, security-reviewer, runtime-auditor（高风险可追加 code-reviewer） |

### Stage Gate（阶段门禁）

每个阶段有必须产出的产物列表。执行 `$HARNESSCTL stage-gate check` 验证产物完整性，不通过则阻止状态转移。

## 目录结构

插件安装后，在项目根目录创建 `.harness/` 目录：

```
.harness/
├── config.json              # 全局配置（版本、风险等级、中断预算等）
├── project-profile.yaml     # 项目画像（类型、技术栈、风险等级）
├── surfaces/                # 项目表面分析缓存
├── features/                # Epic 特性目录
│   └── sh-1-feature-name/   # 单个 Epic 的全部产物
│       ├── state.json       # 状态机（当前阶段、预算、时间戳）
│       ├── domain-frame.json      # CLARIFY：domain-scout
│       ├── generated-scenarios.json # CLARIFY：scenario-expander
│       ├── scenario-coverage.json   # CLARIFY：Semantic Reconciliation
│       ├── challenge-report.md    # CLARIFY：challenger
│       ├── clarification-notes.md
│       ├── impact-scan.md
│       ├── unknowns-ledger.json
│       ├── decision-bundle.json
│       ├── decision-packet.json
│       ├── surface-map.md
│       ├── bridge-spec.md
│       ├── coverage-matrix.json
│       ├── verification.json
│       ├── delivery-summary.md
│       ├── release-notes.md
│       └── receipts/        # 任务执行回执
├── epics/                   # Epic 元数据 JSON
├── specs/                   # 规格说明书
├── tasks/                   # 任务 JSON
└── memory/                  # 经验沉淀（pitfalls.md 等）
```

## 快速上手

仓库根目录 [README.md](../README.md) 汇总了**安装、命令表、手动/自治/JIT 流程与 CLI 速查**。下面是最小闭环示例。

```bash
# 1. 安装插件：将整个仓库作为插件根；Claude CLI 示例（路径换成本机克隆目录）：
#    claude --plugin-dir /opt/agent-delivery-claude/stage-harness
#    需 chmod +x scripts/harnessctl.py scripts/*.sh

# 2. 若未安装到 PATH，在被开发项目根目录指定 CLI（二选一）
#    插件为独立克隆、与项目分离时（推荐绝对路径，与 --plugin-dir 一致）：
export HARNESSCTL=/opt/agent-delivery-claude/stage-harness/scripts/harnessctl
#    插件在被开发仓库的子目录 stage-harness/ 时：
# export HARNESSCTL="${HARNESSCTL:-./stage-harness/scripts/harnessctl}"

# 3. 启动新 Epic（会初始化 .harness/ 并进入 CLARIFY；编排见 commands/harness-start.md）
/stage-harness:harness-start 我想给系统加一个 RBAC 权限管理模块

# 4. 查看状态
/stage-harness:harness-status

# 5a. 手动推进：按阶段依次执行 harness-clarify → spec → plan → work → review →（fix）→ done（slash 均为 /stage-harness:harness-*）

# 5b. 自治模式（自动推进所有阶段直到 DONE）
/stage-harness:harness-auto
```

详细使用说明（各命令产物、CLARIFY 六轴、多仓、CodeMap、metrics、FAQ）参见 [usage.md](./usage.md)。
架构与实现细节参见 [architecture.md](./architecture.md)。
人类开发流程、阶段并串行与「通用性优先」关注点参见 [human-workflow-and-orchestration.md](./human-workflow-and-orchestration.md)。
