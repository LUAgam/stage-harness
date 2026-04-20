# stage-harness 现有实现对齐 Claude Code + LLM 运行模型的调整思路

本文不重复论证 `stage-harness` 的目标形态，而是回答一个更现实的问题：

- 基于当前已经落地的 `stage-harness` 实现
- 对照 `stage-harness-claude-code-llm-operating-model.md`
- 下一步到底还需要怎么调整
- 调整的主线应该是什么

## 一句话判断

当前实现**不需要推倒重来**。

真正合理的方向不是重写前半段，而是：

- 保留已经成熟的 `CLARIFY / SPEC / PLAN` 骨架
- 把后半段从“已有审计与门禁雏形”升级为“正式运行时协议 + 项目知识层 + provider/adapters 能力层”

一句话概括：

- **前半段继续稳**
- **后半段正式化**

## 二次复审后的实施校正

二次复审将若干原先易被误读为「架构级 P0 阻断」的点，收敛为**实施难点与落地顺序**问题，便于按迭代推进：

| 议题 | 复审后的定位 |
|---|---|
| Claude Code 宿主下的控制权 / 硬控制 | **高难度实施约束**：必须在具体落地点（状态机、卡点、工具边界、审计）上做成可阻断机制；**不是**「因此架构不可行」的证明 |
| `compat` 双写与 provider 顺序 | **非架构矛盾**：需要**实施顺序调优**——**最薄 provider 骨架应与 `compat` 双写同周期落地**，避免「先双写很久、后补 provider」造成返工 |
| AI 自动生成 adapter | **不从首阶段主链路强依赖**：首批以**手写官方 adapter**验证协议与运行时；自动生成作为 **P2 / 长期演进**能力逐步引入 |
| VERIFY 的「裁判与运动员」隔离 | **当前最高优先级的实施红线（高风险项）**：必须在工程上落实独立证据链或独立视角，**不因其他工作延后而弱化** |

## 一、当前实现已经具备的基础

结合现有 `harnessctl.py`、`docs/architecture.md`、`docs/usage.md`，当前实现已经具备下面这些强项：

| 能力 | 当前状态 | 判断 |
|---|---|---|
| 状态机 | 已有 `IDEA -> CLARIFY -> SPEC -> PLAN -> EXECUTE -> VERIFY -> FIX -> DONE` | 已成型 |
| 前半段产物 | `domain-frame`、`generated-scenarios`、`surface-routing`、`decision-bundle` 等较完整 | 明显强项 |
| 多仓画像 | 已有 `workspace_mode`、`repo-catalog`、`cross-repo-impact-index`、扫描预算 | 已较成熟 |
| 决策与中断 | 已有 `must_confirm`、`decision-packet`、`interrupt_budget`、`guard check` | 已有雏形 |
| 审计 | 已有 `execution-trace.jsonl`、`execution-summary.json`、`audit show` | 已有运行证据基础 |
| 自治模式 | 已有 `harness-auto`、高风险暂停、失败停止 | 已有自动推进骨架 |
| 安全钩子 | 已有 `pre-tool-use.sh` 拦截高风险 Bash 操作 | 已有第一层防线 |
| 安装与自检 | 已有 `setup / doctor / repair` | 工程化程度不错 |

所以当前最重要的判断是：

- `stage-harness` 已经不是“只有文档的概念方案”
- 它已经有一个很强的**前半段内核 + 审计/门禁基础骨架**

## 二、和 operating model 的主要差距在哪里

如果用 `stage-harness-claude-code-llm-operating-model.md` 的目标形态来对照，差距并不在所有地方，而是集中在后半段。

### 1. `run_id` 还没有成为正式运行时主键

当前代码里已经出现了 `run_id`，但更多还是 trace / audit 语义，而不是完整运行时目录模型。

现状更接近：

- epic 级目录：`.harness/features/<epic-id>/`
- epic 级日志：`.harness/logs/epics/<epic-id>/`
- `run_id` 用来辅助审计、摘要、暂停原因推导

而目标模型要求的是：

- `run_id` 成为后半段协议的基础隔离单位
- 形成 `.harness/runs/<run_id>/`
- 所有动态上下文、资源注册、outputs、evidence、cleanup 信息都与 run 对齐

### 2. 后半段 gate 还是轻的，协议还没正式升格

