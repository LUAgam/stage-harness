# stage-harness 后续阶段通用化改造方案

本文聚焦一个更具体的问题：

- 结合当前对 `stage-harness`、`ai-programmer-oms`、`ai-programmer-sqlshift` 的理解
- 已知你已经实测确认：`stage-harness` 在**需求分析 -> 开发方案形成**这段，已经可以覆盖 `oms` 和 `sqlshift`
- 现在要继续分析：对于后续阶段，`stage-harness` 应该如何改造，才能支持：
  - `oms`
  - `sqlshift`
  - 以及未来更多项目

同时必须满足一个核心约束：

- `stage-harness` 的初衷仍然是**通用插件**
- 不能为了支持 `oms` / `sqlshift`，把自己做成**贴具体项目、贴具体需求、贴具体仓库结构**的专用系统

## 一句话结论

如果前半段已经可行，那么 `stage-harness` 后半段最合理的改造方向不是：

- 把 `oms` / `sqlshift` 的构建脚本、E2E 工具链、部署逻辑直接搬进来

而是：

- 把 `stage-harness` 改造成一个**后续阶段可插拔编排框架**

更具体地说：

- `stage-harness` 负责：阶段治理、状态推进、门禁、证据归档、问题分类、决策回路
- 项目适配层负责：执行、构建、部署、验证、修复、清理这些**项目专属动作**

换句话说：

- **前半段统一流程**
- **后半段统一协议**
- **具体动作通过 adapter / provider / profile 插拔**

## 一、当前现状判断

基于现有实现，可以先形成一个比较清楚的判断：

| 阶段 | 当前 `stage-harness` 状态 | 结论 |
|---|---|---|
| `CLARIFY` | 已能支撑 | 基本可覆盖 `oms/sqlshift` |
| `SPEC` | 已能支撑 | 基本可覆盖 |
| `PLAN` | 已能支撑 | 基本可覆盖 |
| `EXECUTE` | 只有通用回执与阶段门禁骨架 | 缺项目执行器 |
| `VERIFY` | 有 `verification.json` 门禁语义 | 缺项目验证器 |
| `FIX` | 有状态回路与回退机制 | 缺项目修复执行器 |
| `DONE` | 有 `delivery-summary.md` / `release-notes.md` | 缺统一的交付收口协议 |

所以现在真正的差距已经很集中：

- 不在需求与方案层
- 主要在**执行、验证、修复、交付收尾**这四段

## 二、改造目标不应该是什么

为了避免把 `stage-harness` 做坏，先明确哪些方向不应该走。

### 不建议的方向

| 方向 | 问题 |
|---|---|
| 直接内置 `oms` 的 `build_deploy` 逻辑 | 会把通用插件做成 OMS 专用插件 |
| 直接内置 `sqlshift` 的准确率验证链 | 会把通用状态机和专项产品逻辑耦死 |
| 在 CLI 中硬编码项目名分支 | 短期快，长期不可维护 |
| 把具体仓库路径、脚本名、部署命令写进 stage gate | 失去跨项目复用能力 |
| 把“某项目测试通过”的标准写成全局标准 | 不同项目验证语义不同，会造成框架污染 |

### 应该坚持的边界

| 边界 | 说明 |
|---|---|
| `stage-harness` 只定义流程协议，不定义项目动作细节 | 保持框架通用性 |
| 项目动作下沉到适配层 | 支持多项目扩展 |
| 阶段门禁检查“产物契约”，不检查具体脚本名 | 避免耦合具体实现 |
| FIX 只定义问题分类和回路，不预设具体修复工具 | 支持不同项目的修复模型 |

## 三、核心设计原则

如果要让后半段变得通用，我建议 `stage-harness` 后续改造遵循下面 6 个原则。

| 原则 | 含义 | 价值 |
|---|---|---|
| 协议优先 | 先定义输入/输出契约，再接项目能力 | 防止框架污染 |
| 能力下沉 | 执行/验证/修复细节由 adapter 提供 | 便于扩展新项目 |
| 证据统一 | 所有项目都回写统一结构化证据 | VERIFY/FIX/DONE 可统一治理 |
| 问题分类统一 | 失败结果统一归因模型 | FIX 回路才能通用 |
| profile 驱动 | 用项目画像选择能力组合 | 避免硬编码项目名 |
| 渐进增强 | 先支撑基础执行，再支撑专项能力 | 降低一次性大改风险 |

