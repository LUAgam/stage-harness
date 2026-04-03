# Stage-Harness 使用指南

## 安装

1. 将 `stage-harness/` 目录放到 Claude Code 可识别的插件路径下
2. 确保 `scripts/harnessctl.py` 有执行权限：`chmod +x scripts/harnessctl.py`
3. 确保 `scripts/*.sh` 有执行权限：`chmod +x scripts/*.sh`
4. 若未将 `harnessctl` 安装到系统 `PATH`，先在项目根目录设置：
   `export HARNESSCTL=./stage-harness/scripts/harnessctl`
5. 首次使用时，`/harness:start` 会自动执行 `$HARNESSCTL init` 初始化 `.harness/` 目录

## 命令一览

Stage-Harness 提供 11 个 slash 命令：

| 命令 | 阶段 | 说明 |
|------|------|------|
| `/harness:start` | IDEA→CLARIFY | 启动新 Epic，初始化项目、检测画像、创建 Epic、进入 CLARIFY |
| `/harness:clarify` | CLARIFY | 需求澄清：Q&A、影响扫描、未知台账、决策包、门禁检查 |
| `/harness:spec` | SPEC | 生成规格说明：Decision Bundle→ShipSpec→轻量议会审查 |
| `/harness:plan` | PLAN | 任务规划：Bridge 脚本→表面研究→任务 DAG→覆盖矩阵→Plan 议会 |
| `/harness:work` | EXECUTE | 执行任务：重新锚定→预检→TDD 实现→冒烟测试→提交+回执 |
| `/harness:review` | VERIFY | 多维审查：并行审查→对抗性审查→Acceptance 议会 |
| `/harness:fix` | FIX | 修复问题：读取审查结果→修复→回到 VERIFY |
| `/harness:done` | DONE | 交付：Release 议会→交付包→经验沉淀→候选技能挖掘 |
| `/harness:patch` | 任意 | 即时纠偏：诊断刚才的运行偏差、生成系统规则补丁草稿并支持热加载 |
| `/harness:auto` | 全阶段 | 自治模式：自动循环推进所有阶段直到 DONE |
| `/harness:status` | 任意 | 只读状态查看：显示当前 Epic、阶段、预算、任务进度 |
| `/harness:bridge` | PLAN | 将 ShipSpec 规格转化为深度计划的 Bridge 脚本 |

## 典型工作流

### 手动模式（逐阶段推进）

```
用户: /harness:start 我想给订单系统加一个退款功能

  → 自动初始化 .harness/、检测项目画像、创建 Epic sh-1-退款功能
  → 自动进入 CLARIFY 阶段

用户: /harness:clarify

  → 需求分析师分解需求为 REQ-001 ~ REQ-00N
  → 影响分析师扫描代码库受影响范围
  → 挑战者进行压力测试
  → 路由器映射需求到具体文件
  → 如有歧义，深度专家调查
  → 生成 Decision Bundle，打包 must_confirm 为 Decision Packet
  → 消耗中断预算向用户确认关键决策
  → 阶段门禁检查

用户: /harness:spec

  → 将 Decision Bundle 转化为 ShipSpec 规格说明
  → Light Council（3 agent）审查规格

用户: /harness:plan

  → Bridge 脚本连接规格到计划
  → 表面研究定位代码变更点
  → 生成任务 DAG 和覆盖矩阵
  → Plan Council（5 agent）审查计划

用户: /harness:work

  → Worker Agent 按任务顺序执行
  → 每个任务：重新锚定上下文→预检→TDD→冒烟测试→提交+回执
  → 循环直到所有任务完成

用户: /harness:review

  → 并行审查（代码/安全/逻辑/测试/质量）
  → 对抗性审查
  → Acceptance Council（5 agent）投票

  → 如果通过 → 可进入 DONE
  → 如果不通过 → 进入 FIX

用户: /harness:fix       # （如果审查不通过）
用户: /harness:review    # 修复后重新审查

用户: /harness:done

  → Release Council 最终审查
  → 生成交付摘要和发布说明
  → 经验沉淀到 memory/pitfalls.md
  → 挖掘候选技能
```

### JIT 即时纠偏模式（运行受阻时）

