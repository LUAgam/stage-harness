# OMS vs SQLShift 阶段2对比

本文继续对比两套流程在**阶段2**的实现差异：

- `ai-programmer-oms`
- `ai-programmer-sqlshift`

这里的“阶段2”仍然采用功能对齐方式定义，也就是看**阶段1结束后，系统下一步如何继续把需求收敛成可用文档**。

## 一句话结论

如果严格按当前代码实现看，阶段2并不是一一对齐关系，而是出现了明显的**阶段错位**：

- `ai-programmer-oms` 的阶段2是：`apply-clarification + draft_prd`
- `ai-programmer-sqlshift` 的“对应位置”在主入口里其实**缺位**

原因是：

- `oms` 把“人工回复前置澄清”放在阶段2
- `sqlshift` 已经在阶段1直接执行了 `draft_prd`
- 但它后续用于产品确认的 `summary_effect` 并没有接进 `full-run`

所以更准确地说：

- `oms` 的阶段2是一个完整存在的“**回复收敛 -> 初版文档生成**”阶段
- `sqlshift` 的阶段2在现状实现中更像“**阶段压缩后的空档**”

## 一、为什么会出现阶段错位

### `ai-programmer-oms`

上一份阶段1对比已经说明：

- 阶段1停在 `clarification`
- 输出前置澄清问题
- 等人工回复

因此阶段2自然就是：

1. `apply-clarification`
2. `draft_prd`

也就是：

- 先把人工回复合并进需求范围
- 再生成初版 PRD

### `ai-programmer-sqlshift`

而 `sqlshift` 在阶段1就已经执行了：

- `precheck`
- `init`
- `draft_prd`

也就是说，它把 `oms` 的一部分阶段2内容前移到了阶段1。

但与此同时，`sqlshift` 的 `generate_prd.py full-run` 又把下面这些步骤注释掉了：

- `discussion`
- `summary_effect`

而 `merge-final` 虽然存在，却依赖：

- `summary_effect/questions.md`
- `summary_effect/questions.json`

这些前置产物。

因此当前代码状态是：

- 初版文档生成被提前了
- 中间的产品确认问题生成没有自动接上
- 最终合并接口还保留着

这就导致阶段2不再是正常的线性阶段，而像是一个**被压缩后留下来的流程断层**。

## 二、阶段2映射

### `ai-programmer-oms`

阶段2：

- `apply-clarification`
- `draft_prd`

阶段2入口：

- 已经有前置澄清问题
- 用户已经补充回复

阶段2出口：

- 生成 `clarified_requirement.md`
- 生成 `prd/requirements.md`

### `ai-programmer-sqlshift`

如果只看当前主入口：

- 没有一个独立、完整的阶段2与之对应

更准确的现状是：

1. `draft_prd` 已经在阶段1执行
2. `summary_effect` 存在实现，但未接入 `full-run`
3. `merge-final` 存在入口，但依赖 `summary_effect` 前置产物

所以如果硬要标记“阶段2”，只能说：

- **主流程里缺位**

## 三、`oms` 阶段2实现流程

### 1. `apply-clarification`

这一阶段会读取：

- `questions.md`
- `questions.json`
- 产品回复文件

然后完成两件事：

1. 校验回复是否覆盖全部前置问题
2. 若完整，则生成：
   - `reply_coverage_report.md`
   - `clarified_requirement.md`

如果不完整：

- 不会继续生成 PRD
- 会把 AI 补充待确认项写回回复文件末尾
- 直接阻断

这一层的价值在于：

- 它先把“问题问到了”
- 再确保“问题答完整了”

### 2. `draft_prd`

前置澄清完成后，再进入 PRD 生成：

- 先判断知识库说明是否充足
- 再生成 `requirements.md`
- 再做完整性复审并原地补齐

所以 `oms` 的阶段2本质上是：

- **把澄清结果收敛成第一版正式需求文档**

## 四、`sqlshift` 在这一位置的真实实现状态

### 1. `draft_prd` 已被前移

`sqlshift` 的 `draft_prd` 不是在阶段2触发，而是在阶段1的 `full-run` 中直接执行。

这意味着：

- `oms` 阶段2里的“生成初版文档”动作
- 在 `sqlshift` 里已经被提前消费掉了

### 2. 没有 `apply-clarification`

在仓库代码中没有发现：

- `clarification.py`
- `apply-clarification`
- `run_clarification_task`

这说明 `sqlshift` 根本没有建立“前置澄清问题 -> 人工回复 -> 合并澄清后需求”这条链。

也就是说，它没有一个对应 `oms` 阶段2前半段的实现层。

### 3. `summary_effect` 存在，但未接入 `full-run`

`summary_effect.py` 是有实现的，而且它会：

- 读取当前 PRD
- 生成待产品确认问题
- 输出 `questions.md` / `questions.json`

但在 `generate_prd.py full-run` 中，这一步是被注释掉的。

这意味着：

- 相关能力存在
- 但不在当前主链中自动发生