## 四、建议的总体架构

建议把后半段改造成下面这种分层结构：

| 层次 | 角色 | 由谁负责 |
|---|---|---|
| 流程层 | 状态机、阶段切换、门禁、回路、归档 | `stage-harness` |
| 协议层 | 定义 execute/verify/fix/done 的统一契约 | `stage-harness` |
| 能力编排层 | 根据项目 profile 选择 provider/adapters | `stage-harness` |
| 项目适配层 | 构建、部署、测试、修复、清理的真实动作 | 项目 adapter |
| 项目工具层 | 脚本、E2E 工具、部署脚本、日志采集工具 | 各项目自有实现 |

换句话说：

- `stage-harness` 不是直接执行所有项目动作
- 而是调用“满足统一协议的项目能力模块”

## 四点五、跨阶段上下文传递协议（outputs / context）

后半段不仅是「各阶段各自产出 JSON」，还需要在 **EXECUTE → VERIFY → FIX** 之间传递**动态上下文**（例如：被拉起的服务 URL/端口、构建产物路径、临时环境/凭据句柄、测试目标集合、部署实例标识等）。否则 verifier / fix 只能「猜」上一阶段做了什么，既不安全也难复现。

**Run 级隔离（协议基础单位）**：后半段的一切动态状态与落盘产物必须以 **`run_id` 为隔离单位**。`run_id` 是后半段协议的基础隔离单位；所有后半段的动态状态、`context`、`outputs`、锁文件、证据与可追溯索引**必须**落在 **`.harness/runs/<run_id>/`** 之下（具体子路径可再约定，但不得散落在「单例」根路径上裸写）。**禁止**在 workspace 根或固定单文件名上写入可并发覆盖的「全局 context」，以免多 Run 并发时互相覆盖。

建议在协议层明确一份 **outputs / context 契约**（与具体项目解耦、但与阶段衔接强相关），例如（文件名可随实现微调，语义应保留；路径均相对于上述 `run` 目录理解）：

| 产物 / 入口 | 作用 |
|---|---|
| `stage-outputs.json` | 各阶段结构化输出的索引与版本信息，供门禁与下游解析 |
| `context.json` | 机器可读的跨阶段键值（建议含 `schema_version`、关键 ID、路径引用） |
| `context.env` | **仅允许**存放**非敏感**或**仅限本机临时会话**的键值（如本地调试端口、 workspace 内临时路径）；**禁止**将高危凭据（密码、长期 token、私钥材料等）以明文写入磁盘。**禁止**把密钥当作普通字符串落盘。敏感信息**只能**通过 **`secret_reference_id` / secret handle**（由外部秘密管理与解析）等方式传递与引用；框架与门禁侧只校验「引用是否存在、格式是否合法」，不持久化密钥明文 |

**依赖声明**：后一阶段应能**显式声明**依赖前一阶段哪些输出键或哪些文件（而非仅靠隐式目录约定）；框架在切阶段前可做「依赖就绪」检查，避免带着空上下文进入 `VERIFY` / `FIX`。

## 四点六、异常中断下的生命周期：ABORT / CANCEL / TEARDOWN

仅有「正常走完 `DONE`」不足以覆盖真实执行：`timeout`、人为中止、门禁失败后的早退、外部依赖崩溃等都会中断。后续阶段除 `DONE` 外，需要统一的 **`ABORT` / `CANCEL` / `TEARDOWN` 语义**（实现时可映射为状态位或事件名，但语义需稳定、可观测）：

| 语义 | 典型含义 |
|---|---|
| `ABORT` | 不可恢复或策略中止：保留当前证据快照并停止编排 |
| `CANCEL` | 用户 / 上游主动取消：尽量不打断已落盘的审计信息 |
| `TEARDOWN` | 释放资源、关闭进程、撤销临时部署等**清理闭环** |

**无状态 CLI 的现实约束**：典型 `harnessctl` 类 CLI **无法保证**当前进程在任意时刻都走完 `finally` 或完成清理（进程被 kill、机器掉电、子进程泄漏等）。因此 **`TEARDOWN` 不能只依赖当前进程的同步 `finally`**，必须把清理责任设计成**可跨进程、可重入、可补做的机制**。

