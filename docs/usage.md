# Stage-Harness 使用指南

## 安装

推荐先在插件仓库根目录执行：

```bash
scripts/harnessctl setup
scripts/harnessctl doctor
```

`setup` 会检查插件根目录、脚本权限，并输出推荐的 `HARNESSCTL` / `claude --plugin-dir` 命令；`doctor` 会做安装与运行自检。若缺少 install manifests，`doctor` / `repair` 会自动降级到 recorded-only 模式继续输出诊断。若需要自动初始化项目下的 `.harness/`，可追加 `--init-project --project-root <项目根>`。

1. 将整个 **stage-harness 仓库根目录**（含 `.claude-plugin/plugin.json`）作为 Claude Code 插件加载。使用 Claude CLI 时通过 **`--plugin-dir`** 指向该根目录，例如：
   ```bash
   claude --plugin-dir /opt/agent-delivery-claude/stage-harness
   ```
   路径换成本机克隆位置即可。`plugin.json` 中 `name` 为 **`stage-harness`**，对话里 slash 为 **`/stage-harness:harness-*`**（例如启动 Epic：`/stage-harness:harness-start`，编排说明见 `commands/harness-start.md`）。
2. 若未将 `harnessctl` 安装到系统 `PATH`，在**被开发项目根目录**设置 `HARNESSCTL` 指向插件内脚本（二选一）：
   - 插件与项目分离：`export HARNESSCTL=/opt/agent-delivery-claude/stage-harness/scripts/harnessctl`（或 `…/harnessctl.py`，推荐与 `--plugin-dir` 指向同一克隆）
   - 插件在子目录 `stage-harness/`：`export HARNESSCTL=./stage-harness/scripts/harnessctl`
3. 首次使用时，**`/stage-harness:harness-start`** 会自动执行 `$HARNESSCTL init` 初始化 `.harness/` 目录
4. 若运行异常，可使用：
   - `scripts/harnessctl doctor`
   - `scripts/harnessctl repair`（默认 dry-run）
   - `scripts/harnessctl repair --apply`
   - 当输出 `recorded-only` 时，表示 install-state 诊断已降级运行；若源文件不可安全回放，repair 会给出明确错误或手工处理提示，而不会盲目重写文件

## 命令一览

Stage-Harness 提供 11 个 slash 命令：

| 命令 | 阶段 | 说明 |
|------|------|------|
| `/stage-harness:harness-start` | IDEA→CLARIFY | 启动新 Epic，初始化项目、检测画像、创建 Epic、进入 CLARIFY |
| `/stage-harness:harness-clarify` | CLARIFY | 需求澄清：Q&A、影响扫描、未知台账、决策包、门禁检查 |
| `/stage-harness:harness-spec` | SPEC | 生成规格说明：Decision Bundle→ShipSpec→轻量议会审查 |
| `/stage-harness:harness-plan` | PLAN | 任务规划：Bridge 脚本→表面研究→任务 DAG→覆盖矩阵→Plan 议会 |
| `/stage-harness:harness-work` | EXECUTE | 执行任务：重新锚定→预检→TDD 实现→冒烟测试→提交+回执 |
| `/stage-harness:harness-review` | VERIFY | 多维审查：并行审查→对抗性审查→Acceptance 议会 |
| `/stage-harness:harness-fix` | FIX | 修复问题：读取审查结果→修复→回到 VERIFY |
| `/stage-harness:harness-done` | DONE | 交付：Release 议会→交付包→经验沉淀→候选技能挖掘 |
| `/stage-harness:harness-patch` | 任意 | 即时纠偏：诊断刚才的运行偏差、生成系统规则补丁草稿并支持热加载 |
| `/stage-harness:harness-auto` | 全阶段 | 自治模式：自动循环推进所有阶段直到 DONE |
| `/stage-harness:harness-status` | 任意 | 只读状态查看：显示当前 Epic、阶段、预算、任务进度 |
| `/stage-harness:harness-bridge` | PLAN | 将 ShipSpec 规格转化为深度计划的 Bridge 脚本 |

命名空间与 `.claude-plugin/plugin.json` 中的 `name` 一致（本仓库为 **`stage-harness`**）。若你的环境仍把插件注册为短名 `harness`，也可能看到 **`/harness:*`** 形式；与上表及 `commands/harness-*.md` 一一对应，钩子侧等价识别。

## 典型工作流

