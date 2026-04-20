# 技术方案/计划阶段对比

本文承接上一份“广义需求分析阶段对比”，继续分析下一阶段：

- `stage-harness`
- `ai-programmer-oms`

这里对齐的不是“开始写代码”，而是**在正式执行代码修改之前，系统如何把需求规格转成可执行的技术方案、任务图谱和人工确认结论**。

## 一句话结论

如果按阶段功能对齐：

- `stage-harness` 的这一阶段应看作：`PLAN`
- `ai-programmer-oms` 的这一阶段应看作：`repo_tech_design + cross_repo_tech_design + apply-tech-reply`

也就是说：

- `stage-harness` 更强调把规格转成**可执行任务计划**，核心是 task 图谱、coverage matrix、计划审查和议会门禁。
- `ai-programmer-oms` 更强调把最终 PRD 转成**按仓技术方案并做跨仓收敛**，必要时停下来等待人工技术确认，确认后再把结论回写到各仓方案。

## 一、为什么这样对齐

上一份文档已经把“广义需求分析”对齐为：

- `stage-harness`: `CLARIFY + SPEC`
- `ai-programmer-oms`: `clarification + apply-clarification + draft_prd + discussion + summary_effect + finalize_prd`

再往下一步，两个系统都进入“如何把需求转成技术落地计划”的阶段。

但两边落点不同：

### `stage-harness`

`PLAN` 阶段并不是写泛泛方案，而是要把 `SPEC` 产物转成：

- task 列表
- 依赖图谱
- 风险覆盖矩阵
- 计划审查结果

它的目标是保证后面的 `EXECUTE` 不是自由发挥，而是按计划执行。

### `ai-programmer-oms`

技术侧则是：

1. 先按仓库生成技术方案
2. 再做跨仓收敛
3. 若还有高价值未决问题，则要求人工技术回复
4. 回复覆盖后，把结论回写到各仓方案

它的目标不是先生成 task 图，而是先把“每个仓该怎么改、哪些仓不用改、跨仓是否一致”说清楚。

## 二、阶段映射

### `stage-harness`

本阶段：

- `PLAN`

上游输入：

- `.harness/specs/<epic-id>.md`
- `surface-routing.json`
- `unknowns-ledger.json`
- `scenario-coverage.json`
- `bridge-spec.md`

下游输出：

- `.harness/tasks/*.json`
- `coverage-matrix.json`
- `plan-review.json`
- `councils/verdict-plan_council.json`
- 更新后的 `decision-packet.json`

### `ai-programmer-oms`

本阶段：

1. `repo_tech_design`
2. `cross_repo_tech_design`
3. `apply-tech-reply`

上游输入：

- `final_prd.md`
- 知识库
- 多仓代码目录

下游输出：

- `code/<repo>_tech_design.md`
- `code_review/review_report.md`
- `code_review/all_questions.*`
- `code_review/pending_questions.*`
- `code_review/reply_coverage_report.md`
- `code_review/merge_report.md`

## 三、`stage-harness` 的技术方案/计划阶段实现流程

### 1. 承载面缩圈复核

`PLAN` 开始时，先读取并确认：

- `surface-routing.json`

这一层的目的不是再做一轮开放式探索，而是复核：

- 哪些 surface 在 scope 内
- 哪些已经在前面阶段排除
- 跨承载面边界是否已明确
- `repo_id`、`scan_budget`、`evidence_level` 是否与前序结论一致

同时还会建议先做：

- `codemap-audit`

如果缓存已陈旧，就要求后续 scouts 以源码和契约为准，而不是盲信历史摘要。

### 2. 并行 scouts 调研

随后并行调度多类 scouts，例如：

- `repo-router`
- `docs-scout`
- `design-scout`
- `config-scout`
- `symbol-navigator`
- `dependency-mapper`

这些 scout 的目标不是各写一份完整方案，而是补齐任务规划所需的证据：

- 模块边界
- 依赖关系
- 配置约束
- 代码入口
- 文档意图

这里的关键约束是：

- 只能在 `surface-routing.json` 指定范围内调研
- 不能因为“好像还不够”就自动扩大盲扫范围

### 3. 生成 task 图谱

在收集到足够证据后，`PLAN` 会批量创建 tasks。

每个 task 都要求包含：

- `surface`
- `acceptance_criteria`
- `dependencies`
- `evidence`

跨承载面任务还要显式写出：

- `boundary`
- `deps_cross_surface`
- `integration_points`

所以这一步的本质是把规格转成：

- 可执行单元
- 依赖关系
- 验证要求

### 4. 构建 coverage matrix

接下来把 `unknowns-ledger.json` 中的风险和未知项映射到：

- 对应 task
- 验证手段
- 证据路径

产物：

- `coverage-matrix.json`

如果某条风险暂时映射不到 task，不能静默丢掉，必须进入：

- `unmapped_risks`

这说明 `stage-harness` 的 `PLAN` 不只是“拆活”，而是明确要求：

- 风险也要被计划化
- 验证也要被计划化

