# 执行阶段对比

本文承接前两份对比文档，继续分析下一阶段：

- `stage-harness`
- `ai-programmer-oms`

这里对齐的是**真正开始改代码并进入构建校验**的阶段，而不是需求分析或技术方案阶段。

## 一句话结论

如果按阶段功能对齐：

- `stage-harness` 的这一阶段应看作：`EXECUTE`
- `ai-programmer-oms` 的这一阶段应看作：`execute_tech_design + build_deploy`

也就是说：

- `stage-harness` 更强调**按 task 执行、TDD、smoke、receipt、回流控制**。
- `ai-programmer-oms` 更强调**按仓执行方案、写执行报告、再进入构建/热更/失败自动修复闭环**。

## 一、为什么这样对齐

上一份文档已经把“技术方案/计划阶段”对齐为：

- `stage-harness`: `PLAN`
- `ai-programmer-oms`: `repo_tech_design + cross_repo_tech_design + apply-tech-reply`

再往下一步，两边都进入“真正落代码”的阶段。

但它们对“执行阶段”的定义不同：

### `stage-harness`

`EXECUTE` 并不是简单修改代码，而是：

- 严格按 task 执行
- 先做 preflight
- 按 TDD 内循环改代码
- 做 task smoke
- 写 receipt
- 遇到超范围问题必须回流 `PLAN` 或 `SPEC`

所以它更像一个**开发执行控制系统**。

### `ai-programmer-oms`

技术执行则分成两层：

1. `execute_tech_design`
   - 按仓库执行已定稿技术方案
   - 写执行报告
2. `build_deploy`
   - 构建
   - 热更
   - 构建失败自动修复

所以它更像一个**代码落地 + 构建部署闭环系统**。

## 二、阶段映射

### `stage-harness`

本阶段：

- `EXECUTE`

上游输入：

- `.harness/tasks/*.json`
- `coverage-matrix.json`
- `surface-routing.json`
- plan review / council 通过结果

下游输出：

- git commits
- `.harness/features/<epic-id>/receipts/<task-id>.json`
- task 状态更新
- 必要时 triage / plan_patch / spec_patch 回流

### `ai-programmer-oms`

本阶段：

1. `execute_tech_design`
2. `build_deploy`

上游输入：

- `final_prd.md`
- 各仓技术方案文档
- `build_deploy.json`
- 代码仓目录

下游输出：

- `execution/<repo>_execution_report.md`
- `execution/manifest.json`
- `build_deploy/<repo>/...`
- build / deploy reports
- 自动修复相关产物（如 `ai_result.json`、`fix_report.md`）

## 三、`stage-harness` 的执行阶段实现流程

### 1. 入口门禁

在真正执行前，先要求：

- `stage-gate check PLAN`

必须存在：

- tasks
- `coverage-matrix.json`

否则不允许进入执行。

这说明 `stage-harness` 的执行前提非常明确：

- 计划必须先完整
- 不是边做边想

### 2. 选择执行目标

执行目标不是“整仓代码”，而是：

- 某个 epic 下当前 ready 的 task
- 或者用户显式指定的 task

它强调的是：

- 执行粒度 = task

而不是：

- 执行粒度 = 仓库

### 3. Worker 5-Phase 内循环

每个 task 都必须按固定五步执行：

1. `Re-anchor`
2. `Preflight`
3. `TDD`
4. `Task Smoke`
5. `Commit + Receipt`

#### Re-anchor

重新读取：

- task 详情
- epic 状态
- git 状态
- memory

确保当前实现不会脱离上下文。

#### Preflight

进入实现前要确认：

- 前置 task 已完成
- 工作区干净
- 基线测试通过
- 当前 task 的 surface 在 in-scope 范围内

这说明 `stage-harness` 在写代码前就要求：

- 基线环境可执行
- 当前范围合法

#### TDD

严格要求：

1. RED
2. GREEN
3. IMPROVE

如果发现新问题超出当前 task 范围，不能顺手扩写，必须分类成：

- `local_fix`
- `plan_patch`
- `spec_patch`

#### Task Smoke

每个 task 结束后做最小可运行验证，检查：

- 当前 task 相关测试
- 证据文件
- 无新增编译/类型错误
- evidence 完整

#### Commit + Receipt

完成后必须：

- 原子提交
- 写 receipt
- 标记 task done

receipt 会记录：

- `preflight`
- `base_commit`
- `head_commit`
- `smoke`
- `evidence`
- `new_risks`

所以 `stage-harness` 的执行阶段不是只关心“改了什么”，而是关心：

- 怎么改的
- 是否验证了
- 风险有没有扩散

### 4. 回流与阻断

