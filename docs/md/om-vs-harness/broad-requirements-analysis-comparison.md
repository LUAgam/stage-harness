# 广义需求分析阶段对比

本文按“广义需求分析”口径重新对比两套流程：

- `stage-harness`
- `ai-programmer-oms`

这里的“广义需求分析”不是只看前置澄清，而是看**需求如何从模糊输入一路收敛成正式、可消费的需求规格文档**。

## 一句话结论

如果按广义口径对齐：

- `stage-harness` 的需求分析阶段应看作：`CLARIFY + SPEC`
- `ai-programmer-oms` 的需求分析阶段应看作：`clarification + apply-clarification + draft_prd + discussion + summary_effect + finalize_prd`

也就是说：

- `stage-harness` 先把问题空间、风险、未知项、承载面分析清楚，再把结果固化成规格与任务基础。
- `ai-programmer-oms` 先做前置澄清，再产出 PRD，再做产品确认问题抽取和最终 PRD 定稿。

## 一、为什么要这样对齐

之前如果只把：

- `stage-harness` 对齐到 `CLARIFY`
- `ai-programmer-oms` 对齐到 `draft_prd`

其实都偏窄。

原因是：

### 对 `stage-harness`

`CLARIFY` 解决的是：

- 需求边界
- 风险
- 未知项
- 承载面
- 必须确认的决策

但真正把这些内容收敛成正式规格、并连接到任务规划基础的，是后面的 `SPEC`。

所以如果只看 `CLARIFY`，会低估它“需求规格化”的实现部分。

### 对 `ai-programmer-oms`

`draft_prd` 只是初版 PRD。

后面还有：

- `discussion`：补强影响面分析
- `summary_effect`：提炼真正需要产品拍板的问题
- `finalize_prd`：生成 `final_prd.md` 并做最终完整性补齐

所以如果只看 `draft_prd`，会低估它“最终需求定稿”的实现部分。

## 二、阶段映射

### `stage-harness`

广义需求分析阶段：

1. `CLARIFY`
2. `SPEC`

其中：

- `CLARIFY` 偏需求澄清、风险显式化、代码承载面识别
- `SPEC` 偏需求规格化、技术决策沉淀、任务基础结构化

### `ai-programmer-oms`

广义需求分析阶段：

1. `clarification`
2. `apply-clarification`
3. `draft_prd`
4. `discussion`（可选）
5. `summary_effect`
6. `finalize_prd`

其中：

- 前两步偏前置澄清
- 中间几步偏 PRD 生成与补强
- 最后一步偏最终 PRD 定稿

## 三、`stage-harness` 的广义需求分析实现流程

### 1. `CLARIFY`：把问题讲清楚

这一阶段不是直接生成 PRD，而是先建立“问题控制面”。

它的主要动作包括：

1. 读取 epic 描述、项目画像、已有上下文
2. 先跑 `domain-scout` 生成 `domain-frame.json`
3. 并行派发：
   - `requirement-analyst`
   - `impact-analyst`
   - `challenger`
   - `scenario-expander`
4. 对结果做语义归并，生成 `scenario-coverage.json`
5. 做承载面路由，生成 `surface-routing.json`
6. 必要时 deep dive
7. 生成：
   - `unknowns-ledger.json`
   - `decision-bundle.json`
   - `decision-packet.json`
8. 通过 `stage-gate check CLARIFY`

这一阶段的核心不是文档定稿，而是：

- 让需求不再模糊
- 让关键风险显式化
- 让必须确认的问题结构化
- 让后续规格生成不至于脱离上下文

### 2. `SPEC`：把澄清结果固化成规格

`SPEC` 会把 `CLARIFY` 的结果进一步转成机器可消费、可桥接到规划阶段的规格资产。

它依赖 ShipSpec 的 7 阶段能力，产出包括：

- `.shipspec/planning/<feature>/PRD.md`
- `.shipspec/planning/<feature>/SDD.md`
- `.shipspec/planning/<feature>/TASKS.json`
- `.shipspec/planning/<feature>/TASKS.md`

同时还要求产生 harness 原生规格产物：

- `.harness/specs/<epic-id>.md`
- `.harness/features/<epic-id>/spec-council-notes.md`

然后做：

1. SPEC quality gate
2. light council review
3. `stage-gate check SPEC`
4. 为后续 PLAN 生成 `bridge-spec.md`

所以从广义需求分析角度看，`SPEC` 才是 `stage-harness` 中“把分析结果收敛为正式规格”的关键一步。

### 3. `stage-harness` 广义需求分析的最终产物

从业务到规格，核心产物链条是：

- `domain-frame.json`
- `requirements-draft.md`
- `impact-scan.md`
- `challenge-report.md`
- `scenario-coverage.json`
- `surface-routing.json`
- `clarification-notes.md`
- `unknowns-ledger.json`
- `decision-bundle.json`
- `.harness/specs/<epic-id>.md`
- `spec-council-notes.md`
- `.shipspec/planning/<feature>/PRD.md`
- `.shipspec/planning/<feature>/SDD.md`

