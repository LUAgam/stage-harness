# OMS vs SQLShift 阶段3对比

本文继续对比两套流程在**阶段3**的实现差异：

- `ai-programmer-oms`
- `ai-programmer-sqlshift`

这里的“阶段3”采用功能对齐方式定义，也就是看**初版需求文档出来之后，系统如何继续补强影响面、提取待确认问题，并收敛到最终需求文档**。

## 一句话结论

如果按当前代码实现来看，阶段3的关系是：

- `ai-programmer-oms` 的阶段3是：`discussion + summary_effect + finalize_prd`
- `ai-programmer-sqlshift` 的阶段3是：**相关能力存在，但主流程未自动串联**

也就是说：

- `oms` 的阶段3是真正存在的“**影响面补强 -> 产品确认 -> 最终定稿**”阶段。
- `sqlshift` 的阶段3在能力层面并不缺，但在主流程层面更像“**保留了模块，实现了接口，但没有自动接成完整链路**”。

## 一、为什么这样对齐

前两份文档已经说明：

- `oms` 的阶段1、阶段2是正常分阶段推进的
- `sqlshift` 在阶段1就把 `draft_prd` 提前执行了
- 阶段2在主流程里出现了缺位

继续往下看，就会发现两边的“后半段需求收敛”也不一样。

### `ai-programmer-oms`

在初版 PRD 之后，它还会继续经历：

1. `discussion`
2. `summary_effect`
3. `finalize_prd`

这是一个完整的后处理链条，目标是：

- 补强影响面分析
- 提炼真正需要产品拍板的问题
- 合并产品回复生成最终 PRD

### `ai-programmer-sqlshift`

在 `sqlshift` 中：

- `discussion.py` 存在
- `summary_effect.py` 存在
- `finalize_prd.py` 存在
- `merge-final` 入口也存在

但问题在于：

- `full-run` 里把 `discussion` 和 `summary_effect` 注释掉了
- `merge-final` 又要求 `summary_effect/questions.*` 这些前置产物已存在

所以它不是“没有阶段3能力”，而是：

- **阶段3能力存在，但默认主流程不闭合**

## 二、阶段3映射

### `ai-programmer-oms`

阶段3：

1. `discussion`
2. `summary_effect`
3. `finalize_prd`

阶段3入口：

- 已有 `prd/requirements.md`

阶段3出口：

- `final_prd.md`
- `merge_report.md`
- `reply_coverage_report.md`

### `ai-programmer-sqlshift`

如果只看当前主入口：

- 没有一个自动连通的阶段3

更准确的现状是：

1. `discussion` 能力存在，但在 `full-run` 中被注释掉
2. `summary_effect` 能力存在，但在 `full-run` 中被注释掉
3. `merge-final` 能力存在，但依赖 `summary_effect` 先执行

所以阶段3在 `sqlshift` 中更适合描述为：

- **能力存在，但主链未接通**

## 三、`oms` 阶段3实现流程

### 1. `discussion`

这一阶段是可选的，由配置控制。

作用是：

- 继续围绕“影响面分析”开一个议会式讨论
- 角色固定为：议长、议员、评审员
- 每次只讨论一个议题
- 最多 3 轮

这一层不是直接生成最终 PRD，而是：

- 进一步补强初版 PRD 的影响面分析

它的本质是：

- **在 PRD 定稿前，再做一轮高风险影响面的深化**

### 2. `summary_effect`

这一阶段会读取：

- 当前 PRD
- 知识库
- 代码目录

然后提炼出：

- 哪些问题研发不能自己拍板
- 哪些问题需要产品确认

输出：

- `questions.md`
- `questions.json`
- `manifest.json`

也就是说，它的目标不是改 PRD，而是：

- **把“仍需产品决策的问题”单独拉出来**

### 3. `finalize_prd`

最后根据产品回复生成最终 PRD。

它会：

1. 校验产品回复是否覆盖全部待确认问题
2. 若不完整，则补待确认项并阻断
3. 若完整，则生成：
   - `final_prd.md`
   - `merge_report.md`
   - `reply_coverage_report.md`
4. 再做最终 PRD 完整性补齐

所以 `oms` 的阶段3本质上是：

- **从初版 PRD 走到最终 PRD 的定稿阶段**

## 四、`sqlshift` 阶段3的真实实现状态

### 1. `discussion` 能力存在，但未接入主流程

`sqlshift` 中的 `discussion.py` 不是空壳，能力上和 `oms` 很接近：

- 都是议会式讨论
- 都强调“影响面分析”
- 都是议长/议员/评审员三角色

并且 `sqlshift` 版 discussion 还有更强的项目约束：

- 强调必须贴合当前项目
- 强调引用知识库
- 强调术语必须和官方/项目主用术语一致

但在主入口 `generate_prd.py full-run` 中，这一步是被注释掉的。

所以现状不是“没有 discussion”，而是：

- **discussion 模块存在，但默认不会自动运行**

### 2. `summary_effect` 能力存在，但未接入主流程

`summary_effect.py` 会：

- 读取当前 PRD
- 生成面向产品经理的待确认问题
- 输出 `questions.md` / `questions.json`

但同样地，在 `full-run` 中也是被注释掉的。

所以现状依然是：

- **能力存在**
- **主流程不自动触发**

### 3. `merge-final` 能力存在，但依赖阶段3前置产物

