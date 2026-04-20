# OMS vs SQLShift 阶段5对比

本文继续对比两套流程在**阶段5**的实现差异：

- `ai-programmer-oms`
- `ai-programmer-sqlshift`

这里的“阶段5”继续采用**按阶段对齐**方式定义，也就是看：

- 方案已经执行并完成构建/部署后
- 系统如何进入**验证 / E2E / 失败修复闭环**

## 一句话结论

如果按阶段顺序继续往后看，阶段5最合理的定义就是：

- **验证与自动修复闭环阶段**

两边在这个阶段的共同主线都是：

1. 生成完整测试 case 列表
2. 执行测试 case
3. case 失败后进入自动诊断与修复

但两边的侧重点明显不同：

- `oms`：更像通用的 E2E 验证与 OMS 代码 bug 修复闭环
- `sqlshift`：更像带强项目约束的 E2E 验证体系，覆盖 UI/API 分层、前后端缺陷分类、服务端日志采集，以及 SQL 转换准确率专项链路

所以更准确地说：

- `oms` 的阶段5是“**通用 E2E 执行 + OMS 代码缺陷自动修复**”
- `sqlshift` 的阶段5是“**SQLShift 专用验证体系 + 前后端代码缺陷自动修复 + 准确率专项闭环**”

## 一、为什么阶段5应该是验证

从阶段顺序看：

- 阶段4已经进入方案执行、构建和热更/部署
- 接下来最自然的顺序就是验证实际结果是否符合需求

这点在两边目录结构里也很清楚：

- 都有独立的 E2E 入口脚本
- 都把这一阶段拆成：
  - `generate-case-list`
  - `execute-cases`

所以这次按阶段对齐，阶段5就应该落在：

- **验证 / E2E / 失败修复闭环阶段**

## 二、阶段5映射

### `ai-programmer-oms`

阶段5主链：

1. `generate_e2e_case_list`
2. `execute_e2e_cases`

入口在：

- `run_e2e.py generate-case-list`
- `run_e2e.py execute-cases`

并支持：

- 指定 case 执行
- 重跑已有 case
- 只执行不自动修复

### `ai-programmer-sqlshift`

阶段5主链同样也是：

1. `generate_e2e_case_list`
2. `execute_e2e_cases`

入口在：

- `run_sqlshift_e2e.py generate-case-list`
- `run_sqlshift_e2e.py execute-cases`

但当前入口控制更简单，主要暴露：

- `max-case-fix-loops`

也就是说，阶段5在两边**仍然是直接对应的**，但 `sqlshift` 的实现更专用、入口更收敛。

## 三、`oms` 阶段5实现流程

### 1. 用例列表生成

`oms` 的用例列表生成会读取：

- 最终 PRD
- 仓库技术方案目录
- 跨仓库技术方案收敛报告
- 知识库

然后生成：

- `generated_test_case_list.md`
- `manifest.json`

它强调的是：

- 覆盖关键需求维度
- 保留范围外与知识缺口 case
- 每个 case 都要有稳定编号、测试目的、操作步骤、预期结果

这一层的核心思路是：

- **从收敛后的需求和技术方案出发，生成一份完整验证清单**

### 2. case 执行

执行阶段会：

- 解析 case 列表
- 逐个执行单 case
- 为每个 case 输出：
  - `test_steps.md`
  - `report.md`
  - `result.json`

它还有几个比较强的控制能力：

- `rerun_existing`
- `cases`
- `execute_only`

也就是说：

- 可以复用历史结果
- 可以只跑局部 case
- 可以把“执行”和“自动修复”拆开

### 3. 失败后的自动修复

`oms` 的失败修复规则很明确：

- 只有明确判断为 `oms_code_bug` 时才允许修复
- 如果是测试资产、E2E 工具、环境、非 OMS 行为、未知原因，则不继续修

一旦确认是 OMS 代码 bug，允许：

- 修改 OMS 代码
- 做最小范围构建验证
- 进行热更/生效动作

最终形成：

- `e2e_execution_summary.md`
- `manifest.json`
- 每个 case 的失败摘要、AI 结果、修复报告等

因此 `oms` 的阶段5本质上是：

- **E2E 执行 + 仅针对 OMS 代码 bug 的自动修复闭环**

## 四、`sqlshift` 阶段5实现流程

### 1. 用例列表生成

`sqlshift` 的 case 列表生成明显更重：