### 手动模式（逐阶段推进）

```
用户: /stage-harness:harness-start 我想给订单系统加一个退款功能

  → 自动初始化 .harness/、检测项目画像、创建 Epic sh-1-退款功能
  → 自动进入 CLARIFY 阶段

用户: /stage-harness:harness-clarify

  → 需求分析师分解需求为 REQ-001 ~ REQ-00N
  → 影响分析师扫描代码库受影响范围
  → 挑战者进行压力测试
  → 路由器映射需求到具体文件
  → 如有歧义，深度专家调查
  → 生成 Decision Bundle，打包 must_confirm 为 Decision Packet
  → 消耗中断预算向用户确认关键决策
  → 阶段门禁检查

用户: /stage-harness:harness-spec

  → 将 Decision Bundle 转化为 ShipSpec 规格说明
  → Light Council（3 agent）审查规格

用户: /stage-harness:harness-plan

  → Bridge 脚本连接规格到计划
  → 表面研究定位代码变更点
  → 生成任务 DAG 和覆盖矩阵
  → Plan Council（5 agent）审查计划

用户: /stage-harness:harness-work

  → Worker Agent 按任务顺序执行
  → 每个任务：重新锚定上下文→预检→TDD→冒烟测试→提交+回执
  → 循环直到所有任务完成

用户: /stage-harness:harness-review

  → 并行审查（代码/安全/逻辑/测试/质量）
  → 对抗性审查
  → Acceptance Council（5 agent）投票

  → 如果通过 → 可进入 DONE
  → 如果不通过 → 进入 FIX

用户: /stage-harness:harness-fix       # （如果审查不通过）
用户: /stage-harness:harness-review    # 修复后重新审查

用户: /stage-harness:harness-done

  → Release Council 最终审查
  → 生成交付摘要和发布说明
  → 经验沉淀到 memory/pitfalls.md
  → 挖掘候选技能
```

### JIT 即时纠偏模式（运行受阻时）

```
用户: (模型发生死循环或被门禁不断阻挡) -> 用户按 Ctrl+C 中断
用户: /stage-harness:harness-patch <epic-id>

  → 系统诊断刚才发生了什么偏差
  → system-observer 生成一个候选的规则补丁
  → 用户检视并选择 Apply
  → 规则以外挂形式保存到 .harness/rules/epic-local

用户: /stage-harness:harness-auto <epic-id>

  → 会话重新启动，热加载刚写入的补丁规则
  → 模型带着新约束继续执行，成功避开刚才的坑
```

### 自治模式

```
用户: /stage-harness:harness-start 我想给系统加一个通知模块
用户: /stage-harness:harness-auto
```

自治模式会自动循环推进所有阶段：

1. 读取当前阶段
2. 执行 `guard check`（检查门禁 + 预算 + 确认状态）
3. 根据阶段映射到对应命令执行
4. 推进到下一阶段
5. 重复直到 DONE

阶段→命令映射：

| 阶段 | 执行命令 |
|------|---------|
| IDEA | `/stage-harness:harness-start` |
| CLARIFY | `/stage-harness:harness-clarify` |
| SPEC | `/stage-harness:harness-spec` |
| PLAN | `/stage-harness:harness-plan` |
| EXECUTE | `/stage-harness:harness-work` |
| VERIFY | `/stage-harness:harness-review` |
| FIX | `/stage-harness:harness-fix` |

## 各命令详细说明

### /stage-harness:harness-start

**用途**：启动一个新的 Epic，稳定完成 bootstrap，并给出后续入口。

**参数**：命令后跟需求描述文本。

**流程**：
1. `$HARNESSCTL start "<需求>"` 初始化 `.harness/`（如未初始化）
2. 自动检测项目画像并创建 Epic
3. Epic 创建后停在 `CLARIFY` 起点
4. 输出推荐下一步：
   - 自动推进：`/stage-harness:harness-auto <epic-id>`
   - 手动推进：`/stage-harness:harness-clarify <epic-id>`

**产物**：
- `.harness/config.json`
- `.harness/project-profile.yaml`
- `.harness/epics/sh-N-xxx.json`
- `.harness/features/sh-N-xxx/state.json`

### /stage-harness:harness-clarify

**用途**：需求澄清阶段，最关键的阶段之一。

