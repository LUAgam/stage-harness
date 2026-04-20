# OMS vs SQLShift 阶段1对比

本文用于对比两套流程在**第一阶段**的实现差异：

- `ai-programmer-oms`
- `ai-programmer-sqlshift`

这里的“阶段1”采用功能对齐方式定义，也就是“需求进入后，系统第一次正式启动流程时做什么”。

## 一句话结论

第一阶段的核心差异非常明确：

- `ai-programmer-oms` 的阶段1是：`precheck + init + clarification`
- `ai-programmer-sqlshift` 的阶段1是：`precheck + init + draft_prd`

也就是说：

- `oms` 在第一阶段先做**前置澄清**，先问清问题，再往下走。
- `sqlshift` 在第一阶段直接做**PRD/变更说明生成**，跳过了前置澄清这一步。

## 一、为什么这样对齐

### `ai-programmer-oms`

从 `generate_prd.py start` 的实现看，第一阶段依次执行：

1. `precheck`
2. `init`
3. `clarification`

并且在生成前置澄清问题后暂停，等待人工回复。

所以它的第一阶段本质上是：

- 先检查环境
- 先准备代码仓
- 先把关键问题问出来

### `ai-programmer-sqlshift`

从 `generate_prd.py full-run` 的实现看，第一阶段依次执行：

1. `precheck`
2. `init`
3. `draft_prd`

并没有进入：

- `clarification`
- `apply-clarification`

而且代码里把 `discussion`、`summary_effect` 也先注释掉了。

所以它的第一阶段本质上是：

- 先检查环境
- 先准备代码仓
- 直接生成产品变更说明 / 初版 PRD

## 二、阶段1映射

### `ai-programmer-oms`

阶段1：

- `generate_prd.py start`
  - `precheck`
  - `init`
  - `clarification`

阶段1出口：

- 生成前置澄清问题
- 暂停等待人工回复

### `ai-programmer-sqlshift`

阶段1：

- `generate_prd.py full-run`
  - `precheck`
  - `init`
  - `draft_prd`

阶段1出口：

- 直接生成 `prd/` 目录下的需求/变更说明文档

## 三、`oms` 阶段1实现流程

### 1. `precheck`

检查：

- `.env`
- 关键配置
- `agent` / `git` / `ssh`
- `WORKING_DIR`
- 原始需求文件
- 知识库目录

失败时直接阻断。

### 2. `init`

把目标代码仓克隆到工作区，并切到工作分支。

### 3. `clarification`

生成：

- `questions.md`
- `questions.json`
- `answer_template.md`

然后停下来等人工补回复。

这一阶段的关键特征是：

- 不直接生成 PRD
- 先缩需求范围
- 先暴露会影响 PRD 结论的问题

## 四、`sqlshift` 阶段1实现流程

### 1. `precheck`

实现上与 `oms` 非常接近，也是做环境、配置、需求文件、知识库和代码仓配置校验。

### 2. `init`

实现上也与 `oms` 基本一致，同样会准备代码仓工作区。

### 3. `draft_prd`

这一阶段直接进入 PRD/变更说明生成。

而且它不是沿用 `oms` 的通用 PRD prompt，而是明显换成了 SQLShift 场景定制：

- 先判断知识库里是否已有：
  - `SQL 转换主链路`
  - `结果页 AI 修复中心链路`
  - `性能诊断与优化链路`
  - `文件型 SQL 修复接口链路`
- 再结合原始需求、知识库、代码目录生成一份：
  - 面向产品经理的“产品变更说明”

这说明 `sqlshift` 的第一阶段不是通用澄清流程，而是：

- **直接进入 SQLShift 业务口径下的需求文档生成**

## 五、差异总表