也就是说，`stage-harness` 的广义需求分析结果不是单一 PRD，而是一整套：

- 澄清资产
- 风险资产
- 规格资产
- 任务前置资产

## 四、`ai-programmer-oms` 的广义需求分析实现流程

### 1. `clarification`：先问清前置问题

系统会结合：

- 原始需求
- 知识库
- 代码目录

生成前置澄清问题：

- `questions.md`
- `questions.json`
- `answer_template.md`

目标是先把会影响 PRD 结论的问题问清。

### 2. `apply-clarification`：校验人工回复并生成澄清后需求

人工补充回复后，系统会：

1. 校验回复是否覆盖全部问题
2. 若不完整，则回写待补充项并阻断
3. 若完整，则生成：
   - `reply_coverage_report.md`
   - `clarified_requirement.md`

这一步相当于把“原始模糊需求”推进成“可用于写 PRD 的澄清后需求”。

### 3. `draft_prd`：生成初版 PRD

接下来系统会：

1. 判断知识库说明是否充足
2. 生成需求规格型 PRD
3. 对 PRD 做一次完整性复审并原地补齐

核心产物：

- `prd/requirements.md`

这份文档已经是比较接近正式规格的需求文档，而不是分析笔记。

### 4. `discussion`：补强影响面分析（可选）

如果未禁用，会进入议会式讨论，用来补强 PRD 的影响面分析。

这一层不是强制门禁，但它会提高 PRD 的上下文完备度。

### 5. `summary_effect`：抽取需要产品拍板的问题

这一步不是重写 PRD，而是从当前 PRD 中提炼：

- 哪些问题研发不能自己拍板
- 哪些策略仍需要产品确认

输出：

- `summary_effect/questions.md`
- `summary_effect/questions.json`
- `summary_effect/manifest.json`

这里的特点是：

- 问题已经不是前置澄清问题
- 而是“读过 PRD 和代码上下文后，仍然需要产品定夺的问题”

### 6. `finalize_prd`：生成最终 PRD

最后，系统会：

1. 校验产品回复是否覆盖全部待确认问题
2. 若不完整，回写待补充项并阻断
3. 若完整，生成：
   - `final_prd.md`
   - `merge_report.md`
   - `reply_coverage_report.md`
4. 再对最终 PRD 做完整性复审并原地补齐

所以 `ai-programmer-oms` 的广义需求分析最终落点非常明确：

- `final_prd.md`

### 7. `ai-programmer-oms` 广义需求分析的最终产物

核心产物链条是：

- `clarification/questions.md`
- `clarification/reply_coverage_report.md`
- `clarification/clarified_requirement.md`
- `prd/requirements.md`
- `discussion/...`（可选）
- `summary_effect/questions.md`
- `summary_effect/questions.json`
- `summary_effect/final_prd.md`
- `summary_effect/merge_report.md`

它的最终主件是：

- 初版 PRD
- 产品确认问题
- 最终 PRD

## 五、广义需求分析差异总表