除了读取：

- 最终 PRD
- 仓库技术方案目录
- 跨仓库技术方案收敛报告
- 知识库

它还会进一步引入：

- SQLShift E2E 工具文档
- API 参考目录
- 用例层级与前后端映射规则
- `WORKING_DIR` 真实代码目录
- `build_deploy` 阶段 manifest
- `build_deploy` 汇总报告
- 代码修改总结索引

这说明它生成 case 的依据不只是“需求与方案”，而是进一步拉到了：

- **真实代码改动事实**

同时它还有两个很强的约束：

- 测试项必须能回溯到本次需求点
- 当本次需求涉及新增数据库组合时，必须生成准确率测试 case，并显式要求使用 `sqlshift-accuracy-test`

因此 `sqlshift` 的 case 生成更像：

- **需求点驱动 + 真实改动校正 + 准确率专项纳入**

### 2. case 执行

`sqlshift` 的 case 执行同样会为每个 case 生成：

- 步骤文档
- 测试报告
- 结果 JSON

但它比 `oms` 增加了很多产品专属约束：

- 区分 `UI` / `API` / `API+UI`
- UI 验证依赖人工预登录的 Playwright MCP 浏览器会话
- API 500 等服务端错误时，必须采集远端服务端日志
- 结果 JSON 里会额外记录 `affected_component`

也就是说，它不是一个通用 E2E 执行器，而是：

- **带前后端映射、人工登录前提和远端日志采集规范的专用执行链**

### 3. 准确率专项链路

这是 `sqlshift` 阶段5最特殊的一层。

当 case 需要走准确率专项时，执行要求并不是“跑完一个 case 即可”，而是必须完成整条链路：

- 登录与项目准备
- 源端连接
- 批量生成
- 源端验证
- 单条转换并等待
- 结果验证
- 必要修复循环
- 结果汇总

并且有强约束：

- 只要状态还在 `running/pending` 就必须持续轮询
- 验证失败后不能只修不复验
- 必须完成“验证 -> 修复 -> 重新验证”循环，直到终态

这说明 `sqlshift` 的阶段5已经不只是普通 UI/API 验证，而是包含：

- **转换正确性与修复收敛的专项验证流程**

### 4. 失败后的自动修复

`sqlshift` 的失败判因比 `oms` 更细：

- `backend_code_bug`
- `frontend_code_bug`
- `test_asset_issue`
- `e2e_tooling_issue`
- `environment_issue`
- `expected_behavior`
- `unknown`

只有在明确是：

- `backend_code_bug`
- `frontend_code_bug`

时才允许修复。

而且修复后的生效动作不是泛泛地“重新构建热更”，而是更明确地走：

- `python -m sqlshift_e2e_tools.deploy backend`
- `python -m sqlshift_e2e_tools.deploy frontend`

再加上修复前会预采集远端日志，必要时继续补采，说明它的闭环已经深入到：

- 远端服务日志
- 前后端组件级别
- 专用部署工具

因此 `sqlshift` 的阶段5本质上是：

- **E2E 执行 + 前后端分类诊断 + 专用部署修复 + 准确率专项收敛**

## 五、差异总表

| 对比项 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 阶段5是否直接对应 | 是 | 是 | 这一阶段两边仍然直接对应，都是验证与自动修复闭环。 |
| 阶段5主链 | `generate-case-list -> execute-cases` | `generate-case-list -> execute-cases` | 主线一致，可以按同一阶段比较。 |
| 用例生成依据 | PRD + 技术方案 + 收敛报告 + 知识库 | 在前者基础上再引入真实代码、build_deploy 总结、API 参考、映射规则 | `sqlshift` 在“验证范围如何确定”这件事上更严格、更贴近真实改动。 |
| 测试定位 | 通用 OMS E2E | SQLShift 专用 UI/API/UI+API 分层验证 | `sqlshift` 更强调测试层级与前后端映射证据。 |
| 执行入口控制粒度 | 更细，支持指定 case、重跑、只执行 | 当前入口更简，主打整链执行 | `oms` 更像测试控制台，`sqlshift` 更像标准化专用流水线。 |
| 失败分类 | 主要区分是否为 OMS 代码 bug | 明确拆成前端 bug、后端 bug、环境、工具等 | `sqlshift` 的判因粒度更细，后续动作也更明确。 |
| 修复后的生效方式 | 最小范围构建/热更 | 前后端分别走专用 deploy 工具 | `sqlshift` 的修复闭环更贴近实际部署拓扑。 |
| 是否含专项验证链路 | 无明显专项链 | 有准确率专项与验证-修复-复验闭环 | 这是两边阶段5最大的能力差异。 |