```
用户: (模型发生死循环或被门禁不断阻挡) -> 用户按 Ctrl+C 中断
用户: /harness:patch <epic-id>

  → 系统诊断刚才发生了什么偏差
  → system-observer 生成一个候选的规则补丁
  → 用户检视并选择 Apply
  → 规则以外挂形式保存到 .harness/rules/epic-local

用户: /harness:auto <epic-id>

  → 会话重新启动，热加载刚写入的补丁规则
  → 模型带着新约束继续执行，成功避开刚才的坑
```

### 自治模式

```
用户: /harness:start 我想给系统加一个通知模块
用户: /harness:auto
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
| IDEA | `/harness:start` |
| CLARIFY | `/harness:clarify` |
| SPEC | `/harness:spec` |
| PLAN | `/harness:plan` |
| EXECUTE | `/harness:work` |
| VERIFY | `/harness:review` |
| FIX | `/harness:fix` |

## 各命令详细说明

### /harness:start

**用途**：启动一个新的 Epic，从 IDEA 推进到 CLARIFY。

**参数**：命令后跟需求描述文本。

**流程**：
1. 格式化用户需求为 markdown
2. `$HARNESSCTL init` 初始化 `.harness/`（如未初始化）
3. `$HARNESSCTL profile detect` 检测项目画像
4. `$HARNESSCTL epic create "..."` 创建 Epic
5. Epic 创建后已处于 `CLARIFY`，无需额外状态推进
6. 自动进入 CLARIFY 阶段执行
7. `$HARNESSCTL status` 显示最终状态

**产物**：
- `.harness/config.json`
- `.harness/project-profile.yaml`
- `.harness/epics/sh-N-xxx.json`
- `.harness/features/sh-N-xxx/state.json`

### /harness:clarify

**用途**：需求澄清阶段，最关键的阶段之一。

**流程**：
1. 读取 Epic 描述和项目画像
2. **Intake**：Lead 产出简要结构化摘要（风险、预算、初始假设与开放问题）
3. **领域预分析（必选）**：`domain-scout` 仅基于需求与画像 → `domain-frame.json`；Lead 写入 `clarification-notes.md` 的 **Domain Frame / 领域框架** 小节（非独立阶段）
4. **需求分析**：`requirement-analyst`（输入含 `domain-frame.json`，如可用也消费 `generated-scenarios.json`）分解为 REQ-xxx → `requirements-draft.md`
5. **影响扫描**：`impact-analyst` 扫描代码库 → `impact-scan.md`（与上一步并行）。**多仓**（`project-profile.yaml` 中 `workspace_mode: multi-repo`）时另写 `cross-repo-impact-index.json`：先 `repo-catalog` + 契约 `interfaces[]`，深扫仓数不超过 `scan.max_repos_deep_scan`；超出则 Risk Flags 要求收敛。若首轮 map 命中 3+ 主要模块、`risk_level=high` 或 broad/systemic，可在**内部**并行 fan-out，但对外仍只交付一份汇总后的 `impact-scan.md`
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
- `cross-repo-impact-index.json` — `workspace_mode: multi-repo` 时 **门禁必备**；单仓可缺省
- `surface-routing.json` — 承载面路由与扫描预算（**CLARIFY / PLAN 门禁必备**；`surfaces` 须非空）
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

### /harness:spec

**用途**：将澄清结果转化为正式规格说明。

**流程**：
1. 读取 Decision Bundle，转化为 ShipSpec 输入
2. 生成规格说明书 → `.harness/specs/{epic-id}.md`
3. Light Council（**challenger + requirement-analyst + impact-analyst**）审查 — 与 `skills/council` 文档一致
4. 生成 `spec-council-notes.md`

`stage-gate check SPEC` 通过时，CLI 可能对规格打印 **语义提示**（非阻断），例如建议补充场景矩阵。

### /harness:plan

**用途**：将规格分解为可执行的任务计划。

**流程**：
1. `bridge-shipspec-to-deepplan.sh` 连接规格到深度计划
2. 复核 `surface-routing.json`；各 scout **先**查 `.harness/memory/codemaps/` 再回源。并行表面研究：`repo-router`、`docs-scout`、`design-scout`、`config-scout`、`symbol-navigator`、`dependency-mapper`（均受路由约束，见各 agent 的 Inputs）
3. 生成任务 DAG（`$HARNESSCTL task create`）
4. 生成覆盖矩阵 → `coverage-matrix.json`
5. Plan Council（5 agent）审查

**产物**：
- `bridge-spec.md`
- `coverage-matrix.json`
- `.harness/tasks/` 下的任务文件

### /harness:work

**用途**：执行任务，Worker Agent 的 5 阶段循环。

**每个任务的流程**：
1. **Re-anchor**：重新锚定上下文，读取任务描述和相关代码
2. **Preflight**：预检查，确认依赖满足
3. **TDD**：测试驱动开发（RED→GREEN→REFACTOR）
4. **Smoke**：冒烟测试
5. **Commit + Receipt**：提交代码，写执行回执

**产物**：
- `receipts/` 目录下的任务回执

### /harness:review

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

### /harness:fix

**用途**：修复审查发现的问题。

**流程**：
1. 读取 `verification.json` 中的问题清单
2. 逐项修复
3. 完成后回到 VERIFY 阶段重新审查

### /harness:done

**用途**：最终交付与知识沉淀。

**流程**：
1. **Release Council**：最终审查（logic-reviewer + security-reviewer + runtime-auditor；高风险可追加 code-reviewer，与 `skills/council/SKILL.md` 一致）
2. **交付包**：生成 `delivery-summary.md` 和 `release-notes.md`
3. **经验沉淀**：`unknowns-ledger-update.sh sift` 将 resolved 的未知问题沉淀到 `memory/pitfalls.md`
4. **技能挖掘**：skill-miner 提取可复用的候选技能
5. **（可选）CodeMap 补全**：见 `commands/harness-done.md` Step 4c — 将热点模块深读结果整理为 `memory/codemaps/`，供后续 Epic 复用
6. **状态转移**：标记为 DONE

### /harness:auto

**用途**：自治模式，自动推进所有阶段。

**行为**：
- 循环读取当前阶段 → 执行对应命令 → 推进下一阶段
- 每次循环前执行 `guard check` 确保安全
- 到达 DONE 自动停止
- EXECUTE↔VERIFY↔FIX 循环自动处理

### /harness:status

**用途**：只读查看当前状态。

**输出内容**：
- 当前 Epic 名称和 ID
- 当前阶段
- 中断预算（已用/总量）
- 任务进度统计
- 各产物完成状态

### /harness:bridge

**用途**：将 ShipSpec 规格转化为深度计划。

**执行**：调用 `bridge-shipspec-to-deepplan.sh`，在 PLAN 阶段使用。

## 状态查看

随时可以使用 `/harness:status` 查看当前进度，或直接调用 CLI：

```bash
export HARNESSCTL="${HARNESSCTL:-./stage-harness/scripts/harnessctl}"
$HARNESSCTL status
$HARNESSCTL state get sh-1-xxx
$HARNESSCTL task list sh-1-xxx
$HARNESSCTL clarify-selfcheck --epic-id sh-1-xxx
```

## 常见问题

### Q: 多仓工作区要怎么配置？

1. 在 `.harness/project-profile.yaml` 设置 `workspace_mode: multi-repo`（可与 `harnessctl profile detect` 结果合并或手改）。
2. 复制 `stage-harness/templates/repo-catalog.yaml` → `.harness/repo-catalog.yaml`，填写各 `repo_id`、`path`、`package_aliases` / `import_prefixes`（可选，利于依赖名映射到仓）。可用 `$HARNESSCTL profile discover-repo-aliases` 根据各仓根目录的清单文件**启发式补全**别名（默认 dry-run，`--write` 写回）。
3. CLARIFY 阶段会生成 `cross-repo-impact-index.json` 与 `surface-routing.json`；扫描深度受 `scan.max_repos_deep_scan`、`scan.max_files_deep_read_per_scout` 等约束（见模板 `project-profile.yaml`）。

### Q: 如何检查 CodeMap 是否相对源码已过时？

对使用 `templates/codemap-module.md` 写出的 `.harness/memory/codemaps/.../*.md`，在前置 YAML 中填写 `verified_commit` 与 `source_paths` 后，可在项目根执行：

```bash
$HARNESSCTL memory codemap-probe .harness/memory/codemaps/<repo>/<module>.md [--json]
```

若相对 `verified_commit` 与当前 `HEAD` 之间列出的路径有差异，命令以退出码 1 表示陈旧；加 `--write` 可更新 frontmatter 中的探测时间与 `confidence`（见 `docs/architecture.md` → memory）。

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

1. 运行 `/harness:status` 查看缺失的产物
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
