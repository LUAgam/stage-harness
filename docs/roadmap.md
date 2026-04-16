# Stage-Harness Roadmap

> 本文档用于持续维护 `stage-harness` 的中长期演进方向，覆盖需求总览、优先级、核心设计点与分阶段落地建议。

## 使用方式

- 新方向先加到「方向清单」，再决定是否进入 `P0` / `P1` / `P2`
- 每个方向至少写清：目标、价值、风险、核心落点、当前落地情况、待补强点、验收信号
- 每个方向同时维护两类状态：
  - **实现状态**：`未实现` / `部分实现` / `基础已落地`
  - **推进状态**：`proposed` / `planned` / `in_progress` / `done`
- 若某方向改变了边界或优先级，优先改本文件，再改具体设计文档

## 状态图例

- `未实现`：基本还停留在文档或设想层，没有稳定产品入口
- `部分实现`：已有局部能力或首版机制，但还没形成完整闭环
- `基础已落地`：已有可用核心能力，可对外宣传，但仍有明显扩展空间

## 相关补充文档

- [CLARIFY 阶段中更像人的地方与可优化项](./clarify-human-like-analysis.md) — 聚焦需求分析阶段的人类相似性、当前短板与优先优化方向

## 总览

`stage-harness` 当前主线已经具备阶段流水线、门禁、产物校验与基础编排能力。下一阶段演进建议围绕三条主轴推进：

1. **更会沉淀**：把分析、决策、执行证据稳定落盘，减少重复劳动
2. **更会协同**：针对多仓和多视角分析，提升并行能力与收口效率
3. **更会学习**：在受控边界内沉淀项目级模式，并逐步演化为可复用能力

整体原则：

- 先可观测，再复用，再自学习
- 先 project-local，再 plugin-global
- 先候选产物，再正式提升
- 先能解释清楚，再追求自动化

## 优先级总表

| 优先级 | 方向 | 来源 | 实现状态 | 当前判断 | 核心原因 |
|------|------|------|------|------|------|
| P0 | setup / doctor / repair 安装与运行自检体系 | 推荐 | 基础已落地 | 强烈建议继续补强 | 已具备用户可用的 `harnessctl setup/doctor/repair` 入口与 recorded-only 降级诊断，但完整分发安装体系与更广覆盖的自动修复仍待补强 |
| P0 | 期间分析自动落地成文档 | 用户 | 基础已落地 | 强烈建议继续做深 | 已有大量阶段产物，但还缺更强的复用摘要层和主动消费机制 |
| P0 | 可回放执行证据链 | 推荐 | 基础已落地 | 强烈建议继续做深 | 已有 `execution-trace`、轻量 trace schema 收敛、`execution-summary.json` 与 `audit show` 摘要能力，但还缺 session archive、audit findings、replay 视图 |
| P0 | Focus Points 机制增强 | 推荐 | 部分实现 | 建议优先补强 | CLARIFY 闭环已有首版，但还未完整贯穿 TASK / TEST / VERIFY |
| P1 | 多仓代码分析并行 | 用户 | 部分实现 | 很值得做 | 多仓分析与路由基础已在，但执行并行与统一收口仍需继续完善 |
| P1 | 项目画像持续刷新 | 推荐 | 部分实现 | 很值得做 | 目前更像初始化检测，动态刷新与热点演化机制还没完成 |
| P1 | 复用资产库 | 推荐 | 基础已落地 | 很值得做 | `codemap` / `pitfalls` 已有基础，但还未形成更广义资产库 |
| P2 | 记忆 + 自学习到 skills | 用户 | 部分实现 | 值得做但应后置 | 已有 `skill-miner` 与 candidate-skill 基础，但还没有完整 shadow / replay 闭环 |
| P2 | ROI / 成功率度量 | 推荐 | 部分实现 | 值得做但应后置 | 已有 `scan-metrics` / `scan-roi` 基础，但指标面仍偏窄 |

## 当前实现概览

### 已有明显基础，可直接对外宣传