**流程**：
1. 读取 Epic 描述和项目画像
2. **Intake**：Lead 产出简要结构化摘要（风险、预算、初始假设与开放问题）
3. **领域预分析（必选）**：`domain-scout` 仅基于需求与画像 → `domain-frame.json`；Lead 写入 `clarification-notes.md` 的 **Domain Frame / 领域框架** 小节（非独立阶段）
4. **需求分析**：`requirement-analyst`（输入含 `domain-frame.json`，如可用也消费 `generated-scenarios.json`）分解为 REQ-xxx → `requirements-draft.md`
5. **影响扫描**：`impact-analyst` 扫描代码库 → `impact-scan.md`（与上一步并行）。**多仓**（`project-profile.yaml` 中 `workspace_mode: multi-repo`）时另写 `cross-repo-impact-index.json`：先 `repo-catalog` + 契约 `interfaces[]`，深扫仓数不超过 `scan.max_repos_deep_scan`；超出则 Risk Flags 要求收敛。该文件现在还必须带结构化 **`fanout_decision`**，用于说明本轮是按仓 fan-out（`repo_wave`）还是保持单 agent（`single_agent`）。`fanout_decision` 的最小契约是：`mode`、非空 `reason`、以及 `repo_ids`（表示本轮需要按仓独立 fan-out 深扫的 catalog `repo_id` 列表）。其中 `repo_wave` 时 `repo_ids` 非空，`single_agent` 时 `repo_ids` 必须为空数组 `[]`。若首轮 map 命中 3+ 主要模块、`risk_level=high` 或 broad/systemic，可在**内部**并行 fan-out，但对外仍只交付一份汇总后的 `impact-scan.md`
6. **挑战测试**：`challenger`（输入含 `domain-frame.json`）→ `challenge-report.md`（与影响扫描并行）；Critical/Warnings 须沉淀到台账或决策包
7. **场景展开**：`scenario-expander`（输入含 `domain-frame.json`）→ `generated-scenarios.json`
8. **语义归并**：Lead 汇总 `domain-frame`、`generated-scenarios`、`requirements-draft`、`challenge-report`，生成 `scenario-coverage.json`
9. **未知台账**：维护 `unknowns-ledger.json`
10. **表面路由**：`project-surface-router` 映射需求到文件 → `surface-map.md`（按需）；Lead / `project-surface` skill 维护 `surface-routing.json`（含 `repo_id`、`scan_budget`、`evidence_level`；可与 `cross-repo-impact-index.json` 对齐）
11. **深度调查**：`deep-dive-specialist` 调查歧义项（按需）
12. **决策包生成**：`decision-bundle.sh generate` → `decision-bundle.json`
13. **Decision Packet**：打包 must_confirm 项 → `decision-packet.json`
14. **用户确认**：消耗中断预算，向用户确认关键决策
15. **门禁检查**：`$HARNESSCTL stage-gate check CLARIFY`

**产物**：
- `domain-frame.json` — 领域框架结构化草稿（domain-scout）
- `generated-scenarios.json` — 高风险场景展开结果（scenario-expander）
- `scenario-coverage.json` — `SCN-xxx` 到 REQ/CHK/DEC/UNK 的结构化映射（Lead）
- `requirements-draft.md` — 需求草案（requirement-analyst）
- `challenge-report.md` — 挑战报告（challenger，须含 `## Summary`）
- `clarification-notes.md` — 澄清备忘录（**默认 full 也须含 Domain Frame / 领域框架 / 需求上下文 标题，以及六轴覆盖或极简绕行 + Unknowns 闭环**）
- `impact-scan.md` — 影响扫描报告
- `cross-repo-impact-index.json` — `workspace_mode: multi-repo` 时 **门禁必备**；单仓可缺省。当前需包含合法 **`fanout_decision`**（CLARIFY 写入的 PLAN 输入决策）：`mode`、非空 `reason`、以及 `repo_ids`；`mode=repo_wave` 时 `repo_ids` 非空，`mode=single_agent` 时 `repo_ids` 必须为空数组 `[]`。`repo_wave` 时 PLAN 阶段结束前还须落盘 **`repo-fanin-summary.json`**（仅含 `summarized_repo_ids` 与 `summary`）；`single_agent` 不要求该文件
- `surface-routing.json` — 承载面路由与扫描预算（**CLARIFY / PLAN 门禁必备**；`surfaces` 须非空）
- `change-coupling-closure.json` — 可选联动闭包件；项目声明 `coupling_role_ids` 时，可为当前 epic 记录 `required_role_ids` 与 `exemptions`
- `unknowns-ledger.json` — 未知问题台账
- `decision-bundle.json` — 决策包
- `decision-packet.json` — 待确认决策包