当前 gate 的特点是：

- `CLARIFY / SPEC / PLAN` 门禁很强
- `VERIFY` 已有统一主件 `verification.json`
- `DONE` 已有交付产物
- `EXECUTE` 仍然偏弱，主要依赖 receipt / trace / audit

这说明当前实现正处在一个中间态：

- 它已经有后半段的“证据意识”
- 但还没有把这些证据正式提升为统一协议

也就是说：

- `execution-summary.json` 已经开始出现
- 但还没成为 `EXECUTE` 的正式 gate 主件
- `fix-summary.json`、`delivery-manifest.json` 这类协议主件还没有真正进入主流程

### 3. `project-profile` 仍然偏技术画像，不是完整项目知识层

当前 `project-profile.yaml` 主要承载：

- 项目类型
- 风险等级
- 技术栈
- `workspace_mode`
- 扫描预算
- `primary_surfaces`

它更像：

- **扫描与路由画像**

而不是：

- **环境与项目运行知识层**

距离目标模型里要支持的这些内容还差一层：

- 环境部署信息
- 数据源 contract
- secret reference
- bootstrap/init 知识
- provider 绑定信息

### 4. `human-on-demand` 只做了一部分，还没有泛化成正式 handoff 协议

当前已经有：

- `must_confirm`
- `interrupt_budget`
- `latest_pause_reason`
- `handoff.md`
- 高风险 epic 进入 EXECUTE 前暂停

这些很重要，但目前更多还是：

- 阶段级暂停机制

还不是一个更完整的人机接管模型，例如：

- `pause_for_decision`
- `pause_for_knowledge`
- `pause_for_auth`
- `pause_for_recovery`
- `resume_with_context`

所以当前的暂停/恢复还偏“能停住”，还没有真正进化到“能优雅恢复”。

## 三、主线思路：不要重写前半段，要把后半段正式化

这是最重要的调整原则。

### 不建议的方向

| 方向 | 为什么不建议 |
|---|---|
| 重写 `CLARIFY / SPEC / PLAN` | 这部分已经是当前实现的最大优势 |
| 一上来构建很重的 provider 市场 | 运行时和协议层还没先立起来，容易空转 |
| 继续把所有知识都塞进 `project-profile.yaml` | 会让一个文件承担过多语义，难维护 |
| 先做大量项目特判 | 会偏离通用插件定位 |

### 建议坚持的方向

| 方向 | 说明 |
|---|---|
| 保持前半段骨架稳定 | 不动最成熟的部分 |
| 优先补后半段运行时模型 | 先立 `epic + run` 双层结构 |
| 协议先行 | 先把后半段主件定义清楚，并与最薄 provider 骨架**同周期**挂靠（避免「主件已双写、编排层仍空缺」） |
| 项目知识独立分层 | 不再只靠 `project-profile` 承担所有项目事实 |
| 人机 handoff 正式化 | 从“中断”升级到“可恢复的暂停协议” |

## 四、建议的调整顺序

如果按“尽量少返工、尽量承接已有实现”的原则推进，建议顺序如下。

### 第 1 步：先建立 `epic + run` 双层模型

这是后面所有能力的基础。

#### 当前

- `epic` 是主要组织单位
- 产物、日志、状态基本都围绕 epic

#### 建议调整

保留 epic 级目录不变，同时新增 run 级目录：

| 层 | 作用 |
|---|---|
| `epic` | 长周期目标、状态机、任务、规格、决策、历史归档 |
| `run` | 某一次执行/验证/修复尝试的动态上下文与运行证据 |

建议新增：

- `.harness/runs/<run_id>/context.json`
- `.harness/runs/<run_id>/context.env`
- `.harness/runs/<run_id>/stage-outputs.json`
- `.harness/runs/<run_id>/resource-registry.json`
- `.harness/runs/<run_id>/evidence/`

这一层完成后，`run_id` 才会从“审计字段”变成“运行时主键”。

### 第 2 步：把当前 trace / audit 升级成正式运行时 ledger

当前的 `execution-trace.jsonl` 和 `execution-summary.json` 已经很有价值，但还偏“派生审计产物”。

下一步建议是：

- 继续保留 trace 机制
- 但把 trace event 明确成后半段运行时 ledger 的一部分

建议统一 event envelope：