如果执行中发现：

- 计划不够
- 规格不符
- 连续失败

就会：

- 回流 `PLAN`
- 或回流 `SPEC`
- 或生成 triage

也就是说，它不鼓励“带着结构性问题硬往下冲”。

### 5. 阶段出口

当所有 task 都完成后，才进入：

- `VERIFY`

这意味着 `stage-harness` 的执行阶段出口标准是：

- task 全部完成
- receipt 完整
- smoke 通过

## 四、`ai-programmer-oms` 的执行阶段实现流程

### 1. `execute_tech_design`：按仓执行方案

这一步按仓库逐个执行技术方案。

每个仓的规则是：

- 若技术方案明确“不需要变更”，则跳过执行，写“跳过执行”报告
- 若需要变更，则必须直接改代码

产物：

- `execution/<repo>_execution_report.md`
- `execution/manifest.json`

这里有一个很关键的点：

- 单元测试只要求“撰写即可，不需要执行”

这说明在 `execute_tech_design` 这一层，它强调的是：

- 代码是否已落地
- 报告是否已落盘

而不是：

- 测试是否已通过

### 2. `build_deploy`：构建、热更与失败修复

真正的构建验证闭环是在这一层。

它会根据：

- `build_deploy.json`

读取每个仓的：

- build script
- 参数
- artifact glob
- component
- artifact kind

并且默认只处理在 `execution` 阶段中状态为：

- `executed`

的仓库。

### 3. 构建前版本对比

如果满足条件，会先做本地产物与远端版本比对：

- 一致则跳过
- 不一致才继续构建

这说明它很重视：

- 不做无意义重复构建

### 4. 构建失败自动修复

这是 `ai-programmer-oms` 执行阶段最有代表性的能力。

当构建失败时，它会：

1. 抽取 build log 错误摘要
2. 调 agent 分析失败根因
3. 允许修复：
   - 当前 repo 代码
   - 构建脚本
   - 知识库
4. 生成修复结果产物
5. 再判断是否重试

自动修复循环通过：

- `run_auto_repair_loop()`

控制，直到：

- 成功
- 明确不建议继续重试
- 或达到最大轮次

### 5. 构建成功后的热更

如果不是 `build-only`，构建成功后还会继续：

- 本地热更
- 或远程构建/热更

所以 `ai-programmer-oms` 在这个阶段里把：

- 编译
- 部署
- 失败修复

连成了一条连续闭环。

### 6. 阶段出口

这一阶段完成后，系统得到的不是 task 级 receipt，而是：

- 仓级执行报告
- 仓级构建/热更报告
- 构建失败自动修复记录

它的出口标准更像：

- 该改的仓已改
- 该构建的仓已构建
- 能部署的已部署
- 能自动修复的已尽量修复

## 五、差异总表