#### CLARIFY 通用澄清骨架（六轴必答 · 三态 · 闭环落点）

CLARIFY 的目标是 **统一覆盖与表态**，不是「每个轴都要审出风险」。固定 **六个一级澄清轴**（内部 ID 稳定，文档可用中文表述）：

| 轴 ID | 澄清向表述 |
|--------|------------|
| `StateAndTime` | 行为与流程：顺序、重复、异步、重试、状态变化是否说清 |
| `ConstraintsAndConflict` | 规则与边界：互斥、唯一性、版本、非法组合 |
| `CostAndCapacity` | 规模与代价：性能、资源、外部调用；前端可映射为体积/请求次数 |
| `CrossSurfaceConsistency` | 多入口 / 多阶段一致性 |
| `OperationsAndRecovery` | 运行与维护：线上运维、排障、失败与恢复（纯离线一次性可 `not_applicable`） |
| `SecurityAndIsolation` | 权限与隔离（纯本地离线可简短 `not_applicable`） |

每一轴必须三态之一：**`covered`**（已说清）、**`not_applicable`**（明确不适用，可一句话理由）、**`unknown`**（缺证据）。**禁止**整轴留空不表态。Lead 将 **六轴覆盖结论** 写入 `clarification-notes.md` 的 **`## 六轴澄清覆盖`**（表格或列表均可）。

**极简 / Chore 绕行**：明显低风险、无行为语义的 Epic（纯文案/拼写、仅样式 token、纯依赖版本 bump、仅 README 等），允许在 `clarification-notes.md` 使用 **`## 极简澄清绕行`**：声明六轴 **全局 `not_applicable` + 一句总理由**，不要求六行展开表。涉及逻辑、数据写入、API、权限、多入口或线上行为的 Epic **不得**走绕行。

**三条落地护栏**（与骨架同级重要）：

1. **核心 Prompt 极简化**：`challenger` / `requirement-analyst` 等只保留短定义与每轴至多 1～2 个**与领域无关**的通用例；长模式列表见增强层（`scenario-expander` 等），避免诱导编造 `unknown`。
2. **台账平滑降级**：有完整 `.harness` 与约定路径时，`unknown` → `unknowns-ledger.json`，高影响待确认 → `decision-bundle`；**无完整 harness 或陌生仓库**时，不要求强行造孤立 JSON，可将 UNK / must_confirm **编号写入同一 `clarification-notes.md`**，仍视为闭环。**检测顺序**：先读 `clarify_closure_mode`，再选落点。
3. **配置 `clarify_closure_mode`**（`.harness/config.json`）：`full`（默认）= **全套 JSON 门禁 + `clarification-notes.md` 结构校验**；`notes_only` = 仅要求 `clarification-notes.md` 通过结构校验（六轴或极简绕行 + 闭环小节），`stage-gate check CLARIFY` 不强制 ledger/bundle 等文件。

**自检（不阻断）**：`$HARNESSCTL clarify-selfcheck --epic-id <epic-id>` 会打印 `clarification-notes.md` 结构校验结果与 full 模式各文件是否存在（与 `stage-gate check CLARIFY` 中 notes 部分一致），便于陌生项目或 PR 前自查。

**增强层 gate（默认开启，但只在命中信号时生效）**：`clarify_signal_gate_enabled=true` 时，`harnessctl` 会从 `domain-frame.json` 与 `generated-scenarios.json` 提取高/中置信度信号，**按需**强化特定轴：

- 状态/重试/回放/阶段顺序 → `StateAndTime`
- 主键/唯一性/定位谓词/冲突 → `ConstraintsAndConflict`
- 放大/性能/容量/资源 → `CostAndCapacity`
- 跨阶段/UI-后端/API-schema 契约一致性 → `CrossSurfaceConsistency`
- 恢复/回滚/部分失败/运行维护 → `OperationsAndRecovery`
- 权限/鉴权/隔离/敏感边界 → `SecurityAndIsolation`

命中后：

- 不允许使用**全局极简绕行**掩盖这些轴
- 这些轴不得标记为 `not_applicable`
- 允许标记为 `covered` 或 `unknown`
- 若同时存在高风险信号且 `requirements-draft.md` 中有 `UNCLEAR` / `AMBIGUOUS`，`clarify-selfcheck` 会给出 `deep-dive-specialist` 提示