### 4. `merge-final` 存在，但前置依赖没有自动准备好

`merge-final` 会调用 `run_finalize_prd_task()`，而这个函数明确要求：

- `summary_effect` 目录必须存在
- `questions.md`
- `questions.json`

都已经存在

否则会直接报错。

但因为 `full-run` 没有自动执行 `summary_effect`，所以按当前主链来看：

- `merge-final` 在很多情况下并不能自然承接阶段1的输出

## 五、差异总表

| 对比项 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 阶段2是否完整存在 | 是 | 否，主流程中缺位 | 这是当前最关键的结构性差异，不是功能强弱，而是流程是否闭合。 |
| 阶段2主链 | `apply-clarification -> draft_prd` | 无完整等价阶段 | `oms` 是正常分阶段推进，`sqlshift` 是阶段前移后留下空档。 |
| 是否先合并人工回复 | 是 | 否 | `oms` 更强调“先消化人工答复再生成文档”，`sqlshift` 没有这层。 |
| 是否在这一阶段生成初版文档 | 是 | 否，已在阶段1完成 | `sqlshift` 把这个动作提前了。 |
| 是否有独立的“澄清后需求”产物 | 有，`clarified_requirement.md` | 没有 | 这说明 `sqlshift` 少了一层需求收敛缓冲层。 |
| 是否存在后续产品确认能力 | 有，且串在主流程里 | 有实现，但未接入主流程 | `sqlshift` 不是没有能力，而是主链没有把它接起来。 |
| 阶段2推进哲学 | 先吸收回复，再出文档 | 先出文档，后续确认能力悬空 | 我认为 `oms` 更完整，`sqlshift` 更像半压缩版流程。 |

## 六、产物差异表

| 类别 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 回复覆盖校验 | `reply_coverage_report.md` | 无对应阶段产物 | `oms` 这里更稳，因为它显式确认“答复是否完整”。 |
| 澄清后需求 | `clarified_requirement.md` | 无 | `sqlshift` 缺少这一层，意味着原始需求到 PRD 之间过渡更短。 |
| 初版需求文档 | `prd/requirements.md` | 已在阶段1生成 | `sqlshift` 的主文档生成前移了。 |
| 产品确认问题 | 后续 `summary_effect` 再生成 | 有实现，但主链未自动生成 | `sqlshift` 这里是“能力存在、链路未接”。 |

## 七、推进逻辑差异

### `ai-programmer-oms`

更像：

```text
clarification 问题
-> 人工回复
-> apply-clarification
-> clarified_requirement.md
-> draft_prd
```

它先解决的是：

- 前置问题是否已经被回答完整

### `ai-programmer-sqlshift`

更像：

```text
阶段1已完成 draft_prd
-> （主流程里没有对应阶段2）
-> 后续 summary_effect / merge-final 能力存在但未自动串联
```

它在这个位置上没有先解决：

- “人工补充信息如何被吸收进文档”

而是直接跳到了：

- 先有一版文档

## 八、我的总体判断

### 1. `oms` 的阶段2是完整的收敛阶段

它的优势是：

- 有明确的输入
- 有明确的人工回复合并
- 有明确的澄清后需求产物
- 有明确的 PRD 生成出口

所以它是一个真正意义上的：

- **需求收敛阶段**

### 2. `sqlshift` 的阶段2更像流程缺口

它的现状不是“阶段2更轻”，而是：

- 部分动作被提前到阶段1
- 部分能力留在后面
- 中间主链没有完整阶段承接

所以我更倾向把它定义成：

- **阶段压缩后的缺位**

而不是：

- 一个独立、完整的阶段2

### 3. 如果必须做一句最准确的概括

我的判断是：

- `oms` 的阶段2更像“把澄清回复正式收敛进初版需求文档”
- `sqlshift` 在这个位置上更像“没有独立阶段，相关动作被拆散到了前后两端”

## 九、适用场景判断

| 场景 | 更适合 `oms` | 更适合 `sqlshift` | 我的判断 |
|---|---|---|---|
| 需要严格吸收人工澄清回复 | 是 | 一般 | `oms` 更适合。 |
| 希望阶段切分清晰、可追踪 | 是 | 一般 | `oms` 的分阶段更清楚。 |
| 希望主链更短、更快出文档 | 一般 | 是 | `sqlshift` 更快，但代价是结构完整性下降。 |
| 希望后续产品确认能力天然接上 | 是 | 一般 | `sqlshift` 当前主链没有自然闭合到这一步。 |

## 十、最终结论

如果继续看阶段2，最关键的判断就是：

- `ai-programmer-oms`：**阶段2真实存在，并负责“回复收敛 -> 初版 PRD”**
- `ai-programmer-sqlshift`：**阶段2在当前主流程里并不完整，呈现为“前移一部分、后留一部分”的阶段错位**

所以这次对比不能简单说谁“多一步”或“少一步”，而应更准确地理解为：

- `oms` 是标准分阶段推进
- `sqlshift` 是压缩后的非对称流程