**收敛为「即时尝试 + 异步兜底回收」**：

- **即时尝试**：在本 Run 仍存活的路径上，仍应调用 provider `cleanup`，并尽量完成一次幂等的 `TEARDOWN`（与下文 registry 联动）。
- **异步兜底**：在 **`.harness/runs/<run_id>/`**（或约定的集中位置）维护 **`resource-registry.json`**（或等价注册表）与配套的 **`resource.lock` / 锁语义**，登记本会话申请的外部资源（端口、临时部署 id、子进程 pid、云资源句柄等）。进程异常退出后，**独立**的 **`harnessctl gc`**、**`harnessctl teardown <run_id>`** 或定时任务可根据 registry **异步回收**遗留资源；CLI **启动时**也可扫描**遗留 run**（registry 存在且未闭合、锁超时等）触发回收或告警，避免长期泄漏。

**Provider 责任与框架兜底**：

- 每个 provider **必须**提供 `cleanup` hook（或等价接口），说明在异常路径下如何释放本阶段申请的资源，并与 **resource registry** 写入/撤销约定一致（幂等、可重入）。
- `stage-harness` 在流程层负责**兜底调度**：在正常 `DONE`、门禁失败早退、**以及异常路径**中，都应尽量触发一次可幂等的 `TEARDOWN` 尝试，但**不以**「当前进程一定执行完」为唯一保障。

换言之：**清理不能默认只依赖「正常进入 `DONE`」或「单次进程内的 finally」**；必须配合 registry + 异步 gc/teardown，否则长期运行会出现端口占用、临时实例遗留、外部账单类副作用等工程债务。

## 五、对后续四个阶段的改造建议

## 5.1 `EXECUTE` 阶段改造

### 当前问题

当前 `EXECUTE` 的门禁主要还是：

- 有无 `receipts`

这对于真正覆盖 `oms` / `sqlshift` 还太弱，因为不同项目在执行阶段至少会出现这些差异：

- 执行单位不同（任务级、仓库级、模块级、服务级）
- 执行动作不同（改代码、生成文件、构建、热更、远程部署）
- 执行证据不同（receipt、execution report、manifest、change summary）

### 建议改造

把 `EXECUTE` 改造成“**统一执行协议 + 多种执行 provider**”。

#### 建议新增统一执行契约

例如要求每个项目执行完后，至少产出统一结构：

| 文件 | 作用 |
|---|---|
| `execution-summary.json` | 本阶段统一汇总 |
| `execution-items.json` | 每个执行单元的状态 |
| `execution-evidence.md` | 可读性报告 |
| `receipts/` | 保留原有 receipt 机制 |

#### `execution-summary.json` 建议字段

| 字段 | 说明 |
|---|---|
| `execution_mode` | `task` / `repo` / `service` / `custom` |
| `units_total` | 执行单元总数 |
| `units_executed` | 实际执行数 |
| `units_skipped` | 跳过数 |
| `build_followed` | 是否已衔接构建 |
| `artifacts` | 关键产物列表 |
| `provider` | 使用的执行 provider |

### 对 `oms/sqlshift` 的映射方式

| 项目 | 可映射 provider |
|---|---|
| `oms` | `repo-execution-provider` |
| `sqlshift` | `repo-execution-provider` + `project-rules-extension` |
| 未来普通项目 | `generic-task-provider` / `repo-execution-provider` |

### 改造价值

这样 `EXECUTE` 阶段就不再假设：

- 所有项目都必须按 task 执行

而是统一支持：

- task 级
- repo 级
- service 级
- 自定义执行单元

## 5.2 `VERIFY` 阶段改造

### 当前问题

当前 `VERIFY` 主要依赖：

- `verification.json`

并检查若干 review verdict。

但未来想支撑更多项目，就必须接受一件事：

- 不同项目的“验证”并不等于同一种东西

比如：

| 项目类型 | 验证重点 |
|---|---|
| 通用后端项目 | 单测 / 集成测试 / smoke |
| 类 `oms` 项目 | E2E case 执行 + 缺陷归因 |
| 类 `sqlshift` 项目 | E2E + 日志采集 + 准确率专项 |
| 基础设施项目 | plan/apply 校验、漂移检查 |
| 文档/知识项目 | 语义核对、链接/结构校验 |