- 阶段化开发主链与 `FIX` 回路
- 结构化分析产物：`domain-frame`、`impact-scan`、`scenario-coverage`、`decision-bundle`、`verification`、`delivery-summary` 等
- 阶段门禁、自检与产物校验：`stage-gate check`、`clarify-selfcheck`、`verify-artifacts.sh`
- 执行证据链 MVP：`execution-trace.jsonl`、`execution-summary.json`、`audit show`，已能解释 CLARIFY 与 gate / guard / task 的关键执行事实
- 多仓基础能力：`workspace_mode`、`repo-catalog`、`cross-repo-impact-index`、`surface-routing`
- 复用资产基础：`memory/pitfalls.md`、`memory/codemaps/*`、`codemap-audit`

### 已有首版或局部实现，但还不宜宣传为完整能力

- `Focus Points` 闭环校验
- `skill-miner` 与 candidate-skills
- `profile detect`、扫描预算与工作区画像
- `metrics derive/show`、`scan-metrics.json`、`scan-roi.jsonl`

### 目前最明显的空白项

- 完整 manifest / marketplace 驱动的安装分发闭环

## 推荐推进顺序

### P0：先把基础层做扎实

1. setup / doctor / repair 安装与运行自检体系
2. 期间分析自动落地成文档
3. 可回放执行证据链
4. Focus Points 机制增强

### P1：再做多仓协同与长期复用

1. 多仓代码分析并行
2. 项目画像持续刷新
3. 复用资产库

### P2：最后做受控学习与效果度量

1. 记忆 + 自学习到 skills
2. ROI / 成功率度量

## 方向清单

## 1. setup / doctor / repair 安装与运行自检体系

- 来源：推荐
- 优先级：`P0`
- 实现状态：`基础已落地`
- 推进状态：`in_progress`

### 目标

为 `stage-harness` 提供一套面向安装、运行和故障恢复的标准入口，让用户不需要手工猜测插件目录、脚本依赖或环境状态，也能完成初始化、自检和修复。

### 为什么值得做

- 这是把 `stage-harness` 从“本地可用仓库”升级为“可分发产品”的关键基础设施
- 对后续支持 `/plugin install`、marketplace 分发和更低摩擦 onboarding 非常重要
- 运行失败时，用户最需要的是明确的诊断和可执行修复建议，而不是重新阅读长文档

### 当前落地情况

- 已提供统一入口：
  - `scripts/harnessctl setup`
  - `scripts/harnessctl doctor`
  - `scripts/harnessctl repair [--apply]`
- `setup` 已能完成插件根目录检查、脚本执行权限修复、运行时依赖检查，并输出推荐的 `HARNESSCTL` / `claude --plugin-dir` 下一步命令
- `doctor` 已能同时检查：
  - 插件根目录与 `plugin.json`
  - 脚本存在性与执行权限
  - `python3` / `bash` / `node`
  - 项目根的 `.harness/` 可初始化性
  - 已发现 install-state 的 recorded-only 健康状态
- `repair` 已默认 dry-run，只有显式 `--apply` 才执行；目前已支持低风险脚本权限修复，并复用 install-state repair 能力
- install lifecycle 在 manifest 缺失时已支持 `recorded-only` 降级，不再因为缺少 install manifests 直接中断整个 doctor/repair 流程
- `README` / `docs/usage.md` 已改为优先引导 `setup` / `doctor` / `repair`，原手工步骤作为 fallback 保留

### 仍需补强

- 完整 manifest / profile / component 驱动的安装规划仍未随本仓库一并落地，目前主要依赖 recorded-only 降级路径
- `repair` 目前仍以低风险本地修复为主，还不能覆盖更完整的宿主目录恢复与重装场景
- `doctor` / `repair` 的 JSON 契约和测试覆盖还可以继续补强，尤其是 recorded-only repair 的安全边界
- 还未形成面向 `/plugin install` 或 marketplace 分发的真正产品化安装器

### 核心内容

- `setup`：
  - 引导安装后的首次配置
  - 检查宿主环境
  - 引导 `.harness/` 初始化
  - 输出最短下一步命令
- `doctor`：
  - 检查插件是否正确安装
  - 检查脚本、解释器、权限、路径解析、工作区状态
  - 输出 `OK / WARN / FIX` 级别结果
- `repair`：
  - 对低风险问题自动修复
  - 对中高风险问题生成明确操作建议
  - 留下修复前后记录
- 明确与 `--plugin-dir`、`HARNESSCTL`、未来 `/plugin install` 的关系：
  - 尽量自动解析插件根目录
  - 尽量减少用户手工 export
  - 失败时给出精确 remediation

