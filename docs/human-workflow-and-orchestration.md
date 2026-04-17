# 人类需求开发流程与 Stage-Harness 对照

本文档把「人类真实做需求开发」的顺序，与 `@stage-harness` 的阶段、命令、产物，以及**串行/并行**关系做一次汇总；并收录当前对插件演进的**关注点**（通用性优先、澄清骨架、增强层等），便于理解与落地。

权威步骤与产物清单仍以 [usage.md](./usage.md) 与 `commands/harness-*.md` 为准；本文是**理解层**的补充说明。

---

## 1. 一句话心智模型

Stage-Harness 把人类开发里「先想清楚再动手」的习惯，外显成**阶段门禁 + 标准产物**：

**想法 → 澄清 → 定规格 → 拆计划 → 实现 → 审查 →（必要时修复）→ 交付沉淀**

对应命令主链：

`/stage-harness:harness-start` → `/stage-harness:harness-clarify` → `/stage-harness:harness-spec` → `/stage-harness:harness-plan` → `/stage-harness:harness-work` → `/stage-harness:harness-review` →（`/stage-harness:harness-fix`）→ `/stage-harness:harness-done`

自治模式可用 `/stage-harness:harness-auto` 按当前阶段循环推进；纠偏可用 `/stage-harness:harness-patch`。详见 [usage.md](./usage.md)。

---

## 2. 人类流程 ↔ 插件阶段（对照表）

| 人类在做什么 | 插件阶段 | 主要命令 | 典型产物（Epic 目录下，节选） |
|--------------|----------|----------|-------------------------------|
| 立项、建档、接住原始描述 | IDEA → CLARIFY | `/stage-harness:harness-start` | `.harness/` 初始化、`project-profile.yaml`、Epic 元数据、`state.json` |
| 把需求说清楚、圈范围、列未知与决策 | CLARIFY | `/stage-harness:harness-clarify` | **默认（full）**：`clarification-notes.md`（含 [六轴澄清覆盖](usage.md) 或极简绕行）、`domain-frame.json`、`requirements-draft.md`、`impact-scan.md`、`surface-routing.json`、`challenge-report.md`、`generated-scenarios.json`、`scenario-coverage.json`、multi-repo 时 `cross-repo-impact-index.json`（含 `fanout_decision`）、`unknowns-ledger.json`、`decision-bundle.json`、`decision-packet.json` 等。**`clarify_closure_mode=notes_only`** 时门禁可仅校验 `clarification-notes.md` 结构，未知与决策写入同文件即可（见 [usage.md](usage.md)） |
| 把澄清结果写成正式规格 | SPEC | `/stage-harness:harness-spec` | `.harness/specs/{epic-id}.md`、`spec-council-notes.md` |
| 把规格落成可执行任务与覆盖 | PLAN | `/stage-harness:harness-plan` | `bridge-spec.md`、`coverage-matrix.json`、`surface-routing.json`（与 CLARIFY 一致，门禁复验）、`.harness/tasks/`；可选先做 `codemap-audit.json` 以降级 stale 缓存 |
| 按任务实现、测试、留痕 | EXECUTE | `/stage-harness:harness-work` | `receipts/`、代码变更 |
| 多维度验收 | VERIFY | `/stage-harness:harness-review` | `verification.json` 等 |
| 按审查意见返工 | FIX | `/stage-harness:harness-fix` | 修复后再 `/stage-harness:harness-review` |
| 结案与经验沉淀 | DONE | `/stage-harness:harness-done` | `delivery-summary.md`、`release-notes.md`、`memory/`、`scan-metrics.json`（如记录 ROI/验收）等 |

---

## 3. 串行 vs 并行（怎么记）

### 3.1 阶段之间：基本串行

`CLARIFY` 未完成不宜进入 `SPEC`；`SPEC` 未定不宜 `PLAN`；未 `PLAN` 不宜大规模 `WORK`；`REVIEW` 不通过先 `FIX`。这是**控制流串行**，避免「没想清楚就写代码」。

### 3.2 阶段内部：分析可并行、收口必串行