### 建议改造

把 `VERIFY` 改造成“**验证协议 + verifier provider**”。

#### 建议新增统一验证契约

| 文件 | 作用 |
|---|---|
| `verification.json` | 总验收结构化结果 |
| `verification-evidence.md` | 人类可读验收报告 |
| `verification-items.json` | 每个验证项执行情况 |

#### `verification.json` 建议统一字段

| 字段 | 说明 |
|---|---|
| `verification_mode` | `review_only` / `tests` / `e2e` / `hybrid` |
| `provider` | 使用的 verifier |
| `overall_verdict` | `PASS` / `FAIL` / `CONDITIONAL_PASS` |
| `blocking_issues` | 阻断问题列表 |
| `failure_categories` | 失败归因统计 |
| `evidence_refs` | 关键证据路径 |
| `reverify_required` | 是否必须进入 FIX 后复验 |

#### verifier provider 示例

| provider | 适用项目 |
|---|---|
| `generic-review-verifier` | 通用项目 |
| `test-suite-verifier` | 以单测/集成测试为主的项目 |
| `e2e-case-verifier` | 类 `oms` 项目 |
| `scenario-accuracy-verifier` | 类 `sqlshift` 项目 |
| `hybrid-verifier` | 需要多种验证方式并存的项目 |

### 改造价值

这样 `VERIFY` 就不再把“验收”绑死成某一种测试模型，而是：

- 允许不同项目用不同 provider
- 但最后统一回写同一份 `verification.json`

这才适合做通用插件。

## 5.3 `FIX` 阶段改造

### 当前问题

`FIX` 现在在 `stage-harness` 中的优势是：

- 有明确回路
- 能回 `VERIFY`
- 必要时能回 `PLAN`

但它目前缺的是：

- 一个对不同项目都适用的**问题分类和修复协定**

### 建议改造

把 `FIX` 改造成“**统一问题分类模型 + fix provider**”。

#### 建议统一问题分类

不建议只围绕某项目定义，比如“OMS 代码 bug”。

建议定义更抽象的分类：

| 分类 | 含义 |
|---|---|
| `implementation_defect` | 代码实现缺陷 |
| `build_or_package_issue` | 构建/打包问题 |
| `deployment_issue` | 部署/生效问题 |
| `test_asset_issue` | 测试资产问题 |
| `tooling_issue` | 工具链问题 |
| `environment_issue` | 环境问题 |
| `spec_or_plan_gap` | 方案本身缺口，需要回退到 `PLAN` |
| `requirement_gap` | 需求理解问题，需要回退到更前阶段 |
| `expected_behavior` | 当前行为符合预期，无需修复 |
| `unknown` | 暂时无法判定 |

这个分类比 `oms/sqlshift` 当前各自的修复分类更抽象，更适合通用框架。

#### 建议新增统一 FIX 产物

| 文件 | 作用 |
|---|---|
| `fix-summary.json` | 本轮修复的结构化结论 |
| `fix-report.md` | 可读修复报告 |
| `reverify-request.json` | 回 VERIFY 所需信息 |

#### `fix-summary.json` 建议字段

| 字段 | 说明 |
|---|---|
| `root_cause_category` | 统一问题分类 |
| `fix_applied` | 是否实际修复 |
| `provider` | 使用的 fix provider |
| `retry_recommended` | 是否建议重新验证 |
| `fallback_stage` | 若不能在 FIX 收敛，应回退到哪个阶段 |
| `knowledge_action` | 是否补知识 |

### fix provider 示例

| provider | 适用项目 |
|---|---|
| `generic-code-fix-provider` | 普通项目代码修复 |
| `build-repair-provider` | 构建失败项目 |
| `e2e-fix-provider` | 类 `oms` 项目 |
| `scenario-repair-provider` | 类 `sqlshift` 项目 |

### 改造价值

这样 `FIX` 的回路仍然是统一的，但修复动作是插件化的。

## 5.4 `DONE` 阶段改造

### 当前问题

当前 `DONE` 已经有：

- `delivery-summary.md`
- `release-notes.md`
- `release_council`

这已经比很多流程强了，但如果后续阶段要真正通用化，`DONE` 还应承担：