| 对比项 | `stage-harness` | `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 广义阶段范围 | `CLARIFY + SPEC` | `clarification + apply-clarification + draft_prd + discussion + summary_effect + finalize_prd` | 这样对齐后，两边才都覆盖了“澄清 + 规格化 + 定稿”的完整链路。 |
| 阶段核心目标 | 先做问题控制，再固化为规格与任务基础 | 先做前置澄清，再产出并定稿 PRD | `stage-harness` 更像“分析到规格的控制系统”，`ai-programmer-oms` 更像“需求文档生产系统”。 |
| 需求分析起点 | 从领域框架和风险视角切入 | 从问题清单和人工答复切入 | 前者更适合复杂、高风险需求；后者更适合快速把业务输入推进成文档。 |
| 规格化落点 | `.harness/specs/<epic-id>.md` + ShipSpec `PRD.md/SDD.md` | `prd/requirements.md` 再到 `final_prd.md` | `stage-harness` 的规格化更偏工程内部消费；`ai-programmer-oms` 的规格化更偏产品与交付文档消费。 |
| 是否把风险与未知项做成独立资产 | 是 | 相对弱，更多融入问题清单和 PRD 演进 | 这是 `stage-harness` 的明显优势，适合长期治理和复盘。 |
| 是否显式衔接后续任务规划 | 是，`SPEC` 直接产出 `TASKS.json` 并桥接 `PLAN` | 否，PRD 后再进入技术方案阶段 | `stage-harness` 在“需求分析直接服务执行规划”这点上更强。 |
| 是否包含产品最终拍板回路 | 通过 `must_confirm` / 决策包控制 | 明确有 `summary_effect -> finalize_prd` 回路 | `ai-programmer-oms` 在“产品最终确认”这件事上流程更完整、更显性。 |
| 最终主产物 | 澄清资产 + 规格资产 + 任务前置资产 | 最终 PRD + 合并报告 | 如果目标是流程治理与后续自动规划，前者更好；如果目标是形成最终需求文档，后者更直接。 |
| 整体风格 | 分析驱动、门禁驱动、资产驱动 | 文档驱动、回复驱动、定稿驱动 | 两者并不冲突，甚至可以串联使用。 |

## 六、产物差异表

| 类别 | `stage-harness` 代表产物 | `ai-programmer-oms` 代表产物 | 我的判断 |
|---|---|---|---|
| 澄清主文档 | `clarification-notes.md` | `clarified_requirement.md` | 前者偏分析摘要，后者更接近可直接写入 PRD 的需求输入。 |
| 风险/挑战资产 | `challenge-report.md`、`unknowns-ledger.json` | 无严格等价产物 | `stage-harness` 在抗盲区和问题留痕上更强。 |
| 场景覆盖资产 | `generated-scenarios.json`、`scenario-coverage.json` | 无严格等价产物 | `stage-harness` 更适合复杂边界条件场景。 |
| 规格主件 | `.harness/specs/<epic-id>.md`、ShipSpec `PRD.md/SDD.md` | `prd/requirements.md`、`final_prd.md` | `ai-programmer-oms` 的规格主件更统一，阅读门槛更低；`stage-harness` 的规格体系更细分、更工程化。 |
| 决策确认资产 | `decision-bundle.json`、`decision-packet.json` | `summary_effect/questions.*`、`answer.md` | `stage-harness` 更适合自治式决策管理；`ai-programmer-oms` 更适合产品显式参与。 |
| 定稿产物 | 无单一“最终 PRD”中心文件 | `final_prd.md`、`merge_report.md` | 如果组织习惯以最终 PRD 为中心协作，`ai-programmer-oms` 更贴合。 |
| 任务前置资产 | `TASKS.json`、`TASKS.md`、`bridge-spec.md` | 无 | `stage-harness` 更强调需求分析的下游可执行性。 |

## 七、推进逻辑差异

### `stage-harness`

更像这条链：

```text
原始需求
-> CLARIFY（问题、风险、未知项、承载面）
-> SPEC（PRD/SDD/TASKS + harness spec）
-> bridge 到 PLAN
```

它回答的是：

- 需求到底是什么
- 有哪些风险和未知项
- 如何把它固化成可规划、可执行的规格基础

### `ai-programmer-oms`

更像这条链：

```text
原始需求
-> 前置澄清
-> 澄清后需求
-> 初版 PRD
-> 影响面补强
-> 产品确认问题
-> 最终 PRD
```

它回答的是：

- 需求如何被逐步问清
- 如何被整理成一份规范化 PRD
- 产品最后确认后，怎样得到正式定稿

## 八、我的总体判断

### 1. `stage-harness` 更强在“分析控制”

它擅长：

- 把复杂需求拆开
- 暴露风险和未知项
- 建立门禁
- 直接服务后续规划与执行

所以它更像一个：

- **需求分析控制层 + 规格桥接层**

### 2. `ai-programmer-oms` 更强在“需求文档定稿”

它擅长：

- 把模糊需求一步步转成 PRD
- 强化人工回复覆盖校验
- 再做最终产品确认和定稿

所以它更像一个：

- **需求文档生产层 + 产品确认层**

### 3. 如果必须做一句最准确的概括

我的判断是：

- `stage-harness` 的广义需求分析结果，更像“面向后续规划系统的高质量规格底座”。
- `ai-programmer-oms` 的广义需求分析结果，更像“面向产品与交付团队的最终需求文档”。

## 九、适用场景判断

| 场景 | 更适合 `stage-harness` | 更适合 `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 需求复杂、跨模块、风险高 | 是 | 一般 | 这类场景更需要 `stage-harness` 的多角色澄清和风险资产。 |
| 需要快速形成正式 PRD | 一般 | 是 | `ai-programmer-oms` 更适合直接产出和定稿需求文档。 |
| 希望强衔接后续任务规划 | 是 | 一般 | `stage-harness` 从 `SPEC` 就已经开始为 `PLAN` 做准备。 |
| 产品方需要强参与、强确认 | 一般 | 是 | `summary_effect -> finalize_prd` 的回路更符合这种组织方式。 |
| 需要长期审计、复盘未知项和决策 | 是 | 一般 | `stage-harness` 的资产化更完整。 |

## 十、最终结论

如果按广义需求分析来对比，两边其实不是在做同一种“需求分析”：

- `stage-harness` 更偏**分析、约束、规格桥接**
- `ai-programmer-oms` 更偏**PRD 生成、确认、定稿**

所以最准确的理解不是“谁覆盖更多”，而是：

- 一套在构建高质量需求控制面
- 一套在构建高质量最终需求文档

如果你后面还要继续对齐下个阶段，那么最自然的下一份文档应该是：

- `stage-harness` 的 `PLAN`
- 对比 `ai-programmer-oms` 的 `repo_tech_design + cross_repo_tech_design`