| 对比项 | `stage-harness` | `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 阶段范围 | `EXECUTE` | `execute_tech_design + build_deploy` | 两边都在“真正落代码”，但 `ai-programmer-oms` 把构建/热更也算进主执行闭环，而 `stage-harness` 更偏开发执行本身。 |
| 执行粒度 | task 级 | repo 级 | `stage-harness` 更细粒度，适合严格控制；`ai-programmer-oms` 更粗粒度，适合多仓并行推进。 |
| 执行前门禁 | 强，必须先过 PLAN gate | 相对弱，重点在方案已定稿 | `stage-harness` 更强调“准备好了再做”；`ai-programmer-oms` 更强调“先按方案落地，再由构建层验证”。 |
| 开发内循环 | 固定 5-Phase Worker 循环 | 无固定 5-phase，按仓执行方案 | `stage-harness` 的开发方法论更强；`ai-programmer-oms` 的方法论更偏结果导向。 |
| 是否强制 TDD | 是 | 否，单测可写但不要求执行 | 这是两边最明显的差异之一，`stage-harness` 更偏工程纪律，`ai-programmer-oms` 更偏交付效率。 |
| 最小验证位置 | task 完成后立即 smoke | 主要在后续 build_deploy 中体现 | `stage-harness` 把验证前置到 task 级；`ai-programmer-oms` 把验证后移到仓级构建层。 |
| 结果留痕 | receipt + task 状态 + commit | execution report + build/deploy report | 两边都留痕，但前者偏过程审计，后者偏阶段报告。 |
| 超范围问题处理 | 明确回流 `PLAN` / `SPEC` | 主要依赖方案定稿和后续修复闭环 | `stage-harness` 更重视结构性回流；`ai-programmer-oms` 更重视在执行/构建阶段消化问题。 |
| 构建失败修复 | 本阶段不以自动构建修复为中心 | 强，内置 auto repair loop | 在“编译失败自动恢复”这件事上，`ai-programmer-oms` 明显更强。 |
| 部署/热更是否纳入本阶段 | 否，`EXECUTE` 结束即进 `VERIFY` | 是，build 成功后继续 hot-load/deploy | `ai-programmer-oms` 的执行阶段覆盖面更长，已经把部署动作并进来了。 |

## 六、产物差异表

| 类别 | `stage-harness` 代表产物 | `ai-programmer-oms` 代表产物 | 我的判断 |
|---|---|---|---|
| 执行主件 | git commit + task 完成状态 | `<repo>_execution_report.md` | `stage-harness` 以 task 完成为中心；`ai-programmer-oms` 以仓级执行报告为中心。 |
| 过程凭证 | `receipts/<task-id>.json` | `execution/manifest.json` | `receipt` 更细粒度、更适合后续审计；manifest 更适合看阶段概览。 |
| 最小验证凭证 | `smoke` 结果、evidence 文件 | 执行报告中的验证说明 | `stage-harness` 的验证证据更结构化。 |
| 构建产物 | 本阶段无统一构建主件 | `build_deploy/<repo>/...` 各类报告 | `ai-programmer-oms` 在这一阶段把构建产物视为核心资产。 |
| 自动修复产物 | triage / 回流 | `ai_result.json`、`fix_report.md` 等 | 如果关注失败自动修复可视化，`ai-programmer-oms` 更完整。 |
| 阶段出口凭证 | 所有 task done + receipts 完整 | build/deploy reports + manifest | 前者证明“开发任务完成”，后者证明“仓级实施闭环完成”。 |

## 七、推进逻辑差异

### `stage-harness`

更像这条链：

```text
PLAN 通过
-> 选一个 ready task
-> re-anchor
-> preflight
-> TDD
-> smoke
-> commit + receipt
-> 下一个 task
-> 全部完成后进入 VERIFY
```

它要解决的是：

- 当前 task 是否可安全执行
- 当前变更是否可被证据化
- 当前实现是否需要回流计划或规格

### `ai-programmer-oms`

更像这条链：

```text
技术方案定稿
-> execute_tech_design
-> 生成 execution report
-> build_deploy
-> build
-> fail 时 auto repair
-> success 后 deploy/hot-load
```

它要解决的是：

- 仓级方案是否已真正落代码
- 构建是否通过
- 部署是否完成
- 构建失败是否可自动恢复

## 八、我的总体判断

### 1. `stage-harness` 更强在“开发纪律”

它擅长：

- task 粒度控制
- TDD
- smoke
- receipt
- 回流机制

所以它更像：

- **开发执行控制层**

### 2. `ai-programmer-oms` 更强在“落地闭环”

它擅长：

- 按仓执行
- 构建与热更打通
- 构建失败自动修复
- 用报告串起代码落地结果

所以它更像：

- **代码落地与构建修复闭环层**

### 3. 如果必须做一句最准确的概括

我的判断是：

- `stage-harness` 的这一阶段，更像“把计划严格落成开发动作”。
- `ai-programmer-oms` 的这一阶段，更像“把方案落成代码并推动构建部署闭环”。

## 九、适用场景判断

| 场景 | 更适合 `stage-harness` | 更适合 `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 需要强 task 管理和可审计执行链 | 是 | 一般 | `stage-harness` 在这类场景非常强。 |
| 需要把代码修改和构建部署合成一条自动化闭环 | 一般 | 是 | `ai-programmer-oms` 更自然。 |
| 希望测试与验证尽量前置 | 是 | 一般 | `stage-harness` 的 task smoke 和 preflight 更符合这种诉求。 |
| 希望构建失败能自动修复并重试 | 一般 | 是 | `ai-programmer-oms` 明显更强。 |
| 团队更看重工程纪律而不是快速热更 | 是 | 一般 | `stage-harness` 更适合。 |
| 团队更看重多仓交付效率和部署推进 | 一般 | 是 | `ai-programmer-oms` 更适合。 |

## 十、最终结论

如果把这一阶段看成“执行阶段”，那么两边的差别可以概括为：

- `stage-harness` 更偏**task 化开发执行**
- `ai-programmer-oms` 更偏**仓级代码落地 + 构建热更闭环**

所以最准确的理解不是“谁更严格”或“谁更自动化”，而是：

- 一个更擅长控制开发过程
- 一个更擅长推进交付闭环

如果你还要继续往下分析，下一份最自然的文档应该是：

- `stage-harness` 的 `VERIFY + FIX`
- 对比 `ai-programmer-oms` 的 `run_e2e.py generate-case-list + execute_e2e_cases`