- 交付结果标准化
- 项目适配层输出的统一归档
- 收尾策略声明

### 建议改造

把 `DONE` 改造成“**统一交付收口协议**”。

#### 建议新增统一交付产物

| 文件 | 作用 |
|---|---|
| `delivery-summary.md` | 人类可读交付总结 |
| `delivery-manifest.json` | 结构化交付清单 |
| `release-notes.md` | 对外发布说明 |
| `post-delivery-actions.json` | 后续是否需要人工清理/释放/观察 |

#### `delivery-manifest.json` 建议字段

| 字段 | 说明 |
|---|---|
| `execution_provider` | 本次执行器 |
| `verification_provider` | 本次验证器 |
| `fix_provider` | 本次修复器 |
| `artifacts` | 关键交付产物 |
| `known_limits` | 仍保留的限制 |
| `manual_followups` | 需要人工继续做的事 |

### 改造价值

这样 `DONE` 才不会只是“结束标记”，而是：

- 真正的标准交付出口

## 六、建议引入的三类通用扩展机制

如果想保持通用性，我建议不要直接做“项目特判”，而是引入以下三类机制。

## 6.1 Project Profile

通过 profile 决定项目属于什么类型，而不是直接判断项目名。

### 示例画像维度

| 维度 | 示例值 |
|---|---|
| `execution_shape` | `task`, `repo`, `service` |
| `delivery_shape` | `local_build`, `remote_deploy`, `artifactless` |
| `verification_shape` | `review`, `test`, `e2e`, `hybrid` |
| `repair_shape` | `code_only`, `build_fix`, `e2e_fix`, `scenario_fix` |
| `cleanup_shape` | `none`, `manual`, `resource_release` |

这类 profile 可以写入：

- `.harness/project-profile.yaml`

而不是写死项目名。

## 6.2 Stage Providers

每个后续阶段都允许按 profile 装配 provider。

**实施顺序原则（与 `compat` 双写对齐）**：`compat` 双写**不应**先于「最薄 provider 骨架」单独落地；建议与 **default / dummy provider** 同周期引入，由后者承担首轮兼容产物的编排与输出挂靠，再逐步换为真实 adapter。否则易出现「协议主件已双写、但编排层无处承接」的返工。

### 建议 provider 组合

| 阶段 | provider 类型 |
|---|---|
| `EXECUTE` | `execution_provider` |
| `VERIFY` | `verification_provider` |
| `FIX` | `fix_provider` |
| `DONE` | `delivery_provider` |

### provider 选择逻辑

可以采用：

| 方式 | 说明 |
|---|---|
| profile 显式指定 | 最稳定 |
| 默认 provider fallback | 普通项目直接可用 |
| workspace probe 推断 | 作为初始化建议，不作为最终真相 |

### 接入硬约束：幂等性与并发控制

对 **execution / verification / fix** 及各类 provider：`TEARDOWN`、`cleanup`、对外部资源的申请与释放、以及与 **`run_id` 对齐的落盘**，应满足 **幂等性**（同一操作重复执行结果一致、不重复扣费或泄漏）。在存在多进程 / 多会话可能时，必须在 **`run_id` 或更细的约定范围**内使用 **lock scope**（如 `resource.lock`、阶段级锁等），避免并发覆盖 registry、并发双写证据或重复调度 **TEARDOWN**。上述要求是**接入契约的一部分**，不是可选优化项。

## 6.3 Artifact Contract

这是最关键的一层。

不管 provider 如何不同，最后都必须向 `stage-harness` 回写统一产物。

这样 stage gate 才能继续保持通用。

## 七、建议新增的通用门禁设计

未来后半段门禁不应再只是“文件存在”，而应该是：

- 文件存在 + 结构合法 + 语义最小成立 + **可复核的真实证据（防空转 / 防造假）**

仅校验「文件存在 + JSON 结构合法」容易退化为 provider 自证；框架层需要额外约束，使门禁对应到**真实发生过的执行 / 验证**，而不是空壳产物。

**框架职责边界（明确区分「门禁」与「业务真相」）**：