| 对比项 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 第一阶段入口 | `generate_prd.py start` | `generate_prd.py full-run` | `sqlshift` 连命令形态都更“压缩”，不像 `oms` 那样显式拆出 start/apply/merge 这套前置流程。 |
| 第一阶段主链 | `precheck -> init -> clarification` | `precheck -> init -> draft_prd` | 这是最核心的差异：`oms` 先问清，`sqlshift` 先成文。 |
| 是否有前置澄清问题生成 | 有 | 没有 | 我认为 `oms` 更稳，`sqlshift` 更快，但也更依赖原始需求质量。 |
| 是否在阶段1停下来等人工回复 | 是 | 否 | `oms` 的人工阻塞更早；`sqlshift` 第一阶段自治程度更高。 |
| 第一阶段产物中心 | `clarification/questions.*` | `prd/` 下的需求/变更说明文档 | `oms` 第一阶段产物偏问题清单，`sqlshift` 第一阶段产物偏需求文档。 |
| 业务口径 | 通用 OMS 需求收敛 | SQLShift 专用链路口径 | `sqlshift` 的第一阶段领域定制更强，说明它不是单纯复用 `oms` 流程，而是做了场景压缩。 |
| 对原始需求质量的依赖 | 中等 | 高 | 因为 `sqlshift` 跳过了 clarification，所以更吃输入质量。 |
| 推进哲学 | 先缩范围，再写 PRD | 先基于现有信息生成变更说明 | `oms` 更像“先问再写”，`sqlshift` 更像“先写后补”。 |

## 六、产物差异表

| 类别 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 环境检查产物 | 主要是流程门禁，不强调文档产物 | 同样主要是门禁 | 这部分两边差异不大。 |
| 工作区初始化 | 克隆仓库并切分支 | 克隆仓库并切分支 | 这部分基本同构。 |
| 第一阶段主产物 | `questions.md`、`questions.json`、`answer_template.md` | `prd/` 目录下需求/变更说明文档 | 产物重心完全不同，这也是我判断两边阶段1设计哲学不同的核心依据。 |
| 第一阶段结果形态 | 待确认问题列表 | 初版需求说明 | `sqlshift` 更接近“先交出一版文档”，`oms` 更接近“先组织提问”。 |

## 七、推进逻辑差异

### `ai-programmer-oms`

更像：

```text
需求输入
-> precheck
-> init
-> clarification
-> 等人工回复
```

它先解决的是：

- 哪些问题必须先问清

### `ai-programmer-sqlshift`

更像：

```text
需求输入
-> precheck
-> init
-> draft_prd
```

它先解决的是：

- 基于当前输入，先形成一份需求/变更说明

## 八、我的总体判断

### 1. `oms` 的第一阶段更稳

它的优势是：

- 先暴露模糊点
- 先要求人工回答关键问题
- 降低后续 PRD 偏掉的风险

代价是：

- 第一阶段更慢
- 人工参与更早

### 2. `sqlshift` 的第一阶段更快

它的优势是：

- 直接产出文档
- 第一阶段更短
- 对熟悉域、需求模板化较强的场景更高效

代价是：

- 更依赖原始需求质量
- 也更依赖领域 prompt 是否足够强

### 3. 如果必须做一句最准确的概括

我的判断是：

- `oms` 的阶段1更像“前置澄清启动阶段”
- `sqlshift` 的阶段1更像“直接生成需求说明的启动阶段”

## 九、适用场景判断

| 场景 | 更适合 `oms` | 更适合 `sqlshift` | 我的判断 |
|---|---|---|---|
| 原始需求模糊、需要大量澄清 | 是 | 一般 | `oms` 更适合。 |
| 领域相对固定、需求模板化较强 | 一般 | 是 | `sqlshift` 更适合。 |
| 希望第一阶段就让产品参与确认 | 是 | 一般 | `oms` 的人工阻塞点更早、更明确。 |
| 希望先快速得到一版需求文档 | 一般 | 是 | `sqlshift` 的第一阶段更直接。 |

## 十、最终结论

如果只看第一阶段，最关键的判断就是：

- `ai-programmer-oms`：**先澄清，再继续**
- `ai-programmer-sqlshift`：**先成文，再继续**

所以两边虽然共享：

- `precheck`
- `init`

但在真正的阶段1目标上已经明显分叉：

- 一个优先解决“问题是否问清”
- 一个优先解决“文档是否先生成出来”