### 适合纳入检查与修复的项目

- 插件根目录是否可解析
- `plugin.json` / marketplace 清单是否存在且一致
- `scripts/*.sh` 与 `scripts/harnessctl.py` 是否可执行
- `python3`、`bash` 等运行时是否可用
- `HARNESSCTL` 是否可解析或可自动推导
- 当前项目是否可初始化 `.harness/`
- 多仓场景下 `repo-catalog` 是否缺失
- hooks / scripts 路径是否失效

### 主要风险

- `repair` 做得过于激进，误修用户环境
- 检查项过多，输出难以阅读
- 缺少风险分级，导致用户不敢执行修复

### 验收信号

- 新用户能通过 `harnessctl setup` / `doctor` 完成基本自检与启动前准备
- manifests 缺失时，doctor 不再异常退出，而是给出 recorded-only 诊断结果
- 至少一批低风险问题可由 `repair --apply` 自动恢复（如脚本权限）
- 安装和运行失败时的排障成本明显下降

## 2. 期间分析自动落地成文档

- 来源：用户
- 优先级：`P0`
- 实现状态：`基础已落地`
- 推进状态：`planned`

### 目标

把 CLARIFY、PLAN、VERIFY 等阶段中的关键分析过程稳定写入结构化产物或短结论文档，方便后续 Epic 直接复用，而不是每次重新分析。

### 为什么值得做

- 这是后续记忆、自学习、并行分析的输入基础
- 可以减少“看过但没落地、下一次又重做”的重复成本
- 有利于人类复盘和多 agent 共享结论

### 当前落地情况

- CLARIFY / PLAN / VERIFY / DONE 已经会落大量结构化产物
- 已有 `domain-frame.json`、`requirements-draft.md`、`impact-scan.md`、`scenario-coverage.json`
- 已有 `surface-routing.json`、`decision-bundle.json`、`decision-packet.json`
- 已有 `verification.json`、`delivery-summary.md`、`release-notes.md`

### 仍需补强

- 增加更统一的复用摘要层，例如 `analysis-summary.md`
- 让后续 Epic 主动消费历史分析，而不是只把产物留在目录里
- 把“文档存在”进一步推进为“文档可检索、可引用、可比较”

### 核心内容

- 区分三类落点：
  - **结构化 JSON**：适合程序消费和 gate 校验
  - **短 Markdown 结论**：适合人读和快速复用
  - **长期记忆型文档**：适合沉淀跨 Epic 经验
- 优先沉淀高价值信息：
  - 模块入口
  - 影响范围
  - 关键约束
  - 用户关注点闭环
  - 多仓依赖关系
  - 常见改动路径
- 控制文档膨胀：
  - 不落全量思维流
  - 只落“可复用结论”和“决策依据”

### 适合新增或强化的产物

- `.harness/features/<epic-id>/analysis-summary.md`
- `.harness/features/<epic-id>/surface-routing.json`
- `.harness/features/<epic-id>/cross-repo-impact-index.json`
- `.harness/memory/codemaps/*`
- `.harness/memory/pitfalls.md`

### 主要风险

- 文档过多但复用率低
- 结论与实际代码表面脱节
- 写成流水账，后续无法检索

### 验收信号

- 新 Epic 启动时能直接消费历史分析结果
- 同类需求的重复扫描次数下降
- 文档能被 `PLAN` / `VERIFY` 阶段明确引用

## 3. 记忆 + 自学习到 skills

- 来源：用户
- 优先级：`P2`
- 实现状态：`部分实现`
- 推进状态：`proposed`

### 目标

把执行过程中的稳定模式沉淀为项目级记忆，并在足够证据下逐步演化为 `candidate-skill`，最后再决定是否升级为正式 skill。

### 为什么值得做

- 长期可以形成 `stage-harness` 的复用壁垒
- 能把“做过一次”升级为“下次更快做对”
- 适合沉淀项目专有模式、通用套路和反模式

### 当前落地情况

- 已有 `skill-miner` agent
- 已有 `.harness/memory/candidate-skills/`
- 已有 `skill list` / `show` / `promote` / `archive`
- DONE 阶段已经能挖掘候选技能，`memory/pitfalls.md` 也已存在

### 仍需补强