- **框架层（stage gate）**只负责：证据与产物的**存在性**、**格式合法性**、**索引与引用可追溯性**（例如路径、哈希、外部 run id 字段齐全且可解析），以及与本协议互证的最小一致性检查。
- **框架不负责**验证外部系统（CI、云平台、被测业务）中「业务上是否真如所述发生」——那是外部世界的真相问题，超出通用编排内核范围。
- **业务真实性**、专项合规结论应由**人工审计**，或通过可插拔的 **`Audit Verifier` / 外部审计适配器**（若接入）承担；框架可提供挂载点，但不把专项真相验证硬编码进核心门禁逻辑。

### 建议的「真实证据」维度（示例）

| 维度 | 说明 |
|---|---|
| 执行 / 验证日志索引 | 可追溯的控制台、日志片段或归档路径 |
| 计时 | 起止时间或耗时，用于识别「瞬时假完成」 |
| 产物哈希或指纹 | 关键 `artifacts` 的内容哈希，或经约定的大小 + mtime 等组合 |
| 版本锚点 | `commit` / `build id` / CI run id 等，绑定到具体代码与构建 |
| 测试结果索引 | 测试类验证应对接可复核报告（如 JUnit、trace、HTML 报告路径） |
| Provider 运行元数据 | provider 名称、版本、参数摘要、运行环境摘要（不含密钥） |

### 防空转 / 防造假规则（建议作为硬约束写入门禁）

| 规则 | 说明 |
|---|---|
| `units_total = 0` | **不得**默认视为执行成功；除非存在可验证的 `skip` / `no-op` 声明，或经显式授权的空跑策略，并在产物中给出原因与审计锚点 |
| 无真实执行 / 验证证据 | 仅有「空壳」`execution-summary` / `verification` 不通过：至少应能链接到日志、哈希、外部系统 run id 等**一类以上**可复核证据 |
| 单方自证不足 | 门禁既读取 provider 产出，也建议由框架写入最小互证信息（例如门禁判定时刻、输入 / 输出指纹），降低单方伪造空间 |

**实现提醒（高风险 VERIFY）**：对验收链路过长、或模型深度参与生成与解释的场景，**高风险 VERIFY 应优先采用独立 verifier、独立 reviewer 视角或外部可复跑证据**，避免在同一模型会话上下文中「自写自证」。这与框架是否校验「文件存在」无关，是防止静默失败的关键工程红线。

### 建议门禁总表

| 阶段 | 建议门禁 | 证据 / 防空转要点 |
|---|---|---|
| `EXECUTE` | 必须存在 `execution-summary.json` 且 `units_total >= units_executed + units_skipped` | 满足上表「真实证据」中对执行链的最小要求；`units_total = 0` 按上表规则处理 |
| `VERIFY` | 必须存在 `verification.json` 且有 `overall_verdict` | `overall_verdict` 须与可追溯的验证产物或日志索引一致，禁止仅凭空 verdict |
| `FIX` | 必须存在 `fix-summary.json`，若 `retry_recommended=true` 则必须能回 `VERIFY` | 若声明已修复，应有对应变更或工具痕迹的可索引说明 |
| `DONE` | 必须存在 `delivery-manifest.json` 与 `delivery-summary.md` | 交付清单应引用关键 artifacts 与版本锚点，与前置阶段互证 |

### 建议语义门禁

| 情况 | 动作 |
|---|---|
| `verification.json.overall_verdict = FAIL` | 不允许进 `DONE` |
| `fix-summary.json.fallback_stage = PLAN` | 强制回 `PLAN` |
| `delivery-manifest.json.manual_followups` 非空 | 允许 `DONE`，但标记 `RELEASE_WITH_CONDITIONS` |

## 八、如何支持 OMS 和 SQLShift，但又不限于它们

这是这份文档的核心。

我建议这样理解：

| 问题 | 正确方向 |
|---|---|
| 如何支持 `oms` | 不是内置 OMS 逻辑，而是让 OMS 提供一组 provider |
| 如何支持 `sqlshift` | 不是内置 SQLShift 专项逻辑，而是让 SQLShift 提供一组 provider |
| 如何支持未来项目 | 让未来项目也按同一协议接 provider |

换句话说：

- `oms` 和 `sqlshift` 只是第一批 adapter 样本
- 不是框架的目标形态

### 建议的通用落地方式