## 六、产物差异表

| 类别 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 用例清单产物 | `generated_test_case_list.md` + `manifest.json` | 同类产物，但目录与阶段名独立 | 两边都有稳定产物，`sqlshift` 会额外沉淀改动索引辅助生成。 |
| case 执行产物 | `test_steps.md`、报告、结果 JSON | 同类产物，并增加 `test_level`、`affected_component` | `sqlshift` 的结果结构更适合后续前后端归因。 |
| 汇总产物 | `e2e_execution_summary.md` + `e2e_cases_executed` manifest | `e2e_execution_summary.md` + `sqlshift_e2e_cases_executed` manifest | `sqlshift` 明确把自己从通用 E2E 阶段名中分叉出来。 |
| 修复产物 | 失败摘要、AI 结果、修复报告 | 同类产物，并带预采集服务端日志、专项 workflow 完整性信息 | `sqlshift` 的修复证据链更完整。 |

## 七、推进逻辑差异

### `ai-programmer-oms`

更像：

```text
最终方案
-> 生成完整 case 列表
-> 执行 case
-> 日志分析
-> 判断是否为 OMS 代码 bug
-> 若是则最小范围修复并热更
-> 汇总结果
```

它强调的是：

- 完整验证
- 对 OMS 代码 bug 做有限自动修复
- 保持执行控制粒度

### `ai-programmer-sqlshift`

更像：

```text
最终方案
-> 基于需求点与真实改动生成 case 列表
-> 执行 UI/API/API+UI case
-> 采集远端日志并归因前后端
-> 若是前后端代码 bug 则走专用 deploy 修复
-> 对准确率专项继续执行验证-修复-复验循环
-> 汇总结果
```

它强调的是：

- 本次需求真实触达范围
- 前后端归因
- 远端日志证据
- 准确率专项闭环

## 八、我的总体判断

### 1. 阶段5确实应该定义为验证闭环阶段

现在可以比较确定：

- 阶段4是执行
- 阶段5就是验证与自动修复

这个划分是稳定的。

### 2. `oms` 的阶段5更像“通用 E2E 验证控制层”

它的特点是：

- 用例生成逻辑相对通用
- case 执行控制更灵活
- 修复范围集中在 OMS 代码 bug

所以更像一套：

- **通用验证与回归修复控制台**

### 3. `sqlshift` 的阶段5更像“产品专用验收体系”

它的特点是：

- 用例生成强依赖真实改动事实
- 执行时区分 UI / API / API+UI
- 错误分析直接下探到远端日志
- 修复动作按前端/后端组件拆开
- 准确率专项是硬约束链路

所以更像一套：

- **围绕 SQL 转换产品特性深度定制的验收与修复体系**

### 4. 如果必须做一句最准确的概括

我的判断是：

- `oms` 的阶段5是“通用 E2E 验证与 OMS 代码缺陷修复闭环”
- `sqlshift` 的阶段5是“以真实改动、前后端归因和准确率专项为核心的专用验证闭环”

## 九、适用场景判断

| 场景 | 更适合 `oms` | 更适合 `sqlshift` | 我的判断 |
|---|---|---|---|
| 需要通用的 E2E 回归与局部重跑控制 | 是 | 一般 | `oms` 更适合。 |
| 需要严格按本次真实改动筛测试范围 | 一般 | 是 | `sqlshift` 更适合。 |
| 需要把失败明确归因为前端或后端代码问题 | 一般 | 是 | `sqlshift` 的分类与生效动作更清晰。 |
| 需要验证数据库组合转换准确率并闭环修复 | 否 | 是 | 这是 SQLShift 的明显强项。 |

## 十、最终结论

如果继续按阶段对齐，阶段5最合理的定义就是：

- **验证 / E2E / 自动修复闭环阶段**

而在这个阶段里，两边仍然保持同一主线：

- `generate-case-list`
- `execute-cases`

但两边的分化也已经非常明显：

- `oms` 更强调通用 E2E 控制与 OMS 代码缺陷修复
- `sqlshift` 更强调真实改动驱动的验证范围、前后端精细归因，以及 SQL 转换准确率专项闭环