**deep-dive 升级契约**：默认 `clarify_deep_dive_enabled=true` 时，CLI 会识别“高风险信号 + 模糊需求（`requirements-draft.md` 中存在 `UNCLEAR` / `AMBIGUOUS`）+ 尚无 `deep-dive-*.md`”的组合并给出提示；若再设置 `clarify_deep_dive_gate_strict=true`，则 `stage-gate check CLARIFY` 与 `verify-artifacts.sh` 会把这种情况视为阻断项，要求先产出至少一份 `deep-dive-*.md` 备忘录。

**用户关注点闭环（可选但可阻断）**：当用户在对话中**明确点名**若干必须覆盖的要点时，应在 `clarification-notes.md` 增加 `## Focus Points` / `## 用户关注点` / `## 用户点名关注`，每条列表项须包含 `REQ-` / `CHK-` / `SCN-` / `DEC-` / `UNK-` 编号之一；亦可使用可选文件 `.harness/features/<epic-id>/focus-points.json`（`items[]` 中每项通过 `maps_to` / `closure_ref` / `mapped_to` 指向上述编号）。未声明关注点时不增加该小节即可；**一旦**写了非空的关注点小节或 `focus-points.json` 含条目，`stage-gate check CLARIFY`、`clarify-selfcheck` 与 `verify-artifacts.sh` 会校验映射是否齐全。实现见 `scripts/clarify_gate_shared.py` 的 `focus-errors` 子命令。

**可选联动闭包（通用 role 模式）**：若项目在 `.harness/project-profile.yaml` 中声明了**非空** `coupling_role_ids`，则 CLARIFY（`full` 模式）/ PLAN 可额外启用一层 role 闭包提醒。`surface-routing.json.surfaces[].serves_roles` 用于声明某个承载面覆盖了哪些 role；`change-coupling-closure.json` 用于声明本 epic 的 `required_role_ids`，以及未纳入实现时的 `exemptions`。`exemptions[].binds_to` 必须采用 `DEC-*` 或 `UNK-*` 形态。`.harness/config.json` 中 `coupling_closure_gate_mode` 支持 `off | warn | strict`，默认 `warn`；`warn` 模式会输出结构问题与未闭环 role 的 warning，但不阻断阶段推进。

**CLARIFY 跨阶段 Bash 拦截**：`hooks/scripts/pre-tool-use.sh` 会在 Bash 命令**明确指向仍处于 `CLARIFY` 的 epic** 时，拒绝执行跨阶段 slash（例如 `/stage-harness:harness-spec`、`/stage-harness:harness-plan`、`/stage-harness:harness-work`、`/stage-harness:harness-review`、`/stage-harness:harness-done`、`/stage-harness:harness-patch`、`/stage-harness:harness-auto`、`/stage-harness:harness-bridge`、`/stage-harness:harness-fix`），以及等价的 `/harness:*`、`harness:`、`stage-harness:harness-*`（无首斜杠）写法，避免并行子任务把该 epic 拖到后续阶段；其它 epic 的正常推进、以及单纯输出 slash 文本的命令不应被误拦。

### /stage-harness:harness-spec

**用途**：将澄清结果转化为正式规格说明。

**流程**：
1. 读取 Decision Bundle，转化为 ShipSpec 输入
2. 生成规格说明书 → `.harness/specs/{epic-id}.md`
3. Light Council（**challenger + requirement-analyst + impact-analyst**）审查 — 与 `skills/council` 文档一致
4. 生成 `spec-council-notes.md`

`stage-gate check SPEC` 通过时，CLI 可能对规格打印 **语义提示**（非阻断），例如建议补充场景矩阵。

### /stage-harness:harness-plan

**用途**：将规格分解为可执行的任务计划。

**流程**：
1. `bridge-shipspec-to-deepplan.sh` 连接规格到深度计划
2. 复核 `surface-routing.json`；若存在相关 CodeMap，建议先执行 `memory codemap-audit --epic-id <epic-id>` 生成 `codemap-audit.json`，再由各 scout 读取 `.harness/memory/codemaps/` 并按审计结果决定是否回源。并行表面研究：`repo-router`、`docs-scout`、`design-scout`、`config-scout`、`symbol-navigator`、`dependency-mapper`（均受路由约束，见各 agent 的 Inputs）
3. 生成任务 DAG（`$HARNESSCTL task create`）
4. 生成覆盖矩阵 → `coverage-matrix.json`
5. Plan Council（5 agent）审查