| 字段 | 作用 |
|---|---|
| `run_id` | 所属运行实例 |
| `stage` | 所属阶段 |
| `status` | `ok / warn / blocked / error` |
| `summary` | 一行摘要 |
| `artifacts` | 关联产物 |
| `next_actions` | 建议后续动作 |
| `provider` | 对应 provider 名称 |
| `evidence_refs` | 可复核证据引用 |

目标不是替代现有 audit，而是把 audit 和 runtime 协议接起来。

### 第 3 步：`compat` 双写与「最薄 provider 骨架」**同周期**推进

这是当前最值得做的主线，不建议一次切断旧行为；也**不建议**把「最薄 provider 接口/骨架」推迟到所有 `compat` 工作完成之后——二者应**同一迭代周期内**对齐，避免双写产物无处挂靠、后续再大面积改 gate。

#### `legacy`

保留现有行为：

- `EXECUTE` 主要看 receipt / trace
- `VERIFY` 看 `verification.json`
- `DONE` 看 `delivery-summary.md` / `release-notes.md`

#### `compat` + 最薄 provider（同周期）

- **`compat`**：开始双写新协议主件：

| 阶段 | 新增/强化产物 |
|---|---|
| `EXECUTE` | `execution-summary.json`、`execution-items.json` |
| `VERIFY` | `verification.json` 增加 `overall_verdict`、`evidence_refs`、可选 `verification-items.json` |
| `FIX` | `fix-summary.json` |
| `DONE` | `delivery-manifest.json` |

- **最薄 provider 骨架（并行落地）**：在同一阶段只定义 4 类最薄接口（`execution` / `verification` / `fix` / `delivery`），并先用 **default / dummy provider** 承接「把新协议主件写出来、路径与 gate 对齐」的职责；具体项目逻辑仍可通过后续 adapter 替换，不在此步一次做全。

此阶段建议：

- 新协议落盘
- 新 gate 先告警不阻断
- 继续兼容旧产物
- provider 侧先满足最小 contract（输入上下文、输出对应阶段统一主件、可注册 evidence），**不**等待「AI 自动生成 adapter」再开跑

#### `strict`

等 provider、双写路径与证据链稳定后，再正式切换强 gate。

这个顺序最适合当前代码，因为它已经有一套旧产物体系，不应该粗暴替换；同时避免「compat 先行、provider 后置」带来的协议与编排脱节。

### 第 4 步：把项目知识层从 `project-profile` 中拆出来

这是让通用插件真正“对具体项目更好用”的关键。

建议不要只继续扩 `project-profile.yaml`，而是明确拆成几层：

| 文件 | 作用 |
|---|---|
| `.harness/project-profile.yaml` | 项目画像、archetype、默认能力选择 |
| `.harness/environment-manifest.yaml` | 环境部署方式、服务入口、依赖服务、初始化方式 |
| `.harness/data-source-contract.yaml` | 数据源类型、用途、可 mock/seed 策略、读写边界 |
| `.harness/secret-references.yaml` | secret 引用 ID，不落明文 |
| `.harness/bootstrap-notes.md` | 一次性知识注入结果 |

也就是说：

- `project-profile` 回到“画像和路由”
- 环境/数据源/secret/bootstrap 进入“项目知识层”

这一步尤其适合后续接 `oms`、`sqlshift` 这类项目。

### 第 5 步：把现有的 `must_confirm` 扩成正式 handoff 模型

当前的 `must_confirm + interrupt_budget` 很值得保留，但建议升级为更完整的暂停原因模型：

| 类型 | 场景 |
|---|---|
| `pause_for_decision` | 发布、scope、风险动作拍板 |
| `pause_for_knowledge` | 缺环境信息、缺数据源知识、缺入口约定 |
| `pause_for_auth` | 需要凭证、MFA、外部权限 |
| `pause_for_recovery` | 连续失败、错误模式重复、疑似死循环 |

建议保留现有：

- `handoff.md`
- `latest_pause_reason`
- `guard check`

并在此基础上新增：

- `resume <run_id>`
- `pause <run_id> --reason ...`
- 结构化 `decision package`
- 结构化 `knowledge request package`

也就是把“中断”升级成“可恢复的 handoff 协议”。

### 第 6 步：在骨架稳定后充实 provider 实现与官方 adapter（非「从零才有接口」）