- 缺少统一的 `observation -> pattern -> candidate-skill -> promoted-skill` 分层
- 缺少真正的 shadow validation / replay backtest
- 还没有较强的 project-local 与 plugin-global 治理边界

### 核心内容

- 学习分层，不直接从一次成功案例生成正式 skill：
  - `observation`
  - `project-pattern`
  - `candidate-skill`
  - `promoted-skill`
- 明确输入信号：
  - stage gate 结果
  - verification 结果
  - fix 回流次数
  - 人工是否接受
  - 是否跨 Epic 复现
- 先做 project-local，再考虑 plugin-global
- 必须引入 shadow validation，而不是直接生效

### 适合新增的落点

- `.harness/memory/observations.jsonl`
- `.harness/memory/project-patterns.json`
- `.harness/memory/candidate-skills/`

### 主要风险

- 学到一次性 workaround
- 项目特例污染全局 skill
- 自动演化不可解释

### 验收信号

- 能明确区分候选模式和正式能力
- 被提升的 skill 在多个 Epic 中产生稳定正向效果
- 误学率和回滚率可追踪

## 4. 多仓代码分析、实现等步骤开并行

- 来源：用户
- 优先级：`P1`
- 实现状态：`部分实现`
- 推进状态：`planned`

### 目标

在多仓或大型工作区里，把适合 fan-out 的分析、路由、计划拆分步骤并行化，提高吞吐，同时保持统一收口。

### 为什么值得做

- 多仓场景下，串行扫描成本高
- 分析和路由天然适合并行
- 能明显降低 CLARIFY / PLAN 的等待时间

### 当前落地情况

- 已支持 `workspace_mode: multi-repo`
- 已有 `.harness/repo-catalog.yaml`
- 已有 `cross-repo-impact-index.json`
- 已有 `surface-routing.json` 和扫描预算
- PLAN 阶段已有多 scout 并行研究设计

### 仍需补强

- fan-out / fan-in 收口流程还需更明确
- EXECUTE 的多仓并行边界和风险控制还不够成熟
- `cross-repo verification`、`repo-level task lease` 仍未形成稳定能力

### 核心内容

- 优先并行的阶段：
  - CLARIFY：impact scan、contract scan、entrypoint scan、scenario fan-out
  - PLAN：repo surface research、dependency map、coverage assembly
- EXECUTE 并行必须更严格：
  - 以 repo 为边界切分任务
  - 明确 contract owner
  - 最终统一 integration gate
- 采用统一 fan-in 收口：
  - 并行结果不直接推进阶段
  - 必须先汇总为单一结论，再过 gate

### 适合新增的控制点

- `max_repos_deep_scan`
- `max_subagents_wave`
- `cross-repo verification`
- `repo-level task lease`

### 主要风险

- 并行结果冲突
- 跨仓契约不一致
- 计划收口失败导致返工

### 验收信号

- 多仓 Epic 的 CLARIFY / PLAN 耗时下降
- fan-out 结果能被统一汇总而非碎片化
- 并行不会显著增加 FIX 回流率

## 5. 项目画像持续刷新

- 来源：推荐
- 优先级：`P1`
- 实现状态：`部分实现`
- 推进状态：`proposed`

### 目标

让 `project-profile` 不再只是 `start` 时的一次性检测结果，而是随着 Epic 执行逐步刷新热点模块、风险判断和工作区画像。

### 为什么值得做

- 初始画像通常只够粗定位
- 真正的高频改动面往往要经过多个 Epic 才能识别
- 能提高多仓路由和分析边界的准确度

### 当前落地情况

- 已有 `profile detect`
- 已有 `workspace_mode` 检测
- 已有 primary surfaces、repo alias discovery、scan defaults
- 已能根据工作区模式调整扫描边界

### 仍需补强

- 现在更像“初始化检测”，不是“持续刷新”
- 还缺基于 Epic 历史的热点演化和证据驱动更新
- 还缺 stale 字段治理与动态画像版本化

### 核心内容

- 拆分静态画像和动态画像：
  - 静态：项目类型、技术栈、workspace_mode
  - 动态：热点模块、常见入口、风险提示、典型路径
- 动态画像必须带证据：
  - 来源 Epic
  - 命中次数
  - 最后更新时间
- 只刷新稳定字段，不写流水账