**产物**：
- `bridge-spec.md`
- `coverage-matrix.json`
- `.harness/tasks/` 下的任务文件

### /stage-harness:harness-work

**用途**：执行任务，Worker Agent 的 5 阶段循环。

**每个任务的流程**：
1. **Re-anchor**：重新锚定上下文，读取任务描述和相关代码
2. **Preflight**：预检查，确认依赖满足
3. **TDD**：测试驱动开发（RED→GREEN→REFACTOR）
4. **Smoke**：冒烟测试
5. **Commit + Receipt**：提交代码，写执行回执

**产物**：
- `receipts/` 目录下的任务回执

### /stage-harness:harness-review

**用途**：多维度审查。

**流程**（与 `skills/review/SKILL.md`、`skills/council/SKILL.md` 一致）：
1. **并行技术审查**：code-reviewer、logic-reviewer、test-reviewer（logic/test 建议传 `domain_frame_path`）
2. **spec 对齐**：runtime-auditor（spec compliance / 漂移）
3. **安全审查**：security-reviewer
4. **对抗式补盲**：challenger（或编排等价步骤）
5. **验收议会**：acceptance_council 核心五人为 code / logic / security / test / **runtime-auditor**（可按项目追加 reviewer；`quality-auditor` 为可选增强，非核心五人组）

**结果**：
- 通过 → 可进入 DONE
- 不通过 → 进入 FIX，附带具体问题清单

**VERIFY 门禁**：`verification.json` 中若存在 `test_review`（及 `code_review`、`logic_review` 等）且值为 `FAIL`，`stage-gate check VERIFY` 会失败；`acceptance_council` / `council_verdict` 须为 `PASS` 或 `CONDITIONAL_PASS`。

### /stage-harness:harness-fix

**用途**：修复审查发现的问题。

**流程**：
1. 读取 `verification.json` 中的问题清单
2. 逐项修复
3. 完成后回到 VERIFY 阶段重新审查

### /stage-harness:harness-done

**用途**：最终交付与知识沉淀。

**流程**：
1. **Release Council**：最终审查（logic-reviewer + security-reviewer + runtime-auditor；高风险可追加 code-reviewer，与 `skills/council/SKILL.md` 一致）
2. **交付包**：生成 `delivery-summary.md` 和 `release-notes.md`
3. **经验沉淀**：`unknowns-ledger-update.sh sift` 将 resolved 的未知问题沉淀到 `memory/pitfalls.md`
4. **技能挖掘**：skill-miner 提取可复用的候选技能
5. **（可选）CodeMap 补全**：见 `commands/harness-done.md` Step 4c — 将热点模块深读结果整理为 `memory/codemaps/`，供后续 Epic 复用
6. **状态转移**：标记为 DONE

### /stage-harness:harness-auto

**用途**：自治模式，自动推进所有阶段。

**行为**：
- 循环读取当前阶段 → 执行对应命令 → 推进下一阶段
- 每次循环前执行 `guard check` 确保安全
- 到达 DONE 自动停止
- EXECUTE↔VERIFY↔FIX 循环自动处理

### /stage-harness:harness-status

**用途**：只读查看当前状态。

**输出内容**：
- 当前 Epic 名称和 ID
- 当前阶段
- 中断预算（已用/总量）
- 任务进度统计
- 各产物完成状态

### /stage-harness:harness-bridge

**用途**：将 ShipSpec 规格转化为深度计划。

**执行**：调用 `bridge-shipspec-to-deepplan.sh`，在 PLAN 阶段使用。

## 状态查看

随时可以使用 `/stage-harness:harness-status` 查看当前进度，或直接调用 CLI：

```bash
# 插件自检 / 修复
$HARNESSCTL setup
$HARNESSCTL doctor
$HARNESSCTL repair
$HARNESSCTL repair --apply

# 插件在被开发仓库的子目录 stage-harness/ 时：
export HARNESSCTL="${HARNESSCTL:-./stage-harness/scripts/harnessctl}"
# 插件为独立克隆、与项目分离时（推荐绝对路径，与 claude --plugin-dir 一致）：
# export HARNESSCTL=/opt/agent-delivery-claude/stage-harness/scripts/harnessctl
$HARNESSCTL status
$HARNESSCTL state get sh-1-xxx
$HARNESSCTL task list sh-1-xxx
$HARNESSCTL clarify-selfcheck --epic-id sh-1-xxx
```