### 5. plan-review + plan council

在 task 图谱和 coverage matrix 完成后，还要经过两层审查：

1. `plan-reviewer` 输出 `plan-review.json`
2. `plan_council` 输出 `verdict-plan_council.json`

如果 review 或议会没有通过，就不能进入 `EXECUTE`。

### 6. decision bundle 更新

`PLAN` 阶段新增的决策点还要继续进入：

- `decision-bundle`
- `decision-packet`

所有 `must_confirm` 项都必须在阶段出口前处理掉。

### 7. 阶段出口

只有在以下条件满足时，才能转到 `EXECUTE`：

- `plan-review.json` 为 `READY`
- 计划议会 verdict 可接受
- `coverage-matrix.json` 已生成
- 所有 `must_confirm` 已处理

所以 `stage-harness` 的 `PLAN` 更像：

- **执行前控制中心**

它要确保后续实现动作是：

- 有边界
- 有依赖
- 有验证
- 有风险映射

## 四、`ai-programmer-oms` 的技术方案阶段实现流程

### 1. `repo_tech_design`：按仓生成技术方案

这一步以：

- `final_prd.md`
- 知识库
- 各个仓库目录

为输入，为每个仓单独生成一份技术方案：

- `code/<repo>_tech_design.md`

要求是：

- 每个仓都必须判断是否需要改动
- 即使不需要改，也要写清楚理由
- 如果需要改，要写清改动目标、涉及模块、实现思路、风险、测试建议

并且它是并发执行的，多个仓库同时出方案。

### 2. `cross_repo_tech_design`：跨仓收敛

各仓方案出来后，再进入跨仓收敛。

这一步会重新从：

- 跨组件交互
- 整体链路一致性

两个视角审视全部仓方案。

它会直接修改原始技术方案文档，做几件事：

- 自动消化低风险问题
- 删除已能默认决策的问题
- 把模糊项改写成明确结论
- 保持多仓文档之间不冲突

同时产出：

- `all_questions.md`
- `all_questions.json`
- `pending_questions.md`
- `pending_questions.json`
- `review_report.md`

如果还有待技术确认的问题，就在这里停下。

### 3. `apply-tech-reply`：技术人工回复覆盖校验与方案回写

如果存在待确认问题，人工需要补充技术回复。

系统随后会：

1. 校验回复是否覆盖 `pending_questions`
2. 若不完整：
   - 重写待确认问题文件，只保留未解决项
   - 在回复文件末尾补 `AI补充待确认项`
   - 输出 `reply_coverage_report.md`
   - 阻断流程
3. 若完整：
   - 把结论回写到各仓技术方案
   - 生成 `merge_report.md`
   - 将方案状态定稿

所以 `apply-tech-reply` 不是简单“保存回复”，而是：

- 校验
- 过滤未闭合问题
- 回写技术方案
- 让方案真正收敛

### 4. 阶段出口

这套流程结束后，产物已经足够支撑后面的：

- `execute_tech_design`
- `build_deploy`

也就是说，它的阶段出口不是 task 图谱 ready，而是：

- 各仓技术方案已定稿
- 跨仓矛盾已收敛
- 必要的人为技术拍板已完成

所以 `ai-programmer-oms` 的这个阶段更像：

- **执行前方案定稿中心**

## 五、差异总表