### 主要风险

- 把短期热点误当长期画像
- 动态画像噪音过多

### 验收信号

- 后续 Epic 的 surface routing 更准
- 大量无效扫描被减少
- 热点画像与真实改动历史大致一致

## 6. 可回放执行证据链

- 来源：推荐
- 优先级：`P0`
- 实现状态：`基础已落地`
- 推进状态：`in_progress`

### 目标

把每次运行的重要决策点、阶段门禁、状态转移和异常回流写成可回放的结构化证据，支持审计、复盘、学习和自动纠偏。

### 为什么值得做

- 没有证据链，就无法回答“为什么走到这一步”
- 是自动纠偏、candidate skill、ROI 统计的共同输入
- 对排查 gate 误判、阶段漂移特别关键

### 当前落地情况

- 已有 `execution-trace.jsonl`
- `harnessctl` 已在多处写入 trace event
- 已对 trace event 做轻量 envelope 收敛：缺省时可稳定补齐 `event_id`、`ts`、默认 `status`，且兼容 legacy / raw 事件
- 已有 `execution-summary.json`
- 已有 `harnessctl audit show`，可直接汇总并展示 CLARIFY run、gate / guard / task 的关键执行事实
- 已有 `gate-skips.json`
- 已有 `patch diagnose` 消费 trace 的能力
- 已有部分 session log 目录准备和 JIT patch 诊断链路
- 已有针对 legacy trace 兼容、gate / guard / task 摘要的测试覆盖，MVP 链路已可稳定回归

### 仍需补强

- 还缺完整的 session archive
- 还缺 `audit-findings.json` / `audit-summary.md`
- 还缺更高层的 replay / audit 子命令与更完整的跨阶段审计视图
- 还缺与 session 级 transcript / archive 的稳定关联关系
- 还缺更显式的 trace schema 注册表与长期兼容治理

### 核心内容

- 只记录“决策事实”，不记录全量自由思维流
- 已落地的 MVP 重点是：`execution-trace.jsonl` -> `execution-summary.json` -> `audit show`
- 重点事件包括：
  - stage transition
  - gate pass / fail
  - must_confirm 触发
  - task blocked / resumed
  - verification verdict
  - fix 来源问题
- 原始 transcript 与结构化 trace 分层保存

### 适合新增的落点

- `.harness/logs/epics/<epic-id>/execution-trace.jsonl`
- `.harness/logs/epics/<epic-id>/execution-summary.json`
- `.harness/logs/sessions/<session-id>.*`
- `.harness/logs/epics/<epic-id>/audit-findings.json`

### 主要风险

- 事件过多导致不可用
- schema 不稳定导致后续难检索

### 验收信号

- MVP 层面已能通过 `audit show` 解释 gate / guard / task 的关键路径
- 能回放单个 Epic 的关键路径
- 能解释 gate 为何通过或阻断
- 后续分析不必依赖人工翻全量日志

## 7. Focus Points 机制增强

- 来源：推荐
- 优先级：`P0`
- 实现状态：`部分实现`
- 推进状态：`planned`

### 目标

把用户明确点名的关注点贯穿整个阶段链路，而不是只在 CLARIFY 提一次。

### 为什么值得做

- 能显著提高用户对系统“抓重点能力”的感知
- 让关键关注点真正映射到任务、测试和验证
- 避免“分析很完整，但没回答用户最在意的事”

### 当前落地情况

- 已支持 `clarification-notes.md` 的 Focus Points 小节
- 已支持 `.harness/features/<epic-id>/focus-points.json`
- `stage-gate check CLARIFY`、`clarify-selfcheck`、`verify-artifacts.sh` 已会校验映射闭环

### 仍需补强

- 重点仍集中在 CLARIFY，尚未完整贯穿 TASK / TEST / VERIFY
- `verification.json` 里还缺更显式的 focus coverage 结构
- 还没形成 `covered / partial / missed` 的稳定验收口径

### 核心内容

- 为每个 focus point 建立闭环映射：
  - `REQ`
  - `SCN`
  - `TASK`
  - `TEST`
  - `VERIFY`
- 不仅要求在 CLARIFY 写出来，还要在 VERIFY 里标记：
  - `covered`
  - `partial`
  - `missed`
- 支持结构化文件，而不是只靠 Markdown 小节