**原则**：**控制流串行，多视角分析并行，最后由 Lead/编排收束为单一结论。**

#### CLARIFY（并行最多）

依据 [usage.md](./usage.md) 与 `commands/harness-clarify.md`：

- **串行前置**：Intake → **`domain-scout`**（产出 `domain-frame.json`）→ Lead 写入 `clarification-notes` 中 Domain Frame 小节。
- **可并行一批**（在同一批次内，输入主要依赖 epic、画像、`domain-frame.json`）：
  - `requirement-analyst` → `requirements-draft.md`
  - `impact-analyst` → `impact-scan.md`（多仓时另有 `cross-repo-impact-index.json`，并在其中用 `fanout_decision.mode` 明确记录是 `repo_wave` 还是 `single_agent`）
  - `challenger` → `challenge-report.md`
  - `scenario-expander` → `generated-scenarios.json`
- **必须串行收口**：
  - Lead **语义归并** → `scenario-coverage.json` 与澄清笔记中的归并说明（**full** 模式）
  - Lead 将 **六轴澄清覆盖**（或 **极简澄清绕行**）与 **Unknowns 与待确认决策** 写入 `clarification-notes.md`（与 [usage.md — CLARIFY 骨架](usage.md) 一致）
  - `project-surface-router` → `surface-map.md`；Lead 按 `project-surface` skill 生成 **`surface-routing.json`**（**full** 模式下 `stage-gate check CLARIFY` **必备**）
  - **full**：`unknowns-ledger` 初始化与维护；`decision-bundle` / `decision-packet`。**notes_only**：等价信息编号写入 `clarification-notes.md`
  - 若有 `must_confirm`，**必须等用户回复**后再继续
  - `$HARNESSCTL stage-gate check CLARIFY`；可选 `$HARNESSCTL clarify-selfcheck --epic-id …` 作文检

简图：

```text
Lead intake → domain-scout
  → [ 并行：requirement-analyst | impact-analyst | challenger | scenario-expander ]
  → Lead 语义归并 → unknowns / decisions →（用户确认）→ gate
```

补充说明：
- `repo_wave` 表示多仓分析在本轮按 catalog `repo_id` 做 repo 级 fan-out。
- `single_agent` 表示虽然识别为 multi-repo，但本轮保持单 agent 收口；这同样是合法结果，只是 `cross-repo-impact-index.json` 里必须显式写明原因。

#### SPEC

- **生成规格**：通常串行。
- **Light Council 审查**：多个 reviewer 可**并行**给意见，再汇总。

#### PLAN

- **Bridge / 路由复核**：串行主干。
- **CodeMap 可信度检查**：可在并行 scout 前先运行 `harnessctl memory codemap-audit`，将 stale / invalid 缓存降为背景信息。
- **表面研究**（多 scout）：可**并行**，再汇总为计划与 DAG。
- **任务 DAG / 覆盖矩阵**：依赖研究结果，**串行生成**。

#### WORK

- **单个任务内部**（Re-anchor → Preflight → TDD → Smoke → Commit）：**串行**，避免上下文打架。
- **多个任务之间**：按 DAG，**无依赖的可并行**（实现上是否并行取决于编排与资源）。

#### REVIEW

- **多类 reviewer**（code / logic / test / security / runtime 等）：适合**并行**。
- **汇总裁决**（如 acceptance council）：**串行**在并行审查之后。

#### FIX

- 通常**偏串行**逐项修复，降低冲突；若问题清单明显独立，可酌情并行。

#### DONE

- 交付主线**串行**；Release Council、经验沉淀、技能挖掘、ROI 指标回填等收尾动作可部分**并行**。

---

## 4. CLARIFY 内主要 Agent：角色与必要性（理解用）