| 对比项 | `stage-harness` | `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 阶段范围 | `PLAN` | `repo_tech_design + cross_repo_tech_design + apply-tech-reply` | 这两边都处在“需求之后、执行之前”，但前者偏计划编排，后者偏方案收敛。 |
| 核心目标 | 把规格转成 task 图谱与风险覆盖计划 | 把最终 PRD 转成按仓技术方案并完成跨仓收敛 | `stage-harness` 更像任务控制系统，`ai-programmer-oms` 更像技术方案生产系统。 |
| 起点输入 | spec、surface-routing、unknowns、bridge-spec | final PRD、知识库、多仓代码目录 | 前者更依赖前序结构化资产；后者更依赖最终 PRD 作为唯一主输入。 |
| 中间分析方式 | scouts 并行调研 + task 建模 + coverage mapping | 各仓并发出方案 + 跨仓统一审视 | 两者都并行，但并行单元不同：一个是“证据与任务”，一个是“仓级方案”。 |
| 主要产物中心 | tasks、coverage matrix、plan review | `<repo>_tech_design.md`、pending questions、merge report | `stage-harness` 更强调执行可控性；`ai-programmer-oms` 更强调方案可读性和跨仓一致性。 |
| 是否显式管理风险覆盖 | 是，风险必须映射到 task 或 `unmapped_risks` | 相对弱，更多融入方案和待确认问题 | 在计划质量控制上，`stage-harness` 更成熟。 |
| 是否显式管理跨仓/跨面边界 | 是，cross-surface task 要写边界和联调点 | 是，通过 cross repo 收敛统一调整文档 | 两边都重视边界，但 `stage-harness` 把边界写进 task，`ai-programmer-oms` 把边界写进方案。 |
| 人工介入方式 | 通过决策包和议会控制 | 通过 `pending_questions` + 技术回复控制 | `ai-programmer-oms` 的人工确认机制更直观；`stage-harness` 的机制更抽象、更适合自治。 |
| 阶段出口标准 | plan review/council 通过，coverage matrix 完整 | 技术回复覆盖完成，方案已回写定稿 | 前者回答“能不能安全执行”，后者回答“方案是否已经收敛”。 |
| 对下游执行的支持方式 | 直接给 `EXECUTE` 提供 task 和验证边界 | 给 `execute_tech_design` 提供按仓方案文档 | `stage-harness` 更强在执行约束，`ai-programmer-oms` 更强在实施说明。 |

## 六、产物差异表

| 类别 | `stage-harness` 代表产物 | `ai-programmer-oms` 代表产物 | 我的判断 |
|---|---|---|---|
| 计划主件 | `.harness/tasks/*.json` | `code/<repo>_tech_design.md` | 前者是任务主件，后者是方案主件，本质上服务对象不同。 |
| 风险覆盖主件 | `coverage-matrix.json` | 无严格等价产物 | 这是 `stage-harness` 的明显优势，它把风险覆盖做成了强结构化资产。 |
| 计划审查 | `plan-review.json`、`verdict-plan_council.json` | `review_report.md` | `stage-harness` 的审查更门禁化；`ai-programmer-oms` 的审查更偏收敛说明。 |
| 边界控制 | cross-surface task 字段、surface-routing 延续 | 跨仓方案回写与统一术语 | 两边都在做边界控制，只是一个偏结构化字段，一个偏文档回写。 |
| 人工确认产物 | `decision-bundle.json`、`decision-packet.json` | `pending_questions.*`、`reply_coverage_report.md`、`merge_report.md` | `ai-programmer-oms` 的人工确认链条更显式，也更容易被人工理解。 |
| 执行前桥接资产 | `bridge-spec.md`、tasks、evidence 要求 | finalized tech design docs | `stage-harness` 更偏执行编排输入，`ai-programmer-oms` 更偏实现说明输入。 |

## 七、推进逻辑差异

### `stage-harness`

更像这条链：

```text
SPEC 产物
-> 承载面复核
-> scouts 调研
-> task 图谱
-> coverage matrix
-> plan review
-> plan council
-> EXECUTE
```

它要解决的是：

- 做哪些 task
- 先后顺序是什么
- 每个风险由谁覆盖
- 每个 task 的证据和验证是什么

### `ai-programmer-oms`

更像这条链：

```text
final PRD
-> repo_tech_design
-> cross_repo_tech_design
-> pending questions
-> apply-tech-reply
-> finalized tech design
-> execute_tech_design
```

它要解决的是：

- 每个仓该不该改
- 每个仓准备怎么改
- 多仓之间是否冲突
- 还有哪些必须找技术负责人拍板

## 八、我的总体判断

### 1. `stage-harness` 更强在“执行前约束”

它擅长：

- 任务化
- 依赖化
- 风险映射
- 验证前置
- 审查门禁

所以它更像：

- **执行前任务控制层**

### 2. `ai-programmer-oms` 更强在“方案定稿”

它擅长：

- 按仓输出可读方案
- 跨仓统一口径
- 把人工确认问题收敛成少量高价值问题
- 把确认结论回写到最终方案

所以它更像：

- **执行前技术方案定稿层**

### 3. 如果必须做一句最准确的概括

我的判断是：

- `stage-harness` 的这一阶段，更像“把规格压缩成可执行计划”。
- `ai-programmer-oms` 的这一阶段，更像“把 PRD 展开成多仓实施方案并收敛定稿”。

## 九、适用场景判断

| 场景 | 更适合 `stage-harness` | 更适合 `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 需要强任务拆解与依赖控制 | 是 | 一般 | `stage-harness` 更适合需要严格执行治理的团队。 |
| 需要多仓分别给出可读实施方案 | 一般 | 是 | `ai-programmer-oms` 在这类场景更自然。 |
| 风险需要显式映射到验证手段 | 是 | 一般 | `coverage-matrix.json` 是很强的工程化资产。 |
| 技术负责人需要对关键边界做集中拍板 | 一般 | 是 | `pending_questions -> apply-tech-reply` 很贴近实际协作习惯。 |
| 希望后续执行阶段严格按任务推进 | 是 | 一般 | `stage-harness` 更强调“先计划好，再执行”。 |

## 十、最终结论

如果把这一阶段看成“技术方案/计划阶段”，那么两边其实仍然不是在做同一件事：

- `stage-harness` 更偏**任务计划化**
- `ai-programmer-oms` 更偏**技术方案定稿化**

所以最准确的理解不是“哪个更完整”，而是：

- 一个更擅长约束执行
- 一个更擅长收敛方案

如果你还要继续往下分析，下一份最自然的文档应该是：

- `stage-harness` 的 `EXECUTE`
- 对比 `ai-programmer-oms` 的 `execute_tech_design + build_deploy`