| 项目 | 推荐接入方式 |
|---|---|
| `oms` | 接 `repo-execution + build-deploy + e2e-case + code-fix` provider 组合 |
| `sqlshift` | 接 `repo-execution + specialized-deploy + scenario-verifier + scenario-fix` provider 组合 |
| 未来普通 Web 项目 | 接 `repo-execution + test-suite-verifier + generic-code-fix` |
| 未来基础设施项目 | 接 `service-execution + infra-verifier + infra-fix` |

## 八点五、无 profile / 无 provider 时的兼容与灰度迁移

已存在的老项目或尚未接入 profile 的 workspace **不应**被直接判为「不可用」：否则与「通用插件 + 渐进落地」相冲突。

建议用三态模型表达迁移阶段（全局或 workspace 级开关均可）：

| 模式 | 行为 |
|---|---|
| **`legacy`** | **保留旧行为**：未配置 profile/provider 时，回退到**框架既有**最小门禁（例如仅检查历史上的 `receipts`、`verification.json` 等），不强制新协议全量产物；与旧流水对齐，不阻断现有使用 |
| **`compat`** | **双写与告警**：同时写入新旧两类产物（或新协议子集 + 旧路径镜像），新门禁以**告警 / 软失败**为主（可配置），便于团队在 CI 上观测缺口而不一把掐死 |
| **`strict`** | **强约束**：强制执行新协议契约与第七节中的强门禁（含防空转）；不符合则阶段失败 |

**渐进迁移策略**（建议顺序）：

1. **先行为兼容**（`legacy`）：默认不破坏现有流水，能跑照旧跑。
2. **再协议对齐**（`compat`）：启用新产物与 `outputs/context`（及 `.harness/runs/<run_id>/`）契约，双写并只告警。
3. **后门禁收紧**（`strict`）：在证据链与 provider 覆盖就绪后，再切换为强门禁。

这样可以在不停机的前提下，把 `oms` / `sqlshift` 及未来项目迁到统一后半段协议。

## 九、建议的演进路线

为了避免一次性大改，演进顺序建议**由下至上、由契约到适配**，收敛为下列阶段（后一阶段依赖前一阶段已可用的最小闭环）：

| 阶段 | 目标摘要 |
|:---:|:---|
| **0：运行时基建** | 落地 **`run_id`**、**`.harness/runs/<run_id>/`** 目录模型；**resource registry / lock**；**TEARDOWN** 的即时尝试 + **`harnessctl gc` / `harnessctl teardown <run_id>`** 与启动扫描兜底；与无状态 CLI 约束对齐 |
| **1：协议与证据层** | **outputs / context** 契约；**EXECUTE / VERIFY / FIX / DONE** 统一 JSON 契约与 stage gate；第七节**框架职责边界**下的防空转 gate（存在性、格式、索引可追溯）；**Audit Verifier** 挂载点可选 |
| **2：兼容层 + 最薄 provider 骨架** | **`legacy` / `compat` / `strict`** 三态切换与灰度；**`compat` 与 default/dummy provider 同周期**，双写与告警再收紧 |
| **3：通用 provider** | 在骨架已挂靠的前提下，默认 provider 组合与 profile 选择链路跑通，不依赖特定业务仓库 |
| **4：OMS / SQLShift adapter** | 在通用协议上接入项目 adapter，验证多项目形态 |
| **5：共性能力沉淀** | 将远端日志采集、准确率专项、E2E case、部署生效等从单一项目中抽出为**可复用能力模块**（仍经 provider / adapter 接入，不污染核心框架） |

## 十、最终结论

如果前半段已经验证成立，那么后半段最合理的改造方向是：

- **不是把 `stage-harness` 做成 `oms/sqlshift` 的复制品**
- **而是把它做成后续阶段的通用编排框架**

具体来说：

1. `stage-harness` 继续掌握状态机、门禁、证据、回路、交付
2. 后续阶段通过统一契约接入项目 provider
3. `oms` 和 `sqlshift` 只是第一批接入的项目样本
4. 所有项目以后都按同一协议适配，而不是继续堆项目特判

一句话概括就是：

- **前半段统一流程**
- **后半段统一协议**
- **项目差异通过 adapter 消化**

这才既符合你现在的实测结论，也符合 `stage-harness` 作为通用插件的原始定位。