### 适合新增的落点

- `.harness/features/<epic-id>/focus-points.json`
- `verification.json` 中的 focus coverage 字段

### 主要风险

- 关注点太多时绑架主流程
- 只记录不闭环，形式大于实质

### 验收信号

- 用户点名关注的问题在 VERIFY 阶段有明确结论
- 关注点能追踪到对应任务与测试
- 漏项可以被自动发现

## 8. 复用资产库

- 来源：推荐
- 优先级：`P1`
- 实现状态：`基础已落地`
- 推进状态：`proposed`

### 目标

把高价值产物从单次 Epic 目录中抽离出来，形成长期可复用的资产库，用于加速后续需求。

### 为什么值得做

- 单个 Epic 目录天然是“局部沉淀”
- 真正能持续提效的是可搜索、可复用、可校验的共享资产

### 当前落地情况

- 已有 `memory/pitfalls.md`
- 已有 `memory/codemaps/*`
- 已有 `codemap-init`、`codemap-probe`、`codemap-audit`
- 已支持 stale / invalid CodeMap 的可信度降级

### 仍需补强

- 还缺更广义的 playbook、验证模板、常见改动路径资产
- 资产还缺统一元数据治理和主动引用机制
- “单次 Epic 产物”与“长期资产”之间的提升路径还可继续明确

### 核心内容

- 优先沉淀三类资产：
  - codemap / surface map
  - 常见改动 playbook
  - 测试与验证模板
- 所有资产都要带元数据：
  - 来源 Epic
  - 更新时间
  - 可信度
  - 适用范围
  - stale 检查方式

### 主要风险

- 资产过期
- 没有可信度标记导致误用

### 验收信号

- 新 Epic 能主动引用已有资产
- 高频模块不再重复手工建图
- stale 资产能被及时识别

## 9. ROI / 成功率度量

- 来源：推荐
- 优先级：`P2`
- 实现状态：`部分实现`
- 推进状态：`proposed`

### 目标

量化哪些机制真的提升了完成率、复用率和质量，避免系统无限膨胀却无法验证收益。

### 为什么值得做

- 没有度量，就很难知道哪些机制值得继续投入
- 可以帮助判断并行、自学习、文档沉淀是否真正有效

### 当前落地情况

- 已有 `metrics check`
- 已有 `metrics derive`
- 已有 `metrics show`
- 已有 `.harness/features/<epic-id>/scan-metrics.json`
- 已有 `.harness/metrics/scan-roi.jsonl`

### 仍需补强

- 当前指标仍偏向扫描 / 路由 / codemap ROI
- 还缺更广义的 Epic 完成率、FIX 回流率、focus point 命中率、candidate-skill 成功率
- 还缺更明确的 dashboard / 周期性复盘视图

### 核心内容

- 先收最少必要指标：
  - Epic 完成率
  - FIX 回流率
  - artifact 复用率
  - 多仓并行节省的轮次或时间
- 后续再扩：
  - focus point 命中率
  - candidate skill promotion 成功率
  - gate 误伤率

### 主要风险

- 指标采集成本过高
- 为了指标而指标

### 验收信号

- 能回答“哪个机制真有用”
- 指标能指导 roadmap 调整
- 不会显著增加维护负担

## 建议的实施里程碑

### Milestone 1：沉淀层打底

- setup / doctor / repair 自检与修复入口
- 分析自动落地成文档
- 执行证据链
- Focus Points 闭环

### Milestone 2：多仓协同与复用

- 多仓分析并行
- 项目画像持续刷新
- 复用资产库

### Milestone 3：受控学习与度量

- 候选记忆与 candidate-skill
- shadow validation
- ROI / 成功率度量

## 暂不建议优先投入的事情

- 直接自动生成正式 skill 并立即生效
- 在没有稳定证据链前做复杂自动纠偏
- 在没有统一 fan-in 前做大规模多仓并行实现
- 在没有复用层前做过细的统计指标

## 维护模板

后续可按以下模板继续追加新方向：

```md
## X. 新方向名称

- 来源：用户 / 推荐 / 运行反馈
- 优先级：P0 / P1 / P2
- 状态：proposed / planned / in_progress / done

### 目标

### 为什么值得做

### 核心内容

### 主要风险

### 验收信号
```