| 角色 | 像团队里的谁 | 主要作用 | 必要性（理解层） |
|------|----------------|----------|------------------|
| Lead / Orchestrator | PM + Tech Lead | 串流程、汇总、语义归并、unknown/decision 收口、用户确认 | **必须** |
| domain-scout | 前期业务/领域理解 | 仅基于需求与画像产出轻量 `domain-frame` | **推荐**；宜保持轻量 |
| requirement-analyst | 产品/需求分析 | REQ/AC/Open Questions | **非琐碎任务基本必须** |
| impact-analyst | 熟悉代码边界的人 | 影响面、缩圈、blast radius | **工程改动基本必须** |
| challenger | 挑刺/压力测试 | `challenge-report`，促 must_confirm | **重要**；复杂任务更应强化 |
| scenario-expander | 场景推演 | `generated-scenarios.json` | **偏增强**；不必所有任务同等强度 |
| project-surface-router | 代码导航/映射 | `surface-map.md`、`surface-routing.json` | **中后期有用**；视任务而定 |
| deep-dive-specialist | 专项调查 | 高影响 unknown 的深挖 | **按需** |

具体输入输出约束见 `agents/*.md` 与 `commands/harness-clarify.md`。

---

## 5. 当前演进关注点（通用性优先）

以下条目来自对插件方向的共识，用于指导 **CLARIFY / 编排** 的迭代，而不是替代现有 [usage.md](./usage.md)。

### 5.1 优先级

1. **第一目标**：插件在**陌生项目**也能用**统一、稳定**的方式产出结构（少依赖领域硬编码、少形式主义）。
2. **第二目标**：在**不牺牲通用性、不拖重主流程**的前提下，通过**可插拔增强**多发现问题。

### 5.2 核心层 vs 增强层（概念分层）

- **核心层（宜轻、宜稳定）**
  - 少量固定「澄清必答」维度（如六轴：每轴 `covered | not_applicable | unknown`）。
  - **禁止沉默**：不适用时用 `not_applicable`（短理由即可），不知道用 `unknown`，并有闭环落点。
  - Lead 产出**覆盖结论**（完整表或约定的极简形式）。
  - **台账降级**：有完整 `.harness` 时对齐 `unknowns-ledger` / `decision-bundle`；否则允许**仅**落在 `clarification-notes`（或单次说明文件），仍视为合法闭环。
  - **极简 / Chore 绕行**：明显无行为语义的 epic，允许全局 `not_applicable` + 一句总理由，避免六列表仪式感；**禁止滥用**（涉及逻辑、数据、API、权限、多入口、线上行为等仍走完整表态）。
  - **核心 Prompt 极简化**：避免长模式列表诱导模型「硬找茬」；具象例、模式库宜放增强文档/专用 agent。

- **增强层（第二阶段、按需）**
  - 二级模式库、更重的语义 gate、`scenario-expander` 新模式族、`deep-dive-specialist`、细粒度风险升级等。

### 5.3 协议层 vs 实现映射（长期卫生）

- **协议层**：澄清协议本身（覆盖三态、unknown/decision 落点、极简绕行规则）应尽量**与具体文件名解耦**表述。
- **实现映射**：当前仓库里对应到 `clarification-notes.md`、`unknowns-ledger.json` 等——属于 **Stage-Harness 绑定实现**，可演进，但不应把「只有这一种落盘方式」写死成通用插件的唯一形态。

### 5.4 任务分流优先于「六轴世界观」

六轴是**一类工程需求**的主协议，不是所有任务的默认宇宙。更合理的叙事是：

**先分流任务类型 → 再选择完整六轴表 / 极简绕行 / 其他轻协议。**

这样轻量项目（文档、纯样式、一次性脚本等）不会被默认拖进重型澄清。

### 5.5 验收建议（跨类型自然）

除「产物齐全、gate 通过」外，建议用**多类样本 epic** 做体感验收：文档类、纯 UI、脚本工具、内部小工具、后端/数据/工作流类——确认流程**不违和**、**不过重**。

---

## 6. 相关文档

- [usage.md](./usage.md) — 命令、CLARIFY 逐步说明、产物列表
- [README.md](./README.md) — 插件概览与阶段表
- [architecture.md](./architecture.md) — 架构与实现
- `commands/harness-clarify.md` — CLARIFY 编排细节（含 domain-scout 必选、并行批次、gate 清单）

---

## 7. 修订记录

- 2026-04-03：初版 — 汇总人类流程对照、并串行、Agent 角色与「通用性优先」关注点。