`merge-final` 会读取：

- 当前 PRD
- `summary_effect/questions.md`
- `summary_effect/questions.json`
- 产品回复文件

并生成：

- `final_prd.md`
- `merge_report.md`
- `reply_coverage_report.md`

但如果 `summary_effect` 没先跑，就会因为缺少前置产物而失败。

这说明：

- `merge-final` 不是不可用
- 但它默认并不能自然承接 `full-run`

### 4. 当前主流程的真实状态

因此，`sqlshift` 阶段3最准确的描述不是：

- “没有阶段3”

而是：

- “阶段3的模块都在，但主链没有自动把它们接起来”

换句话说：

- **能力完整度高**
- **流程闭合度低**

## 五、差异总表

| 对比项 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 阶段3是否完整存在 | 是 | 能力存在，但主链未接通 | 这是这阶段最核心的差异：不是有没有功能，而是流程是否真正闭合。 |
| 阶段3主链 | `discussion -> summary_effect -> finalize_prd` | `discussion`/`summary_effect`/`merge-final` 各自存在，但默认不串联 | `oms` 是完整流水线，`sqlshift` 更像手工拼装式能力集。 |
| 是否补强影响面分析 | 是，通过 `discussion` | 有能力，但默认不触发 | `sqlshift` 并不是弱，只是当前主流程没有把它用起来。 |
| 是否提炼待产品确认问题 | 是，`summary_effect` 自动承接 | 有能力，但默认不触发 | `oms` 在“自动把问题提炼出来”这件事上更完整。 |
| 是否自然进入最终定稿 | 是 | 否，依赖前置步骤手动补齐 | `sqlshift` 的后半段存在天然断点。 |
| 阶段3出口 | `final_prd.md` | 理论上也是 `final_prd.md`，但默认主链不自然到达 | 两边目标相似，但可达性不同。 |
| 流程哲学 | 初版文档后继续系统化收敛 | 保留能力模块，按需启用 | `oms` 更偏“编排完整性”，`sqlshift` 更偏“能力预置”。 |

## 六、产物差异表

| 类别 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 影响面补强产物 | `discussion/` 目录 | `discussion/` 目录（能力存在） | 产物层面接近，但 `oms` 会自动进入，`sqlshift` 默认不会。 |
| 产品确认问题 | `summary_effect/questions.md`、`questions.json` | 同名产物能力存在 | 这部分不是能力差异，而是主链接线差异。 |
| 最终定稿产物 | `final_prd.md`、`merge_report.md` | 同名产物能力存在 | `sqlshift` 理论上能到，但默认主链不自然到。 |
| 回复覆盖校验 | `reply_coverage_report.md` | 同名能力存在 | 两边都有能力，但 `oms` 的串联完整性明显更高。 |

## 七、推进逻辑差异

### `ai-programmer-oms`

更像：

```text
初版 PRD
-> discussion（可选）
-> summary_effect
-> 产品回复
-> finalize_prd
-> final_prd.md
```

它先解决的是：

- 还有哪些问题需要产品最终拍板

### `ai-programmer-sqlshift`

更像：

```text
阶段1已生成 draft_prd
-> discussion 能力存在但默认不跑
-> summary_effect 能力存在但默认不跑
-> merge-final 入口存在但依赖前置产物
```

它当前主流程没有自然解决的是：

- 初版文档之后，如何自动走到产品确认和最终定稿

## 八、我的总体判断

### 1. `oms` 的阶段3是完整的后处理收敛阶段

它的优势是：

- 初版 PRD 之后还能继续补强
- 能自动提炼待确认问题
- 能自然进入最终 PRD 合并

所以它是一个真正意义上的：

- **定稿收敛阶段**

### 2. `sqlshift` 的阶段3是“能力完整、链路未闭”

它的特点不是简单的“少了几步”，而是：

- discussion 有
- summary_effect 有
- finalize_prd 有
- 但主流程默认不用

所以我更倾向把它定义成：

- **后处理能力已具备，但未接入默认主链**

### 3. 如果必须做一句最准确的概括

我的判断是：

- `oms` 的阶段3更像“初版 PRD 之后的自动补强与最终定稿”
- `sqlshift` 的阶段3更像“相关模块已经准备好，但仍停留在手工编排状态”

## 九、适用场景判断

| 场景 | 更适合 `oms` | 更适合 `sqlshift` | 我的判断 |
|---|---|---|---|
| 希望初版文档后自动继续收敛 | 是 | 一般 | `oms` 更适合。 |
| 希望能力模块先保留，按需启用 | 一般 | 是 | `sqlshift` 的当前状态更像这种风格。 |
| 希望产品确认问题自动产出并自然进入定稿 | 是 | 一般 | `oms` 主链更完整。 |
| 团队能接受手动拼接后续阶段 | 一般 | 是 | `sqlshift` 在这种场景下也能工作。 |

## 十、最终结论

如果继续看阶段3，最关键的判断就是：

- `ai-programmer-oms`：**阶段3是真正存在的“补强 -> 提问 -> 定稿”阶段**
- `ai-programmer-sqlshift`：**阶段3在能力层面存在，但在默认主流程层面没有闭合**

所以这次最准确的理解不是：

- 一个“有阶段3”
- 一个“没有阶段3”

而是：

- 一个已经把阶段3编排好了
- 一个只把阶段3的零件准备好了