## 常见问题

### Q: 多仓工作区要怎么配置？

1. 在 `.harness/project-profile.yaml` 设置 `workspace_mode: multi-repo`（可与 `harnessctl profile detect` 结果合并或手改）。
2. 复制 `stage-harness/templates/repo-catalog.yaml` → `.harness/repo-catalog.yaml`，填写各 `repo_id`、`path`、`package_aliases` / `import_prefixes`（可选，利于依赖名映射到仓）。可用 `$HARNESSCTL profile discover-repo-aliases` 根据各仓根目录的清单文件**启发式补全**别名（默认 dry-run，`--write` 写回）。
3. CLARIFY 阶段会生成 `cross-repo-impact-index.json` 与 `surface-routing.json`；扫描深度受 `scan.max_repos_deep_scan`、`scan.max_files_deep_read_per_scout` 等约束（见模板 `project-profile.yaml`）。其中 `cross-repo-impact-index.json` 现在必须带 `fanout_decision`：包含 `mode`、非空 `reason` 和 `repo_ids`；`repo_wave` 表示按 catalog `repo_id` 做 repo 级 fan-out，`single_agent` 表示多仓已识别但本轮保持单 agent 收口，且 `repo_ids` 必须为空数组 `[]`。
4. 审计查看时，`execution-summary.json` / `harnessctl audit show` 现在会额外区分 `repo_fanout_waves_completed`。它只统计 repo-scope `parallel_wave_completed`；`fanout_used` / `fanout_children_count` 优先根据 repo-scope `parallel_wave_completed` 推导，若缺少该类 trace，才会回退到 multi-repo 的 artifact 证据。

### Q: 多仓 Epic 怎么记录每个 repo 的 branch / worktree？

默认仍可记录一个 epic 级 worktree：

```bash
$HARNESSCTL epic set-worktree <epic-id> .harness/worktrees/<epic-id>
```

若同一 Epic 需要多个仓各自独立分支，则按 `repo_id` 分别记录：

```bash
$HARNESSCTL epic set-worktree <epic-id> ../service-a-wt --repo-id service-a --branch harness/<epic-id>/service-a
$HARNESSCTL epic set-worktree <epic-id> ../service-b-wt --repo-id service-b --branch harness/<epic-id>/service-b
$HARNESSCTL epic show-worktrees <epic-id> [--json]
```

这样可在 Epic 元数据中保留 `repo_id -> branch/path` 映射，供后续 WORK / REVIEW / RELEASE 汇总使用。

### Q: 如何检查 CodeMap 是否相对源码已过时？

对使用 `templates/codemap-module.md` 写出的 `.harness/memory/codemaps/.../*.md`，在前置 YAML 中填写 `verified_commit` 与 `source_paths` 后，可在项目根执行：

```bash
$HARNESSCTL memory codemap-probe .harness/memory/codemaps/<repo>/<module>.md [--json]
```

若相对 `verified_commit` 与当前 `HEAD` 之间列出的路径有差异，命令以退出码 1 表示陈旧；加 `--write` 可更新 frontmatter 中的探测时间与 `confidence`（见 `docs/architecture.md` → memory）。

若想在进入 PLAN 前批量检查某个 repo 的 CodeMap 缓存，可执行：

```bash
$HARNESSCTL memory codemap-audit .harness/memory/codemaps/<repo_id> [--write] [--epic-id <epic-id>] [--json]
```

它会汇总 `fresh` / `stale` / `missing_verified_commit` / `invalid` 数量；存在 stale 或 invalid 时返回退出码 1，便于在编排层降级这些缓存的可信度。若提供 `--epic-id`，还会落盘 `.harness/features/<epic-id>/codemap-audit.json`，供 PLAN scouts 直接读取。

若要初始化一个标准 CodeMap 文件，而不是手工复制模板，可执行：

```bash
$HARNESSCTL memory codemap-init <repo_id> <module_slug> --source-path src/module.py [--source-path ...] [--purpose "模块职责摘要"]
```

### Q: 怎么记录这套扫描方案的 ROI 与阶段验收？

可直接用 CLI 记录单个 epic 的 ROI 指标和阶段验收结论：