最薄接口与 default/dummy 已在**第 3 步**与 `compat` 同周期落地；本步关注的是**把真实项目能力接进同一套 contract**，而不是事后补「第一层接口定义」。

建议优先用**手写官方 adapter** 验证协议与运行时（覆盖 `oms/sqlshift` 等样本），把边界跑通后再考虑自动化生成与模板沉淀。

每类 provider 仍只要求满足最小 contract：

- 输入：`project-profile + project knowledge + run context`
- 输出：对应阶段统一协议主件
- 额外要求：可注册资源、可写 evidence、可 cleanup

不要一开始就把 `oms/sqlshift` 的所有逻辑都抽象成大而全 provider；**AI 自动生成 adapter** 放在长期演进（见下文优先级），不作为首阶段主链路硬依赖。

## 五、对现有实现最应该保留的部分

为了避免调整时把真正值钱的东西打散，建议明确哪些内容应尽量保持不动。

| 应保留部分 | 原因 |
|---|---|
| `CLARIFY / SPEC / PLAN` 主流程 | 当前成熟度最高 |
| `decision-bundle / must_confirm / interrupt_budget` | 已具备很强的人机协作基础 |
| `guard check` | 是后续硬控制的入口 |
| `execution-trace.jsonl` / `execution-summary.json` | 是后续 runtime ledger 的良好基础 |
| 多仓 `workspace_mode` / `cross-repo-impact-index` | 是 profile-driven 的重要资产 |
| `setup / doctor / repair` | 说明项目已经有工程化自检意识 |

## 六、对现有实现最值得补齐的部分

| 最值得补齐 | 当前问题 | 调整目标 |
|---|---|---|
| `run` 级模型 | 仍主要按 epic 组织动态状态 | 建立运行时主键与隔离 |
| 后半段协议主件 | `EXECUTE/FIX/DONE` 尚未正式协议化 | 统一后半段主件 |
| 项目知识层 | `project-profile` 承担过多、信息不足 | 环境/数据源/secret 独立分层 |
| handoff / resume | 已有暂停，但恢复协议不完整 | 形成正式人机恢复机制 |
| provider 接口 | 文档里已有方向，代码里未成层 | 后半段能力可插拔化 |
| cleanup / teardown | 文档目标更完整，代码里还偏散 | 形成 run 级资源回收闭环 |

## 七、建议的实施优先级

建议按下面优先级推进：

### P0：必须先做

1. `epic + run` 双层模型
2. 后半段协议化的 `compat` 双写框架，与 **最薄 provider 接口 + default/dummy provider 骨架** **同周期**落地（见第四节第 3 步）
3. `pause / resume` 的最小运行时协议
4. **VERIFY 独立证据链 / 避免同上下文自证**（实施红线，与上列并行约束工程落地，不因「功能未齐」而推迟设计）

### P1：紧接着做

1. 项目知识层拆分
2. resource registry + cleanup / teardown（与已落地的 provider hook 对齐）
3. 手写官方 adapter 扩样，充实各 provider 的真实实现

### P2：稳定后再做

1. AI 自动生成 adapter skeleton（长期演进，非首阶段主链路）
2. capability pack / provider 沉淀机制
3. 更完整的 `strict` gate 收紧

## 八、最终结论

基于当前已有实现，对齐 `stage-harness-claude-code-llm-operating-model.md` 的最合理思路不是：

- 重写整套插件
- 重构前半段
- 先做庞大的 provider 市场

而是：

1. 保留当前已经成熟的前半段与控制骨架
2. 把 `run_id` 从审计字段升级成正式运行时主键
3. 把后半段从“有审计、有门禁”升级成“有正式协议、有运行时、有项目知识层”
4. 把 `must_confirm` 进化为正式的 handoff / resume 机制
5. 在 `compat` 阶段同步落地最薄 provider 骨架与 default/dummy，再用手写官方 adapter 充实，并通过 `legacy / compat / strict` 渐进迁移（自动生成 adapter 属长期演进）

一句话概括：

- **当前最该调的不是前半段思考能力**
- **而是后半段的运行时、协议层、项目知识层和恢复机制**

这条路线既承接了现有实现，也更符合 `stage-harness` 在 Claude Code 上作为通用研发编排器的目标定位。