```bash
$HARNESSCTL metrics record --epic-id <epic-id> cache_hit_rate 0.67 --stage PLAN
$HARNESSCTL metrics record --epic-id <epic-id> avg_latency_clarify_plan 18.2 --notes "minutes"
$HARNESSCTL metrics check --epic-id <epic-id> mvp_no_blind_scan met
$HARNESSCTL metrics check --epic-id <epic-id> routing_auditable met --notes "surface-routing + impact-index present"
$HARNESSCTL metrics derive --epic-id <epic-id> [--json]
$HARNESSCTL metrics show --epic-id <epic-id> [--json]
$HARNESSCTL metrics show [--json]
```

数据写入 `.harness/features/<epic-id>/scan-metrics.json`，同时事件追加到 `.harness/metrics/scan-roi.jsonl`，便于后续人工汇总或脚本统计。若不带 `--epic-id`，`metrics show` 还会输出跨 Epic 的均值/计数与验收状态分布；`metrics derive` 则会根据路由、跨仓索引与 CodeMap 审计结果自动回填一组基础验收项。

### Q: 插件如何知道项目类型？

`$HARNESSCTL profile detect` 根据项目根目录的标志文件自动检测：

| 文件 | 项目类型 |
|------|---------|
| `package.json` | frontend |
| `go.mod` | backend |
| `setup.py` / `pyproject.toml` | library |
| `Dockerfile` | backend |
| `*.tf` | infra |

### Q: 中断预算用完了怎么办？

预算用尽后，所有剩余的 `must_confirm` 决策会使用 `proposed_default`（安全默认值）自动处理，不再向用户提问。

### Q: SPEC 门禁里的「语义提示」能否改成不通过？

可以。在 `.harness/config.json` 中设置：

```json
"spec_semantic_hints_strict": true
```

则 `stage-gate check SPEC` 会把 `_spec_semantic_warnings` 的每条提示当作**阻断项**（写入 `missing`）。默认 `false` 时仅在 stderr 打印提示，不挡门禁。

### Q: 陌生仓库不想维护 unknowns-ledger / decision-bundle 怎么办？

在 `.harness/config.json` 设置 `"clarify_closure_mode": "notes_only"`。此时 `stage-gate check CLARIFY` 只要求 `clarification-notes.md` 通过结构校验（六轴或极简绕行 + Unknowns/待确认闭环）；`verify-artifacts.sh` 会读取同一配置。团队项目若要走完整台账，保持默认 `"full"` 即可。

### Q: 如何快速检查 clarification-notes 是否满足六轴契约？

```bash
$HARNESSCTL clarify-selfcheck --epic-id <epic-id>
```

不阻断流程，会列出 `clarification-notes.md` 结构校验结果与 full 门禁文件清单（`--json` 时字段为 `clarification_notes_errors` / `clarification_notes_ok`，`notes_only_*` 为兼容别名）。若需指定项目根目录，**全局参数写在子命令前**：`$HARNESSCTL --project-root /path/to/repo clarify-selfcheck --epic-id <epic-id>`。

### Q: 可以跳过某个阶段吗？

可以使用 `$HARNESSCTL gate skip <STAGE> --epic-id <id>` 跳过指定阶段的门禁检查。但不建议在生产项目中使用。

### Q: 阶段转移失败怎么办？

1. 运行 `/stage-harness:harness-status` 查看缺失的产物
2. 补全缺失产物
3. 重新执行该阶段的命令
4. 或使用 `$HARNESSCTL gate skip` 强制跳过（不推荐）

### Q: 如何查看某个 Epic 的所有产物？

```bash
ls -la .harness/features/sh-N-xxx/
```

### Q: 支持同时运行多个 Epic 吗？

支持。每个 Epic 有独立的 features 目录和 state.json，互不影响。

### Q: 钩子做了什么？

| 钩子 | 触发时机 | 作用 |
|------|---------|------|
| SessionStart | 会话开始 | 检测活跃 Epic，输出阶段/预算/健康上下文 |
| UserPromptSubmit | 用户输入前 | 输出当前阶段提醒 |
| PreToolUse (Bash) | 执行 Bash 前 | 拦截危险命令（rm -rf, DROP TABLE 等） |
| Stop | 会话结束 | 为每个活跃 Epic 生成 handoff.md |
| TaskCompleted | 任务完成 | 触发任务完成后处理 |
| TeammateIdle | 队友空闲 | 触发空闲通知处理 |
